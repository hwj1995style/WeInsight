from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from types import MappingProxyType
from typing import Literal, Mapping, Sequence


PriceSide = Literal["single", "low", "high"]
CellSource = Literal["observed", "extrapolated", "empty"]


@dataclass(frozen=True)
class AccountMatrixRule:
    account_name: str
    unit: str


@dataclass(frozen=True)
class PriceMatrixCell:
    value: Decimal | None
    source: CellSource
    explanation: str | None = None


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
    AccountMatrixRule(account_name=account_name, unit=unit)
    for account_name, unit in (
        ("家美鲜鸡蛋 佳美鲜", "元/箱"),
        ("河北馆陶鸡蛋报价", "元/箱"),
        ("河南金咕咕蛋品", "元/斤"),
        ("贵阳鸡蛋价格", "元/箱"),
        ("蓝天禽蛋联盟", "元/箱"),
        ("湖南三尖农牧公司", "元/箱"),
        ("成都鸡蛋价格", "元/箱"),
        ("河北辛集城方蛋品", "元/箱"),
        ("江西九江褐壳蛋", "元/箱"),
    )
)


def build_price_matrix(
    rows: Sequence[PriceMatrixSourceRow], quote_date: date
) -> PriceMatrix:
    matrix_rows = tuple(
        PriceMatrixRow(size=size, cells=MappingProxyType({}))
        for size in range(50, 29, -1)
    )
    return PriceMatrix(
        quote_date=quote_date,
        updated_at=None,
        source_count=len(rows),
        columns=(),
        rows=matrix_rows,
        rules=ACCOUNT_MATRIX_RULES,
    )
