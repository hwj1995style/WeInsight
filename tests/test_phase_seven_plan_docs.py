from __future__ import annotations

from pathlib import Path


PLAN = Path("docs/superpowers/plans/2026-07-07-微信信息采集分析系统第七阶段小规模试运行和AI灰度计划.md")
DESIGN = Path("docs/design/微信信息采集分析系统落地方案设计.md")
README = Path("README.md")


def test_phase_seven_plan_is_documented() -> None:
    assert PLAN.exists()

    content = PLAN.read_text(encoding="utf-8")

    assert "第七阶段小规模试运行和AI灰度准备" in content
    for task_name in [
        "Task 51: 小规模试运行方案",
        "Task 52: 双链路试运行巡检报告",
        "Task 53: 日报质量人工评估表",
        "Task 54: AI 灰度设计",
        "Task 55: AI 分析最小 POC",
        "Task 56: 生产配置和回滚预案复核",
    ]:
        assert task_name in content

    assert "核心群不超过5个" in content
    assert "公众号/订阅号不超过20个" in content
    assert "默认关闭 AI" in content
    assert "不发送 raw 原文、文章全文、HTML" in content
    assert "AI 失败不得回写 group/article 链路状态" in content


def test_phase_seven_design_and_readme_reference_plan() -> None:
    design = DESIGN.read_text(encoding="utf-8")
    readme = README.read_text(encoding="utf-8")

    plan_name = "2026-07-07-微信信息采集分析系统第七阶段小规模试运行和AI灰度计划.md"
    assert "第七阶段小规模试运行和AI灰度准备" in design
    assert plan_name in design
    assert plan_name in readme
