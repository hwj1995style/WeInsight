from __future__ import annotations

from pathlib import Path

from app.security.output_policy import USER_FACING_DOC_PATHS


PLAN = Path("docs/superpowers/plans/2026-07-07-微信信息采集分析系统第八阶段受控真实账号POC计划.md")
CHECKLIST = Path("docs/operations/真实POC前置复核清单.md")
README = Path("README.md")
DESIGN = Path("docs/design/微信信息采集分析系统落地方案设计.md")


def test_phase_eight_plan_documents_controlled_real_account_poc_tasks() -> None:
    content = PLAN.read_text(encoding="utf-8")

    assert "第八阶段受控真实账号POC" in content
    for task_name in [
        "Task 57: 真实 POC 前置复核清单",
        "Task 58: 单公众号/订阅号真实 POC",
        "Task 59: 单核心群真实轮询 POC",
        "Task 60: 双链路交错小窗口验证",
        "Task 61: POC 验收与扩容判断",
    ]:
        assert task_name in content

    assert "1 个实际授权公众号/订阅号" in content
    assert "1 个核心群" in content
    assert "手动命令触发" in content
    assert "不注册 Windows 计划任务" in content
    assert "AI 仍保持 dry-run" in content


def test_real_poc_readiness_checklist_documents_go_no_go_gates() -> None:
    content = CHECKLIST.read_text(encoding="utf-8")

    for keyword in [
        "实际授权公众号/订阅号",
        "实际授权核心群",
        "微信 PC 4.1.8.107",
        "微信自动更新已关闭",
        "只采集当天发布数据",
        "正文只运行时读取",
        "不长期保存文章正文",
        "AI 仍保持 dry-run",
        "model_called=0",
        "手动命令触发",
        "有人值守",
        "Go / No-Go",
    ]:
        assert keyword in content


def test_phase_eight_docs_are_referenced_and_scanned() -> None:
    readme = README.read_text(encoding="utf-8")
    design = DESIGN.read_text(encoding="utf-8")

    assert PLAN.name in readme
    assert "真实POC前置复核清单.md" in readme
    assert "第八阶段受控真实账号POC" in design
    assert "真实POC前置复核清单.md" in design
    assert CHECKLIST.as_posix() in USER_FACING_DOC_PATHS
