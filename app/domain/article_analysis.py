from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from app.domain.article_egg_price import (
    EggPriceExtraction,
    EggPriceItem,
    extract_egg_prices,
    resolve_quote_date,
)


TRACKED_KEYWORDS = ("深圳", "湖北", "供应链", "报价", "供需", "招聘", "政策", "市场")


@dataclass(frozen=True)
class CleanArticleForAnalysis:
    article_hash: str
    account_name: str
    title: str
    publish_time: datetime | None
    author: str | None
    digest: str | None
    content_length: int
    article_url: str = ""
    content_locator: str | None = None
    content_locator_type: str | None = None
    collect_time: datetime | None = None
    transient_body_text: str | None = None
    transient_html_tables: list[dict[str, Any]] | None = None
    transient_ocr_tables: list[dict[str, Any]] | None = None


@dataclass(frozen=True)
class AnalyzedArticle:
    article_hash: str
    account_name: str
    title: str
    publish_time: datetime | None
    publish_date: date | None
    author: str | None
    summary_text: str
    topic_tags: list[str]
    keyword_hits: list[str]
    extracted_tables: list[dict[str, Any]]
    price_items: list[dict[str, Any]]
    content_length: int
    analysis_version: str
    analyze_time: datetime
    collect_time: datetime | None = None
    quote_date: date | None = None
    quote_date_source: str = "unknown"
    quote_date_confidence: float = 0.0
    egg_price_items: list[EggPriceItem] = field(default_factory=list)
    extraction_notes: list[dict[str, Any]] = field(default_factory=list)

    def topic_tags_json(self) -> str:
        return json.dumps(self.topic_tags, ensure_ascii=False)

    def keyword_hits_json(self) -> str:
        return json.dumps(self.keyword_hits, ensure_ascii=False)

    def extracted_tables_json(self) -> str:
        return json.dumps(
            {
                "version": "egg_table_summary_v1",
                "tables": self.extracted_tables,
                "notes": self.extraction_notes,
            },
            ensure_ascii=False,
        )

    def price_items_json(self) -> str:
        preview_limit = len(self.price_items)
        return json.dumps(
            {
                "version": "egg_price_v1",
                "total_item_count": len(self.egg_price_items),
                "preview_limit": preview_limit,
                "truncated": len(self.egg_price_items) > preview_limit,
                "items": self.price_items,
            },
            ensure_ascii=False,
        )


def analyze_clean_article(
    article: CleanArticleForAnalysis,
    analyze_time: datetime,
    *,
    price_items_preview_limit: int = 20,
    egg_price_extraction_enabled: bool = True,
) -> AnalyzedArticle:
    text = f"{article.title}\n{article.digest or ''}\n{article.transient_body_text or ''}"
    hits = [keyword for keyword in TRACKED_KEYWORDS if keyword in text]
    summary = (article.digest or article.title).strip()
    publish_date = None if article.publish_time is None else article.publish_time.date()
    quote_date_info = resolve_quote_date(article)
    if egg_price_extraction_enabled:
        egg_price_extraction = extract_egg_prices(
            article,
            analyze_time=analyze_time,
            quote_date_info=quote_date_info,
        )
    else:
        egg_price_extraction = EggPriceExtraction(
            items=[],
            table_summaries=[],
            notes=[],
            status="disabled",
        )

    return AnalyzedArticle(
        article_hash=article.article_hash,
        account_name=article.account_name,
        title=article.title,
        publish_time=article.publish_time,
        publish_date=publish_date,
        collect_time=article.collect_time,
        quote_date=quote_date_info.quote_date,
        quote_date_source=quote_date_info.source,
        quote_date_confidence=quote_date_info.confidence,
        author=article.author,
        summary_text=summary,
        topic_tags=hits,
        keyword_hits=hits,
        extracted_tables=egg_price_extraction.table_summaries,
        price_items=[
            item.preview_dict()
            for item in egg_price_extraction.items[:price_items_preview_limit]
        ],
        egg_price_items=egg_price_extraction.items,
        extraction_notes=[
            note for note in egg_price_extraction.notes if isinstance(note, dict)
        ],
        content_length=article.content_length,
        analysis_version="v1",
        analyze_time=analyze_time,
    )
