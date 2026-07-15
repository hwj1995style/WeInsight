from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any


@dataclass(frozen=True)
class AiAnalysisConfig:
    enabled: bool
    dry_run: bool
    provider: str
    prompt_version: str
    model_version: str
    allowed_sources: tuple[str, ...]
    max_input_chars: int


@dataclass(frozen=True)
class AiAnalysisServiceInput:
    source: str
    source_date: date
    title: str
    summary_text: str
    structured_features: dict[str, Any]


@dataclass(frozen=True)
class AiAnalysisResult:
    source: str
    source_date: date
    dry_run: bool
    enabled: bool
    provider: str
    prompt_version: str
    model_version: str
    input_field_count: int
    status: str
    model_called: bool
    error_summary: str | None


def build_ai_input_payload(
    *,
    source: str,
    title: str | None = None,
    summary_text: str | None = None,
    structured_features: dict[str, Any] | None = None,
    source_date: date | None = None,
    quality_scores: dict[str, Any] | None = None,
    **unsafe_fields: Any,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"source": source}
    if source_date is not None:
        payload["source_date"] = source_date.isoformat()
    if title is not None:
        payload["title"] = title
    if summary_text is not None:
        payload["summary_text"] = summary_text
    if structured_features is not None:
        payload["structured_features"] = structured_features
    if quality_scores is not None:
        payload["quality_scores"] = quality_scores
    return payload
