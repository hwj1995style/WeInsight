from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Generic, TypeVar


T = TypeVar("T")


@dataclass(frozen=True)
class PagedResult(Generic[T]):
    items: list[T]
    page: int
    page_size: int
    total_count: int


@dataclass(frozen=True)
class GroupDetailRow:
    msg_hash: str
    group_name: str
    sender_display: str | None
    msg_time_inferred: datetime | None
    clean_content: str
    intent_type: str
    region_hits: tuple[str, ...]
    category_hits: tuple[str, ...]
    keyword_hits: tuple[str, ...]
    opportunity_score: int
    has_contact: bool


@dataclass(frozen=True)
class ArticleDetailRow:
    article_hash: str
    account_name: str
    title: str
    publish_time: datetime | None
    quote_date: date | None
    collect_time: datetime | None
    summary_text: str
    topic_tags: tuple[str, ...]
    content_length: int
    analysis_version: str


@dataclass(frozen=True)
class EggPriceDetailRow:
    account_name: str
    quote_date: date | None
    region: str | None
    market_name: str | None
    product_family: str
    product_name: str | None
    spec_text: str | None
    price_text: str | None
    price_low: Decimal | None
    price_high: Decimal | None
    price_unit_text: str | None
    standard_price_low: Decimal | None
    standard_price_high: Decimal | None
    standard_price_unit: str
    change_text: str | None
    change_value: Decimal | None
    trend: str
    conversion_method: str
    conversion_confidence: Decimal


@dataclass(frozen=True)
class GroupDetailFilter:
    group_name: str | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None
    intent_type: str | None = None


@dataclass(frozen=True)
class ArticleDetailFilter:
    account_name: str | None = None
    publish_date: date | None = None
    quote_date: date | None = None


@dataclass(frozen=True)
class PriceDetailFilter:
    account_name: str | None = None
    quote_date: date | None = None
    region: str | None = None
    product_family: str | None = None
