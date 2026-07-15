from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class AnalysisRuleSet:
    version: str
    change_note: str
    demand_keywords: tuple[str, ...]
    supply_keywords: tuple[str, ...]
    region_keywords: tuple[str, ...]
    category_keywords: tuple[str, ...]
    opportunity_keywords: tuple[str, ...]
    extra_tracked_keywords: tuple[str, ...]

    @property
    def tracked_keywords(self) -> tuple[str, ...]:
        return _dedupe(
            self.demand_keywords
            + self.supply_keywords
            + self.region_keywords
            + self.category_keywords
            + self.opportunity_keywords
            + self.extra_tracked_keywords
        )


DEFAULT_ANALYSIS_RULE_SET = AnalysisRuleSet(
    version="v1",
    change_note="内置默认规则",
    demand_keywords=("有没有", "需要", "谁有", "采购", "求", "找", "收"),
    supply_keywords=("供应", "提供", "出售", "有货", "转让", "出"),
    region_keywords=("深圳", "湖北", "广州", "东莞", "惠州", "武汉"),
    category_keywords=("兼职", "岗位", "报价", "客户", "项目", "资源", "客服", "渠道", "订单"),
    opportunity_keywords=("合作", "对接", "项目", "报价", "客户", "资源", "渠道", "订单", "转介绍"),
    extra_tracked_keywords=(),
)


def load_analysis_rule_set(path: Path) -> AnalysisRuleSet:
    if not path.exists():
        return DEFAULT_ANALYSIS_RULE_SET

    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return AnalysisRuleSet(
        version=str(data.get("version") or DEFAULT_ANALYSIS_RULE_SET.version),
        change_note=str(data.get("change_note") or ""),
        demand_keywords=_tuple_from_data(data.get("demand_keywords"), DEFAULT_ANALYSIS_RULE_SET.demand_keywords),
        supply_keywords=_tuple_from_data(data.get("supply_keywords"), DEFAULT_ANALYSIS_RULE_SET.supply_keywords),
        region_keywords=_tuple_from_data(data.get("region_keywords"), DEFAULT_ANALYSIS_RULE_SET.region_keywords),
        category_keywords=_tuple_from_data(data.get("category_keywords"), DEFAULT_ANALYSIS_RULE_SET.category_keywords),
        opportunity_keywords=_tuple_from_data(
            data.get("opportunity_keywords"),
            DEFAULT_ANALYSIS_RULE_SET.opportunity_keywords,
        ),
        extra_tracked_keywords=_tuple_from_data(data.get("extra_tracked_keywords"), ()),
    )


def _tuple_from_data(value, fallback: tuple[str, ...]) -> tuple[str, ...]:
    if value is None:
        return fallback
    if not isinstance(value, list):
        raise ValueError("analysis rule keywords must be a list")
    return _dedupe(tuple(str(item).strip() for item in value if str(item).strip()))


def _dedupe(values: tuple[str, ...]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return tuple(result)
