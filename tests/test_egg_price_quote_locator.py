from app.domain.egg_price_quote_locator import (
    locate_quote_content,
    parse_account_ocr_lines,
)


def table(*, title="", headers=None, rows=None, context=None, media="dom_table"):
    return {
        "source_media_type": media,
        "source_table_index": 0,
        "title": title,
        "headers": headers or [],
        "rows": rows or [],
        "context": context or {},
    }


def test_jiameixian_locator_parses_current_article_lower_step() -> None:
    main = table(
        title="通货装车价（含包装）",
        headers=["净重", "价差", "昨日价", "今日价", "涨跌"],
        context={"quote_basis": "360枚/箱", "package_policy": "含包装"},
        rows=[
            ["33", "-5", "198", "198", "0"],
            ["32", "-5", "193", "193", "0"],
            ["32以下顺减-6"],
        ],
    )
    other = table(
        title="多彩鸡蛋网：贵州报价",
        headers=["毛重", "建议区间价", "涨跌"],
        rows=[["52斤以上", "240-245", "-5"]],
    )

    located = locate_quote_content(
        "家美鲜鸡蛋 佳美鲜", "全文", [main, other], []
    )

    assert located.body_text == ""
    assert len(located.tables) == 1
    assert located.tables[0]["rows"][-2:] == [
        ["31", "", "", "187", ""],
        ["30", "", "", "181", ""],
    ]


def test_edge_steps_are_parsed_from_table_text_instead_of_account_constants() -> None:
    main = table(
        title="通货装车价（含包装）",
        headers=["净重", "价差", "今日价", "涨跌稳"],
        rows=[
            ["精品大码以上每斤+3"],
            ["48", "标价", "218", "0"],
            ["47", "-2", "216", "0"],
            ["38", "-4", "186", "0"],
            ["小码以下每斤-5元"],
        ],
    )

    located = locate_quote_content("江西九江褐壳蛋", "", [main], [])

    prices = {int(row[0]): row[2] for row in located.tables[0]["rows"]}
    assert prices[50] == "224"
    assert prices[49] == "221"
    assert prices[37] == "181"
    assert prices[30] == "146"


def test_direct_table_rule_takes_priority_over_inferred_nearby_title() -> None:
    main = table(
        title="相邻表说明：小码以下每斤-9元",
        headers=["净重", "价差", "今日价", "涨跌稳"],
        rows=[
            ["38", "-4", "186", "0"],
            ["小码以下每斤-4元"],
        ],
    )

    located = locate_quote_content("江西九江褐壳蛋", "", [main], [])

    prices = {int(row[0]): row[2] for row in located.tables[0]["rows"]}
    assert prices[37] == "182"
    assert prices[30] == "154"


def test_jiujiang_brown_and_powder_tables_apply_their_own_dynamic_rules() -> None:
    brown = table(
        title="当日褐壳参考价",
        headers=["毛重", "价差", "今日价", "涨跌稳"],
        rows=[["33", "-5", "198", "0"], ["32", "-5", "193", "0"], ["32以下顺减-6"]],
    )
    powder = table(
        title="当日粉壳参考价",
        headers=["净重", "价差", "今日价", "涨跌稳"],
        rows=[["33", "-4", "202", "0"], ["32", "-4", "198", "0"], ["32以下顺减-7"]],
    )

    located = locate_quote_content("江西九江褐壳蛋", "", [brown, powder], [])

    brown_prices = {int(row[0]): row[2] for row in located.tables[0]["rows"]}
    powder_prices = {int(row[0]): row[2] for row in located.tables[1]["rows"]}
    assert brown_prices[30] == "181"
    assert powder_prices[30] == "184"


def test_guiyang_locator_selects_quote_table_and_expands_thresholds() -> None:
    quote = table(
        title="7月15日贵阳鸡蛋价格参考仅供参考",
        headers=["规格", "毛重", "含包装价", "跌"],
        rows=[
            ["大码", "52斤以上", "240—245", "↓5"],
            ["大码", "50斤以上", "235—240", "↓5"],
            ["中码", "48斤以上", "230—235", "↓5"],
            ["初产", "33斤以上", "195—200", "↓5"],
            ["初产", "33斤以下", "190—195", "↓5"],
        ],
    )
    ad = table(title="鹌鹑蛋", headers=["价格"], rows=[["120-130"]])

    located = locate_quote_content("贵阳鸡蛋价格", "全文", [ad, quote], [])

    weights = [row[1] for row in located.tables[0]["rows"]]
    assert "50斤" in weights
    assert "49斤" in weights
    assert "48斤" in weights
    assert "35斤" in weights
    assert "33斤" in weights
    assert weights[-3:] == ["30斤", "31斤", "32斤"]
    assert all(30 <= int(weight.removesuffix("斤")) <= 50 for weight in weights)


def test_guiyang_locator_ignores_matching_single_row_non_main_table() -> None:
    partial = table(
        title="趋势参考",
        headers=["规格", "毛重", "含包装价"],
        rows=[["趋势", "45斤以上", "240-245"]],
    )

    located = locate_quote_content("贵阳鸡蛋价格", "", [partial], [])

    assert located.tables == []


def test_lantian_locator_keeps_only_fuyang_premium_large_text_block() -> None:
    body = "\n".join(
        [
            "阜阳地区鸡蛋报价",
            "精品蛋报价",
            "大码蛋系列",
            "44-45斤230",
            "42-43斤225",
            "小码蛋系列",
            "36-37斤225",
            "其他地区鸡蛋报价",
            "44-45斤220",
        ]
    )

    located = locate_quote_content("蓝天禽蛋联盟", body, [], [])

    assert located.body_text == ""
    assert located.tables[0]["source_media_type"] == "text_block"
    assert located.tables[0]["rows"] == [
        ["44-45斤", "230"],
        ["42-43斤", "225"],
    ]
    assert located.tables[0]["context"]["region"] == "阜阳"


def test_jiujiang_locator_keeps_brown_and_powder_tables_with_product_names() -> None:
    brown = table(
        title="当日褐壳参考价",
        headers=["毛重", "价差", "今日价", "涨跌稳"],
        rows=[["45", "标价", "236", "0"], ["44", "-2", "234", "0"]],
        context={"adjacent_table": "德安粉壳参考价"},
    )
    powder = table(
        title="当日德安粉壳参考价",
        headers=["净重", "价差", "今日价", "涨跌稳"],
        rows=[["45", "标价", "236", "0"], ["44", "-2", "234", "0"]],
    )

    located = locate_quote_content("江西九江褐壳蛋", "", [brown, powder], [])

    assert [item["title"] for item in located.tables] == [
        "当日褐壳参考价",
        "当日德安粉壳参考价",
    ]
    assert [item["context"]["product_name"] for item in located.tables] == [
        "褐壳蛋",
        "粉壳蛋",
    ]


def test_target_image_accounts_use_only_recognized_ocr_tables() -> None:
    unsupported = {
        "source_media_type": "image_quote_not_supported_v1",
        "source_image_index": 0,
        "note": "image_quote_not_supported_v1",
    }
    recognized = table(
        title="湖南三尖精品蛋360枚/箱收购价",
        headers=["净重", "价差", "昨日价", "今日价", "涨跌"],
        rows=[["48", "-1", "262", "262", "0"]],
        media="image_ocr",
    )

    located = locate_quote_content(
        "湖南三尖农牧公司", "说明文字", [], [unsupported, recognized]
    )

    assert located.body_text == ""
    assert located.tables[0]["source_media_type"] == "image_ocr"
    assert located.tables[0]["rows"] == recognized["rows"]
    assert located.tables[0]["context"]["product_name"] == "鸡蛋"
    assert located.ocr_notes == []


def test_parse_henan_ocr_lines_builds_price_table() -> None:
    parsed = parse_account_ocr_lines(
        "河南金咕咕蛋品",
        [
            "金咕咕蛋品 2026年7月15日今日报价",
            "30斤-37斤 4.95元/斤 4.95元/斤 稳",
            "37斤-40斤 4.80元/斤 4.80元/斤 稳",
        ],
        source_image_index=1,
    )

    assert parsed is not None
    assert parsed["source_media_type"] == "image_ocr"
    assert parsed["headers"] == ["净重", "今日价"]
    assert parsed["rows"] == [
        ["30-37斤", "4.95元/斤"],
        ["37-40斤", "4.80元/斤"],
    ]


def test_parse_hunan_ocr_lines_uses_today_price_column() -> None:
    parsed = parse_account_ocr_lines(
        "湖南三尖农牧公司",
        [
            "湖南三尖精品蛋360枚/箱收购价",
            "48 -1 262 262 0",
            "47 -1 261 261 0",
            "45 标准价 258 258 0",
        ],
        source_image_index=0,
    )

    assert parsed is not None
    assert parsed["headers"] == ["净重", "价差", "昨日价", "今日价", "涨跌"]
    assert parsed["rows"] == [
        ["48", "-1", "262", "262", "0"],
        ["47", "-1", "261", "261", "0"],
        ["45", "标准价", "258", "258", "0"],
    ]


def test_parse_hunan_ocr_separate_columns_maps_today_prices_to_all_weights() -> None:
    prices = [str(value) for value in range(262, 243, -1)]
    parsed = parse_account_ocr_lines(
        "湖南三尖农牧公司",
        [
            "湖南三尖精品蛋360枚/箱收购价",
            "昨日价",
            *prices,
            "今日价 涨跌",
            *prices,
        ],
        source_image_index=1,
    )

    assert parsed is not None
    assert parsed["headers"] == ["净重", "今日价"]
    assert parsed["rows"][0] == ["48", "262"]
    assert parsed["rows"][-1] == ["30", "244"]
