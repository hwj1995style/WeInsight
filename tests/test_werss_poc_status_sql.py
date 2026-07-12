from pathlib import Path


def test_werss_poc_status_sql_is_read_only_and_covers_required_gates():
    sql = Path("sql/operations/check_werss_poc_status.sql").read_text("utf-8")

    assert "SET @poc_start" in sql
    for fragment in (
        "enabled_target_count",
        "wechat_collection_job_run",
        "failed_collect_count",
        "article_ui_lock_count",
        "non_allowlisted_downstream_task_count",
        "wechat_worker_heartbeat",
        "article_task_backlog_count",
        "group_task_backlog_count",
    ):
        assert fragment in sql
    lowered = sql.lower()
    for mutation in ("insert ", "update ", "delete ", "truncate ", "drop ", "alter "):
        assert mutation not in lowered
