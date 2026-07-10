from __future__ import annotations

from datetime import datetime

from app.domain.group_analysis import analyze_clean_group_message
from app.domain.group_analysis_rules import AnalysisRuleSet, load_analysis_rule_set
from app.domain.group_cleaning import CleanGroupMessage


def _clean_message(content: str) -> CleanGroupMessage:
    return CleanGroupMessage(
        msg_hash="hash-1",
        group_name="核心群A",
        sender_hash="sender-hash",
        sender_display="张***",
        msg_time_display="09:15",
        msg_time_inferred=None,
        msg_type="text",
        clean_content=content,
        content_length=len(content),
        is_empty=content == "",
        has_phone=False,
        has_wechat_id=False,
        clean_version="v1",
        source_collect_batch_id="batch-1",
        clean_time=datetime(2026, 7, 3, 9, 15, 0),
    )


def test_load_analysis_rule_set_from_yaml(tmp_path) -> None:
    rules_path = tmp_path / "rules.yaml"
    rules_path.write_text(
        """
version: custom-v2
change_note: 新增广州客服规则
demand_keywords:
  - 招人
supply_keywords:
  - 派单
region_keywords:
  - 广州
category_keywords:
  - 客服
opportunity_keywords:
  - 合作
extra_tracked_keywords:
  - 日结
""".strip(),
        encoding="utf-8",
    )

    rule_set = load_analysis_rule_set(rules_path)

    assert rule_set.version == "custom-v2"
    assert rule_set.change_note == "新增广州客服规则"
    assert rule_set.demand_keywords == ("招人",)
    assert rule_set.supply_keywords == ("派单",)
    assert rule_set.opportunity_keywords == ("合作",)
    assert "广州" in rule_set.tracked_keywords
    assert "客服" in rule_set.tracked_keywords
    assert "合作" in rule_set.tracked_keywords
    assert "日结" in rule_set.tracked_keywords


def test_custom_rule_set_changes_intent_and_analysis_version() -> None:
    rule_set = AnalysisRuleSet(
        version="custom-v2",
        change_note="新增广州客服规则",
        demand_keywords=("招人",),
        supply_keywords=("派单",),
        region_keywords=("广州",),
        category_keywords=("客服",),
        opportunity_keywords=("合作",),
        extra_tracked_keywords=("日结",),
    )

    analysis = analyze_clean_group_message(
        _clean_message("广州客服招人，合作日结"),
        analyze_time=datetime(2026, 7, 3, 10, 0, 0),
        rule_set=rule_set,
    )

    assert analysis.intent_type == "demand"
    assert analysis.analysis_version == "custom-v2"
    assert analysis.keyword_hits == ["招人", "广州", "客服", "合作", "日结"]
    assert analysis.region_hits == ["广州"]
    assert analysis.category_hits == ["客服"]
    assert analysis.opportunity_hits == ["合作"]
    assert analysis.opportunity_score == 4


def test_custom_supply_rule_set_changes_intent() -> None:
    rule_set = AnalysisRuleSet(
        version="custom-v2",
        change_note="新增派单规则",
        demand_keywords=("招人",),
        supply_keywords=("派单",),
        region_keywords=("广州",),
        category_keywords=("客服",),
        opportunity_keywords=("合作",),
        extra_tracked_keywords=(),
    )

    analysis = analyze_clean_group_message(
        _clean_message("广州客服资源可以派单"),
        analyze_time=datetime(2026, 7, 3, 10, 0, 0),
        rule_set=rule_set,
    )

    assert analysis.intent_type == "supply"
    assert "派单" in analysis.keyword_hits
