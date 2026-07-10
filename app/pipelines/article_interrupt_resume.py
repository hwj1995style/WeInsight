from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from app.pipelines.article_pipeline import ArticleStage, ArticleUiDecision


@dataclass(frozen=True)
class ArticleCollectProgressRecord:
    crawl_date: date
    account_name: str
    stage: str
    status: str
    last_article_url: str | None = None
    retry_count: int = 0
    last_error_code: str | None = None
    last_error_msg: str | None = None


class ArticleInterruptedForCoreGroup(RuntimeError):
    def __init__(
        self,
        *,
        stage: ArticleStage,
        last_article_url: str | None,
        blocked_seconds: float,
    ) -> None:
        self.stage = stage
        self.last_article_url = last_article_url
        self.blocked_seconds = blocked_seconds
        super().__init__(
            "article interrupted for core group "
            f"stage={stage.value} blocked_seconds={blocked_seconds:.3f}"
        )


class ArticleStopRequested(RuntimeError):
    def __init__(
        self,
        stage: ArticleStage,
        last_article_url: str | None = None,
    ) -> None:
        self.stage = stage
        self.last_article_url = last_article_url
        super().__init__(f"article stop requested at stage={stage.value}")


def should_interrupt_article_for_core_group(
    *,
    checkpoint_time: datetime,
    next_core_group_due: datetime | None,
) -> ArticleUiDecision:
    if next_core_group_due is None:
        return ArticleUiDecision.RUN
    if checkpoint_time >= next_core_group_due:
        return ArticleUiDecision.DEFER
    return ArticleUiDecision.RUN


def core_group_block_seconds(checkpoint_time: datetime, next_core_group_due: datetime | None) -> float:
    if next_core_group_due is None or checkpoint_time < next_core_group_due:
        return 0.0
    return (checkpoint_time - next_core_group_due).total_seconds()
