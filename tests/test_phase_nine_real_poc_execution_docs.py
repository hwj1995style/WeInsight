from __future__ import annotations

from pathlib import Path

from app.security.output_policy import USER_FACING_DOC_PATHS


PLAN = Path("docs/superpowers/plans/2026-07-07-微信信息采集分析系统第九阶段真实账户POC执行计划.md")
FREEZE_DOC = Path("docs/operations/第九阶段真实POC执行准入冻结.md")
README = Path("README.md")
DESIGN = Path("docs/design/微信信息采集分析系统落地方案设计.md")


def test_phase_nine_plan_documents_controlled_execution_tasks() -> None:
    content = PLAN.read_text(encoding="utf-8")

    assert "真实账户受控 POC 执行与 3 账号小规模扩容" in content
    for task_name in [
        "Task 62: 阶段九执行方案与准入冻结",
        "Task 63: 真实 POC 环境核验",
        "Task 64: 单公众号/订阅号真实 POC 执行",
        "Task 65: 单核心群真实轮询 POC 执行",
        "Task 66: 双链路交错真实小窗口验证",
        "Task 67: 真实 POC 验收报告落地",
        "Task 68: 3 个公众号/订阅号扩容配置",
        "Task 69: 3 账号小规模交错 POC",
        "Task 70: 3 账号验收与最多 20 个扩容判断",
    ]:
        assert task_name in content

    for keyword in [
        "微信 PC 4.1.8.107",
        "AI 继续 dry-run",
        "model_called=0",
        "不注册 Windows 计划任务",
        "不启用无人值守",
        "1 个实际授权公众号/订阅号",
        "1 个实际授权核心群",
        "扩到 3 个",
        "最多 20 个只做后续评估",
    ]:
        assert keyword in content


def test_phase_nine_freeze_doc_documents_entry_and_rollback_gates() -> None:
    content = FREEZE_DOC.read_text(encoding="utf-8")

    for keyword in [
        "准入冻结",
        "不得临时扩大账号",
        "微信 PC 4.1.8.107",
        "微信自动更新已关闭",
        "AI 继续 dry-run",
        "model_called=0",
        "不注册 Windows 计划任务",
        "不启用无人值守",
        "1 个实际授权公众号/订阅号",
        "1 个实际授权核心群",
        "任一账号连续失败 3 次",
        "核心群等待超过阈值",
        "回滚到单账号模式",
        "只保留群链路",
    ]:
        assert keyword in content


def test_phase_nine_docs_are_referenced_and_scanned() -> None:
    readme = README.read_text(encoding="utf-8")
    design = DESIGN.read_text(encoding="utf-8")

    assert PLAN.name in readme
    assert FREEZE_DOC.name in readme
    assert "第九阶段真实账户POC执行计划" in design
    assert FREEZE_DOC.name in design
    assert FREEZE_DOC.as_posix() in USER_FACING_DOC_PATHS
