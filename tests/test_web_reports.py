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
from app.storage.article_daily_report_query_repo import (
    MysqlArticleDailyReportQueryRepo,
)
from app.storage.group_daily_report_query_repo import MysqlGroupDailyReportQueryRepo
from app.storage.summary_daily_report_query_repo import MysqlSummaryDailyReportQueryRepo
from app.web.app import create_app
from app.web.routes import reports as report_routes


REPORT_DATE = date(2026, 7, 10)
GENERATED_AT = datetime(2026, 7, 10, 23, 55)
CUTOFF_AT = datetime(2026, 7, 10, 23, 50, tzinfo=ZoneInfo("Asia/Shanghai"))


class FakeAuthService:
    admin = AuthenticatedAdmin(id=1, username="admin", using_default_password=False)

    def authenticate(self, session_token, csrf_token, now):
        return self.admin if session_token == "session-token" else None


class FakeGroupReportService:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

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
                report_status=ReportStatus.PROVISIONAL,
                data_cutoff_time=CUTOFF_AT,
                generation_trigger=GenerationTrigger.MANUAL,
                last_generated_by="admin",
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
            report_status=ReportStatus.PROVISIONAL,
            data_cutoff_time=CUTOFF_AT,
            generation_trigger=GenerationTrigger.MANUAL,
            last_generated_by="admin",
        )


class FakeArticleReportService:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

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
                report_status=ReportStatus.PROVISIONAL,
                data_cutoff_time=CUTOFF_AT,
                generation_trigger=GenerationTrigger.MANUAL,
                last_generated_by="admin",
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
            report_status=ReportStatus.PROVISIONAL,
            data_cutoff_time=CUTOFF_AT,
            generation_trigger=GenerationTrigger.MANUAL,
            last_generated_by="admin",
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
def app(config: Config, report_services) -> FastAPI:
    group, article, summary = report_services
    return create_app(
        config,
        auth_service=FakeAuthService(),
        group_report_service=group,
        article_report_service=article,
        summary_report_service=summary,
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
