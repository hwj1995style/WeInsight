from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
import re
from typing import Iterator
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import Config, load_config
from app.domain.group_reports import DailyReportDetail, DailyReportSummary
from app.domain.report_lifecycle import GenerationTrigger, ReportStatus
from app.pipelines.article_daily_report_query_service import (
    ArticleDailyReportDetail,
    ArticleDailyReportSummary,
)
from app.pipelines.summary_daily_report_query_service import (
    SummaryArticleDailyReport,
    SummaryDailyReportQueryService,
    SummaryDailyReportSourceBundle,
    SummaryGroupDailyReport,
)
from app.services.auth_service import AuthenticatedAdmin
from app.services.report_generation_service import ReportValidationError
from app.storage.article_daily_report_query_repo import (
    MysqlArticleDailyReportQueryRepo,
)
from app.storage.group_daily_report_query_repo import MysqlGroupDailyReportQueryRepo
from app.storage.report_request_repo import (
    ReportRequest,
    ReportRequestStatus,
    ReportType,
)
from app.storage.summary_daily_report_query_repo import MysqlSummaryDailyReportQueryRepo
from app.web.app import create_app
from app.web.routes import reports as report_routes


REPORT_DATE = date(2026, 7, 10)
GENERATED_AT = datetime(2026, 7, 10, 23, 55)
CUTOFF_AT = datetime(2026, 7, 10, 23, 50, tzinfo=ZoneInfo("Asia/Shanghai"))
NOW = datetime(2026, 7, 11, 9, 15, tzinfo=ZoneInfo("Asia/Shanghai"))


class FakeAuthService:
    admin = AuthenticatedAdmin(id=1, username="admin", using_default_password=False)

    def authenticate(self, session_token, csrf_token, now):
        return self.admin if session_token == "session-token" else None

    def verify_csrf(self, session_token, csrf_token, now):
        return session_token == "session-token" and csrf_token == "csrf-token"


class FakeReportRequestService:
    def __init__(self) -> None:
        self.request_calls: list[tuple] = []
        self.execute_calls: list[tuple] = []
        self.error: Exception | None = None

    def request_manual(
        self,
        report_type,
        report_date,
        source_name,
        actor,
        idempotency_key,
        now,
    ):
        self.request_calls.append(
            (
                report_type,
                report_date,
                source_name,
                actor,
                idempotency_key,
                now,
            )
        )
        if self.error is not None:
            raise self.error
        return 41

    def execute_request(self, *args, **kwargs):
        self.execute_calls.append((args, kwargs))
        raise AssertionError("Web must not execute report generation")


class FakeReportRequestRepo:
    def __init__(self) -> None:
        self.requests: dict[int, ReportRequest] = {}
        self.calls: list[int] = []

    def get_request(self, request_id: int):
        self.calls.append(request_id)
        return self.requests.get(request_id)


def report_request(
    *,
    status: ReportRequestStatus = ReportRequestStatus.PENDING,
    error_summary: str | None = None,
) -> ReportRequest:
    running = status is ReportRequestStatus.RUNNING
    terminal = status in {
        ReportRequestStatus.SUCCESS,
        ReportRequestStatus.PARTIAL_SUCCESS,
        ReportRequestStatus.FAILED,
    }
    return ReportRequest(
        id=41,
        idempotency_key="manual-form-key-abcdefghijklmnopqrstuvwxyz",
        report_type=ReportType.GROUP,
        report_date=REPORT_DATE,
        source_name="核心群",
        generation_trigger=GenerationTrigger.MANUAL,
        data_cutoff_time=CUTOFF_AT,
        requested_by="admin",
        status=status,
        worker_id="pipeline-1" if running or terminal else None,
        lease_expires_at=(NOW.replace(hour=10) if running else None),
        error_summary=error_summary,
        create_time=CUTOFF_AT,
        start_time=CUTOFF_AT if running or terminal else None,
        end_time=NOW if terminal else None,
    )


class FakeGroupReportService:
    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.report_status = ReportStatus.PROVISIONAL
        self.generation_trigger = GenerationTrigger.MANUAL
        self.data_cutoff_time = CUTOFF_AT
        self.last_generated_by = "admin"

    def list_reports(self, report_date, group_name, limit, offset=0):
        self.calls.append(("list", report_date, group_name, limit, offset))
        return [
            DailyReportSummary(
                report_date=REPORT_DATE,
                group_name="核心群",
                title="核心群日报",
                message_count=18,
                sender_count=6,
                demand_count=5,
                supply_count=4,
                contact_count=3,
                peak_hour=9,
                generate_time=GENERATED_AT,
                report_status=self.report_status,
                data_cutoff_time=self.data_cutoff_time,
                generation_trigger=self.generation_trigger,
                last_generated_by=self.last_generated_by,
            )
        ]

    def get_report(self, report_date, group_name):
        self.calls.append(("get", report_date, group_name))
        return DailyReportDetail(
            report_date=REPORT_DATE,
            group_name=group_name,
            title="核心群日报",
            markdown_body=(
                "# 安全日报\n<script>alert(1)</script>"
                "[危险链接](https://example.test/private)"
                '<span onclick="bad()">指标</span>'
            ),
            message_count=18,
            sender_count=6,
            demand_count=5,
            supply_count=4,
            contact_count=3,
            peak_hour=9,
            top_keywords="[]",
            report_version="v1",
            generate_time=GENERATED_AT,
            report_status=self.report_status,
            data_cutoff_time=self.data_cutoff_time,
            generation_trigger=self.generation_trigger,
            last_generated_by=self.last_generated_by,
        )


class FakeArticleReportService:
    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.report_status = ReportStatus.PROVISIONAL
        self.generation_trigger = GenerationTrigger.MANUAL
        self.data_cutoff_time = CUTOFF_AT
        self.last_generated_by = "admin"

    def list_reports(self, report_date, account_name, limit, offset=0):
        self.calls.append(("list", report_date, account_name, limit, offset))
        return [
            ArticleDailyReportSummary(
                report_date=REPORT_DATE,
                account_name="行情观察",
                title="文章日报",
                article_count=7,
                avg_content_length=420,
                generate_time=GENERATED_AT,
                report_status=self.report_status,
                data_cutoff_time=self.data_cutoff_time,
                generation_trigger=self.generation_trigger,
                last_generated_by=self.last_generated_by,
            )
        ]

    def get_report(self, report_date, account_name):
        self.calls.append(("get", report_date, account_name))
        return ArticleDailyReportDetail(
            report_date=REPORT_DATE,
            account_name=account_name,
            title="文章日报",
            markdown_body="# 文章日报\n\n| 指标 | 数量 |\n| --- | ---: |\n| 文章 | 7 |",
            article_count=7,
            avg_content_length=420,
            top_tags_json="[]",
            top_keywords_json="[]",
            report_version="v1",
            generate_time=GENERATED_AT,
            report_status=self.report_status,
            data_cutoff_time=self.data_cutoff_time,
            generation_trigger=self.generation_trigger,
            last_generated_by=self.last_generated_by,
        )


class FakeSummaryReportService:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def load_sources(self, report_date, limit=100, offset=0):
        self.calls.append(("load", report_date, limit, offset))
        return SummaryDailyReportSourceBundle(
            report_date=report_date,
            group_reports=[
                SummaryGroupDailyReport(
                    report_date=REPORT_DATE,
                    group_name="核心群",
                    title="核心群日报",
                    message_count=18,
                    sender_count=6,
                    demand_count=5,
                    supply_count=4,
                    contact_count=3,
                    peak_hour=9,
                    generate_time=GENERATED_AT,
                )
            ],
            article_reports=[
                SummaryArticleDailyReport(
                    report_date=REPORT_DATE,
                    account_name="行情观察",
                    title="文章日报",
                    article_count=7,
                    avg_content_length=420,
                    generate_time=GENERATED_AT,
                )
            ],
        )


@pytest.fixture
def config() -> Config:
    return load_config(Path("config/config.dev.yaml"))


@pytest.fixture
def report_services():
    return (
        FakeGroupReportService(),
        FakeArticleReportService(),
        FakeSummaryReportService(),
    )


@pytest.fixture
def report_request_dependencies():
    return FakeReportRequestService(), FakeReportRequestRepo()


@pytest.fixture
def app(config: Config, report_services, report_request_dependencies) -> FastAPI:
    group, article, summary = report_services
    request_service, request_repo = report_request_dependencies
    return create_app(
        config,
        auth_service=FakeAuthService(),
        group_report_service=group,
        article_report_service=article,
        summary_report_service=summary,
        report_request_service=request_service,
        report_request_repo=request_repo,
    )


@pytest.fixture
def raw_client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as client:
        yield client


@pytest.fixture
def authenticated_client(raw_client: TestClient) -> TestClient:
    raw_client.cookies.set("weinsight_session", "session-token")
    raw_client.cookies.set("weinsight_csrf", "csrf-token")
    return raw_client


def test_group_report_list_is_url_filtered_and_server_paginated(
    authenticated_client: TestClient,
    report_services,
) -> None:
    group, _, _ = report_services

    response = authenticated_client.get(
        "/reports?date=2026-07-10&type=group&source=%E6%A0%B8%E5%BF%83%E7%BE%A4&"
        "page=2&page_size=20"
    )

    assert response.status_code == 200
    assert "核心群日报" in response.text
    assert 'name="date" value="2026-07-10"' in response.text
    assert 'option value="group" selected' in response.text
    assert 'name="source" value="核心群"' in response.text
    assert group.calls == [
        ("list", REPORT_DATE, "核心群", 21, 20),
        ("get", REPORT_DATE, "核心群"),
    ]


def test_reports_page_contains_server_generated_manual_request_key(
    authenticated_client: TestClient,
) -> None:
    first = authenticated_client.get("/reports?date=2026-07-10&type=group")
    second = authenticated_client.get("/reports?date=2026-07-10&type=group")

    assert first.status_code == 200
    keys = [
        re.search(r'name="idempotency_key" value="([A-Za-z0-9_-]+)"', body.text)
        for body in (first, second)
    ]
    assert all(match is not None for match in keys)
    values = [match.group(1) for match in keys if match is not None]
    assert all(32 <= len(value) <= 100 for value in values)
    assert values[0] != values[1]
    assert 'name="csrf_token" value="csrf-token"' in first.text


@pytest.mark.parametrize(
    "path",
    [
        "/reports?date=2026-07-10&type=group&unknown=1",
        "/reports?date=2026-07-10&type=group&type=article",
        "/reports?date=2026-07-10&type=group&source=A&source=B",
        "/reports?date=2026-07-10&type=group&source=..",
        "/reports?date=2026-07-10&type=group&source=A%0AB",
    ],
)
def test_reports_query_rejects_unknown_and_duplicate_fields(
    authenticated_client: TestClient,
    path: str,
) -> None:
    response = authenticated_client.get(path)

    assert response.status_code == 422
    assert "日报查询条件无效" in response.text


def test_report_markdown_is_safely_rendered_without_raw_source(
    authenticated_client: TestClient,
) -> None:
    response = authenticated_client.get(
        "/reports?date=2026-07-10&type=group&source=%E6%A0%B8%E5%BF%83%E7%BE%A4"
    )

    assert response.status_code == 200
    assert "<h1>安全日报</h1>" in response.text
    assert "危险链接" in response.text
    report_body = re.search(
        r'<article class="report-markdown">(.*?)</article>',
        response.text,
        re.DOTALL,
    )
    assert report_body is not None
    safe_html = report_body.group(1).lower()
    assert "<a" not in safe_html
    assert "href=" not in safe_html
    assert "<script" not in safe_html
    assert "onclick" not in safe_html
    assert "markdown_body" not in response.text
    assert "https://example.test/private" not in response.text


def test_article_report_detail_allows_sanitized_markdown_table(
    authenticated_client: TestClient,
) -> None:
    response = authenticated_client.get(
        "/reports?date=2026-07-10&type=article&source=%E8%A1%8C%E6%83%85%E8%A7%82%E5%AF%9F"
    )

    assert response.status_code == 200
    assert "<table>" in response.text
    assert "文章日报" in response.text
    assert "top_tags_json" not in response.text


def test_report_list_and_detail_show_real_lifecycle_metadata(
    authenticated_client: TestClient,
    report_services,
) -> None:
    group, _, _ = report_services
    provisional = authenticated_client.get(
        "/reports?date=2026-07-10&type=group&source=%E6%A0%B8%E5%BF%83%E7%BE%A4"
    )

    assert "临时版" in provisional.text
    assert "2026-07-10 23:50" in provisional.text
    assert "手动生成 · admin" in provisional.text

    group.report_status = ReportStatus.FINAL
    group.generation_trigger = GenerationTrigger.COMPENSATION
    group.last_generated_by = "system"
    final = authenticated_client.get(
        "/reports?date=2026-07-10&type=group&source=%E6%A0%B8%E5%BF%83%E7%BE%A4"
    )

    assert "最终版" in final.text
    assert "次日补偿 · system" in final.text


def test_summary_report_reads_both_source_lists_with_bounded_page(
    authenticated_client: TestClient,
    report_services,
) -> None:
    _, _, summary = report_services

    response = authenticated_client.get(
        "/reports?date=2026-07-10&type=summary&page=3&page_size=10"
    )

    assert response.status_code == 200
    assert "核心群" in response.text
    assert "行情观察" in response.text
    assert summary.calls == [("load", REPORT_DATE, 11, 20)]


@pytest.mark.parametrize(
    ("path", "body_text", "filename_prefix"),
    [
        (
            "/reports/group/2026-07-10/%E6%A0%B8%E5%BF%83%E7%BE%A4.md",
            "# 安全日报",
            "weinsight-group-report-2026-07-10.md",
        ),
        (
            "/reports/article/2026-07-10/%E8%A1%8C%E6%83%85%E8%A7%82%E5%AF%9F.md",
            "# 文章日报",
            "weinsight-article-report-2026-07-10.md",
        ),
    ],
)
def test_group_and_article_download_only_stored_markdown_with_safe_headers(
    authenticated_client: TestClient,
    path: str,
    body_text: str,
    filename_prefix: str,
) -> None:
    response = authenticated_client.get(path)

    assert response.status_code == 200
    assert response.headers["content-type"] == "text/markdown; charset=utf-8"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["content-disposition"] == (
        f'attachment; filename="{filename_prefix}"'
    )
    assert body_text in response.text
    assert "核心群" not in response.headers["content-disposition"]
    assert "行情观察" not in response.headers["content-disposition"]


def test_summary_download_is_read_only_composition_of_stored_summaries(
    authenticated_client: TestClient,
) -> None:
    response = authenticated_client.get("/reports/summary/2026-07-10.md")

    assert response.status_code == 200
    assert response.headers["content-type"] == "text/markdown; charset=utf-8"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["content-disposition"] == (
        'attachment; filename="weinsight-summary-report-2026-07-10.md"'
    )
    assert "# 双链路汇总日报（2026-07-10）" in response.text
    assert "核心群" in response.text
    assert "行情观察" in response.text
    assert "18" in response.text and "7" in response.text
    assert "安全日报" not in response.text
    assert "https://example.test/private" not in response.text


def test_summary_download_escapes_markdown_cells_from_stored_summaries(
    authenticated_client: TestClient,
    report_services,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, _, summary = report_services
    bundle = SummaryDailyReportSourceBundle(
        report_date=REPORT_DATE,
        group_reports=[
            SummaryGroupDailyReport(
                report_date=REPORT_DATE,
                group_name="群A|第二列\n<script>",
                title="标题\\破坏|表格",
                message_count=1,
                sender_count=1,
                demand_count=0,
                supply_count=0,
                contact_count=0,
                peak_hour=None,
                generate_time=GENERATED_AT,
            )
        ],
        article_reports=[],
    )
    monkeypatch.setattr(summary, "load_sources", lambda *args: bundle)

    response = authenticated_client.get("/reports/summary/2026-07-10.md")

    assert response.status_code == 200
    assert "群A\\|第二列 ＜script＞" in response.text
    assert "标题\\\\破坏\\|表格" in response.text
    assert "<script>" not in response.text


@pytest.mark.parametrize(
    "path",
    [
        "/reports/group/not-a-date/A.md",
        "/reports/group/2026-07-10/...md",
        "/reports/group/2026-07-10/%0D%0AContent-Disposition%3Ainline.md",
        "/reports/article/2026-07-10/...md",
        "/reports/summary/not-a-date.md",
    ],
)
def test_download_rejects_invalid_date_path_and_header_injection(
    authenticated_client: TestClient,
    path: str,
) -> None:
    response = authenticated_client.get(path)

    assert response.status_code == 404
    assert "日报不存在" in response.text
    assert "Content-Disposition: inline" not in response.headers.get(
        "content-disposition",
        "",
    )


@pytest.mark.parametrize(
    ("service_index", "path"),
    [
        (0, "/reports/group/2026-07-10/missing.md"),
        (1, "/reports/article/2026-07-10/missing.md"),
    ],
)
def test_missing_stored_report_download_is_safe_404(
    authenticated_client: TestClient,
    report_services,
    service_index: int,
    path: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = report_services[service_index]
    monkeypatch.setattr(service, "get_report", lambda *args: None)

    response = authenticated_client.get(path)

    assert response.status_code == 404
    assert "日报不存在" in response.text


def test_empty_summary_download_is_safe_404(
    authenticated_client: TestClient,
    report_services,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, _, summary = report_services
    monkeypatch.setattr(
        summary,
        "load_sources",
        lambda *args: SummaryDailyReportSourceBundle(
            report_date=REPORT_DATE,
            group_reports=[],
            article_reports=[],
        ),
    )

    response = authenticated_client.get("/reports/summary/2026-07-10.md")

    assert response.status_code == 404
    assert "日报不存在" in response.text


@pytest.mark.parametrize(
    "path",
    [
        "/reports/requests/41",
        "/reports/group/2026-07-10/A.md",
        "/reports/article/2026-07-10/A.md",
        "/reports/summary/2026-07-10.md",
    ],
)
def test_new_report_status_and_download_routes_require_authentication(
    raw_client: TestClient,
    path: str,
) -> None:
    response = raw_client.get(path, follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_manual_report_post_requires_authentication(raw_client: TestClient) -> None:
    response = raw_client.post(
        "/reports/generate",
        data={
            "csrf_token": "csrf-token",
            "idempotency_key": "manual-form-key-abcdefghijklmnopqrstuvwxyz",
            "report_type": "group",
            "report_date": "2026-07-10",
            "source_name": "",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_report_routes_hide_unexpected_repo_and_service_errors(
    authenticated_client: TestClient,
    report_request_dependencies,
    report_services,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_service, request_repo = report_request_dependencies
    unsafe = RuntimeError("password=hunter2 C:/secret/report.md SQL SELECT raw")
    request_service.error = unsafe

    post = authenticated_client.post(
        "/reports/generate",
        data={
            "csrf_token": "csrf-token",
            "idempotency_key": "manual-form-key-abcdefghijklmnopqrstuvwxyz",
            "report_type": "group",
            "report_date": "2026-07-10",
            "source_name": "",
        },
    )
    monkeypatch.setattr(request_repo, "get_request", lambda request_id: (_ for _ in ()).throw(unsafe))
    status = authenticated_client.get("/reports/requests/41")
    monkeypatch.setattr(report_services[0], "get_report", lambda *args: (_ for _ in ()).throw(unsafe))
    download = authenticated_client.get("/reports/group/2026-07-10/A.md")

    for response in (post, status, download):
        assert response.status_code == 503
        assert "hunter2" not in response.text
        assert "C:/secret" not in response.text
        assert "SELECT raw" not in response.text


@pytest.mark.parametrize(
    "path",
    [
        "/reports?date=nope&type=group",
        "/reports?date=2026-07-10&type=unknown",
        "/reports?date=2026-07-10&type=article&page_size=101",
        "/reports?date=2026-07-10&type=group&page=0",
    ],
)
def test_invalid_report_query_returns_safe_html_422(
    authenticated_client: TestClient,
    path: str,
) -> None:
    response = authenticated_client.get(path)

    assert response.status_code == 422
    assert response.headers["content-type"].startswith("text/html")
    assert "日报查询条件无效" in response.text
    assert "ValueError" not in response.text


def test_reports_require_authentication(raw_client: TestClient) -> None:
    response = raw_client.get("/reports", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_manual_report_post_only_creates_request_and_redirects_303(
    authenticated_client: TestClient,
    report_request_dependencies,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_service, _ = report_request_dependencies
    monkeypatch.setattr(report_routes, "_now", lambda request: NOW)
    form = {
        "csrf_token": "csrf-token",
        "idempotency_key": "manual-form-key-abcdefghijklmnopqrstuvwxyz",
        "report_type": "group",
        "report_date": "2026-07-10",
        "source_name": "核心群",
    }

    first = authenticated_client.post(
        "/reports/generate",
        data=form,
        follow_redirects=False,
    )
    second = authenticated_client.post(
        "/reports/generate",
        data=form,
        follow_redirects=False,
    )

    assert first.status_code == 303
    assert first.headers["location"] == "/reports/requests/41"
    assert second.status_code == 303
    assert request_service.request_calls == [
        (
            ReportType.GROUP,
            REPORT_DATE,
            "核心群",
            "admin",
            "manual-form-key-abcdefghijklmnopqrstuvwxyz",
            NOW,
        ),
        (
            ReportType.GROUP,
            REPORT_DATE,
            "核心群",
            "admin",
            "manual-form-key-abcdefghijklmnopqrstuvwxyz",
            NOW,
        ),
    ]
    assert request_service.execute_calls == []


@pytest.mark.parametrize(
    "body",
    [
        (
            "csrf_token=csrf-token&"
            "idempotency_key=manual-form-key-abcdefghijklmnopqrstuvwxyz&"
            "report_type=group&report_date=2026-07-10&source_name=A&unknown=1"
        ),
        (
            "csrf_token=csrf-token&"
            "idempotency_key=manual-form-key-abcdefghijklmnopqrstuvwxyz&"
            "report_type=group&report_type=article&"
            "report_date=2026-07-10&source_name=A"
        ),
        (
            "csrf_token=csrf-token&idempotency_key=short&"
            "report_type=group&report_date=2026-07-10&source_name=A"
        ),
        (
            "csrf_token=csrf-token&"
            "idempotency_key=manual-form-key-abcdefghijklmnopqrstuvwxyz&"
            "report_type=summary&report_date=2026-07-10&source_name=A"
        ),
    ],
)
def test_manual_report_post_rejects_unknown_duplicate_and_invalid_fields(
    authenticated_client: TestClient,
    report_request_dependencies,
    body: str,
) -> None:
    request_service, _ = report_request_dependencies

    response = authenticated_client.post(
        "/reports/generate",
        content=body,
        headers={"content-type": "application/x-www-form-urlencoded"},
    )

    assert response.status_code == 422
    assert "日报生成请求无效" in response.text
    assert request_service.request_calls == []


def test_manual_report_post_requires_csrf(
    authenticated_client: TestClient,
    report_request_dependencies,
) -> None:
    request_service, _ = report_request_dependencies

    response = authenticated_client.post(
        "/reports/generate",
        data={
            "idempotency_key": "manual-form-key-abcdefghijklmnopqrstuvwxyz",
            "report_type": "group",
            "report_date": "2026-07-10",
            "source_name": "",
        },
    )

    assert response.status_code == 403
    assert request_service.request_calls == []


def test_manual_report_service_validation_is_safe_422(
    authenticated_client: TestClient,
    report_request_dependencies,
) -> None:
    request_service, _ = report_request_dependencies
    request_service.error = ReportValidationError(
        "future date / secret SQL password=hunter2"
    )

    response = authenticated_client.post(
        "/reports/generate",
        data={
            "csrf_token": "csrf-token",
            "idempotency_key": "manual-form-key-abcdefghijklmnopqrstuvwxyz",
            "report_type": "all",
            "report_date": "2026-07-12",
            "source_name": "",
        },
    )

    assert response.status_code == 422
    assert "日报生成请求无效" in response.text
    assert "hunter2" not in response.text
    assert "future date" not in response.text


@pytest.mark.parametrize(
    ("status", "label", "polls"),
    [
        (ReportRequestStatus.PENDING, "等待处理", True),
        (ReportRequestStatus.RUNNING, "生成中", True),
        (ReportRequestStatus.SUCCESS, "生成成功", False),
        (ReportRequestStatus.PARTIAL_SUCCESS, "部分成功", False),
        (ReportRequestStatus.FAILED, "生成失败", False),
    ],
)
def test_report_request_status_polling_only_for_pending_and_running(
    authenticated_client: TestClient,
    report_request_dependencies,
    status: ReportRequestStatus,
    label: str,
    polls: bool,
) -> None:
    _, repo = report_request_dependencies
    repo.requests[41] = report_request(
        status=status,
        error_summary="&lt;safe failure&gt;" if status is ReportRequestStatus.FAILED else None,
    )

    response = authenticated_client.get("/reports/requests/41")

    assert response.status_code == 200
    assert label in response.text
    assert "核心群" in response.text
    assert "2026-07-10" in response.text
    if polls:
        assert 'hx-trigger="every 2s"' in response.text
        assert 'hx-get="/reports/requests/41"' in response.text
    else:
        assert "hx-trigger" not in response.text
        assert "hx-get" not in response.text
    assert "lease_expires_at" not in response.text
    assert "pipeline-1" not in response.text


@pytest.mark.parametrize("request_id", ["0", "-1", "abc", "999"])
def test_report_request_status_missing_or_invalid_is_safe_404(
    authenticated_client: TestClient,
    request_id: str,
) -> None:
    response = authenticated_client.get(f"/reports/requests/{request_id}")

    assert response.status_code == 404
    assert "日报请求不存在" in response.text
    assert "ValueError" not in response.text


def test_all_report_service_calls_run_in_threadpool(
    authenticated_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    async def recording_threadpool(function, *args, **kwargs):
        calls.append(function.__name__)
        return function(*args, **kwargs)

    monkeypatch.setattr(report_routes, "run_in_threadpool", recording_threadpool)

    assert authenticated_client.get("/reports?type=summary&date=2026-07-10").status_code == 200
    assert authenticated_client.get("/reports?type=group&date=2026-07-10&source=A").status_code == 200
    assert authenticated_client.get("/reports?type=article&date=2026-07-10&source=B").status_code == 200

    assert calls == ["load_sources", "list_reports", "get_report", "list_reports", "get_report"]


def test_new_post_status_and_download_calls_run_in_threadpool(
    authenticated_client: TestClient,
    report_request_dependencies,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, repo = report_request_dependencies
    repo.requests[41] = report_request()
    calls: list[str] = []

    async def recording_threadpool(function, *args, **kwargs):
        calls.append(function.__name__)
        return function(*args, **kwargs)

    monkeypatch.setattr(report_routes, "run_in_threadpool", recording_threadpool)

    post = authenticated_client.post(
        "/reports/generate",
        data={
            "csrf_token": "csrf-token",
            "idempotency_key": "manual-form-key-abcdefghijklmnopqrstuvwxyz",
            "report_type": "group",
            "report_date": "2026-07-10",
            "source_name": "核心群",
        },
        follow_redirects=False,
    )
    assert post.status_code == 303
    assert authenticated_client.get("/reports/requests/41").status_code == 200
    assert authenticated_client.get(
        "/reports/group/2026-07-10/%E6%A0%B8%E5%BF%83%E7%BE%A4.md"
    ).status_code == 200
    assert authenticated_client.get(
        "/reports/article/2026-07-10/%E8%A1%8C%E6%83%85%E8%A7%82%E5%AF%9F.md"
    ).status_code == 200
    assert authenticated_client.get("/reports/summary/2026-07-10.md").status_code == 200

    assert calls == [
        "request_manual",
        "get_request",
        "get_report",
        "get_report",
        "load_sources",
    ]


def test_default_report_request_dependencies_share_the_web_engine(
    config: Config,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import importlib

    web_app_module = importlib.import_module("app.web.app")
    engine = object()
    calls = []

    def fake_create_engine(mysql_config):
        calls.append(mysql_config)
        return engine

    monkeypatch.setattr(web_app_module, "create_mysql_engine", fake_create_engine)

    application = web_app_module.create_app(config)

    assert calls == [config.mysql]
    assert application.state.report_request_repo.engine is engine
    request_service = application.state.report_request_service
    assert request_service.repo is application.state.report_request_repo
    assert request_service.group_report_service.repo.engine is engine
    assert request_service.article_report_service.repo.engine is engine
    assert (
        request_service.summary_report_service.query_service
        is application.state.summary_report_service
    )
    assert application.state.group_report_service.repo.engine is engine
    assert application.state.article_report_service.repo.engine is engine
    assert application.state.summary_report_service.repo.engine is engine


class RecordingConnection:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def execute(self, statement, params):
        self.calls.append((str(statement), params))
        return self

    def mappings(self):
        return self

    def all(self):
        return []


class RecordingEngine:
    def __init__(self) -> None:
        self.connection = RecordingConnection()

    def begin(self):
        connection = self.connection

        class Context:
            def __enter__(self):
                return connection

            def __exit__(self, *args):
                return False

        return Context()


@pytest.mark.parametrize(
    ("repo_factory", "method_name", "source"),
    [
        (MysqlGroupDailyReportQueryRepo, "list_daily_reports", "群A"),
        (MysqlArticleDailyReportQueryRepo, "list_daily_reports", "号A"),
    ],
)
def test_report_repositories_apply_limit_and_offset(
    repo_factory, method_name: str, source: str
) -> None:
    engine = RecordingEngine()
    repo = repo_factory(engine)
    method = getattr(repo, method_name)

    method(REPORT_DATE, source, 21, 40)

    sql, params = engine.connection.calls[0]
    assert "LIMIT :limit" in sql
    assert "OFFSET :offset" in sql
    assert params["limit"] == 21
    assert params["offset"] == 40


def test_summary_query_service_and_repo_bound_both_lists() -> None:
    engine = RecordingEngine()
    service = SummaryDailyReportQueryService(
        repo=MysqlSummaryDailyReportQueryRepo(engine)
    )

    bundle = service.load_sources(REPORT_DATE, limit=11, offset=20)

    assert bundle.group_reports == []
    assert bundle.article_reports == []
    assert len(engine.connection.calls) == 2
    for sql, params in engine.connection.calls:
        assert "LIMIT :limit OFFSET :offset" in " ".join(sql.split())
        assert params == {"report_date": REPORT_DATE, "limit": 11, "offset": 20}
