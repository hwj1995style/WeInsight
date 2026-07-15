from __future__ import annotations

from pathlib import Path


INIT_SQL = Path("sql/init.sql")
MIGRATION = Path("sql/migrations/20260709_001_create_article_egg_price_item.sql")
QUOTE_DATE_MIGRATION = Path("sql/migrations/20260709_002_add_article_quote_date.sql")
STANDARDIZATION_MIGRATION = Path("sql/migrations/20260709_003_add_article_price_standardization.sql")


def test_init_sql_has_article_egg_price_item_table() -> None:
    sql = INIT_SQL.read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS wechat_article_egg_price_item" in sql
    for column in [
        "article_hash VARCHAR(64) NOT NULL COMMENT '文章唯一hash，与article_analysis一致'",
        "account_name VARCHAR(200) NOT NULL COMMENT '公众号或订阅号名称'",
        "collect_time DATETIME NULL COMMENT '文章采集时间'",
        "quote_date DATE NULL COMMENT '报价业务日期'",
        "quote_date_source VARCHAR(50) DEFAULT 'unknown' COMMENT '报价日期来源'",
        "quote_date_confidence DECIMAL(5,4) DEFAULT 0 COMMENT '报价日期置信度'",
        "item_index INT NOT NULL COMMENT '同一文章内报价明细序号'",
        "source_media_type VARCHAR(50) NOT NULL COMMENT '来源类型：dom_table/text_line/text_block'",
        "product_family VARCHAR(50) NOT NULL COMMENT '产品族：chicken_egg/duck_egg/quail_egg/preserved_egg/salted_egg/other_egg'",
        "include_in_egg_price TINYINT DEFAULT 0 COMMENT '是否纳入鸡蛋报价主口径'",
        "quote_basis VARCHAR(100) NULL COMMENT '报价基准，如30斤、27.5斤、360枚/箱'",
        "price_text VARCHAR(100) NULL COMMENT '价格原文'",
        "standard_price_low DECIMAL(10,4) NULL COMMENT '统一口径价格下限'",
        "standard_price_high DECIMAL(10,4) NULL COMMENT '统一口径价格上限'",
        "standard_price_unit VARCHAR(50) DEFAULT 'yuan_per_jin' COMMENT '统一口径价格单位'",
        "conversion_basis_weight_low DECIMAL(10,3) NULL COMMENT '换算分母重量下限'",
        "conversion_basis_weight_high DECIMAL(10,3) NULL COMMENT '换算分母重量上限'",
        "conversion_basis_weight_unit VARCHAR(20) NULL COMMENT '换算分母重量单位'",
        "conversion_method VARCHAR(50) DEFAULT 'unconverted' COMMENT '规格换算方法'",
        "conversion_confidence DECIMAL(5,4) DEFAULT 0 COMMENT '规格换算置信度'",
        "conversion_notes_json TEXT NULL COMMENT '规格换算备注JSON'",
        "include_in_standard_price TINYINT DEFAULT 0 COMMENT '是否纳入统一鸡蛋价格主口径'",
        "raw_row_json TEXT NULL COMMENT '来源行JSON'",
        "analysis_version VARCHAR(20) DEFAULT 'egg_price_v1' COMMENT '蛋价解析版本'",
    ]:
        assert column in sql
    assert "UNIQUE KEY uk_article_price_item (article_hash, item_index)" in sql
    assert "KEY idx_article_price_account_date (account_name, publish_date)" in sql
    assert "KEY idx_article_price_quote_date (account_name, quote_date)" in sql
    assert "KEY idx_article_price_product_date (product_family, publish_date)" in sql
    assert "KEY idx_article_price_product_quote_date (product_family, quote_date)" in sql
    assert "KEY idx_article_price_standard_quote_date (include_in_standard_price, quote_date)" in sql
    assert "KEY idx_article_price_region_date (region, publish_date)" in sql


def test_article_egg_price_item_migration_is_idempotent_and_isolated() -> None:
    assert MIGRATION.exists()

    sql = MIGRATION.read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS wechat_article_egg_price_item" in sql
    assert "wechat_group_" not in sql
    assert "DROP TABLE" not in sql.upper()
    assert "TRUNCATE TABLE" not in sql.upper()


def test_article_price_standardization_migration_adds_columns() -> None:
    assert STANDARDIZATION_MIGRATION.exists()

    sql = STANDARDIZATION_MIGRATION.read_text(encoding="utf-8")

    assert "ALTER TABLE wechat_article_egg_price_item" in sql
    assert "ADD COLUMN standard_price_low DECIMAL(10,4) NULL COMMENT ''统一口径价格下限''" in sql
    assert "ADD COLUMN standard_price_high DECIMAL(10,4) NULL COMMENT ''统一口径价格上限''" in sql
    assert "ADD COLUMN standard_price_unit VARCHAR(50) DEFAULT ''yuan_per_jin'' COMMENT ''统一口径价格单位''" in sql
    assert "ADD COLUMN conversion_method VARCHAR(50) DEFAULT ''unconverted'' COMMENT ''规格换算方法''" in sql
    assert "ADD COLUMN include_in_standard_price TINYINT DEFAULT 0 COMMENT ''是否纳入统一鸡蛋价格主口径''" in sql
    assert "ADD INDEX idx_article_price_standard_quote_date (include_in_standard_price, quote_date)" in sql
    assert "wechat_group_" not in sql
    assert "DROP TABLE" not in sql.upper()
    assert "TRUNCATE TABLE" not in sql.upper()


def test_article_quote_date_migration_adds_egg_price_item_columns() -> None:
    assert QUOTE_DATE_MIGRATION.exists()

    sql = QUOTE_DATE_MIGRATION.read_text(encoding="utf-8")

    assert "ALTER TABLE wechat_article_egg_price_item" in sql
    assert "ADD COLUMN collect_time DATETIME NULL COMMENT ''文章采集时间''" in sql
    assert "ADD COLUMN quote_date DATE NULL COMMENT ''报价业务日期''" in sql
    assert "ADD COLUMN quote_date_source VARCHAR(50) DEFAULT ''unknown'' COMMENT ''报价日期来源''" in sql
    assert "ADD COLUMN quote_date_confidence DECIMAL(5,4) DEFAULT 0 COMMENT ''报价日期置信度''" in sql
    assert "ADD INDEX idx_article_price_quote_date (account_name, quote_date)" in sql
    assert "ADD INDEX idx_article_price_product_quote_date (product_family, quote_date)" in sql
    assert "wechat_group_" not in sql
    assert "DROP TABLE" not in sql.upper()
    assert "TRUNCATE TABLE" not in sql.upper()
