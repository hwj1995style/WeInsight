from __future__ import annotations

from dataclasses import fields
from datetime import date, datetime

import pytest

from app.domain.admin_results import (
    ArticleDetailFilter,
    ArticleDetailRow,
    EggPriceDetailRow,
    GroupDetailFilter,
    GroupDetailRow,
    PagedResult,
    PriceDetailFilter,
)
from app.services.result_query_service import ResultQueryService
from app.domain.price_matrix import ACCOUNT_MATRIX_RULES


class Repo:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object, int, int]] = []
        self.latest_date = None
        self.matrix_date = None

    def list_group_details(self, filters, page, page_size):
        self.calls.append(("group", filters, page, page_size))
        return PagedResult([], page, page_size, 0)

    def list_article_details(self, filters, page, page_size):
        self.calls.append(("article", filters, page, page_size))
        return PagedResult([], page, page_size, 0)

    def list_price_details(self, filters, page, page_size):
        self.calls.append(("price", filters, page, page_size))
        return PagedResult([], page, page_size, 0)

    def latest_price_quote_date(self, account_names):
        self.matrix_accounts = account_names
        return self.latest_date

    def list_price_matrix_rows(self, quote_date, account_names):
        self.matrix_date = quote_date
        self.matrix_accounts = account_names
        return []


def test_get_price_matrix_defaults_to_latest_date() -> None:
    repo = Repo()
    repo.latest_date = date(2026, 7, 14)

    matrix = ResultQueryService(repo).get_price_matrix(None)

    assert matrix.quote_date == date(2026, 7, 14)
    assert repo.matrix_date == date(2026, 7, 14)
    assert repo.matrix_accounts == tuple(rule.account_name for rule in ACCOUNT_MATRIX_RULES)


def test_get_price_matrix_returns_none_without_any_quote_date() -> None:
    repo = Repo()
    assert ResultQueryService(repo).get_price_matrix(None) is None
    assert repo.matrix_date is None


def test_get_price_matrix_rejects_datetime_before_repo_call() -> None:
    repo = Repo()
    with pytest.raises(TypeError):
        ResultQueryService(repo).get_price_matrix(datetime(2026, 7, 14))
    assert repo.matrix_date is None


@pytest.mark.parametrize(
    ("method_name", "filters"),
    [
        ("list_group_details", GroupDetailFilter()),
        ("list_article_details", ArticleDetailFilter()),
        ("list_price_details", PriceDetailFilter()),
    ],
)
def test_service_delegates_all_three_query_types_symmetrically(
    method_name, filters
) -> None:
    repo = Repo()
    service = ResultQueryService(repo)

    result = getattr(service, method_name)(filters, page=2, page_size=50)

    assert result == PagedResult([], 2, 50, 0)
    assert repo.calls == [(method_name.removeprefix("list_").removesuffix("_details"), filters, 2, 50)]


@pytest.mark.parametrize("page", [0, -1, True, 1.5, "1", None])
def test_service_rejects_invalid_page_before_repo_call(page) -> None:
    repo = Repo()

    with pytest.raises((TypeError, ValueError)):
        ResultQueryService(repo).list_group_details(
            GroupDetailFilter(), page=page, page_size=20
        )

    assert repo.calls == []


@pytest.mark.parametrize("page_size", [0, -1, 101, True, 1.5, "20", None])
def test_service_rejects_invalid_page_size_before_repo_call(page_size) -> None:
    repo = Repo()

    with pytest.raises((TypeError, ValueError)):
        ResultQueryService(repo).list_article_details(
            ArticleDetailFilter(), page=1, page_size=page_size
        )

    assert repo.calls == []


@pytest.mark.parametrize(
    ("method_name", "wrong_filter"),
    [
        ("list_group_details", ArticleDetailFilter()),
        ("list_article_details", PriceDetailFilter()),
        ("list_price_details", GroupDetailFilter()),
        ("list_group_details", object()),
        ("list_article_details", None),
    ],
)
def test_service_rejects_the_wrong_filter_type(method_name, wrong_filter) -> None:
    repo = Repo()

    with pytest.raises(TypeError):
        getattr(ResultQueryService(repo), method_name)(
            wrong_filter, page=1, page_size=20
        )

    assert repo.calls == []


@pytest.mark.parametrize(
    "filters",
    [
        GroupDetailFilter(group_name=""),
        GroupDetailFilter(group_name="   "),
        GroupDetailFilter(group_name="g" * 201),
        GroupDetailFilter(group_name=123),
        GroupDetailFilter(start_at=date(2026, 7, 10)),
        GroupDetailFilter(end_at="2026-07-10"),
        GroupDetailFilter(intent_type="other"),
        GroupDetailFilter(intent_type=1),
        GroupDetailFilter(
            start_at=datetime(2026, 7, 10, 10),
            end_at=datetime(2026, 7, 10, 10),
        ),
        GroupDetailFilter(
            start_at=datetime(2026, 7, 10, 11),
            end_at=datetime(2026, 7, 10, 10),
        ),
    ],
)
def test_group_filter_types_ranges_and_time_order_are_validated(filters) -> None:
    repo = Repo()

    with pytest.raises((TypeError, ValueError)):
        ResultQueryService(repo).list_group_details(filters, page=1, page_size=20)

    assert repo.calls == []


@pytest.mark.parametrize(
    "filters",
    [
        ArticleDetailFilter(account_name=""),
        ArticleDetailFilter(account_name="a" * 201),
        ArticleDetailFilter(account_name=7),
        ArticleDetailFilter(publish_date=datetime(2026, 7, 10)),
        ArticleDetailFilter(quote_date="2026-07-10"),
    ],
)
def test_article_filter_types_and_ranges_are_validated(filters) -> None:
    repo = Repo()

    with pytest.raises((TypeError, ValueError)):
        ResultQueryService(repo).list_article_details(filters, page=1, page_size=20)

    assert repo.calls == []


@pytest.mark.parametrize(
    "filters",
    [
        PriceDetailFilter(account_name=" "),
        PriceDetailFilter(account_name="a" * 201),
        PriceDetailFilter(quote_date=datetime(2026, 7, 10)),
        PriceDetailFilter(region=""),
        PriceDetailFilter(region="r" * 101),
        PriceDetailFilter(product_family="unsupported"),
        PriceDetailFilter(product_family=7),
    ],
)
def test_price_filter_types_ranges_and_enums_are_validated(filters) -> None:
    repo = Repo()

    with pytest.raises((TypeError, ValueError)):
        ResultQueryService(repo).list_price_details(filters, page=1, page_size=20)

    assert repo.calls == []


def test_valid_filter_boundary_values_are_accepted() -> None:
    repo = Repo()
    service = ResultQueryService(repo)
    start = datetime(2026, 7, 10, 8)
    end = datetime(2026, 7, 10, 9)

    service.list_group_details(
        GroupDetailFilter(
            group_name="g" * 200,
            start_at=start,
            end_at=end,
            intent_type="empty",
        ),
        page=1,
        page_size=100,
    )
    service.list_article_details(
        ArticleDetailFilter(
            account_name="a" * 200,
            publish_date=date(2026, 7, 10),
            quote_date=date(2026, 7, 9),
        ),
        page=1,
        page_size=1,
    )
    service.list_price_details(
        PriceDetailFilter(
            account_name="a" * 200,
            quote_date=date(2026, 7, 10),
            region="r" * 100,
            product_family="other_egg",
        ),
        page=1,
        page_size=100,
    )

    assert [call[0] for call in repo.calls] == ["group", "article", "price"]


def test_dto_fields_are_explicit_and_exclude_sensitive_source_columns() -> None:
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
    price_fields = {field.name for field in fields(EggPriceDetailRow)}
    assert {
        "account_name",
        "quote_date",
        "region",
        "market_name",
        "product_family",
        "product_name",
        "spec_text",
        "price_text",
        "standard_price_low",
        "standard_price_high",
        "standard_price_unit",
        "change_text",
        "change_value",
        "trend",
        "conversion_method",
        "conversion_confidence",
    }.issubset(price_fields)
    assert price_fields.isdisjoint(
        {
            "article_url",
            "body_text",
            "html_content",
            "digest",
            "raw_headers_json",
            "raw_row_json",
            "source_context_json",
        }
    )
