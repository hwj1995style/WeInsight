from __future__ import annotations

from datetime import date
from pathlib import Path

import yaml

from app.domain.ai_analysis import AiAnalysisConfig, AiAnalysisServiceInput, build_ai_input_payload
from app.pipelines.ai_analysis_service import AiAnalysisService


CONFIG = Path("config/ai_analysis.yaml")


def test_build_ai_input_payload_allows_only_safe_fields() -> None:
    payload = build_ai_input_payload(
        source="summary_daily_report",
        title="2026-07-07 双链路汇总日报草稿",
        summary_text="群链路稳定，article 链路有少量积压。",
        structured_features={"group_success_count": 10, "article_failed_count": 1},
        raw_content="不应进入 AI 输入",
        html_content="<table>不应进入 AI 输入</table>",
        article_url="https://mp.weixin.qq.com/s/unsafe",
    )

    assert payload["source"] == "summary_daily_report"
    assert payload["title"] == "2026-07-07 双链路汇总日报草稿"
    assert payload["summary_text"] == "群链路稳定，article 链路有少量积压。"
    assert payload["structured_features"] == {"group_success_count": 10, "article_failed_count": 1}
    assert "raw_content" not in payload
    assert "html_content" not in payload
    assert "article_url" not in payload


def test_ai_analysis_service_dry_run_returns_payload_shape_without_model_call() -> None:
    service = AiAnalysisService(
        config=AiAnalysisConfig(
            enabled=False,
            dry_run=True,
            provider="none",
            prompt_version="poc-v1",
            model_version="dry-run",
            allowed_sources=("summary_daily_report",),
            max_input_chars=2000,
        )
    )

    result = service.analyze_sample(
        AiAnalysisServiceInput(
            source="summary_daily_report",
            source_date=date(2026, 7, 7),
            title="2026-07-07 双链路汇总日报草稿",
            summary_text="群链路稳定。",
            structured_features={"group_success_count": 10},
        )
    )

    assert result.source == "summary_daily_report"
    assert result.source_date == date(2026, 7, 7)
    assert result.dry_run is True
    assert result.enabled is False
    assert result.provider == "none"
    assert result.prompt_version == "poc-v1"
    assert result.model_version == "dry-run"
    assert result.input_field_count == 5
    assert result.status == "dry_run"
    assert result.model_called is False
    assert result.error_summary is None


def test_ai_analysis_config_defaults_to_disabled_dry_run() -> None:
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))

    assert config["ai"]["enabled"] is False
    assert config["ai"]["dry_run"] is True
    assert config["ai"]["provider"] == "none"
    assert config["ai"]["prompt_version"] == "poc-v1"
    assert config["ai"]["model_version"] == "dry-run"
    assert "summary_daily_report" in config["ai"]["allowed_sources"]
