from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal


@dataclass(frozen=True)
class ArticleBackfillCommand:
    scope: Literal["single", "selected", "enabled"]
    source_id: int | None
    start_date: date
    end_date: date
    mode: Literal["missing_only", "force_analyze"]
    force_confirmed: bool
    source_ids: tuple[int, ...] = ()


@dataclass(frozen=True)
class ArticleBackfillSummary:
    matched_article_count: int
    clean_task_created_count: int
    clean_task_recovered_count: int
    analyze_task_created_count: int
    analyze_task_recovered_count: int
    existing_result_skipped_count: int
    running_task_skipped_count: int
    out_of_scope_skipped_count: int
