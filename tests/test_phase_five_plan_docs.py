from __future__ import annotations

from pathlib import Path


PLAN = Path("docs/superpowers/plans/2026-07-06-微信信息采集分析系统第五阶段受控真实POC计划.md")
DESIGN = Path("docs/design/微信信息采集分析系统落地方案设计.md")
README = Path("README.md")


def test_phase_five_plan_is_documented() -> None:
    content = PLAN.read_text(encoding="utf-8")

    assert "第五阶段受控真实 POC" in content
    assert "Task 34" in content
    assert "Task 40" in content
    assert "开发阶段继续不注册 Windows 计划任务" in content


def test_phase_five_design_and_readme_reference_plan() -> None:
    design = DESIGN.read_text(encoding="utf-8")
    readme = README.read_text(encoding="utf-8")

    assert "公众号/订阅号受控真实 POC + 双链路隔离回归" in design
    assert "2026-07-06-微信信息采集分析系统第五阶段受控真实POC计划.md" in readme
