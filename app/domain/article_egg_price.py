from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Protocol

from app.domain.egg_price_quote_locator import locate_quote_content


ANALYSIS_VERSION = "egg_price_v1"
QUOTE_DATE_SOURCE_UNKNOWN = "unknown"
STANDARD_PRICE_UNIT = "yuan_per_jin"
STANDARD_WEIGHT_UNIT = "jin"
MIN_REASONABLE_YUAN_PER_JIN = 2.0
MAX_REASONABLE_YUAN_PER_JIN = 10.0


@dataclass(frozen=True)
class QuoteDateInfo:
    quote_date: date | None
    source: str
    confidence: float


@dataclass(frozen=True)
class PriceStandardization:
    standard_price_low: float | None
    standard_price_high: float | None
    standard_price_unit: str
    conversion_basis_weight_low: float | None
    conversion_basis_weight_high: float | None
    conversion_basis_weight_unit: str | None
    conversion_method: str
    conversion_confidence: float
    conversion_notes: list[str]
    include_in_standard_price: bool


@dataclass(frozen=True)
class EggPriceItem:
    article_hash: str
    account_name: str
    title: str
    publish_time: datetime | None
    publish_date: date | None
    item_index: int
    source_media_type: str
    source_table_index: int | None
    source_row_index: int | None
    source_table_title: str | None
    source_context: dict[str, Any]
    source_confidence: float | None
    product_family: str
    product_name: str | None
    include_in_egg_price: bool
    region: str | None
    market_name: str | None
    quote_basis: str | None
    trade_scene: str | None
    package_policy: str | None
    spec_text: str | None
    weight_text: str | None
    weight_low: float | None
    weight_high: float | None
    weight_unit: str | None
    price_text: str | None
    price_low: float | None
    price_high: float | None
    price_unit_text: str | None
    yesterday_price_text: str | None
    yesterday_price_low: float | None
    yesterday_price_high: float | None
    change_text: str | None
    change_value: float | None
    trend: str
    raw_headers: list[str]
    raw_row: list[str]
    row_note: str | None
    parse_notes: list[str]
    analysis_version: str
    analyze_time: datetime
    collect_time: datetime | None = None
    quote_date: date | None = None
    quote_date_source: str = QUOTE_DATE_SOURCE_UNKNOWN
    quote_date_confidence: float = 0.0
    standard_price_low: float | None = None
    standard_price_high: float | None = None
    standard_price_unit: str = STANDARD_PRICE_UNIT
    conversion_basis_weight_low: float | None = None
    conversion_basis_weight_high: float | None = None
    conversion_basis_weight_unit: str | None = None
    conversion_method: str = "unconverted"
    conversion_confidence: float = 0.0
    conversion_notes: list[str] = field(default_factory=list)
    include_in_standard_price: bool = False

    def preview_dict(self) -> dict[str, Any]:
        return {
            "item_index": self.item_index,
            "source_media_type": self.source_media_type,
            "quote_date": self.quote_date.isoformat() if self.quote_date else None,
            "quote_date_source": self.quote_date_source,
            "product_family": self.product_family,
            "product_name": self.product_name,
            "include_in_egg_price": self.include_in_egg_price,
            "region": self.region,
            "market_name": self.market_name,
            "quote_basis": self.quote_basis,
            "trade_scene": self.trade_scene,
            "package_policy": self.package_policy,
            "spec_text": self.spec_text,
            "weight_text": self.weight_text,
            "price_text": self.price_text,
            "standard_price_low": self.standard_price_low,
            "standard_price_high": self.standard_price_high,
            "standard_price_unit": self.standard_price_unit,
            "conversion_method": self.conversion_method,
            "include_in_standard_price": self.include_in_standard_price,
            "yesterday_price_text": self.yesterday_price_text,
            "change_text": self.change_text,
            "trend": self.trend,
            "row_note": self.row_note,
            "parse_notes": self.parse_notes,
        }


@dataclass(frozen=True)
class EggPriceExtraction:
    items: list[EggPriceItem]
    table_summaries: list[dict[str, Any]]
    notes: list[dict[str, Any]]
    status: str

    def preview_json(self, preview_limit: int) -> str:
        limited_items = self.items[:preview_limit]
        return json.dumps(
            {
                "version": ANALYSIS_VERSION,
                "total_item_count": len(self.items),
                "preview_limit": preview_limit,
                "truncated": len(self.items) > preview_limit,
                "items": [item.preview_dict() for item in limited_items],
            },
            ensure_ascii=False,
        )

    def tables_json(self) -> str:
        return json.dumps(
            {
                "version": "egg_table_summary_v1",
                "tables": self.table_summaries,
                "notes": self.notes,
            },
            ensure_ascii=False,
        )


class EggPriceArticleSource(Protocol):
    article_hash: str
    account_name: str
    title: str
    publish_time: datetime | None
    collect_time: datetime | None
    transient_body_text: str | None
    transient_html_tables: list[dict[str, Any]] | None


_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")
_RANGE_RE = re.compile(r"(?P<low>\d+(?:\.\d+)?)(?:\s*[-—~至]\s*(?P<high>\d+(?:\.\d+)?))?")
_FULL_DATE_RE = re.compile(
    r"(?P<year>20\d{2})\s*(?:年|-|/)\s*(?P<month>\d{1,2})\s*(?:月|-|/)\s*(?P<day>\d{1,2})\s*日?"
)
_QUOTE_DATE_BODY_KEYWORDS = ("报价", "价格", "参考", "行情", "蛋价")


def extract_egg_prices(
    article: EggPriceArticleSource,
    analyze_time: datetime,
    quote_date_info: QuoteDateInfo | None = None,
) -> EggPriceExtraction:
    items: list[EggPriceItem] = []
    table_summaries: list[dict[str, Any]] = []
    located = locate_quote_content(
        article.account_name,
        getattr(article, "transient_body_text", None) or "",
        list(getattr(article, "transient_html_tables", None) or []),
        list(getattr(article, "transient_ocr_tables", None) or []),
    )
    notes = _unsupported_image_notes(located.ocr_notes)
    publish_date = None if article.publish_time is None else article.publish_time.date()
    quote_info = quote_date_info or resolve_quote_date(article)

    for table_index, table in enumerate(located.tables):
        parsed_items = _items_from_table(
            article,
            publish_date,
            quote_info,
            table,
            table_index,
            len(items),
            analyze_time,
        )
        items.extend(parsed_items)
        table_summaries.append(
            {
                "source_media_type": str(
                    table.get("source_media_type") or "dom_table"
                ),
                "source_table_index": table.get("source_table_index", table_index),
                "title": str(table.get("title") or ""),
                "headers": [str(header) for header in table.get("headers", [])],
                "row_count": len(table.get("rows", []) or []),
                "parsed_item_count": len(parsed_items),
            }
        )

    text_items = _items_from_text(
        article,
        publish_date,
        quote_info,
        len(items),
        analyze_time,
        text=located.body_text,
    )
    items.extend(text_items)

    return EggPriceExtraction(
        items=items,
        table_summaries=table_summaries,
        notes=notes,
        status="success" if items else "no_price_data",
    )


def resolve_quote_date(article: EggPriceArticleSource) -> QuoteDateInfo:
    title_date = _first_full_date(getattr(article, "title", ""))
    if title_date is not None:
        return QuoteDateInfo(title_date, "title", 1.0)

    body_date = _first_body_quote_date(getattr(article, "transient_body_text", None) or "")
    if body_date is not None:
        return QuoteDateInfo(body_date, "body", 0.9)

    publish_time = getattr(article, "publish_time", None)
    if publish_time is not None:
        return QuoteDateInfo(publish_time.date(), "publish_date_fallback", 0.6)

    collect_time = getattr(article, "collect_time", None)
    if collect_time is not None:
        return QuoteDateInfo(collect_time.date(), "collect_date_fallback", 0.4)

    return QuoteDateInfo(None, QUOTE_DATE_SOURCE_UNKNOWN, 0.0)


def _first_body_quote_date(text: str) -> date | None:
    for raw_line in text.splitlines():
        line = re.sub(r"\s+", " ", raw_line).strip()
        if any(keyword in line for keyword in _QUOTE_DATE_BODY_KEYWORDS):
            parsed = _first_full_date(line)
            if parsed is not None:
                return parsed
    return _first_full_date(text)


def _first_full_date(text: str) -> date | None:
    for match in _FULL_DATE_RE.finditer(text):
        try:
            return date(
                int(match.group("year")),
                int(match.group("month")),
                int(match.group("day")),
            )
        except ValueError:
            continue
    return None


def _unsupported_image_notes(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    notes: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        source_media_type = item.get("source_media_type")
        if source_media_type not in {
            "image_quote_not_supported_v1",
            "image_ocr_failed_v1",
        }:
            continue
        notes.append(
            {
                "source_media_type": source_media_type,
                "source_image_index": item.get("source_image_index"),
                "width": item.get("width"),
                "height": item.get("height"),
                "note": str(item.get("note") or source_media_type),
            }
        )
    return notes


def _items_from_table(
    article: EggPriceArticleSource,
    publish_date: date | None,
    quote_date_info: QuoteDateInfo,
    table: dict[str, Any],
    table_index: int,
    item_offset: int,
    analyze_time: datetime,
) -> list[EggPriceItem]:
    headers = [str(header).strip() for header in table.get("headers", [])]
    rows = [[str(cell).strip() for cell in row] for row in table.get("rows", [])]
    title = str(table.get("title") or "")
    context = dict(table.get("context") or {})
    context = _merge_context_from_text(context, title)
    context = _merge_context_from_text(context, " ".join(headers))
    source_media_type = str(table.get("source_media_type") or "dom_table")
    items: list[EggPriceItem] = []
    if not headers:
        return items

    for row_index, row in enumerate(rows):
        if _row_is_context_heading(row):
            context = _merge_context_from_text(context, row[0])
            continue
        row_map = dict(zip(headers, row, strict=False))
        if not _row_has_quote(row_map, row, context):
            continue
        item = _build_item(
            article=article,
            publish_date=publish_date,
            quote_date_info=quote_date_info,
            item_index=item_offset + len(items) + 1,
            source_media_type=source_media_type,
            source_table_index=table.get("source_table_index", table_index),
            source_row_index=row_index,
            source_table_title=title or None,
            context=context,
            raw_headers=headers,
            raw_row=row,
            analyze_time=analyze_time,
            row_map=row_map,
            line=" ".join(row),
        )
        items.append(item)

    return items


def _row_is_context_heading(row: list[str]) -> bool:
    if len(row) != 1:
        return False
    text = row[0]
    if _NUMBER_RE.search(text):
        return False
    return "蛋" in text or "报价" in text


def _items_from_text(
    article: EggPriceArticleSource,
    publish_date: date | None,
    quote_date_info: QuoteDateInfo,
    item_offset: int,
    analyze_time: datetime,
    *,
    text: str | None = None,
) -> list[EggPriceItem]:
    text = article.transient_body_text or "" if text is None else text
    context: dict[str, Any] = {}
    items: list[EggPriceItem] = []

    for row_index, raw_line in enumerate(text.splitlines()):
        line = re.sub(r"\s+", " ", raw_line).strip()
        if not line:
            continue
        context = _merge_context_from_text(context, line)
        if not _line_has_quote(line, context):
            continue
        item = _build_item(
            article=article,
            publish_date=publish_date,
            quote_date_info=quote_date_info,
            item_index=item_offset + len(items) + 1,
            source_media_type="text_line",
            source_table_index=None,
            source_row_index=row_index,
            source_table_title=context.get("source_table_title"),
            context=context,
            raw_headers=[],
            raw_row=[line],
            analyze_time=analyze_time,
            row_map={},
            line=line,
        )
        items.append(item)

    return items


def _build_item(
    *,
    article: EggPriceArticleSource,
    publish_date: date | None,
    quote_date_info: QuoteDateInfo,
    item_index: int,
    source_media_type: str,
    source_table_index: int | None,
    source_row_index: int | None,
    source_table_title: str | None,
    context: dict[str, Any],
    raw_headers: list[str],
    raw_row: list[str],
    analyze_time: datetime,
    row_map: dict[str, str],
    line: str,
) -> EggPriceItem:
    product_name = _product_name(line, context)
    if product_name is None and ("鸡蛋" in article.account_name or "鸡蛋" in article.title):
        product_name = "鸡蛋"
    product_family = _product_family(product_name or line)
    price_text = _first_non_empty(
        row_map.get("今日价"),
        row_map.get("含包装价"),
        row_map.get("建议区间价"),
        _price_text_from_line(line),
    )
    yesterday_price_text = _first_non_empty(row_map.get("昨日价"))
    weight_text = _first_non_empty(row_map.get("净重"), row_map.get("毛重"), _weight_text_from_line(line))
    price_low, price_high = _numeric_range(price_text)
    yesterday_low, yesterday_high = _numeric_range(yesterday_price_text)
    weight_low, weight_high = _numeric_range(weight_text)
    change_text = _first_non_empty(row_map.get("涨跌"), row_map.get("涨"), _change_text_from_line(line))
    standardization = _standardize_price(
        product_family=product_family,
        include_in_egg_price=product_family == "chicken_egg",
        price_low=price_low,
        price_high=price_high,
        quote_basis=context.get("quote_basis"),
        weight_low=weight_low,
        weight_high=weight_high,
    )

    return EggPriceItem(
        article_hash=article.article_hash,
        account_name=article.account_name,
        title=article.title,
        publish_time=article.publish_time,
        publish_date=publish_date,
        item_index=item_index,
        source_media_type=source_media_type,
        source_table_index=source_table_index,
        source_row_index=source_row_index,
        source_table_title=source_table_title,
        source_context=dict(context),
        source_confidence=0.85,
        product_family=product_family,
        product_name=product_name,
        include_in_egg_price=product_family == "chicken_egg",
        region=context.get("region") or _region_from_line(line),
        market_name=context.get("market_name") or _market_from_line(line),
        quote_basis=context.get("quote_basis"),
        trade_scene=context.get("trade_scene"),
        package_policy=context.get("package_policy"),
        spec_text=_first_non_empty(row_map.get("规格"), row_map.get("价差"), _spec_from_line(line)),
        weight_text=weight_text,
        weight_low=weight_low,
        weight_high=weight_high,
        weight_unit="斤" if weight_text and "斤" in weight_text else None,
        price_text=price_text,
        price_low=price_low,
        price_high=price_high,
        price_unit_text="元" if price_text and "元" in price_text else None,
        yesterday_price_text=yesterday_price_text,
        yesterday_price_low=yesterday_low,
        yesterday_price_high=yesterday_high,
        change_text=change_text,
        change_value=_first_number(change_text),
        trend=_trend(line, change_text),
        raw_headers=raw_headers,
        raw_row=raw_row,
        row_note=_row_note(line, row_map),
        parse_notes=[],
        analysis_version=ANALYSIS_VERSION,
        analyze_time=analyze_time,
        collect_time=getattr(article, "collect_time", None),
        quote_date=quote_date_info.quote_date,
        quote_date_source=quote_date_info.source,
        quote_date_confidence=quote_date_info.confidence,
        standard_price_low=standardization.standard_price_low,
        standard_price_high=standardization.standard_price_high,
        standard_price_unit=standardization.standard_price_unit,
        conversion_basis_weight_low=standardization.conversion_basis_weight_low,
        conversion_basis_weight_high=standardization.conversion_basis_weight_high,
        conversion_basis_weight_unit=standardization.conversion_basis_weight_unit,
        conversion_method=standardization.conversion_method,
        conversion_confidence=standardization.conversion_confidence,
        conversion_notes=standardization.conversion_notes,
        include_in_standard_price=standardization.include_in_standard_price,
    )


def _standardize_price(
    *,
    product_family: str,
    include_in_egg_price: bool,
    price_low: float | None,
    price_high: float | None,
    quote_basis: str | None,
    weight_low: float | None,
    weight_high: float | None,
) -> PriceStandardization:
    if price_low is None or price_high is None:
        return _unconverted_standardization(["missing_price"])

    if _is_reasonable_yuan_per_jin(price_low, price_high):
        return _converted_standardization(
            low=round(price_low, 4),
            high=round(price_high, 4),
            basis_low=None,
            basis_high=None,
            method="already_yuan_per_jin",
            confidence=0.9,
            product_family=product_family,
            include_in_egg_price=include_in_egg_price,
            notes=[],
        )

    basis_low, basis_high, method = _conversion_weight_basis(
        quote_basis=quote_basis,
        weight_low=weight_low,
        weight_high=weight_high,
    )
    if basis_low is None or basis_high is None or basis_low <= 0 or basis_high <= 0:
        return _unconverted_standardization(["missing_conversion_basis"])

    standard_low = round(price_low / basis_high, 4)
    standard_high = round(price_high / basis_low, 4)
    if not _is_reasonable_yuan_per_jin(standard_low, standard_high):
        return _unconverted_standardization(
            ["out_of_reasonable_range"],
            basis_low=basis_low,
            basis_high=basis_high,
        )

    return _converted_standardization(
        low=standard_low,
        high=standard_high,
        basis_low=basis_low,
        basis_high=basis_high,
        method=method,
        confidence=0.85 if method == "row_weight" else 0.8,
        product_family=product_family,
        include_in_egg_price=include_in_egg_price,
        notes=[],
    )


def _conversion_weight_basis(
    *,
    quote_basis: str | None,
    weight_low: float | None,
    weight_high: float | None,
) -> tuple[float | None, float | None, str]:
    if weight_low is not None and weight_high is not None:
        return (weight_low, weight_high, "row_weight")
    quote_basis_weight = _weight_from_quote_basis(quote_basis)
    if quote_basis_weight is not None:
        return (quote_basis_weight, quote_basis_weight, "quote_basis_weight")
    return (None, None, "unconverted")


def _weight_from_quote_basis(value: str | None) -> float | None:
    if not value:
        return None
    match = re.search(r"(\d+(?:\.\d+)?)\s*斤", value)
    return float(match.group(1)) if match else None


def _converted_standardization(
    *,
    low: float,
    high: float,
    basis_low: float | None,
    basis_high: float | None,
    method: str,
    confidence: float,
    product_family: str,
    include_in_egg_price: bool,
    notes: list[str],
) -> PriceStandardization:
    include_in_standard_price = (
        include_in_egg_price
        and product_family == "chicken_egg"
        and method != "unconverted"
        and _is_reasonable_yuan_per_jin(low, high)
    )
    return PriceStandardization(
        standard_price_low=low,
        standard_price_high=high,
        standard_price_unit=STANDARD_PRICE_UNIT,
        conversion_basis_weight_low=basis_low,
        conversion_basis_weight_high=basis_high,
        conversion_basis_weight_unit=STANDARD_WEIGHT_UNIT if basis_low is not None else None,
        conversion_method=method,
        conversion_confidence=confidence,
        conversion_notes=notes,
        include_in_standard_price=include_in_standard_price,
    )


def _unconverted_standardization(
    notes: list[str],
    *,
    basis_low: float | None = None,
    basis_high: float | None = None,
) -> PriceStandardization:
    return PriceStandardization(
        standard_price_low=None,
        standard_price_high=None,
        standard_price_unit=STANDARD_PRICE_UNIT,
        conversion_basis_weight_low=basis_low,
        conversion_basis_weight_high=basis_high,
        conversion_basis_weight_unit=STANDARD_WEIGHT_UNIT if basis_low is not None else None,
        conversion_method="unconverted",
        conversion_confidence=0.0,
        conversion_notes=notes,
        include_in_standard_price=False,
    )


def _is_reasonable_yuan_per_jin(low: float | None, high: float | None) -> bool:
    if low is None or high is None:
        return False
    if low > high:
        return False
    return low >= MIN_REASONABLE_YUAN_PER_JIN and high <= MAX_REASONABLE_YUAN_PER_JIN


def _merge_context_from_text(context: dict[str, Any], text: str) -> dict[str, Any]:
    updated = dict(context)
    quote_basis = re.search(r"报价单位[:：]?\s*(\d+(?:\.\d+)?斤)", text)
    if quote_basis:
        updated["quote_basis"] = quote_basis.group(1)
    box_basis = re.search(r"(\d+\s*枚/箱)", text)
    if box_basis:
        updated["quote_basis"] = box_basis.group(1).replace(" ", "")
    if "含包装" in text:
        updated["package_policy"] = "含包装"
    if "带包装" in text:
        updated["package_policy"] = "带包装"
    if "筐装" in text:
        updated["package_policy"] = "筐装"
    if "不含运费和包装费" in text:
        updated["package_policy"] = "不含运费和包装费"
    if "装车" in text:
        updated["trade_scene"] = "装车"
    if "停车场" in text:
        updated["trade_scene"] = "停车场"
        updated["source_table_title"] = text
    for name in ("洋鸡蛋", "红壳蛋", "褐壳蛋", "粉壳蛋", "红心蛋", "绿壳蛋", "草鸡蛋", "红蛋", "粉蛋", "鸭蛋", "鹌鹑蛋"):
        if name in text:
            updated["product_name"] = name
            break
    if "鸡蛋" in text and "product_name" not in updated:
        updated["product_name"] = "鸡蛋"
    if "贵州" in text:
        updated["region"] = "贵州"
    if "广西" in text:
        updated["region"] = "广西"
    return updated


def _row_has_quote(row_map: dict[str, str], row: list[str], context: dict[str, Any]) -> bool:
    joined = " ".join(row)
    return bool(
        row_map.get("今日价")
        or row_map.get("含包装价")
        or row_map.get("建议区间价")
        or _line_has_quote(joined, context)
    )


def _line_has_quote(line: str, context: dict[str, Any] | None = None) -> bool:
    if re.search(r"1[3-9]\d{9}", line):
        return False
    compact = re.sub(r"\s+", "", line)
    if compact.startswith("报价单位"):
        return False
    if any(word in line for word in ("鸡苗", "拉稀", "疫苗", "支原体", "销售战神", "老母鸡")):
        return False

    candidate = _strip_leading_marker(line)
    price_text = _price_text_from_line(candidate)
    if price_text is None:
        return False

    has_inherited_product_context = bool(
        context
        and context.get("product_name")
        and (
            "净重" in candidate
            or "毛重" in candidate
            or "斤" in candidate
            or any(size in candidate for size in ("大码", "中码", "小码", "特小"))
        )
    )
    has_product_context = bool(
        any(word in candidate for word in ("蛋", "鸡蛋价格", "报价"))
        or has_inherited_product_context
    )
    has_numeric_context = bool(_NUMBER_RE.search(candidate))
    has_quote_word = bool(
        "元" in candidate
        or "价" in candidate
        or "稳" in candidate
        or "涨" in candidate
        or "落" in candidate
        or "跌" in candidate
    )
    return has_product_context and has_numeric_context and has_quote_word


def _strip_leading_marker(line: str) -> str:
    return re.sub(r"^\s*\d+[.、)]?\s*(?=[^\d斤元])", "", line).strip()


def _product_name(line: str, context: dict[str, Any]) -> str | None:
    for name in (
        "洋鸡蛋",
        "红壳蛋",
        "褐壳蛋",
        "粉壳蛋",
        "红心蛋",
        "绿壳蛋",
        "草鸡蛋",
        "红蛋",
        "粉蛋",
        "咸鸭蛋",
        "海鸭蛋",
        "鸭蛋",
        "鹌鹑蛋",
        "皮蛋",
        "变蛋",
        "咸蛋",
    ):
        if name in line:
            return name
    return context.get("product_name") or ("鸡蛋" if "鸡蛋" in line else None)


def _product_family(text: str) -> str:
    if "鹌鹑蛋" in text:
        return "quail_egg"
    if any(name in text for name in ("皮蛋", "变蛋")):
        return "preserved_egg"
    if any(name in text for name in ("咸鸭蛋", "咸蛋", "海鸭蛋")):
        return "salted_egg"
    if "鸭蛋" in text:
        return "duck_egg"
    if any(name in text for name in ("鸡蛋", "洋鸡蛋", "红蛋", "粉蛋", "红壳蛋", "褐壳蛋", "粉壳蛋", "红心蛋", "绿壳蛋", "草鸡蛋")):
        return "chicken_egg"
    return "other_egg"


def _price_text_from_line(line: str) -> str | None:
    match = re.search(r"(\d+(?:\.\d+)?(?:\s*[-—~至]\s*\d+(?:\.\d+)?)?\s*元)", line)
    if match:
        return re.sub(r"\s+", "", match.group(1))
    match = re.search(r"价格[:：]?\s*(\d+(?:\.\d+)?(?:\s*[-—~至]\s*\d+(?:\.\d+)?)?)", line)
    if match:
        return match.group(1)
    compact = re.sub(r"\s+", "", line)
    match = re.search(r"(\d+(?:[-—~至]\d+)?)\s*(?:稳|稳定|涨|落|跌)$", compact)
    return match.group(1) if match else None


def _weight_text_from_line(line: str) -> str | None:
    match = re.search(
        r"(?P<prefix>净重|毛重)?\s*(?P<value>\d+(?:\.\d+)?(?:\s*[-—~至]\s*\d+(?:\.\d+)?)?斤(?:以上)?)",
        line,
    )
    if not match:
        return None
    value = re.sub(r"\s+", "", match.group("value"))
    if match.group("prefix") == "净重":
        return f"净重{value}"
    return value


def _change_text_from_line(line: str) -> str | None:
    match = re.search(r"(?:涨|落|跌)\s*[-+]?\d+(?:\.\d+)?", line)
    if match:
        return re.sub(r"\s+", "", match.group(0))
    if any(word in line for word in ("稳定", "稳")):
        return "稳"
    return None


def _numeric_range(value: str | None) -> tuple[float | None, float | None]:
    if not value:
        return (None, None)
    match = _RANGE_RE.search(value)
    if not match:
        return (None, None)
    low = float(match.group("low"))
    high = float(match.group("high") or match.group("low"))
    return (low, high)


def _first_number(value: str | None) -> float | None:
    if not value:
        return None
    match = re.search(r"[-+]?\d+(?:\.\d+)?", value)
    return float(match.group(0)) if match else None


def _trend(line: str, change_text: str | None) -> str:
    text = f"{line} {change_text or ''}"
    if "稳" in text or "稳定" in text or change_text == "0":
        return "flat"
    if "涨" in text:
        return "up"
    if "落" in text or "跌" in text:
        return "down"
    value = _first_number(change_text)
    if value is None:
        return "unknown"
    if value > 0:
        return "up"
    if value < 0:
        return "down"
    return "flat"


def _spec_from_line(line: str) -> str | None:
    for keyword in ("大码", "中码", "小码", "特小", "双色", "标价"):
        if keyword in line:
            return keyword
    return None


def _region_from_line(line: str) -> str | None:
    match = re.match(r"([\u4e00-\u9fa5]+)-", line)
    return match.group(1) if match else None


def _market_from_line(line: str) -> str | None:
    match = re.match(r"[\u4e00-\u9fa5]+-([\u4e00-\u9fa5]+?)(?:鸡蛋价格|蛋价|价格|\s|$)", line)
    return match.group(1) if match else None


def _row_note(line: str, row_map: dict[str, str]) -> str | None:
    for value in row_map.values():
        if "以质论价" in value or "双色" in value:
            return value
    if "顺减" in line:
        return line
    return None


def _first_non_empty(*values: str | None) -> str | None:
    for value in values:
        if value and value.strip():
            return value.strip()
    return None
