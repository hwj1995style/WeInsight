from __future__ import annotations

import re
from dataclasses import fields
from datetime import date, datetime
from decimal import Decimal

import pytest

from app.domain.admin_results import (
    ArticleDetailFilter,
    ArticleDetailRow,
    EggPriceDetailRow,
    GroupDetailFilter,
    GroupDetailRow,
    PriceDetailFilter,
)
from app.storage.safe_result_query_repo import MysqlSafeResultQueryRepo
from app.domain.price_matrix import ACCOUNT_MATRIX_RULES, PriceMatrixSourceRow


NOW = datetime(2026, 7, 10, 9, 30)
NINE_ACCOUNT_NAMES = tuple(rule.account_name for rule in ACCOUNT_MATRIX_RULES)


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


class SingleQueryEngine:
    def __init__(self, result: Result) -> None:
        self.connection = Connection([result])

    def begin(self):
        return self.connection


def test_latest_matrix_date_is_scoped_to_safe_accounts_and_eligible_rows() -> None:
    engine = SingleQueryEngine(Result(scalar=date(2026, 7, 14)))

    result = MysqlSafeResultQueryRepo(engine).latest_price_quote_date(
        NINE_ACCOUNT_NAMES
    )

    sql, params = engine.connection.executions[0]
    assert result == date(2026, 7, 14)
    assert "MAX(p.quote_date)" in sql
    assert "p.account_name IN" in sql
    assert "p.include_in_egg_price = 1" in sql
    assert params == {f"account_{i}": name for i, name in enumerate(NINE_ACCOUNT_NAMES)}


def test_matrix_query_is_account_scoped_and_selects_only_safe_fields() -> None:
    engine = SingleQueryEngine(Result(rows=[]))
    repo = MysqlSafeResultQueryRepo(engine)

    repo.list_price_matrix_rows(date(2026, 7, 14), NINE_ACCOUNT_NAMES)

    sql, params = engine.connection.executions[0]
    normalized = " ".join(sql.split())
    assert "p.quote_date = :quote_date" in normalized
    assert "p.account_name IN" in normalized
    assert "p.include_in_egg_price = 1" in normalized
    assert "p.product_family = :product_family" in normalized
    assert "p.article_hash AS article_hash" in sql
    assert "p.weight_low AS weight_low" in sql
    assert params["quote_date"] == date(2026, 7, 14)
    assert params["product_family"] == "chicken_egg"
    assert tuple(params[f"account_{i}"] for i in range(9)) == NINE_ACCOUNT_NAMES
    for forbidden in ("article_url", "raw_row_json", "raw_headers_json", "runtime_content"):
        assert forbidden not in sql


def test_matrix_query_maps_safe_source_rows() -> None:
    source = {
        "row_id": 7, "article_hash": "hash", "account_name": NINE_ACCOUNT_NAMES[0],
        "quote_date": date(2026, 7, 14), "publish_time": NOW, "analyze_time": NOW,
        "region": None, "market_name": "market", "product_family": "chicken_egg",
        "include_in_egg_price": 1, "spec_text": "45斤", "weight_low": "45",
        "weight_high": None, "price_low": "180", "price_high": "182",
        "price_unit_text": "元/箱", "raw_row_json": "secret",
    }
    engine = SingleQueryEngine(Result(rows=[source]))

    rows = MysqlSafeResultQueryRepo(engine).list_price_matrix_rows(
        date(2026, 7, 14), NINE_ACCOUNT_NAMES
    )

    assert rows == [PriceMatrixSourceRow(
        row_id=7, article_hash="hash", account_name=NINE_ACCOUNT_NAMES[0],
        quote_date=date(2026, 7, 14), publish_time=NOW, analyze_time=NOW,
        region=None, market_name="market", product_family="chicken_egg",
        include_in_egg_price=True, spec_text="45斤", weight_low=Decimal("45"),
        weight_high=None, price_low=Decimal("180"), price_high=Decimal("182"),
        price_unit_text="元/箱",
    )]


GROUP_SOURCES = (
    ("wechat_group_msg_clean", "c"),
    ("wechat_group_msg_analysis", "a"),
)
GROUP_SELECT_MAPPING = (
    ("a", "id", "row_id"),
    ("c", "msg_hash", "msg_hash"),
    ("c", "group_name", "group_name"),
    ("c", "sender_display", "sender_display"),
    ("a", "msg_time_inferred", "msg_time_inferred"),
    ("c", "clean_content", "clean_content"),
    ("a", "intent_type", "intent_type"),
    ("a", "region_hits", "region_hits"),
    ("a", "category_hits", "category_hits"),
    ("a", "keyword_hits", "keyword_hits"),
    ("a", "opportunity_score", "opportunity_score"),
    ("a", "has_contact", "has_contact"),
)
ARTICLE_SOURCES = (("wechat_article_analysis", "a"),)
ARTICLE_SELECT_MAPPING = (
    ("a", "id", "row_id"),
    ("a", "article_hash", "article_hash"),
    ("a", "account_name", "account_name"),
    ("a", "title", "title"),
    ("a", "publish_time", "publish_time"),
    ("a", "quote_date", "quote_date"),
    ("a", "collect_time", "collect_time"),
    ("a", "summary_text", "summary_text"),
    ("a", "topic_tags_json", "topic_tags_json"),
    ("a", "content_length", "content_length"),
    ("a", "analysis_version", "analysis_version"),
)
PRICE_SOURCES = (("wechat_article_egg_price_item", "p"),)
PRICE_SELECT_MAPPING = (
    ("p", "id", "row_id"),
    ("p", "account_name", "account_name"),
    ("p", "quote_date", "quote_date"),
    ("p", "region", "region"),
    ("p", "market_name", "market_name"),
    ("p", "product_family", "product_family"),
    ("p", "product_name", "product_name"),
    ("p", "spec_text", "spec_text"),
    ("p", "price_text", "price_text"),
    ("p", "price_low", "price_low"),
    ("p", "price_high", "price_high"),
    ("p", "price_unit_text", "price_unit_text"),
    ("p", "standard_price_low", "standard_price_low"),
    ("p", "standard_price_high", "standard_price_high"),
    ("p", "standard_price_unit", "standard_price_unit"),
    ("p", "change_text", "change_text"),
    ("p", "change_value", "change_value"),
    ("p", "trend", "trend"),
    ("p", "conversion_method", "conversion_method"),
    ("p", "conversion_confidence", "conversion_confidence"),
)


@pytest.mark.parametrize(
    (
        "method_name",
        "filters",
        "expected_sources",
        "expected_mapping",
        "forbidden",
    ),
    [
        (
            "list_group_details",
            GroupDetailFilter(),
            GROUP_SOURCES,
            GROUP_SELECT_MAPPING,
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
            ARTICLE_SOURCES,
            ARTICLE_SELECT_MAPPING,
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
            PRICE_SOURCES,
            PRICE_SELECT_MAPPING,
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
def test_detail_queries_use_exact_sources_and_ordered_column_mappings(
    method_name, filters, expected_sources, expected_mapping, forbidden
) -> None:
    engine = Engine()

    getattr(MysqlSafeResultQueryRepo(engine), method_name)(
        filters, page=1, page_size=20
    )

    count_sql, data_sql = [sql for sql, _ in engine.connection.executions]
    _assert_query_shape(
        count_sql,
        data_sql,
        expected_sources=expected_sources,
        expected_mapping=expected_mapping,
        forbidden=forbidden,
    )


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


def test_article_shape_rejects_safe_alias_spoofing_and_an_extra_join() -> None:
    data_sql = _captured_data_sql("list_article_details", ArticleDetailFilter())
    mutated = data_sql.replace(
        "a.summary_text AS summary_text",
        "p.source_context_json AS summary_text",
    ).replace(
        "FROM wechat_article_analysis AS a",
        """FROM wechat_article_analysis AS a
           JOIN wechat_article_egg_price_item AS p
             ON p.article_hash = a.article_hash""",
    )
    assert mutated != data_sql

    with pytest.raises(AssertionError):
        _assert_data_query_shape(
            mutated,
            expected_sources=ARTICLE_SOURCES,
            expected_mapping=ARTICLE_SELECT_MAPPING,
        )


@pytest.mark.parametrize("mutation", ["remove_analysis", "add_extra_table"])
def test_group_shape_requires_only_clean_and_analysis_sources(mutation) -> None:
    data_sql = _captured_data_sql("list_group_details", GroupDetailFilter())
    if mutation == "remove_analysis":
        mutated = data_sql.replace(
            """INNER JOIN wechat_group_msg_analysis AS a
                ON a.msg_hash = c.msg_hash""",
            "",
        )
    else:
        mutated = data_sql.replace(
            "ON a.msg_hash = c.msg_hash",
            """ON a.msg_hash = c.msg_hash
               JOIN wechat_article_analysis AS x
                 ON x.article_hash = c.msg_hash""",
        )
    assert mutated != data_sql

    with pytest.raises(AssertionError):
        _assert_data_query_shape(
            mutated,
            expected_sources=GROUP_SOURCES,
            expected_mapping=GROUP_SELECT_MAPPING,
        )


@pytest.mark.parametrize(
    ("safe_expression", "unsafe_expression"),
    [
        ("p.price_text AS price_text", "p.raw_row_json AS price_text"),
        ("p.spec_text AS spec_text", "p.raw_headers_json AS spec_text"),
    ],
)
def test_price_shape_rejects_raw_columns_spoofing_safe_aliases(
    safe_expression, unsafe_expression
) -> None:
    data_sql = _captured_data_sql("list_price_details", PriceDetailFilter())
    mutated = data_sql.replace(safe_expression, unsafe_expression)
    assert mutated != data_sql

    with pytest.raises(AssertionError):
        _assert_data_query_shape(
            mutated,
            expected_sources=PRICE_SOURCES,
            expected_mapping=PRICE_SELECT_MAPPING,
        )


def test_query_shape_parser_ignores_comments_case_and_token_whitespace() -> None:
    data_sql = _captured_data_sql("list_article_details", ArticleDetailFilter())
    variant = (
        "/* harmless BODY_TEXT mention in a comment */\n"
        + data_sql.upper()
        .replace("A.ID", "A /*column owner*/ . ID")
        .replace(" AS ", "\n AS\t")
    )

    _assert_data_query_shape(
        variant,
        expected_sources=ARTICLE_SOURCES,
        expected_mapping=ARTICLE_SELECT_MAPPING,
    )


def test_result_dto_fields_are_exact_for_all_three_query_types() -> None:
    assert {field.name for field in fields(GroupDetailRow)} == {
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
    assert {field.name for field in fields(ArticleDetailRow)} == {
        "article_hash",
        "account_name",
        "title",
        "publish_time",
        "quote_date",
        "collect_time",
        "summary_text",
        "topic_tags",
        "content_length",
        "analysis_version",
    }
    assert {field.name for field in fields(EggPriceDetailRow)} == {
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


def _captured_data_sql(method_name: str, filters: object) -> str:
    engine = Engine()
    getattr(MysqlSafeResultQueryRepo(engine), method_name)(
        filters, page=1, page_size=20
    )
    return engine.connection.executions[1][0]


def _assert_query_shape(
    count_sql: str,
    data_sql: str,
    *,
    expected_sources: tuple[tuple[str, str], ...],
    expected_mapping: tuple[tuple[str, str, str], ...],
    forbidden: set[str],
) -> None:
    assert _source_tables(count_sql) == expected_sources
    assert _source_tables(data_sql) == expected_sources
    assert _normalized_select_list(count_sql) == "count(*) as total_count"
    _assert_data_query_shape(
        data_sql,
        expected_sources=expected_sources,
        expected_mapping=expected_mapping,
    )
    _assert_forbidden_identifiers_absent(count_sql, forbidden)
    _assert_forbidden_identifiers_absent(data_sql, forbidden)


def _assert_data_query_shape(
    sql: str,
    *,
    expected_sources: tuple[tuple[str, str], ...],
    expected_mapping: tuple[tuple[str, str, str], ...],
) -> None:
    assert _source_tables(sql) == expected_sources
    assert _selected_column_mapping(sql) == expected_mapping


def _source_tables(sql: str) -> tuple[tuple[str, str], ...]:
    normalized = _normalize_sql(sql)
    identifier = r"[a-z_][a-z0-9_]*"
    reserved = (
        "inner|left|right|full|cross|join|on|where|group|order|having|limit|offset"
    )
    pattern = re.compile(
        rf"\b(?:from|join)\s+"
        rf"(?P<table>{identifier})"
        rf"(?:\s+(?:as\s+)?(?P<alias>(?!(?:{reserved})\b){identifier}))?"
    )
    return tuple(
        (match.group("table"), match.group("alias") or "")
        for match in pattern.finditer(normalized)
    )


def _selected_column_mapping(sql: str) -> tuple[tuple[str, str, str], ...]:
    expressions = _split_select_expressions(_normalized_select_list(sql))
    mapping: list[tuple[str, str, str]] = []
    for expression in expressions:
        match = re.fullmatch(
            r"(?P<table>[a-z_][a-z0-9_]*)\s*\.\s*"
            r"(?P<column>[a-z_][a-z0-9_]*)\s+as\s+"
            r"(?P<output>[a-z_][a-z0-9_]*)",
            expression,
        )
        assert match is not None, f"non-canonical SELECT expression: {expression}"
        mapping.append(
            (match.group("table"), match.group("column"), match.group("output"))
        )
    return tuple(mapping)


def _normalized_select_list(sql: str) -> str:
    normalized = _normalize_sql(sql)
    match = re.search(r"\bselect\s+(?P<select>.*?)\s+from\b", normalized)
    assert match is not None
    return match.group("select").strip()


def _split_select_expressions(select_list: str) -> tuple[str, ...]:
    expressions: list[str] = []
    start = 0
    depth = 0
    for index, character in enumerate(select_list):
        if character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
            assert depth >= 0, "unbalanced SELECT expression parentheses"
        elif character == "," and depth == 0:
            expressions.append(select_list[start:index].strip())
            start = index + 1
    assert depth == 0, "unbalanced SELECT expression parentheses"
    expressions.append(select_list[start:].strip())
    assert all(expressions), "empty SELECT expression"
    return tuple(expressions)


def _assert_forbidden_identifiers_absent(
    sql: str, forbidden: set[str]
) -> None:
    identifiers = set(
        re.findall(r"[a-z_][a-z0-9_]*", _normalize_sql(sql))
    )
    assert identifiers.isdisjoint(forbidden), identifiers & forbidden


def _normalize_sql(sql: str) -> str:
    without_comments = re.sub(
        r"/\*.*?\*/|--[^\r\n]*|#[^\r\n]*",
        " ",
        sql,
        flags=re.S,
    )
    without_identifier_quotes = without_comments.replace("`", "")
    return " ".join(without_identifier_quotes.lower().split())
