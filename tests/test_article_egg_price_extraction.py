from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime

from app.domain.article_egg_price import extract_egg_prices


@dataclass(frozen=True)
class Source:
    article_hash: str = "hash-1"
    account_name: str = "测试账号"
    title: str = "测试文章"
    publish_time: datetime | None = datetime(2026, 7, 9, 9, 0)
    author: str | None = None
    digest: str | None = None
    content_length: int = 100
    article_url: str = ""
    collect_time: datetime | None = None
    transient_body_text: str | None = None
    transient_html_tables: list[dict] | None = None
    transient_ocr_tables: list[dict] | None = None


def test_extracts_fujian_short_text_quotes() -> None:
    source = Source(
        account_name="福建闽融鸡蛋报价平台",
        transient_body_text="1.红蛋价格：4.90元/筐装(稳)\n2.粉蛋价格：5.00元/筐装(稳)",
    )

    result = extract_egg_prices(source, analyze_time=datetime(2026, 7, 9, 10, 0))

    assert result.status == "success"
    assert len(result.items) == 2
    first = result.items[0]
    assert first.product_family == "chicken_egg"
    assert first.product_name == "红蛋"
    assert first.price_text == "4.90元"
    assert first.price_low == 4.9
    assert first.price_high == 4.9
    assert first.package_policy == "筐装"
    assert first.trend == "flat"
    assert first.include_in_egg_price is True
    assert first.standard_price_low == 4.9
    assert first.standard_price_high == 4.9
    assert first.standard_price_unit == "yuan_per_jin"
    assert first.conversion_method == "already_yuan_per_jin"
    assert first.conversion_confidence == 0.9
    assert first.include_in_standard_price is True


def test_classifies_brown_shell_egg_as_chicken_egg() -> None:
    source = Source(transient_body_text="褐壳蛋价格：4.90元/斤（稳）")

    result = extract_egg_prices(source, analyze_time=datetime(2026, 7, 9, 10, 0))

    assert result.items[0].product_name == "褐壳蛋"
    assert result.items[0].product_family == "chicken_egg"


def test_uses_title_quote_date_when_publish_time_is_previous_day() -> None:
    source = Source(
        account_name="福建闽融鸡蛋报价平台",
        title="2026年07月09日｜福建闽融平台",
        publish_time=datetime(2026, 7, 8, 21, 59),
        collect_time=datetime(2026, 7, 9, 8, 3),
        transient_body_text="1.红蛋价格：4.90元/筐装(稳)",
    )

    result = extract_egg_prices(source, analyze_time=datetime(2026, 7, 9, 10, 0))

    assert len(result.items) == 1
    item = result.items[0]
    assert item.publish_date == date(2026, 7, 8)
    assert item.collect_time == datetime(2026, 7, 9, 8, 3)
    assert item.quote_date == date(2026, 7, 9)
    assert item.quote_date_source == "title"
    assert item.quote_date_confidence == 1.0


def test_extracts_shanghai_full_poultry_catalog_with_chicken_filter() -> None:
    source = Source(
        account_name="上海禽蛋价格综合报价",
        transient_body_text="\n".join(
            [
                "洋鸡蛋净重26.5斤为132元",
                "翻箱零破损洋鸡蛋137元",
                "绿壳蛋小185元",
                "青皮新鲜鸭蛋27斤165元便宜货155元",
                "鹌鹑蛋净重30斤160元",
            ]
        ),
    )

    result = extract_egg_prices(source, analyze_time=datetime(2026, 7, 9, 10, 0))

    assert [item.product_family for item in result.items] == [
        "chicken_egg",
        "chicken_egg",
        "chicken_egg",
        "duck_egg",
        "quail_egg",
    ]
    assert [item.include_in_egg_price for item in result.items] == [True, True, True, False, False]
    assert result.items[0].product_name == "洋鸡蛋"
    assert result.items[0].weight_text == "净重26.5斤"
    assert result.items[0].price_text == "132元"


def test_extracts_jiameixian_dom_table_context() -> None:
    source = Source(
        account_name="家美鲜鸡蛋 佳美鲜",
        transient_html_tables=[
            {
                "source_media_type": "dom_table",
                "source_table_index": 0,
                "title": "通货装车价（含包装）",
                "context": {"quote_basis": "360枚/箱"},
                "headers": ["净重", "价差", "昨日价", "今日价", "涨跌"],
                "rows": [
                    ["45", "标价", "215", "220", "5"],
                    ["44", "-2", "213", "218", "5"],
                ],
            }
        ],
    )

    result = extract_egg_prices(source, analyze_time=datetime(2026, 7, 9, 10, 0))

    assert len(result.items) == 2
    assert result.items[0].source_media_type == "dom_table"
    assert result.items[0].quote_basis == "360枚/箱"
    assert result.items[0].trade_scene == "装车"
    assert result.items[0].package_policy == "含包装"
    assert result.items[0].weight_text == "45"
    assert result.items[0].price_text == "220"
    assert result.items[0].yesterday_price_text == "215"
    assert result.items[0].change_value == 5
    assert result.items[0].standard_price_low == 4.8889
    assert result.items[0].standard_price_high == 4.8889
    assert result.items[0].conversion_basis_weight_low == 45
    assert result.items[0].conversion_basis_weight_high == 45
    assert result.items[0].conversion_basis_weight_unit == "jin"
    assert result.items[0].conversion_method == "row_weight"
    assert result.items[0].include_in_standard_price is True
    assert result.table_summaries[0]["row_count"] == 2
    assert result.table_summaries[0]["parsed_item_count"] == 2


def test_extracts_hebei_mid_table_heading_context() -> None:
    source = Source(
        account_name="河北馆陶鸡蛋报价",
        transient_html_tables=[
            {
                "source_media_type": "dom_table",
                "source_table_index": 0,
                "title": "河北馆陶鸡蛋报价",
                "context": {
                    "quote_basis": "360枚/箱",
                    "package_policy": "不含运费和包装费",
                },
                "headers": ["净重", "昨日价", "今日价", "涨跌"],
                "rows": [
                    ["精品菜花黄蛋托（粉蛋）"],
                    ["45斤", "192元", "192元", "0"],
                    ["44斤", "191元", "191元", "0"],
                ],
            }
        ],
    )

    result = extract_egg_prices(source, analyze_time=datetime(2026, 7, 9, 10, 0))

    assert len(result.items) == 2
    assert result.items[0].product_name == "粉蛋"
    assert result.items[0].quote_basis == "360枚/箱"
    assert result.items[0].package_policy == "不含运费和包装费"
    assert result.items[0].weight_text == "45斤"
    assert result.items[0].price_text == "192元"


def test_extracts_guiyang_packaged_price_dom_table() -> None:
    source = Source(
        account_name="贵阳鸡蛋价格",
        title="继续上涨：7月8日贵阳鸡蛋价格参考",
        transient_html_tables=[
            {
                "source_media_type": "dom_table",
                "source_table_index": 3,
                "title": "7月8日贵阳鸡蛋价格参考仅供参考",
                "context": {},
                "headers": ["规格", "毛重", "含包装价", "涨"],
                "rows": [
                    ["大码", "52斤以上", "228—233", "↑5"],
                    ["大码", "50斤以上", "224—229", "↑5"],
                    ["中码", "48斤以上", "220—225", "↑5"],
                    ["中码", "46斤以上", "215—220", "↑4"],
                    ["中码", "44斤以上", "210—215", "↑3"],
                    ["小码", "42斤以上", "205—210", "↑2"],
                    ["小码", "40斤以上", "200—205", "↑1"],
                    ["小码", "38斤以上", "195—200", "-"],
                    ["初产", "36斤以上", "190—195", "-"],
                    ["初产", "33斤以上", "185—190", "-"],
                    ["初产", "33斤以下", "180—190", "-"],
                ],
            }
        ],
    )

    result = extract_egg_prices(source, analyze_time=datetime(2026, 7, 9, 10, 0))

    assert len(result.items) == 21
    assert all(item.product_family == "chicken_egg" for item in result.items)
    assert all(item.product_name == "鸡蛋" for item in result.items)
    size_50 = next(item for item in result.items if item.weight_low == 50)
    assert size_50.spec_text == "大码"
    assert size_50.weight_text == "50斤"
    assert size_50.price_text == "224—229"
    assert size_50.change_text == "↑5"
    assert size_50.trend == "up"
    assert size_50.package_policy == "含包装"
    assert size_50.conversion_method == "row_weight"
    assert size_50.include_in_standard_price is True
    assert result.table_summaries[0]["parsed_item_count"] == 21


def test_guiyang_old_hen_price_does_not_inherit_egg_context() -> None:
    source = Source(
        account_name="贵阳鸡蛋价格",
        transient_body_text="\n".join(
            [
                "7月8日价格论斤参考：",
                "粉壳红心蛋论斤净重：大码4.90—5.00元/斤，中小码溢价；",
                "褐壳红心蛋论斤净重：大码5.00—5.10元/斤，中小码溢价；",
                "贵州老母鸡价格参考：粉鸡6.3—6.8元/斤，红鸡7.8—7.9元/斤",
            ]
        ),
    )

    result = extract_egg_prices(source, analyze_time=datetime(2026, 7, 9, 10, 0))

    assert result.items == []
    assert result.status == "no_price_data"


def test_no_header_dom_prose_table_does_not_duplicate_text_line_quotes() -> None:
    source = Source(
        account_name="贵阳鸡蛋价格",
        transient_body_text="粉壳红心蛋论斤净重：大码4.90—5.00元/斤，中小码溢价；",
        transient_html_tables=[
            {
                "source_media_type": "dom_table",
                "source_table_index": 5,
                "title": "鸡蛋规格：标准箱360枚装",
                "context": {},
                "headers": [],
                "rows": [["粉壳红心蛋论斤净重：大码4.90—5.00元/斤，中小码溢价；"]],
            }
        ],
    )

    result = extract_egg_prices(source, analyze_time=datetime(2026, 7, 9, 10, 0))

    assert result.items == []
    assert result.status == "no_price_data"


def test_extracts_yixiandan_quote_basis_and_region() -> None:
    source = Source(
        account_name="一箱蛋",
        transient_body_text="报价单位：30斤\n徐州-丰县鸡蛋价格 133 稳\n宿迁-泗阳鸡蛋价格 133 稳",
    )

    result = extract_egg_prices(source, analyze_time=datetime(2026, 7, 9, 10, 0))

    assert len(result.items) == 2
    assert result.items[0].quote_basis == "30斤"
    assert result.items[0].region == "徐州"
    assert result.items[0].market_name == "丰县"
    assert result.items[0].price_text == "133"
    assert result.items[0].trend == "flat"
    assert result.items[0].standard_price_low == 4.4333
    assert result.items[0].standard_price_high == 4.4333
    assert result.items[0].conversion_basis_weight_low == 30
    assert result.items[0].conversion_basis_weight_high == 30
    assert result.items[0].conversion_method == "quote_basis_weight"
    assert result.items[0].include_in_standard_price is True


def test_standard_price_rejects_out_of_range_converted_price() -> None:
    source = Source(
        account_name="一箱蛋",
        transient_body_text="报价单位：30斤\n异常-样本鸡蛋价格 45 稳",
    )

    result = extract_egg_prices(source, analyze_time=datetime(2026, 7, 9, 10, 0))

    assert len(result.items) == 1
    item = result.items[0]
    assert item.price_text == "45"
    assert item.standard_price_low is None
    assert item.standard_price_high is None
    assert item.conversion_method == "unconverted"
    assert item.include_in_standard_price is False
    assert "out_of_reasonable_range" in item.conversion_notes


def test_extracts_xinli_group_heading_context() -> None:
    source = Source(
        account_name="信立鸡蛋当日价格",
        transient_body_text="1停车场红壳蛋带包装价\n毛重49-51斤223-223元♐稳定",
    )

    result = extract_egg_prices(source, analyze_time=datetime(2026, 7, 9, 10, 0))

    assert len(result.items) == 1
    assert result.items[0].trade_scene == "停车场"
    assert result.items[0].product_name == "红壳蛋"
    assert result.items[0].package_policy == "带包装"
    assert result.items[0].weight_text == "49-51斤"
    assert result.items[0].weight_low == 49
    assert result.items[0].weight_high == 51
    assert result.items[0].price_text == "223-223元"
    assert result.items[0].trend == "flat"


def test_extracts_xinli_all_parking_lot_package_groups() -> None:
    source = Source(
        account_name="信立鸡蛋当日价格",
        transient_body_text="\n".join(
            [
                "1停车场红壳蛋带包装价",
                "箱/斤 | 重量 | 今日价 | 涨/落",
                "毛重49-51斤223-223元↗稳定",
                "毛重47-48斤220-220元↗稳定",
                "毛重45-46斤218-218元↗稳定",
                "2停车场粉壳蛋带包装价",
                "箱/斤 | 重量 | 今日价 | 涨/落",
                "大码49-51斤211-211元↗稳定",
                "中码47-48斤210-210元↗稳定",
                "小码45-46斤209-209元↗稳定",
                "特小44-42斤208-208元↗稳定",
                "3停车场红心蛋带包装价",
                "毛重49-51斤230-230元↗涨5元",
                "毛重47-48斤228-228元↗涨5元",
                "毛重45-46斤226-226元↗涨5元",
            ]
        ),
    )

    result = extract_egg_prices(source, analyze_time=datetime(2026, 7, 9, 10, 0))

    assert len(result.items) == 10
    assert Counter(item.product_name for item in result.items) == {
        "红壳蛋": 3,
        "粉壳蛋": 4,
        "红心蛋": 3,
    }
    assert all(item.product_family == "chicken_egg" for item in result.items)
    assert all(item.trade_scene == "停车场" for item in result.items)
    assert all(item.package_policy == "带包装" for item in result.items)

    powder = result.items[3]
    assert powder.product_name == "粉壳蛋"
    assert powder.spec_text == "大码"
    assert powder.weight_text == "49-51斤"
    assert powder.price_text == "211-211元"

    red_heart = result.items[-3]
    assert red_heart.product_name == "红心蛋"
    assert red_heart.weight_text == "49-51斤"
    assert red_heart.price_text == "230-230元"
    assert red_heart.change_text == "涨5"
    assert red_heart.trend == "up"


def test_no_price_data_returns_empty_result() -> None:
    source = Source(
        account_name="家美鲜鸡蛋 佳美鲜",
        transient_body_text="夏季蛋鸡反复拉稀，肠道不好，高产全白搭。",
    )

    result = extract_egg_prices(source, analyze_time=datetime(2026, 7, 9, 10, 0))

    assert result.status == "no_price_data"
    assert result.items == []
    assert result.preview_json(preview_limit=20) == json.dumps(
        {
            "version": "egg_price_v1",
            "total_item_count": 0,
            "preview_limit": 20,
            "truncated": False,
            "items": [],
        },
        ensure_ascii=False,
    )
