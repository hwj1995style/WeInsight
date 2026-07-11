from pathlib import Path


def test_init_sql_keeps_group_and_downstream_article_tables_separate() -> None:
    sql = Path("sql/init.sql").read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS wechat_group_process_task" in sql
    assert "CREATE TABLE IF NOT EXISTS wechat_article_process_task" in sql
    assert "CREATE TABLE IF NOT EXISTS wechat_group_collect_log" in sql
    assert "CREATE TABLE IF NOT EXISTS wechat_article_collect_log" in sql
    assert "CREATE TABLE IF NOT EXISTS wechat_ui_lock" in sql


def test_rss_runner_does_not_import_group_pipeline_or_rpa() -> None:
    source = Path("app/pipelines/rss_article_polling_runner.py").read_text(encoding="utf-8")
    assert "group_polling_runner" not in source
    assert "app.rpa" not in source
