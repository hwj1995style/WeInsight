from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
import re
from types import MappingProxyType
from collections import defaultdict
from typing import Literal, Mapping, Sequence


PriceSide = Literal["single", "low", "high"]
CellSource = Literal["observed", "extrapolated", "empty"]


@dataclass(frozen=True)
class AccountMatrixRule:
    account_name: str
    unit: str
    description: str = ""
    target_market: str | None = None


@dataclass(frozen=True)
class PriceMatrixCell:
    value: Decimal | None
    source: CellSource
    explanation: str | None = None

    @property
    def display_value(self) -> str:
        if self.value is None:
            return ""
        rounded = self.value.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
        return format(rounded, "f").rstrip("0").rstrip(".")


@dataclass(frozen=True)
class PriceMatrixColumn:
    key: str
    account_name: str
    label: str
    unit: str
    price_side: PriceSide


@dataclass(frozen=True)
class PriceMatrixRow:
    size: int
    cells: Mapping[str, PriceMatrixCell]

    def __post_init__(self) -> None:
        object.__setattr__(self, "cells", MappingProxyType(dict(self.cells)))


@dataclass(frozen=True)
class PriceMatrix:
    quote_date: date
    updated_at: datetime | None
    source_count: int
    columns: tuple[PriceMatrixColumn, ...]
    rows: tuple[PriceMatrixRow, ...]
    rules: tuple[AccountMatrixRule, ...]


@dataclass(frozen=True)
class PriceMatrixSourceRow:
    row_id: int
    article_hash: str
    account_name: str
    quote_date: date | None
    publish_time: datetime | None
    analyze_time: datetime | None
    region: str | None
    market_name: str | None
    product_family: str
    include_in_egg_price: bool
    spec_text: str | None
    weight_low: Decimal | None
    weight_high: Decimal | None
    price_low: Decimal | None
    price_high: Decimal | None
    price_unit_text: str | None


ACCOUNT_MATRIX_RULES = tuple(
    AccountMatrixRule(account_name=account_name, unit=unit, description=description)
    for account_name, unit, description in (
        ("家美鲜鸡蛋 佳美鲜", "元/箱", "按元/箱展示；精确码数或重量区间展开；价格存在上下限时拆分低价、高价列。"),
        ("河北馆陶鸡蛋报价", "元/箱", "按元/箱展示；净重区间内各码使用同一报价；价格存在上下限时拆分低价、高价列。"),
        ("河南金咕咕蛋品", "元/斤", "按元/斤展示；规格区间展开；区间边界重复时取较高价格；价格存在上下限时拆分低价、高价列。"),
        ("贵阳鸡蛋价格", "元/箱", "按元/箱展示；明确拆分低价、高价列；重量区间展开。"),
        ("蓝天禽蛋联盟", "元/箱", "按元/箱展示；只纳入配置指定的目标市场；重量区间内各码使用同一报价。"),
        ("湖南三尖农牧公司", "元/箱", "按元/箱展示；精确码数或重量区间展开；价格存在上下限时拆分低价、高价列。"),
        ("成都鸡蛋价格", "元/箱", "按元/箱展示；净重区间内各码使用同一报价；价格区间拆低价、高价列。"),
        ("河北辛集城方蛋品", "元/箱", "按元/箱展示；精确码数或重量区间展开；价格存在上下限时拆分低价、高价列。"),
        ("江西九江褐壳蛋", "元/箱", "按元/箱展示；精确码数或重量区间展开；价格存在上下限时拆分低价、高价列。"),
    )
)

_ACCOUNT_KEYS = {
    "家美鲜鸡蛋 佳美鲜": "jiameixian",
    "河北馆陶鸡蛋报价": "guantao",
    "河南金咕咕蛋品": "henan",
    "贵阳鸡蛋价格": "guiyang",
    "蓝天禽蛋联盟": "lantian",
    "湖南三尖农牧公司": "sanjian",
    "成都鸡蛋价格": "chengdu",
    "河北辛集城方蛋品": "xinji",
    "江西九江褐壳蛋": "jiujiang",
}


def select_latest_article_rows(
    rows: Sequence[PriceMatrixSourceRow], quote_date: date
) -> tuple[PriceMatrixSourceRow, ...]:
    rules_by_account = {rule.account_name: rule for rule in ACCOUNT_MATRIX_RULES}
    eligible = []
    for row in rows:
        rule = rules_by_account.get(row.account_name)
        if (
            rule is None
            or row.quote_date != quote_date
            or not row.include_in_egg_price
            or row.product_family != "chicken_egg"
        ):
            continue
        if row.account_name == "蓝天禽蛋联盟":
            if rule.target_market is None or row.market_name != rule.target_market:
                continue
        eligible.append(row)
    by_account_and_article: dict[
        tuple[str, str], list[PriceMatrixSourceRow]
    ] = defaultdict(list)
    for row in eligible:
        by_account_and_article[(row.account_name, row.article_hash)].append(row)

    article_groups: dict[str, list[tuple[tuple[datetime, str, int], list[PriceMatrixSourceRow]]]] = defaultdict(list)
    for (account_name, article_hash), article_rows in by_account_and_article.items():
        latest_publish = max(
            (row.publish_time or datetime.min for row in article_rows),
            default=datetime.min,
        )
        article_groups[account_name].append(
            ((latest_publish, article_hash, max(row.row_id for row in article_rows)), article_rows)
        )

    selected: list[PriceMatrixSourceRow] = []
    for groups in article_groups.values():
        selected.extend(max(groups, key=lambda item: item[0])[1])
    return tuple(sorted(selected, key=lambda row: row.row_id))


def _column_definitions(
    rows: Sequence[PriceMatrixSourceRow],
) -> tuple[PriceMatrixColumn, ...]:
    rows_by_account: dict[str, list[PriceMatrixSourceRow]] = defaultdict(list)
    for row in rows:
        rows_by_account[row.account_name].append(row)

    columns: list[PriceMatrixColumn] = []
    for rule in ACCOUNT_MATRIX_RULES:
        account_rows = rows_by_account.get(rule.account_name)
        if not account_rows:
            continue
        sides: tuple[PriceSide, ...] = (
            ("low", "high")
            if any(row.price_high is not None for row in account_rows)
            else ("single",)
        )
        for side in sides:
            columns.append(
                PriceMatrixColumn(
                    key=f"{_ACCOUNT_KEYS[rule.account_name]}:{side}",
                    account_name=rule.account_name,
                    label={"single": "报价", "low": "低价", "high": "高价"}[side],
                    unit=rule.unit,
                    price_side=side,
                )
            )
    return tuple(columns)


def map_observed_cells(
    rows: Sequence[PriceMatrixSourceRow],
    columns: Sequence[PriceMatrixColumn],
) -> dict[str, dict[int, PriceMatrixCell]]:
    column_by_account_and_side = {
        (column.account_name, column.price_side): column for column in columns
    }
    observed: dict[str, dict[int, PriceMatrixCell]] = {
        column.key: {} for column in columns
    }
    for row in rows:
        size_range = _row_size_range(row)
        if size_range is None or row.price_low is None:
            continue
        low_size, high_size = size_range
        has_split_columns = (row.account_name, "low") in column_by_account_and_side
        prices: tuple[tuple[PriceSide, Decimal | None], ...] = (
            (("low", row.price_low), ("high", row.price_high))
            if has_split_columns
            else (("single", row.price_low),)
        )
        for side, price in prices:
            column = column_by_account_and_side.get((row.account_name, side))
            if column is None or price is None:
                continue
            for size in range(low_size, high_size + 1):
                existing = observed[column.key].get(size)
                if existing is None:
                    observed[column.key][size] = PriceMatrixCell(price, "observed")
                elif existing.value == price:
                    continue
                elif row.account_name == "河南金咕咕蛋品":
                    if existing.value is None or price > existing.value:
                        observed[column.key][size] = PriceMatrixCell(price, "observed")
                else:
                    observed[column.key][size] = PriceMatrixCell(
                        None,
                        "empty",
                        "同一账号同一码数存在不同原始报价，按规则无法决胜，已留空",
                    )
    return observed


_SPEC_SIZE_PATTERN = re.compile(
    r"(?<!\d)(3\d|4\d|50)\s*(?:[-—–~～至到]\s*(3\d|4\d|50))?\s*(?:码|斤)"
)


def _row_size_range(row: PriceMatrixSourceRow) -> tuple[int, int] | None:
    if row.weight_low is not None and row.weight_high is not None:
        low_size = max(30, int(row.weight_low))
        high_size = min(50, int(row.weight_high))
    else:
        match = _SPEC_SIZE_PATTERN.search(row.spec_text or "")
        if match is None:
            return None
        first = int(match.group(1))
        second = int(match.group(2) or first)
        low_size, high_size = sorted((first, second))
    if low_size > high_size:
        return None
    return low_size, high_size


def _format_decimal(value: Decimal) -> str:
    return format(value, "f")


def extrapolate_missing_cells(
    observed: Mapping[str, Mapping[int, PriceMatrixCell]],
) -> dict[str, dict[int, PriceMatrixCell]]:
    completed: dict[str, dict[int, PriceMatrixCell]] = {}
    for column_key, source_cells in observed.items():
        cells = dict(source_cells)
        known = sorted(
            (size, cell.value)
            for size, cell in source_cells.items()
            if cell.value is not None and cell.source == "observed"
        )
        pairs = list(zip(known, known[1:]))
        for target in range(30, 51):
            existing = cells.get(target)
            if existing is not None and existing.source != "empty":
                continue
            if not pairs:
                cells[target] = PriceMatrixCell(None, "empty")
                continue
            if target < known[0][0]:
                pair = pairs[0]
            elif target > known[-1][0]:
                pair = pairs[-1]
            else:
                pair = min(
                    pairs,
                    key=lambda candidate: (
                        min(abs(target - candidate[0][0]), abs(target - candidate[1][0])),
                        candidate[0][0],
                    ),
                )
            (low_size, low_price), (high_size, high_price) = pair
            assert low_price is not None and high_price is not None
            delta = (high_price - low_price) / Decimal(high_size - low_size)
            value = low_price + delta * Decimal(target - low_size)
            direction = "高码" if target > high_size else "低码"
            signed_delta = f"{delta:+f}"
            explanation = (
                f"依据 {low_size}码 {_format_decimal(low_price)} 与 "
                f"{high_size}码 {_format_decimal(high_price)}，"
                f"按每码 {signed_delta} 向{direction}推算"
            )
            if existing is not None and existing.explanation:
                explanation = f"原始报价冲突未参与计算；{explanation}"
            cells[target] = PriceMatrixCell(value, "extrapolated", explanation)
        completed[column_key] = cells
    return completed


def build_price_matrix(
    rows: Sequence[PriceMatrixSourceRow], quote_date: date
) -> PriceMatrix:
    selected_rows = select_latest_article_rows(rows, quote_date)
    columns = _column_definitions(selected_rows)
    observed = map_observed_cells(selected_rows, columns)
    completed = extrapolate_missing_cells(observed)
    matrix_rows = tuple(
        PriceMatrixRow(
            size=size,
            cells={column.key: completed[column.key][size] for column in columns},
        )
        for size in range(50, 29, -1)
    )
    return PriceMatrix(
        quote_date=quote_date,
        updated_at=max(
            (
                timestamp
                for row in selected_rows
                if (timestamp := row.analyze_time or row.publish_time) is not None
            ),
            default=None,
        ),
        source_count=len(selected_rows),
        columns=columns,
        rows=matrix_rows,
        rules=ACCOUNT_MATRIX_RULES,
    )
