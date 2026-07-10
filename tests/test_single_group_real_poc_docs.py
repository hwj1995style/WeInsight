from __future__ import annotations

from pathlib import Path

from app.security.output_policy import USER_FACING_DOC_PATHS


DOC = Path("docs/operations/单核心群真实轮询POC运行记录.md")
PLAN = Path("docs/superpowers/plans/2026-07-07-微信信息采集分析系统第八阶段受控真实账号POC计划.md")


def test_single_group_real_poc_doc_limits_to_one_core_group() -> None:
    content = DOC.read_text(encoding="utf-8")

    assert "1 个实际授权核心群" in content
    assert "run-group-scheduler --once" in content
    assert "group-runtime-summary" in content
    assert "group-runtime-metrics" in content
    assert "截图" in content
    assert "去重" in content


def test_single_group_real_poc_doc_documents_safe_runtime_boundaries() -> None:
    content = DOC.read_text(encoding="utf-8")

    for keyword in [
        "手动命令触发",
        "有人值守",
        "不注册 Windows 计划任务",
        "不启动 article 链路",
        "collect-group-once",
        "group-config-upsert",
        "group-task-failed-list",
        "UI 锁",
        "连续失败 3 次",
        "Go / Watch / No-Go",
    ]:
        assert keyword in content


def test_single_group_real_poc_doc_is_scanned_and_task_recorded() -> None:
    plan = PLAN.read_text(encoding="utf-8")

    assert DOC.as_posix() in USER_FACING_DOC_PATHS
    assert "Task 59: 单核心群真实轮询 POC" in plan
    assert "单核心群真实轮询POC运行记录.md" in plan
