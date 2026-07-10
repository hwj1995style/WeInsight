from __future__ import annotations

from pathlib import Path

from app.security.output_policy import USER_FACING_DOC_PATHS


DOC = Path("docs/operations/三账号小规模交错POC运行记录.md")
PLAN = Path("docs/superpowers/plans/2026-07-07-微信信息采集分析系统第九阶段真实账户POC执行计划.md")


def test_three_account_interleaved_poc_doc_documents_hourly_rules() -> None:
    content = DOC.read_text(encoding="utf-8")

    for keyword in [
        "3 个账号",
        "每小时执行 1 次",
        "只采集当天发布数据",
        "群链路优先",
        "article 链路可中断",
        "核心群等待超过阈值",
    ]:
        assert keyword in content


def test_three_account_interleaved_poc_doc_documents_commands_and_isolation() -> None:
    content = DOC.read_text(encoding="utf-8")

    for keyword in [
        "Task 68",
        "三公众号订阅号扩容配置记录.md",
        "run-group-scheduler --once",
        "run-article-scheduler --once",
        "trial-monitor-report",
        "article-task-failed-list",
        "group-task-failed-list",
        "任一账号失败都可单独关闭",
        "回滚到单账号模式",
        "只保留群链路",
        "model_called=0",
    ]:
        assert keyword in content


def test_three_account_interleaved_poc_doc_is_scanned_and_task_recorded() -> None:
    plan = PLAN.read_text(encoding="utf-8")

    assert DOC.as_posix() in USER_FACING_DOC_PATHS
    assert "Task 69: 3 账号小规模交错 POC" in plan
    assert "三账号小规模交错POC运行记录.md" in plan
