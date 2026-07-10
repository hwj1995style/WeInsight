from __future__ import annotations

from pathlib import Path


INIT_SQL = Path("sql/init.sql")
MIGRATION = Path("sql/migrations/20260706_003_create_article_analysis.sql")
QUOTE_DATE_MIGRATION = Path("sql/migrations/20260709_002_add_article_quote_date.sql")


def test_init_sql_has_article_analysis_table() -> None:
    sql = INIT_SQL.read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS wechat_article_analysis" in sql
    for column in [
        "article_hash VARCHAR(64) NOT NULL COMMENT '文章唯一hash，与clean表一致'",
        "account_name VARCHAR(200) NOT NULL COMMENT '公众号或订阅号名称'",
        "title VARCHAR(500) NOT NULL COMMENT '文章标题'",
        "publish_time DATETIME NULL COMMENT '文章发布时间'",
        "publish_date DATE NULL COMMENT '文章发布日期'",
        "collect_time DATETIME NULL COMMENT '文章采集时间'",
        "quote_date DATE NULL COMMENT '报价业务日期'",
        "quote_date_source VARCHAR(50) DEFAULT 'unknown' COMMENT '报价日期来源'",
        "quote_date_confidence DECIMAL(5,4) DEFAULT 0 COMMENT '报价日期置信度'",
        "author VARCHAR(200) NULL COMMENT '作者'",
        "summary_text TEXT NULL COMMENT '规则摘要'",
        "topic_tags_json TEXT NULL COMMENT '主题标签JSON'",
        "keyword_hits_json TEXT NULL COMMENT '关键词命中JSON'",
        "extracted_tables_json TEXT NULL COMMENT '提取表格JSON'",
        "price_items_json TEXT NULL COMMENT '价格项JSON'",
        "content_length INT DEFAULT 0 COMMENT '正文长度'",
        "analysis_version VARCHAR(20) DEFAULT 'v1' COMMENT '分析规则版本'",
        "analyze_time DATETIME NOT NULL COMMENT '分析时间'",
    ]:
        assert column in sql
    assert "UNIQUE KEY uk_article_analysis_hash (article_hash)" in sql
    assert "KEY idx_article_analysis_account_date (account_name, publish_date)" in sql
    assert "KEY idx_article_analysis_quote_date (account_name, quote_date)" in sql
    assert "KEY idx_article_analysis_time (analyze_time)" in sql


def test_article_analysis_migration_is_idempotent_and_isolated() -> None:
    assert MIGRATION.exists()

    sql = MIGRATION.read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS wechat_article_analysis" in sql
    assert "wechat_group_msg_raw" not in sql
    assert "wechat_group_process_task" not in sql
    assert "wechat_group_daily_report" not in sql
    assert "DROP TABLE" not in sql.upper()
    assert "TRUNCATE TABLE" not in sql.upper()


def test_article_quote_date_migration_is_idempotent_and_isolated() -> None:
    assert QUOTE_DATE_MIGRATION.exists()

    sql = QUOTE_DATE_MIGRATION.read_text(encoding="utf-8")

    assert "ALTER TABLE wechat_article_analysis" in sql
    assert "ADD COLUMN collect_time DATETIME NULL COMMENT ''文章采集时间''" in sql
    assert "ADD COLUMN quote_date DATE NULL COMMENT ''报价业务日期''" in sql
    assert "ADD COLUMN quote_date_source VARCHAR(50) DEFAULT ''unknown'' COMMENT ''报价日期来源''" in sql
    assert "ADD COLUMN quote_date_confidence DECIMAL(5,4) DEFAULT 0 COMMENT ''报价日期置信度''" in sql
    assert "ADD INDEX idx_article_analysis_quote_date (account_name, quote_date)" in sql
    assert "wechat_group_" not in sql
    assert "DROP TABLE" not in sql.upper()
    assert "TRUNCATE TABLE" not in sql.upper()
