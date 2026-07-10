from __future__ import annotations

from pathlib import Path


def test_init_sql_has_group_collect_tables() -> None:
    sql = Path("sql/init.sql").read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS wechat_group_config" in sql
    assert "CREATE TABLE IF NOT EXISTS wechat_group_msg_raw" in sql
    assert "CREATE TABLE IF NOT EXISTS wechat_group_msg_clean" in sql
    assert "CREATE TABLE IF NOT EXISTS wechat_group_msg_analysis" in sql
    assert "CREATE TABLE IF NOT EXISTS wechat_group_daily_report" in sql
    assert "CREATE TABLE IF NOT EXISTS wechat_group_collect_cursor" in sql
    assert "UNIQUE KEY uk_msg_hash (msg_hash)" in sql
    assert "UNIQUE KEY uk_clean_msg_hash (msg_hash)" in sql
    assert "UNIQUE KEY uk_group_analysis_msg_hash (msg_hash)" in sql
    assert "UNIQUE KEY uk_group_daily_report (report_date, group_name)" in sql
    assert "sender_hash VARCHAR(64)" in sql
    assert "clean_content TEXT" in sql
    assert "intent_type VARCHAR(50)" in sql
    assert "region_hits TEXT" in sql
    assert "category_hits TEXT" in sql
    assert "opportunity_hits TEXT" in sql
    assert "opportunity_score INT" in sql
    assert "markdown_body MEDIUMTEXT" in sql
    assert "has_phone TINYINT" in sql
    assert "has_wechat_id TINYINT" in sql
    assert "UNIQUE KEY uk_group_name (group_name)" in sql
    assert "wechat_article_process_task" in sql
