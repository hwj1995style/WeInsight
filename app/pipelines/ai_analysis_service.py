from __future__ import annotations

import json
from pathlib import Path

import yaml

from app.domain.ai_analysis import (
    AiAnalysisConfig,
    AiAnalysisResult,
    AiAnalysisServiceInput,
    build_ai_input_payload,
)


class AiAnalysisService:
    def __init__(self, *, config: AiAnalysisConfig) -> None:
        self._config = config

    def analyze_sample(self, service_input: AiAnalysisServiceInput) -> AiAnalysisResult:
        if service_input.source not in self._config.allowed_sources:
            raise ValueError(f"AI source is not allowed: {service_input.source}")
        if not self._config.dry_run:
            raise ValueError("AI sample POC only supports dry-run")

        payload = build_ai_input_payload(
            source=service_input.source,
            source_date=service_input.source_date,
            title=service_input.title,
            summary_text=service_input.summary_text,
            structured_features=service_input.structured_features,
        )
        _ensure_payload_size(payload, self._config.max_input_chars)

        return AiAnalysisResult(
            source=service_input.source,
            source_date=service_input.source_date,
            dry_run=True,
            enabled=self._config.enabled,
            provider=self._config.provider,
            prompt_version=self._config.prompt_version,
            model_version=self._config.model_version,
            input_field_count=len(payload),
            status="dry_run",
            model_called=False,
            error_summary=None,
        )


def load_ai_analysis_config(path: Path) -> AiAnalysisConfig:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    data = raw["ai"]
    return AiAnalysisConfig(
        enabled=bool(data["enabled"]),
        dry_run=bool(data["dry_run"]),
        provider=str(data["provider"]),
        prompt_version=str(data["prompt_version"]),
        model_version=str(data["model_version"]),
        allowed_sources=tuple(data["allowed_sources"]),
        max_input_chars=int(data["max_input_chars"]),
    )


def _ensure_payload_size(payload: dict, max_input_chars: int) -> None:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    if len(encoded) > max_input_chars:
        raise ValueError("AI input payload exceeds max_input_chars")
