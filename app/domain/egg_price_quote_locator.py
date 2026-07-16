from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import re
from typing import Any


TARGET_ACCOUNT_NAMES = frozenset(
    {
        "家美鲜鸡蛋 佳美鲜",
        "河北馆陶鸡蛋报价",
        "河南金咕咕蛋品",
        "贵阳鸡蛋价格",
        "蓝天禽蛋联盟",
        "湖南三尖农牧公司",
        "成都鸡蛋价格",
        "河北辛集城方蛋品",
        "江西九江褐壳蛋",
    }
)

OCR_ACCOUNT_NAMES = frozenset(
    {"河南金咕咕蛋品", "湖南三尖农牧公司"}
)


@dataclass(frozen=True)
class LocatedQuoteContent:
    body_text: str
    tables: list[dict[str, Any]]
    ocr_notes: list[dict[str, Any]]


def locate_quote_content(
    account_name: str,
    body_text: str,
    html_tables: list[dict[str, Any]],
    ocr_tables: list[dict[str, Any]],
) -> LocatedQuoteContent:
    notes = [
        dict(item)
        for item in ocr_tables
        if item.get("source_media_type") != "image_ocr"
    ]
    if account_name not in TARGET_ACCOUNT_NAMES:
        return LocatedQuoteContent(
            body_text=body_text,
            tables=[dict(item) for item in html_tables],
            ocr_notes=notes,
        )

    recognized_ocr = [
        dict(item)
        for item in ocr_tables
        if item.get("source_media_type") == "image_ocr"
    ]
    selected: list[dict[str, Any]] = []

    if account_name == "家美鲜鸡蛋 佳美鲜":
        candidates = [
            item
            for item in html_tables
            if _is_jiameixian_main(item) and _row_count(item) >= 2
        ]
        if candidates:
            selected = [_with_chicken_context(max(candidates, key=_row_count))]
    elif account_name == "河北馆陶鸡蛋报价":
        candidates = [item for item in html_tables if _has_headers(item, "净重", "今日价")]
        candidates = [item for item in candidates if _row_count(item) >= 2]
        if candidates:
            selected = [_with_chicken_context(max(candidates, key=_row_count))]
    elif account_name == "贵阳鸡蛋价格":
        candidates = [
            item
            for item in html_tables
            if _has_headers(item, "规格", "毛重", "含包装价")
            and _row_count(item) >= 2
        ]
        if candidates:
            selected = [_expand_guiyang_thresholds(max(candidates, key=_row_count))]
    elif account_name == "蓝天禽蛋联盟":
        synthetic = _locate_lantian_text_table(body_text)
        if synthetic is not None:
            selected = [synthetic]
    elif account_name == "成都鸡蛋价格":
        candidates = [item for item in html_tables if _has_headers(item, "净重", "参考价格")]
        candidates = [item for item in candidates if _row_count(item) >= 2]
        if candidates:
            selected = [_normalize_headers(max(candidates, key=_row_count), {"参考价格": "今日价"})]
    elif account_name == "河北辛集城方蛋品":
        candidates = [item for item in html_tables if _has_headers(item, "重量", "今日价")]
        candidates = [item for item in candidates if _row_count(item) >= 2]
        if candidates:
            selected = [
                _with_chicken_context(
                    _normalize_headers(max(candidates, key=_row_count), {"重量": "净重"})
                )
            ]
    elif account_name == "江西九江褐壳蛋":
        candidates = [
            item
            for item in html_tables
            if _has_any_header(item, "净重", "毛重")
            and _has_headers(item, "今日价")
            and _row_count(item) >= 2
        ]
        brown = [item for item in candidates if not _is_powder_shell_table(item)]
        powder = [item for item in candidates if _is_powder_shell_table(item)]
        if brown:
            selected.append(
                _with_product_context(max(brown, key=_row_count), "褐壳蛋")
            )
        if powder:
            selected.append(
                _with_product_context(max(powder, key=_row_count), "粉壳蛋")
            )
    elif account_name in OCR_ACCOUNT_NAMES:
        selected = [_with_chicken_context(item) for item in recognized_ocr]
        if selected:
            notes = [
                item
                for item in notes
                if item.get("source_media_type")
                != "image_quote_not_supported_v1"
            ]

    selected = [_expand_table_edge_steps(item) for item in selected]

    return LocatedQuoteContent(body_text="", tables=selected, ocr_notes=notes)


def parse_account_ocr_lines(
    account_name: str,
    lines: list[str],
    *,
    source_image_index: int,
) -> dict[str, Any] | None:
    normalized = [_normalize_ocr_text(line) for line in lines if line.strip()]
    if account_name == "河南金咕咕蛋品":
        rows: list[list[str]] = []
        parsed_rows: list[tuple[list[int], str]] = []
        for line in normalized:
            compact = re.sub(r"\s+", "", line)
            price_match = re.search(r"(?<!\d)(\d\.\d{1,2})(?!\d)", compact)
            weights = [
                int(value)
                for value in re.findall(r"(?<!\d)(3\d|4\d)(?=\s*斤)", line)
            ]
            if price_match:
                parsed_rows.append((weights, price_match.group(1)))
        if len(parsed_rows) == 5:
            template = [(30, 37), (37, 40), (40, 42), (42, 44), (44, 46)]
            rows = [
                [f"{low}-{high}斤", f"{price}元/斤"]
                for (low, high), (_, price) in zip(template, parsed_rows, strict=True)
            ]
        else:
            for weights, price in parsed_rows:
                if len(weights) >= 2:
                    rows.append(
                        [f"{weights[0]}-{weights[-1]}斤", f"{price}元/斤"]
                    )
        if len(rows) < 2:
            return None
        return _ocr_table(
            source_image_index,
            "金咕咕蛋品今日报价",
            ["净重", "今日价"],
            rows,
        )

    if account_name == "湖南三尖农牧公司":
        rows = []
        pattern = re.compile(
            r"^\s*(3\d|4\d|50)\s+(标准价|[-+]?[0-9]+)\s+"
            r"(\d{3})\s+(\d{3})\s+([-+]?\d+)\s*$"
        )
        for line in normalized:
            match = pattern.match(line)
            if match:
                rows.append(list(match.groups()))
        compact_lines = [re.sub(r"\s+", "", line) for line in normalized]
        marker_index = next(
            (
                index
                for index, line in enumerate(compact_lines)
                if "今日价" in line
            ),
            None,
        )
        if marker_index is not None:
            today_prices = [
                line
                for line in compact_lines[marker_index + 1 :]
                if re.fullmatch(r"\d{3}", line)
            ]
            if len(today_prices) >= 19:
                return _ocr_table(
                    source_image_index,
                    "湖南三尖精品蛋360枚/箱收购价",
                    ["净重", "今日价"],
                    [
                        [str(weight), price]
                        for weight, price in zip(
                            range(48, 29, -1), today_prices[:19], strict=True
                        )
                    ],
                )
        if len(rows) < 2:
            return None
        return _ocr_table(
            source_image_index,
            "湖南三尖精品蛋360枚/箱收购价",
            ["净重", "价差", "昨日价", "今日价", "涨跌"],
            rows,
        )
    return None


def _ocr_table(
    source_image_index: int,
    title: str,
    headers: list[str],
    rows: list[list[str]],
) -> dict[str, Any]:
    return {
        "source_media_type": "image_ocr",
        "source_image_index": source_image_index,
        "source_table_index": source_image_index,
        "title": title,
        "context": {"product_name": "鸡蛋"},
        "headers": headers,
        "rows": rows,
    }


def _normalize_ocr_text(value: str) -> str:
    translation = str.maketrans(
        "０１２３４５６７８９．，。／−·",
        "0123456789.../-.",
    )
    return re.sub(r"[\t\r\n]+", " ", value.translate(translation)).strip()


def _is_jiameixian_main(item: dict[str, Any]) -> bool:
    return _has_headers(item, "净重", "价差", "昨日价", "今日价") and (
        "360枚/箱" in _table_text(item)
        or "含包装" in _table_text(item)
        or _row_count(item) >= 12
    )


_EXPLICIT_LOWER_STEP_PATTERN = re.compile(
    r"(?<!\d)(3\d|4\d|50)\s*(?:码|斤)?\s*以下\s*"
    r"(?:顺减|每斤)?\s*[-－—–]?\s*(\d+(?:\.\d+)?)"
)
_HIGH_EDGE_STEP_PATTERN = re.compile(
    r"(?:精品)?大码\s*以上\s*每斤\s*[+＋]\s*(\d+(?:\.\d+)?)"
)
_LOW_EDGE_STEP_PATTERN = re.compile(
    r"小码\s*以下\s*每斤\s*[-－—–]\s*(\d+(?:\.\d+)?)"
)


def _expand_table_edge_steps(item: dict[str, Any]) -> dict[str, Any]:
    result = _with_chicken_context(item)
    headers = list(result.get("headers") or [])
    rows = [list(row) for row in result.get("rows") or []]
    weight_index = next(
        (index for index, header in enumerate(headers) if "净重" in header or "毛重" in header),
        None,
    )
    today_index = next(
        (index for index, header in enumerate(headers) if "今日价" in header),
        None,
    )
    if weight_index is None or today_index is None:
        return result

    known: dict[int, Decimal] = {}
    for row in rows:
        if len(row) <= max(weight_index, today_index):
            continue
        size = _first_int(row[weight_index])
        price = _first_decimal(row[today_index])
        if size is not None and 30 <= size <= 50 and price is not None:
            known[size] = price
    if not known:
        return result

    # A single-cell row belongs to this table. Title/context may be inferred
    # from nearby DOM siblings, so evaluate direct rows first when duplicate
    # direction rules are present.
    fragments = [row[0] for row in rows if len(row) == 1]
    fragments.append(str(result.get("title") or ""))
    fragments.extend(str(value) for value in (result.get("context") or {}).values())
    explicit_lower_rules: list[tuple[int, Decimal]] = []
    high_steps: list[Decimal] = []
    low_steps: list[Decimal] = []
    for fragment in fragments:
        explicit_lower_rules.extend(
            (int(match.group(1)), Decimal(match.group(2)))
            for match in _EXPLICIT_LOWER_STEP_PATTERN.finditer(fragment)
        )
        high_steps.extend(
            Decimal(match.group(1))
            for match in _HIGH_EDGE_STEP_PATTERN.finditer(fragment)
        )
        low_steps.extend(
            Decimal(match.group(1))
            for match in _LOW_EDGE_STEP_PATTERN.finditer(fragment)
        )
    if not explicit_lower_rules and not high_steps and not low_steps:
        return result

    original_low_size = min(known)
    original_low_price = known[original_low_size]
    original_high_size = max(known)
    original_high_price = known[original_high_size]

    rule_patterns = (
        _EXPLICIT_LOWER_STEP_PATTERN,
        _HIGH_EDGE_STEP_PATTERN,
        _LOW_EDGE_STEP_PATTERN,
    )
    data_rows = [
        row
        for row in rows
        if not (
            len(row) == 1
            and any(pattern.search(row[0]) for pattern in rule_patterns)
        )
    ]

    def append_price(size: int, price: Decimal) -> None:
        if size in known:
            return
        new_row = [""] * len(headers)
        new_row[weight_index] = str(size)
        new_row[today_index] = _decimal_text(price)
        data_rows.append(new_row)
        known[size] = price

    for base_size, step in explicit_lower_rules:
        base_price = known.get(base_size)
        if base_price is None or step <= 0:
            continue
        for size in range(base_size - 1, 29, -1):
            append_price(size, base_price - step * Decimal(base_size - size))

    for step in low_steps:
        if step <= 0:
            continue
        for size in range(original_low_size - 1, 29, -1):
            append_price(
                size,
                original_low_price - step * Decimal(original_low_size - size),
            )

    for step in high_steps:
        if step <= 0:
            continue
        for size in range(original_high_size + 1, 51):
            append_price(
                size,
                original_high_price + step * Decimal(size - original_high_size),
            )

    result["rows"] = data_rows
    return result


def _expand_guiyang_thresholds(item: dict[str, Any]) -> dict[str, Any]:
    result = _with_chicken_context(item)
    headers = list(result.get("headers") or [])
    rows = [list(row) for row in result.get("rows") or []]
    try:
        weight_index = headers.index("毛重")
    except ValueError:
        return result

    above: list[tuple[int, list[str]]] = []
    below: list[tuple[int, list[str]]] = []
    for row in rows:
        if len(row) <= weight_index:
            continue
        match = re.search(r"(\d{2})斤以(上|下)", row[weight_index])
        if not match:
            continue
        target = above if match.group(2) == "上" else below
        target.append((int(match.group(1)), row))

    expanded: list[list[str]] = []
    above.sort(key=lambda item: item[0])
    for index, (threshold, row) in enumerate(above):
        next_threshold = above[index + 1][0] if index + 1 < len(above) else 51
        low = max(30, threshold)
        high = min(50, next_threshold - 1)
        for size in range(low, high + 1):
            copy = list(row)
            copy[weight_index] = f"{size}斤"
            expanded.append(copy)
    for threshold, row in below:
        for size in range(30, min(50, threshold - 1) + 1):
            copy = list(row)
            copy[weight_index] = f"{size}斤"
            expanded.append(copy)
    result["rows"] = expanded
    return result


def _locate_lantian_text_table(body_text: str) -> dict[str, Any] | None:
    rows: list[list[str]] = []
    in_region = False
    in_premium = False
    in_large = False
    pattern = re.compile(r"(?<!\d)(3\d|4\d)\s*[-—–~至]\s*(3\d|4\d)斤?\s*(\d{3})(?!\d)")
    for raw_line in body_text.splitlines():
        line = re.sub(r"\s+", "", raw_line)
        if not line:
            continue
        if "阜阳地区" in line and "报价" in line:
            in_region, in_premium, in_large = True, False, False
            continue
        if in_region and "精品蛋报价" in line:
            in_premium = True
            continue
        if in_premium and any(
            marker in line for marker in ("大码蛋系列", "大粉系列", "大粉蛋系列")
        ):
            in_large = True
            continue
        if in_large and (
            any(marker in line for marker in ("小码蛋系列", "小粉蛋系列", "小粉系列"))
            or ("地区" in line and "报价" in line and "阜阳" not in line)
        ):
            break
        if in_large:
            match = pattern.search(line)
            if match:
                rows.append([f"{match.group(1)}-{match.group(2)}斤", match.group(3)])
    if not rows:
        return None
    return {
        "source_media_type": "text_block",
        "source_table_index": None,
        "title": "阜阳地区精品蛋大码蛋系列",
        "context": {
            "product_name": "鸡蛋",
            "region": "阜阳",
            "market_name": "阜阳",
        },
        "headers": ["净重", "今日价"],
        "rows": rows,
    }


def _normalize_headers(item: dict[str, Any], aliases: dict[str, str]) -> dict[str, Any]:
    result = _with_chicken_context(item)
    result["headers"] = [aliases.get(str(header), str(header)) for header in item.get("headers") or []]
    return result


def _with_chicken_context(item: dict[str, Any]) -> dict[str, Any]:
    result = dict(item)
    result["headers"] = list(item.get("headers") or [])
    result["rows"] = [list(row) for row in item.get("rows") or []]
    context = dict(item.get("context") or {})
    context.setdefault("product_name", "鸡蛋")
    result["context"] = context
    return result


def _with_product_context(item: dict[str, Any], product_name: str) -> dict[str, Any]:
    result = _with_chicken_context(item)
    context = dict(result.get("context") or {})
    context["product_name"] = product_name
    result["context"] = context
    return result


def _is_powder_shell_table(item: dict[str, Any]) -> bool:
    # DOM context can contain text from an adjacent table. Prefer this table's
    # own promoted title so a brown-shell table is not reclassified as powder.
    title = str(item.get("title") or "").strip()
    if title:
        return "粉壳" in title
    return "粉壳" in _table_text(item)


def _has_headers(item: dict[str, Any], *required: str) -> bool:
    headers = "|".join(str(header) for header in item.get("headers") or [])
    return all(value in headers for value in required)


def _has_any_header(item: dict[str, Any], *values: str) -> bool:
    headers = "|".join(str(header) for header in item.get("headers") or [])
    return any(value in headers for value in values)


def _row_count(item: dict[str, Any]) -> int:
    return len(item.get("rows") or [])


def _table_text(item: dict[str, Any]) -> str:
    parts = [str(item.get("title") or "")]
    parts.extend(str(value) for value in (item.get("context") or {}).values())
    parts.extend(str(header) for header in item.get("headers") or [])
    parts.extend(str(cell) for row in item.get("rows") or [] for cell in row)
    return " ".join(parts)


def _first_int(value: str) -> int | None:
    match = re.search(r"\d+", value)
    return int(match.group(0)) if match else None


def _first_decimal(value: str) -> Decimal | None:
    match = re.search(r"\d+(?:\.\d+)?", value)
    return Decimal(match.group(0)) if match else None


def _decimal_text(value: Decimal) -> str:
    return format(value.normalize(), "f")
