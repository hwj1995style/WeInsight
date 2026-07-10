from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal

import pytest

from app.domain.admin_results import (
    ArticleDetailFilter,
    EggPriceDetailRow,
    GroupDetailFilter,
    PriceDetailFilter,
)
from app.storage.safe_result_query_repo import MysqlSafeResultQueryRepo


NOW = datetime(2026, 7, 10, 9, 30)


class Result:
    def __init__(self, *, rows=None, scalar=None) -> None:
        self.rows = list(rows or [])
        self.scalar = scalar

    def scalar_one(self):
        return self.scalar

    def mappings(self):
        return self

    def all(self):
        return self.rows


class Connection:
    def __init__(self, results) -> None:
        self.results = iter(results)
        self.executions: list[tuple[str, dict[str, object]]] = []

    def execute(self, statement, params=None):
        self.executions.append((str(statement), dict(params or {})))
        return next(self.results)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class Engine:
    def __init__(self, *, count=0, rows=None) -> None:
        self.connection = Connection(
            [Result(scalar=count), Result(rows=rows or [])]
        )
        self.begin_count = 0

    def begin(self):
        self.begin_count += 1
        return self.connection


GROUP_COLUMNS = {
    "row_id",
    "msg_hash",
    "group_name",
    "sender_display",
    "msg_time_inferred",
    "clean_content",
    "intent_type",
    "region_hits",
    "category_hits",
    "keyword_hits",
    "opportunity_score",
    "has_contact",
}
ARTICLE_COLUMNS = {
    "row_id",
    "article_hash",
    "account_name",
    "title",
    "publish_time",
    "quote_date",
    "collect_time",
    "summary_text",
    "topic_tags_json",
    "content_length",
    "analysis_version",
}
PRICE_COLUMNS = {
    "row_id",
    "account_name",
    "quote_date",
    "region",
    "market_name",
    "product_family",
    "product_name",
    "spec_text",
    "price_text",
    "price_low",
    "price_high",
    "price_unit_text",
    "standard_price_low",
    "standard_price_high",
    "standard_price_unit",
    "change_text",
    "change_value",
    "trend",
    "conversion_method",
    "conversion_confidence",
}


@pytest.mark.parametrize(
    ("method_name", "filters", "table", "allowed", "forbidden"),
    [
        (
            "list_group_details",
            GroupDetailFilter(),
            "wechat_group_msg_clean",
            GROUP_COLUMNS,
            {
                "wechat_group_msg_raw",
                "raw_content",
                "sender_hash",
                "has_phone",
                "has_wechat_id",
            },
        ),
        (
            "list_article_details",
            ArticleDetailFilter(),
            "wechat_article_analysis",
            ARTICLE_COLUMNS,
            {
                "article_url",
                "body_text",
                "html_content",
                "digest",
                "extracted_tables_json",
                "price_items_json",
                "keyword_hits_json",
            },
        ),
        (
            "list_price_details",
            PriceDetailFilter(),
            "wechat_article_egg_price_item",
            PRICE_COLUMNS,
            {
                "article_url",
                "body_text",
                "html_content",
                "digest",
                "source_context_json",
                "raw_headers_json",
                "raw_row_json",
                "parse_notes_json",
                "conversion_notes_json",
            },
        ),
    ],
)
def test_detail_queries_use_exact_safe_select_allowlists(
    method_name, filters, table, allowed, forbidden
) -> None:
    engine = Engine()

    getattr(MysqlSafeResultQueryRepo(engine), method_name)(
        filters, page=1, page_size=20
    )

    count_sql, data_sql = [sql for sql, _ in engine.connection.executions]
    assert table in count_sql
    assert table in data_sql
    assert _selected_output_names(data_sql) == allowed
    _assert_forbidden_identifiers_absent(count_sql, forbidden)
    _assert_forbidden_identifiers_absent(data_sql, forbidden)


@pytest.mark.parametrize(
    ("method_name", "filters", "expected_params", "where_fragments", "order_by"),
    [
        (
            "list_group_details",
            GroupDetailFilter(
                group_name="core'; DROP TABLE audit; --",
                start_at=NOW,
                end_at=datetime(2026, 7, 10, 10, 30),
                intent_type="demand",
            ),
            {
                "group_name": "core'; DROP TABLE audit; --",
                "start_at": NOW,
                "end_at": datetime(2026, 7, 10, 10, 30),
                "intent_type": "demand",
            },
            (
                "c.group_name = :group_name",
                "a.msg_time_inferred >= :start_at",
                "a.msg_time_inferred < :end_at",
                "a.intent_type = :intent_type",
            ),
            "ORDER BY a.msg_time_inferred DESC, a.id DESC",
        ),
        (
            "list_article_details",
            ArticleDetailFilter(
                account_name="acct' OR 1=1 --",
                publish_date=date(2026, 7, 9),
                quote_date=date(2026, 7, 10),
            ),
            {
                "account_name": "acct' OR 1=1 --",
                "publish_date": date(2026, 7, 9),
                "quote_date": date(2026, 7, 10),
            },
            (
                "a.account_name = :account_name",
                "a.publish_date = :publish_date",
                "a.quote_date = :quote_date",
            ),
            "ORDER BY a.publish_time DESC, a.id DESC",
        ),
        (
            "list_price_details",
            PriceDetailFilter(
                account_name="acct' UNION SELECT secret --",
                quote_date=date(2026, 7, 10),
                region="east%'; --",
                product_family="chicken_egg",
            ),
            {
                "account_name": "acct' UNION SELECT secret --",
                "quote_date": date(2026, 7, 10),
                "region": "east%'; --",
                "product_family": "chicken_egg",
            },
            (
                "p.account_name = :account_name",
                "p.quote_date = :quote_date",
                "p.region = :region",
                "p.product_family = :product_family",
            ),
            "ORDER BY p.quote_date DESC, p.id DESC",
        ),
    ],
)
def test_filters_are_bound_and_count_data_pagination_are_symmetric(
    method_name, filters, expected_params, where_fragments, order_by
) -> None:
    engine = Engine(count=17)

    result = getattr(MysqlSafeResultQueryRepo(engine), method_name)(
        filters, page=3, page_size=20
    )

    assert engine.begin_count == 1
    assert len(engine.connection.executions) == 2
    count_execution, data_execution = engine.connection.executions
    count_sql, count_params = count_execution
    data_sql, data_params = data_execution
    for fragment in where_fragments:
        assert fragment in count_sql
        assert fragment in data_sql
    assert count_params == expected_params
    assert data_params == {**expected_params, "limit": 20, "offset": 40}
    assert "LIMIT :limit OFFSET :offset" in data_sql
    assert order_by in " ".join(data_sql.split())
    for malicious_value in expected_params.values():
        if isinstance(malicious_value, str):
            assert malicious_value not in count_sql
            assert malicious_value not in data_sql
    assert result.total_count == 17
    assert isinstance(result.total_count, int)
    assert result.page == 3
    assert result.page_size == 20


def test_group_rows_parse_only_json_arrays_of_scalar_strings_and_warn_safely(
    caplog,
) -> None:
    secret = 'https://secret.invalid/body?q=private'
    engine = Engine(
        count=1,
        rows=[
            {
                "row_id": 41,
                "msg_hash": "m1",
                "group_name": "core",
                "sender_display": None,
                "msg_time_inferred": None,
                "clean_content": None,
                "intent_type": "demand",
                "region_hits": '["east", "north"]',
                "category_hits": '["egg", 7]',
                "keyword_hits": secret,
                "opportunity_score": None,
                "has_contact": None,
                "raw_content": secret,
            }
        ],
    )

    result = MysqlSafeResultQueryRepo(engine).list_group_details(
        GroupDetailFilter(), page=1, page_size=20
    )

    row = result.items[0]
    assert row.region_hits == ("east", "north")
    assert row.category_hits == ()
    assert row.keyword_hits == ()
    assert row.sender_display is None
    assert row.clean_content == ""
    assert row.opportunity_score == 0
    assert row.has_contact is False
    assert secret not in caplog.text
    assert "field=category_hits" in caplog.text
    assert "field=keyword_hits" in caplog.text
    assert "row_id=41" in caplog.text
    assert "raw_content" not in row.__dataclass_fields__


def test_article_rows_are_none_safe_and_do_not_retain_the_source_mapping() -> None:
    source_row = {
        "row_id": 8,
        "article_hash": "a1",
        "account_name": "news",
        "title": "daily market",
        "publish_time": None,
        "quote_date": None,
        "collect_time": None,
        "summary_text": None,
        "topic_tags_json": None,
        "content_length": None,
        "analysis_version": None,
        "article_url": "https://secret.invalid/article",
        "body_text": "secret body",
    }
    engine = Engine(count="1", rows=[source_row])

    result = MysqlSafeResultQueryRepo(engine).list_article_details(
        ArticleDetailFilter(), page=1, page_size=20
    )
    source_row["title"] = "mutated"

    row = result.items[0]
    assert row.title == "daily market"
    assert row.summary_text == ""
    assert row.topic_tags == ()
    assert row.content_length == 0
    assert row.analysis_version == ""
    assert result.total_count == 1
    assert "article_url" not in row.__dataclass_fields__
    assert "body_text" not in row.__dataclass_fields__


def test_price_row_maps_only_display_fields_and_numeric_values() -> None:
    engine = Engine(
        count=1,
        rows=[
            {
                "row_id": 9,
                "account_name": "market",
                "quote_date": date(2026, 7, 10),
                "region": "east",
                "market_name": None,
                "product_family": "chicken_egg",
                "product_name": None,
                "spec_text": None,
                "price_text": "135 yuan / 30 jin",
                "price_low": Decimal("135.000"),
                "price_high": None,
                "price_unit_text": None,
                "standard_price_low": Decimal("4.5000"),
                "standard_price_high": Decimal("4.5000"),
                "standard_price_unit": "yuan_per_jin",
                "change_text": None,
                "change_value": None,
                "trend": None,
                "conversion_method": None,
                "conversion_confidence": None,
                "raw_row_json": '["secret body"]',
            }
        ],
    )

    result = MysqlSafeResultQueryRepo(engine).list_price_details(
        PriceDetailFilter(), page=1, page_size=20
    )

    row = result.items[0]
    assert isinstance(row, EggPriceDetailRow)
    assert row.standard_price_low == Decimal("4.5000")
    assert row.standard_price_unit == "yuan_per_jin"
    assert row.trend == "unknown"
    assert row.conversion_method == "unconverted"
    assert row.conversion_confidence == Decimal("0")
    assert "raw_row_json" not in row.__dataclass_fields__


def test_allowlist_assertion_rejects_a_forbidden_select_mutation() -> None:
    engine = Engine()
    MysqlSafeResultQueryRepo(engine).list_article_details(
        ArticleDetailFilter(), page=1, page_size=20
    )
    data_sql = engine.connection.executions[1][0]
    mutated = data_sql.replace(
        "a.summary_text AS summary_text,",
        "a.summary_text AS summary_text, a.body_text AS body_text,",
    )

    assert _selected_output_names(mutated) != ARTICLE_COLUMNS
    with pytest.raises(AssertionError):
        _assert_forbidden_identifiers_absent(mutated, {"body_text"})


def _selected_output_names(sql: str) -> set[str]:
    match = re.search(r"\bSELECT\b(?P<select>.*?)\bFROM\b", sql, re.I | re.S)
    assert match is not None
    names: set[str] = set()
    for expression in match.group("select").split(","):
        normalized = " ".join(expression.split())
        alias = re.search(r"\bAS\s+([a-z_][a-z0-9_]*)$", normalized, re.I)
        if alias:
            names.add(alias.group(1).lower())
        else:
            names.add(normalized.rsplit(".", 1)[-1].lower())
    return names


def _assert_forbidden_identifiers_absent(
    sql: str, forbidden: set[str]
) -> None:
    identifiers = set(re.findall(r"[a-z_][a-z0-9_]*", sql.lower()))
    assert identifiers.isdisjoint(forbidden), identifiers & forbidden
