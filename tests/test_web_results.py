from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import Config, load_config
from app.domain.admin_results import (
    ArticleDetailRow,
    EggPriceDetailRow,
    GroupDetailRow,
    PagedResult,
)
from app.domain.price_matrix import (
    AccountMatrixRule,
    PriceMatrix,
    PriceMatrixCell,
    PriceMatrixColumn,
    PriceMatrixRow,
)
from app.services.auth_service import AuthenticatedAdmin
from app.web.app import create_app
from app.web.routes import results as result_routes


class FakeAuthService:
    admin = AuthenticatedAdmin(id=1, username="admin", using_default_password=False)

    def authenticate(self, session_token, csrf_token, now):
        return self.admin if session_token == "session-token" else None


class FakeResultService:
    def __init__(self) -> None:
        self.calls: list[tuple] = []
        columns = (
            PriceMatrixColumn("henan:low", "河南金咕咕蛋品", "低价", "元/斤", "low"),
            PriceMatrixColumn("henan:high", "河南金咕咕蛋品", "高价", "元/斤", "high"),
            PriceMatrixColumn("guiyang:single", "贵阳鸡蛋价格", "报价", "元/箱", "single"),
        )
        self.matrix: PriceMatrix | None = PriceMatrix(
            quote_date=date(2026, 7, 14),
            updated_at=datetime(2026, 7, 14, 9, 30),
            source_count=3,
            columns=columns,
            rows=tuple(
                PriceMatrixRow(
                    size=size,
                    cells={
                        "henan:low": PriceMatrixCell(Decimal("4.80"), "observed"),
                        "henan:high": PriceMatrixCell(Decimal("5.00"), "observed"),
                        "guiyang:single": PriceMatrixCell(
                            Decimal("236") if size == 50 else Decimal("216"),
                            "extrapolated" if size == 50 else "observed",
                            "依据 39码 214 与 40码 216，按每码 +2 向高码推算"
                            if size == 50
                            else None,
                        ),
                    },
                )
                for size in range(50, 29, -1)
            ),
            rules=(
                AccountMatrixRule("河南金咕咕蛋品", "元/斤"),
                AccountMatrixRule("贵阳鸡蛋价格", "元/箱"),
            ),
        )

    def list_group_details(self, filters, page: int, page_size: int):
        self.calls.append(("group", filters, page, page_size))
        return PagedResult(
            items=[
                GroupDetailRow(
                    msg_hash="secret-hash-must-not-render",
                    group_name="核心群",
                    sender_display="脱敏发送人",
                    msg_time_inferred=datetime(2026, 7, 10, 9, 30),
                    clean_content="脱敏内容",
                    intent_type="demand",
                    region_hits=("华东",),
                    category_hits=("鸡蛋",),
                    keyword_hits=("采购",),
                    opportunity_score=88,
                    has_contact=True,
                )
            ],
            page=page,
            page_size=page_size,
            total_count=21,
        )

    def list_article_details(self, filters, page: int, page_size: int):
        self.calls.append(("article", filters, page, page_size))
        return PagedResult(
            items=[
                ArticleDetailRow(
                    article_hash="secret-article-hash",
                    account_name="行情观察",
                    title="今日报价摘要",
                    publish_time=datetime(2026, 7, 10, 8),
                    quote_date=date(2026, 7, 10),
                    collect_time=datetime(2026, 7, 10, 8, 10),
                    summary_text="只含安全摘要",
                    topic_tags=("蛋价",),
                    content_length=320,
                    analysis_version="v1",
                )
            ],
            page=page,
            page_size=page_size,
            total_count=1,
        )

    def list_price_details(self, filters, page: int, page_size: int):
        self.calls.append(("price", filters, page, page_size))
        return PagedResult(
            items=[
                EggPriceDetailRow(
                    account_name="行情观察",
                    quote_date=date(2026, 7, 10),
                    region="华东",
                    market_name="样例市场",
                    product_family="chicken_egg",
                    product_name="红蛋",
                    spec_text="箱装",
                    price_text="原始报价 123",
                    price_low=Decimal("3.10"),
                    price_high=Decimal("3.20"),
                    price_unit_text="元/斤",
                    standard_price_low=Decimal("3.10"),
                    standard_price_high=Decimal("3.20"),
                    standard_price_unit="CNY/500g",
                    change_text="上涨",
                    change_value=Decimal("0.10"),
                    trend="up",
                    conversion_method="identity",
                    conversion_confidence=Decimal("0.99"),
                )
            ],
            page=page,
            page_size=page_size,
            total_count=1,
        )

    def get_price_matrix(self, quote_date):
        self.calls.append(("price_matrix", quote_date))
        return self.matrix


@pytest.fixture
def config() -> Config:
    return load_config(Path("config/config.dev.yaml"))


@pytest.fixture
def result_service() -> FakeResultService:
    return FakeResultService()


@pytest.fixture
def app(config: Config, result_service: FakeResultService) -> FastAPI:
    return create_app(
        config,
        auth_service=FakeAuthService(),
        result_service=result_service,
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


def test_group_results_render_clean_content_only_and_preserve_filters(
    authenticated_client: TestClient,
    result_service: FakeResultService,
) -> None:
    response = authenticated_client.get(
        "/results/groups?group_name=%E6%A0%B8%E5%BF%83%E7%BE%A4&"
        "intent_type=demand&page=1&page_size=20"
    )

    assert response.status_code == 200
    assert "脱敏内容" in response.text
    assert "脱敏发送人" in response.text
    assert "secret-hash" not in response.text
    assert "raw_content" not in response.text
    assert "wechat_group_msg_raw" not in response.text
    assert 'name="group_name" value="核心群"' in response.text
    assert "page=2" in response.text
    assert "%E6%A0%B8%E5%BF%83%E7%BE%A4" in response.text
    assert result_service.calls[0][0] == "group"
    assert result_service.calls[0][1].group_name == "核心群"


def test_article_results_do_not_render_original_or_hidden_fields(
    authenticated_client: TestClient,
) -> None:
    response = authenticated_client.get("/results/articles")

    assert response.status_code == 200
    assert "只含安全摘要" in response.text
    assert "secret-article-hash" not in response.text
    for forbidden in (
        "article_url",
        "打开原文",
        "正文",
        "raw json",
        "runtime_content",
        "https://mp.weixin.qq.com",
    ):
        assert forbidden.lower() not in response.text.lower()


def test_price_results_render_matrix_groups_units_and_extrapolation(
    authenticated_client: TestClient,
) -> None:
    response = authenticated_client.get("/results/prices?quote_date=2026-07-14")

    assert response.status_code == 200
    assert "公众号报价矩阵" in response.text
    assert "河南金咕咕（元/斤）" in response.text
    assert "贵阳鸡蛋" in response.text
    assert "低价" in response.text and "高价" in response.text
    assert 'data-price-source="extrapolated"' in response.text
    assert "依据 39码 214 与 40码 216" in response.text
    assert "取数规则" in response.text


def test_price_matrix_uses_service_default_date_and_never_renders_sensitive_fields(
    authenticated_client: TestClient,
    result_service: FakeResultService,
) -> None:
    response = authenticated_client.get("/results/prices")

    assert response.status_code == 200
    assert 'name="quote_date" value="2026-07-14"' in response.text
    assert result_service.calls[-1] == ("price_matrix", None)
    for forbidden in (
        "article_url",
        "raw_row_json",
        "runtime_content",
        "https://mp.weixin.qq.com",
    ):
        assert forbidden not in response.text


def test_price_matrix_empty_state(
    authenticated_client: TestClient,
    result_service: FakeResultService,
) -> None:
    result_service.matrix = None

    response = authenticated_client.get("/results/prices")

    assert response.status_code == 200
    assert "暂无可展示的公众号报价" in response.text


@pytest.mark.parametrize("query", ["account_name=x", "page=1", "region=x"])
def test_price_matrix_rejects_unknown_query_parameters(
    authenticated_client: TestClient,
    query: str,
) -> None:
    response = authenticated_client.get(f"/results/prices?{query}")

    assert response.status_code == 422
    assert "查询条件无效" in response.text


def test_result_templates_autoescape_untrusted_safe_dto_text(
    authenticated_client: TestClient,
    result_service: FakeResultService,
) -> None:
    result_service.list_article_details = lambda filters, page, page_size: PagedResult(
        items=[
            ArticleDetailRow(
                article_hash="not-rendered",
                account_name='<img src=x onerror="bad()">',
                title="<script>alert(1)</script>",
                publish_time=None,
                quote_date=None,
                collect_time=None,
                summary_text='<span style="color:red">摘要</span>',
                topic_tags=("<iframe>",),
                content_length=1,
                analysis_version="v1",
            )
        ],
        page=page,
        page_size=page_size,
        total_count=1,
    )

    response = authenticated_client.get("/results/articles")

    assert response.status_code == 200
    assert "<script>" not in response.text
    assert "<img src=" not in response.text
    assert "&lt;script&gt;" in response.text
    assert "&lt;img" in response.text
    assert "onerror=&#34;bad()&#34;" in response.text
    assert "style=&#34;color:red&#34;" in response.text


@pytest.mark.parametrize(
    "path",
    [
        "/results/groups?page=1&page_size=101",
        "/results/articles?page=zero&page_size=20",
        "/results/prices?quote_date=not-a-date",
        "/results/groups?start_at=2026-07-10T10:00&end_at=2026-07-10T09:00",
    ],
)
def test_invalid_result_queries_return_safe_html_422(
    authenticated_client: TestClient,
    path: str,
) -> None:
    response = authenticated_client.get(path)

    assert response.status_code == 422
    assert response.headers["content-type"].startswith("text/html")
    assert "查询条件无效" in response.text
    assert "Traceback" not in response.text
    assert "ValueError" not in response.text


def test_result_pages_require_authentication(raw_client: TestClient) -> None:
    response = raw_client.get("/results/groups", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_result_service_calls_run_in_threadpool(
    authenticated_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    async def recording_threadpool(function, *args, **kwargs):
        calls.append(function.__name__)
        return function(*args, **kwargs)

    monkeypatch.setattr(result_routes, "run_in_threadpool", recording_threadpool)

    for path in ("/results/groups", "/results/articles", "/results/prices"):
        assert authenticated_client.get(path).status_code == 200

    assert calls == [
        "list_group_details",
        "list_article_details",
        "get_price_matrix",
    ]


def test_result_tables_have_accessible_scroll_regions_and_empty_state(
    authenticated_client: TestClient,
    result_service: FakeResultService,
) -> None:
    result_service.list_group_details = lambda filters, page, page_size: PagedResult(
        items=[], page=page, page_size=page_size, total_count=0
    )

    response = authenticated_client.get("/results/groups")

    assert 'class="table-scroll"' in response.text
    assert 'tabindex="0"' in response.text
    assert 'aria-label="微信群结果明细"' in response.text
    assert "暂无符合条件的群明细" in response.text
