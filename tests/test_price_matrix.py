from datetime import date, datetime
from decimal import Decimal

import pytest

from app.domain.price_matrix import (
    ACCOUNT_MATRIX_RULES,
    PriceMatrixCell,
    PriceMatrixRow,
    PriceMatrixSourceRow,
    build_price_matrix,
)


def source_row(
    *,
    row_id: int = 1,
    article_hash: str = "article",
    account_name: str = "家美鲜鸡蛋 佳美鲜",
    quote_date: date | None = date(2026, 7, 14),
    publish_time: datetime | None = datetime(2026, 7, 14, 8),
    product_family: str = "chicken_egg",
    include_in_egg_price: bool = True,
    weight_low: int | str | Decimal | None = 40,
    weight_high: int | str | Decimal | None = 40,
    price_low: str | Decimal | None = "216",
    price_high: str | Decimal | None = None,
) -> PriceMatrixSourceRow:
    decimal_or_none = lambda value: None if value is None else Decimal(value)
    return PriceMatrixSourceRow(
        row_id=row_id,
        article_hash=article_hash,
        account_name=account_name,
        quote_date=quote_date,
        publish_time=publish_time,
        analyze_time=publish_time,
        region=None,
        market_name=None,
        product_family=product_family,
        include_in_egg_price=include_in_egg_price,
        spec_text=None,
        weight_low=decimal_or_none(weight_low),
        weight_high=decimal_or_none(weight_high),
        price_low=decimal_or_none(price_low),
        price_high=decimal_or_none(price_high),
        price_unit_text=None,
    )


def cell(matrix, size: int, column_key: str) -> PriceMatrixCell:
    return next(row for row in matrix.rows if row.size == size).cells[column_key]


def cell_value(matrix, size: int, column_key: str) -> Decimal | None:
    return cell(matrix, size, column_key).value


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


def test_latest_article_wins_and_observed_value_is_not_overwritten() -> None:
    matrix = build_price_matrix(
        [
            source_row(article_hash="old", publish_time=datetime(2026, 7, 14, 8), price_low="210"),
            source_row(article_hash="new", publish_time=datetime(2026, 7, 14, 9), price_low="216"),
        ],
        date(2026, 7, 14),
    )

    assert cell(matrix, 40, "jiameixian:single") == PriceMatrixCell(
        Decimal("216"), "observed", None
    )


def test_weight_range_expands_and_price_range_splits_columns() -> None:
    matrix = build_price_matrix(
        [
            source_row(
                account_name="贵阳鸡蛋价格",
                weight_low=39,
                weight_high=40,
                price_low="214",
                price_high="219",
            )
        ],
        date(2026, 7, 14),
    )

    assert cell_value(matrix, 39, "guiyang:low") == Decimal("214")
    assert cell_value(matrix, 40, "guiyang:high") == Decimal("219")


def test_henan_boundary_collision_uses_higher_price() -> None:
    matrix = build_price_matrix(
        [
            source_row(account_name="河南金咕咕蛋品", weight_low=30, weight_high=37, price_low="4.95"),
            source_row(account_name="河南金咕咕蛋品", row_id=2, weight_low=37, weight_high=40, price_low="4.80"),
        ],
        date(2026, 7, 14),
    )

    assert cell_value(matrix, 37, "henan:single") == Decimal("4.95")


def test_nearest_delta_extrapolates_both_directions_with_explanation() -> None:
    known = {35: "200", 36: "204", 37: "208", 38: "212", 39: "214", 40: "216"}
    matrix = build_price_matrix(
        [source_row(row_id=size, weight_low=size, weight_high=size, price_low=value) for size, value in known.items()],
        date(2026, 7, 14),
    )

    assert cell_value(matrix, 34, "jiameixian:single") == Decimal("196")
    assert cell_value(matrix, 33, "jiameixian:single") == Decimal("192")
    assert cell_value(matrix, 41, "jiameixian:single") == Decimal("218")
    assert cell_value(matrix, 42, "jiameixian:single") == Decimal("220")
    assert cell(matrix, 42, "jiameixian:single") == PriceMatrixCell(
        Decimal("220"),
        "extrapolated",
        "依据 39码 214 与 40码 216，按每码 +2 向高码推算",
    )


def test_internal_gap_uses_nearest_pair_and_lower_pair_on_equal_distance() -> None:
    matrix = build_price_matrix(
        [
            source_row(row_id=1, weight_low=35, weight_high=35, price_low="200"),
            source_row(row_id=2, weight_low=36, weight_high=36, price_low="204"),
            source_row(row_id=3, weight_low=40, weight_high=40, price_low="220"),
            source_row(row_id=4, weight_low=41, weight_high=41, price_low="230"),
        ],
        date(2026, 7, 14),
    )

    assert cell_value(matrix, 38, "jiameixian:single") == Decimal("212")


def test_one_known_value_does_not_extrapolate() -> None:
    matrix = build_price_matrix([source_row()], date(2026, 7, 14))

    assert cell(matrix, 41, "jiameixian:single").source == "empty"


def test_filters_date_non_target_accounts_and_non_egg_rows() -> None:
    matrix = build_price_matrix(
        [
            source_row(price_low="216"),
            source_row(row_id=2, quote_date=date(2026, 7, 13), price_low="999"),
            source_row(row_id=3, account_name="非目标公众号", price_low="998"),
            source_row(row_id=4, include_in_egg_price=False, price_low="997"),
        ],
        date(2026, 7, 14),
    )

    assert cell_value(matrix, 40, "jiameixian:single") == Decimal("216")
    assert matrix.source_count == 1


def test_low_high_columns_extrapolate_independently() -> None:
    matrix = build_price_matrix(
        [
            source_row(account_name="贵阳鸡蛋价格", row_id=1, weight_low=39, weight_high=39, price_low="210", price_high="215"),
            source_row(account_name="贵阳鸡蛋价格", row_id=2, weight_low=40, weight_high=40, price_low="212", price_high="220"),
        ],
        date(2026, 7, 14),
    )

    assert cell_value(matrix, 41, "guiyang:low") == Decimal("214")
    assert cell_value(matrix, 41, "guiyang:high") == Decimal("225")
