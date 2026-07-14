from datetime import date
from decimal import Decimal

import pytest

from app.domain.price_matrix import (
    ACCOUNT_MATRIX_RULES,
    PriceMatrixCell,
    PriceMatrixRow,
    build_price_matrix,
)


def test_matrix_rules_cover_nine_accounts_in_fixed_order_and_units() -> None:
    assert [rule.account_name for rule in ACCOUNT_MATRIX_RULES] == [
        "家美鲜鸡蛋 佳美鲜",
        "河北馆陶鸡蛋报价",
        "河南金咕咕蛋品",
        "贵阳鸡蛋价格",
        "蓝天禽蛋联盟",
        "湖南三尖农牧公司",
        "成都鸡蛋价格",
        "河北辛集城方蛋品",
        "江西九江褐壳蛋",
    ]
    assert (
        next(
            rule
            for rule in ACCOUNT_MATRIX_RULES
            if rule.account_name == "河南金咕咕蛋品"
        ).unit
        == "元/斤"
    )
    assert all(
        rule.unit == "元/箱"
        for rule in ACCOUNT_MATRIX_RULES
        if rule.account_name != "河南金咕咕蛋品"
    )


def test_matrix_always_contains_sizes_50_down_to_30() -> None:
    matrix = build_price_matrix([], date(2026, 7, 14))

    assert [row.size for row in matrix.rows] == list(range(50, 29, -1))


def test_matrix_row_copies_cells_into_a_read_only_mapping() -> None:
    original_cells = {
        "example": PriceMatrixCell(value=Decimal("1.00"), source="observed")
    }
    row = PriceMatrixRow(size=50, cells=original_cells)

    original_cells["example"] = PriceMatrixCell(value=None, source="empty")

    assert row.cells["example"].value == Decimal("1.00")
    with pytest.raises(TypeError):
        row.cells["example"] = PriceMatrixCell(value=None, source="empty")
