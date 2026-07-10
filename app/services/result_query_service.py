from __future__ import annotations

from datetime import date, datetime
from typing import Protocol

from app.domain.admin_results import (
    ArticleDetailFilter,
    ArticleDetailRow,
    EggPriceDetailRow,
    GroupDetailFilter,
    GroupDetailRow,
    PagedResult,
    PriceDetailFilter,
)


INTENT_TYPES = frozenset({"demand", "supply", "neutral", "empty"})
PRODUCT_FAMILIES = frozenset(
    {
        "chicken_egg",
        "duck_egg",
        "quail_egg",
        "preserved_egg",
        "salted_egg",
        "other_egg",
    }
)


class SafeResultQueryRepo(Protocol):
    def list_group_details(
        self, filters: GroupDetailFilter, page: int, page_size: int
    ) -> PagedResult[GroupDetailRow]: ...

    def list_article_details(
        self, filters: ArticleDetailFilter, page: int, page_size: int
    ) -> PagedResult[ArticleDetailRow]: ...

    def list_price_details(
        self, filters: PriceDetailFilter, page: int, page_size: int
    ) -> PagedResult[EggPriceDetailRow]: ...


class ResultQueryService:
    def __init__(self, repo: SafeResultQueryRepo) -> None:
        self.repo = repo

    def list_group_details(
        self, filters: GroupDetailFilter, page: int, page_size: int
    ) -> PagedResult[GroupDetailRow]:
        _validate_pagination(page, page_size)
        if not isinstance(filters, GroupDetailFilter):
            raise TypeError("filters must be a GroupDetailFilter")
        _validate_optional_string(filters.group_name, "group_name", 200)
        _validate_optional_datetime(filters.start_at, "start_at")
        _validate_optional_datetime(filters.end_at, "end_at")
        _validate_optional_enum(filters.intent_type, "intent_type", INTENT_TYPES)
        if (
            filters.start_at is not None
            and filters.end_at is not None
            and filters.start_at >= filters.end_at
        ):
            raise ValueError("start_at must be earlier than end_at")
        return self.repo.list_group_details(filters, page, page_size)

    def list_article_details(
        self, filters: ArticleDetailFilter, page: int, page_size: int
    ) -> PagedResult[ArticleDetailRow]:
        _validate_pagination(page, page_size)
        if not isinstance(filters, ArticleDetailFilter):
            raise TypeError("filters must be an ArticleDetailFilter")
        _validate_optional_string(filters.account_name, "account_name", 200)
        _validate_optional_date(filters.publish_date, "publish_date")
        _validate_optional_date(filters.quote_date, "quote_date")
        return self.repo.list_article_details(filters, page, page_size)

    def list_price_details(
        self, filters: PriceDetailFilter, page: int, page_size: int
    ) -> PagedResult[EggPriceDetailRow]:
        _validate_pagination(page, page_size)
        if not isinstance(filters, PriceDetailFilter):
            raise TypeError("filters must be a PriceDetailFilter")
        _validate_optional_string(filters.account_name, "account_name", 200)
        _validate_optional_date(filters.quote_date, "quote_date")
        _validate_optional_string(filters.region, "region", 100)
        _validate_optional_enum(
            filters.product_family, "product_family", PRODUCT_FAMILIES
        )
        return self.repo.list_price_details(filters, page, page_size)


def _validate_pagination(page: int, page_size: int) -> None:
    if not isinstance(page, int) or isinstance(page, bool):
        raise TypeError("page must be an integer")
    if page < 1:
        raise ValueError("page must be greater than 0")
    if not isinstance(page_size, int) or isinstance(page_size, bool):
        raise TypeError("page_size must be an integer")
    if page_size < 1 or page_size > 100:
        raise ValueError("page_size must be between 1 and 100")


def _validate_optional_string(
    value: object, field_name: str, max_length: int
) -> None:
    if value is None:
        return
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    if not value.strip() or len(value) > max_length:
        raise ValueError(
            f"{field_name} must contain between 1 and {max_length} characters"
        )


def _validate_optional_datetime(value: object, field_name: str) -> None:
    if value is not None and not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")


def _validate_optional_date(value: object, field_name: str) -> None:
    if value is not None and type(value) is not date:
        raise TypeError(f"{field_name} must be a date")


def _validate_optional_enum(
    value: object, field_name: str, allowed: frozenset[str]
) -> None:
    if value is None:
        return
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    if value not in allowed:
        raise ValueError(f"{field_name} has an unsupported value")
