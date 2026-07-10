from __future__ import annotations

from datetime import datetime, timedelta

from app.pipelines.article_pipeline import (
    ArticleProgress,
    ArticleStage,
    ArticleUiDecision,
    should_defer_article_ui,
)


def test_article_ui_defers_when_core_group_due_soon() -> None:
    now = datetime(2026, 7, 2, 8, 30, 0)
    next_core_group_due = now + timedelta(seconds=10)

    decision = should_defer_article_ui(
        now=now,
        next_core_group_due=next_core_group_due,
        min_article_ui_window_seconds=20,
    )

    assert decision == ArticleUiDecision.DEFER


def test_article_progress_can_resume_after_interruption() -> None:
    progress = ArticleProgress(
        crawl_date="2026-07-02",
        account_name="行业观察",
        stage=ArticleStage.COPY_LINKS,
        status="interrupted",
        last_article_url="https://mp.weixin.qq.com/s/1",
        retry_count=1,
    )

    resumed = progress.mark_running()

    assert resumed.stage == ArticleStage.COPY_LINKS
    assert resumed.status == "running"
