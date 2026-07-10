from __future__ import annotations

import json
from datetime import date, datetime

import pytest

from app.domain.article_analysis import AnalyzedArticle
from app.domain.article_egg_price import EggPriceItem
from app.storage.article_analysis_repo import MysqlArticleAnalysisRepo


class FakeResult:
    def __init__(self, rows=None, rowcount: int = 1) -> None:
        self._rows = rows or []
        self.rowcount = rowcount

    def mappings(self):
        return self

    def all(self):
        return self._rows


class FakeConnection:
    def __init__(self) -> None:
        self.executions: list[tuple[str, object]] = []

    def execute(self, statement, params=None):
        sql = str(statement)
        self.executions.append((sql, params))
        if "JOIN wechat_article_clean" in sql:
            return FakeResult(
                rows=[
                    {
                        "article_hash": "hash-1",
                        "account_name": "行业观察",
                        "title": "深圳供应链价格观察",
                        "article_url": "https://mp.weixin.qq.com/s/abc",
                        "publish_time": datetime(2026, 7, 6, 8, 30),
                        "collect_time": datetime(2026, 7, 6, 8, 5),
                        "author": "作者A",
                        "digest": "深圳企业关注报价和供需变化。",
                        "content_length": 1200,
                    }
                ]
            )
        return FakeResult(rowcount=1)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeEngine:
    def __init__(self) -> None:
        self.connection = FakeConnection()

    def begin(self):
        return self.connection

    @property
    def sql(self) -> list[str]:
        return [sql for sql, _ in self.connection.executions]

    @property
    def params(self) -> list[dict]:
        return [params for _, params in self.connection.executions]

    def params_by_sql_fragment(self, fragment: str) -> list[dict]:
        return [
            params
            for sql, params in self.connection.executions
            if fragment in sql
        ]


@pytest.fixture
def fake_engine() -> FakeEngine:
    return FakeEngine()


def test_mysql_article_analysis_repo_lists_pending_clean_articles_without_group_tables() -> None:
    engine = FakeEngine()
    repo = MysqlArticleAnalysisRepo(engine)

    articles = repo.list_pending_analyze_articles(limit=5)

    assert len(articles) == 1
    assert articles[0].article_hash == "hash-1"
    assert articles[0].article_url == "https://mp.weixin.qq.com/s/abc"
    assert articles[0].collect_time == datetime(2026, 7, 6, 8, 5)
    sql, params = engine.connection.executions[0]
    assert "FROM wechat_article_process_task" in sql
    assert "JOIN wechat_article_clean" in sql
    assert "JOIN wechat_article_raw" in sql
    assert "task.task_type = 'analyze_article'" in sql
    assert "task.status = 'pending'" in sql
    _assert_article_analysis_sql_is_isolated(sql)
    assert params["limit"] == 5


def test_mysql_article_analysis_repo_upserts_analysis_and_updates_article_tasks_only() -> None:
    engine = FakeEngine()
    repo = MysqlArticleAnalysisRepo(engine)
    analysis = AnalyzedArticle(
        article_hash="hash-1",
        account_name="行业观察",
        title="深圳供应链价格观察",
        publish_time=datetime(2026, 7, 6, 8, 30),
        publish_date=datetime(2026, 7, 6, 8, 30).date(),
        author="作者A",
        summary_text="深圳企业关注报价和供需变化。",
        topic_tags=["深圳", "湖北", "供应链", "报价", "供需"],
        keyword_hits=["深圳", "湖北", "供应链", "报价", "供需"],
        extracted_tables=[
            {
                "source_media_type": "html_table",
                "headers": ["规格", "毛重", "含包装价", "涨"],
                "rows": [["大码", "52斤以上", "208-213", "+8"]],
            }
        ],
        price_items=[
            {
                "source_media_type": "html_table",
                "spec": "大码",
                "weight": "52斤以上",
                "price": "208-213",
                "change": "+8",
            }
        ],
        content_length=1200,
        analysis_version="v1",
        analyze_time=datetime(2026, 7, 6, 9, 0),
    )

    repo.upsert_article_analysis_with_price_items(analysis)
    repo.create_daily_report_task(datetime(2026, 7, 6, 8, 30).date())
    repo.mark_analyze_task_success("hash-1")
    repo.mark_analyze_task_failed("hash-2", "analysis failed")

    executed_sql = "\n".join(sql for sql, _ in engine.connection.executions)
    assert "INSERT INTO wechat_article_analysis" in executed_sql
    assert "extracted_tables_json" in executed_sql
    assert "price_items_json" in executed_sql
    assert "INSERT INTO wechat_article_process_task" in executed_sql
    assert "task_type = 'analyze_article'" in executed_sql
    _assert_article_analysis_sql_is_isolated(executed_sql)

    analysis_params = engine.connection.executions[0][1]
    assert json.loads(analysis_params["topic_tags_json"]) == ["深圳", "湖北", "供应链", "报价", "供需"]
    assert json.loads(analysis_params["price_items_json"])["items"][0]["price"] == "208-213"
    assert "transient_body_text" not in analysis_params
    assert "html_content" not in analysis_params

    task_params = engine.params_by_sql_fragment("INSERT INTO wechat_article_process_task")[0]
    assert task_params["task_type"] == "article_daily_report"
    assert task_params["ref_id"] == "2026-07-06"


def test_mysql_article_analysis_repo_replaces_egg_price_items(fake_engine) -> None:
    repo = MysqlArticleAnalysisRepo(fake_engine)
    analysis = AnalyzedArticle(
        article_hash="hash-1",
        account_name="家美鲜鸡蛋 佳美鲜",
        title="报价",
        publish_time=datetime(2026, 7, 9, 9, 0),
        publish_date=date(2026, 7, 9),
        collect_time=datetime(2026, 7, 9, 9, 3),
        quote_date=date(2026, 7, 9),
        quote_date_source="title",
        quote_date_confidence=1.0,
        author=None,
        summary_text="报价",
        topic_tags=["报价"],
        keyword_hits=["报价"],
        extracted_tables=[],
        price_items=[],
        content_length=100,
        analysis_version="v1",
        analyze_time=datetime(2026, 7, 9, 10, 0),
        egg_price_items=[
            EggPriceItem(
                article_hash="hash-1",
                account_name="家美鲜鸡蛋 佳美鲜",
                title="报价",
                publish_time=datetime(2026, 7, 9, 9, 0),
                publish_date=date(2026, 7, 9),
                collect_time=datetime(2026, 7, 9, 9, 3),
                quote_date=date(2026, 7, 9),
                quote_date_source="title",
                quote_date_confidence=1.0,
                item_index=1,
                source_media_type="dom_table",
                source_table_index=0,
                source_row_index=1,
                source_table_title="通货装车价（含包装）",
                source_context={"quote_basis": "360枚/箱"},
                source_confidence=0.85,
                product_family="chicken_egg",
                product_name="鸡蛋",
                include_in_egg_price=True,
                region="湖北",
                market_name="兄弟蛋业",
                quote_basis="360枚/箱",
                trade_scene="装车",
                package_policy="含包装",
                spec_text="标价",
                weight_text="45",
                weight_low=45,
                weight_high=45,
                weight_unit=None,
                price_text="220",
                price_low=220,
                price_high=220,
                price_unit_text=None,
                yesterday_price_text="215",
                yesterday_price_low=215,
                yesterday_price_high=215,
                change_text="5",
                change_value=5,
                trend="up",
                raw_headers=["净重", "价差", "昨日价", "今日价", "涨跌"],
                raw_row=["45", "标价", "215", "220", "5"],
                row_note=None,
                parse_notes=[],
                analysis_version="egg_price_v1",
                analyze_time=datetime(2026, 7, 9, 10, 0),
                standard_price_low=4.8889,
                standard_price_high=4.8889,
                standard_price_unit="yuan_per_jin",
                conversion_basis_weight_low=45,
                conversion_basis_weight_high=45,
                conversion_basis_weight_unit="jin",
                conversion_method="row_weight",
                conversion_confidence=0.85,
                conversion_notes=[],
                include_in_standard_price=True,
            )
        ],
    )

    repo.upsert_article_analysis_with_price_items(analysis)

    executed_sql = "\n".join(fake_engine.sql)
    assert "INSERT INTO wechat_article_analysis" in executed_sql
    assert "DELETE FROM wechat_article_egg_price_item" in executed_sql
    assert "INSERT INTO wechat_article_egg_price_item" in executed_sql
    assert "wechat_group_" not in executed_sql
    analysis_params = fake_engine.params_by_sql_fragment("INSERT INTO wechat_article_analysis")[0]
    assert analysis_params["collect_time"] == datetime(2026, 7, 9, 9, 3)
    assert analysis_params["quote_date"] == date(2026, 7, 9)
    assert analysis_params["quote_date_source"] == "title"
    assert analysis_params["quote_date_confidence"] == 1.0
    insert_params = fake_engine.params_by_sql_fragment("INSERT INTO wechat_article_egg_price_item")[0]
    assert insert_params["article_hash"] == "hash-1"
    assert insert_params["collect_time"] == datetime(2026, 7, 9, 9, 3)
    assert insert_params["quote_date"] == date(2026, 7, 9)
    assert insert_params["quote_date_source"] == "title"
    assert insert_params["quote_date_confidence"] == 1.0
    assert insert_params["standard_price_low"] == 4.8889
    assert insert_params["standard_price_high"] == 4.8889
    assert insert_params["standard_price_unit"] == "yuan_per_jin"
    assert insert_params["conversion_basis_weight_low"] == 45
    assert insert_params["conversion_basis_weight_high"] == 45
    assert insert_params["conversion_basis_weight_unit"] == "jin"
    assert insert_params["conversion_method"] == "row_weight"
    assert insert_params["conversion_confidence"] == 0.85
    assert insert_params["conversion_notes_json"] == "[]"
    assert insert_params["include_in_standard_price"] == 1
    assert insert_params["source_context_json"] == '{"quote_basis": "360枚/箱"}'
    assert insert_params["raw_row_json"] == '["45", "标价", "215", "220", "5"]'


def _assert_article_analysis_sql_is_isolated(sql: str) -> None:
    assert "wechat_group_" not in sql
    assert "raw_content" not in sql
    assert "article_body" not in sql
    assert "body_text" not in sql
    assert "html_content" not in sql
    assert "ocr_raw" not in sql
