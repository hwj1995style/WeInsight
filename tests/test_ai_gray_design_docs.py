from __future__ import annotations

from pathlib import Path


DESIGN = Path("docs/design/AI分析灰度设计.md")
MAIN_DESIGN = Path("docs/design/微信信息采集分析系统落地方案设计.md")


def test_ai_gray_design_documents_default_off_and_input_whitelist() -> None:
    content = DESIGN.read_text(encoding="utf-8")

    assert "默认关闭 AI" in content
    assert "不发送 raw 原文、文章全文、HTML" in content
    assert "只允许输入摘要、结构化特征、脱敏字段" in content
    assert "AI 失败不得回写 group/article 链路状态" in content
    assert "prompt 版本" in content
    assert "模型版本" in content


def test_ai_gray_design_includes_design_checklist_sections() -> None:
    content = DESIGN.read_text(encoding="utf-8")

    for section in [
        "背景与现状",
        "目标与非目标",
        "影响范围",
        "输入白名单",
        "输出模型",
        "权限和配置模型",
        "后端实现方案",
        "前端影响",
        "测试与回归方案",
        "风险与分阶段落地建议",
    ]:
        assert section in content


def test_main_design_references_ai_gray_design() -> None:
    content = MAIN_DESIGN.read_text(encoding="utf-8")

    assert "AI分析灰度设计.md" in content
    assert "AI 灰度只读输入" in content
