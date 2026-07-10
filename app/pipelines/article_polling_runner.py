from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

from app.domain.collection_jobs import ensure_schedule_datetime
from app.pipelines.article_collect_service import ArticleCollectResult
from app.pipelines.article_interrupt_resume import (
    ArticleCollectProgressRecord,
    ArticleInterruptedForCoreGroup,
    ArticleStopRequested,
    core_group_block_seconds,
    should_interrupt_article_for_core_group,
)
from app.pipelines.article_pipeline import ArticleStage, ArticleUiDecision
from app.storage.article_log_repo import ArticleCollectLogRecord


@dataclass(frozen=True)
class ArticlePollingTarget:
    account_name: str
    priority: int
    poll_interval_minutes: int
    max_articles_per_round: int


@dataclass(frozen=True)
class ArticlePollingRunResult:
    attempted_count: int
    success_count: int
    failed_count: int
    lock_timeout_count: int
    interrupted_count: int = 0
    link_count: int = 0
    raw_insert_count: int = 0
    duplicate_count: int = 0
    skipped_count: int = 0
    task_created_count: int = 0
    stop_requested_count: int = 0
    core_group_interrupted_count: int = 0
    error_code: str | None = None
    error_summary: str | None = None
    screenshot_path: str | None = None


class ArticleCollectServiceProtocol(Protocol):
    def collect_once(
        self,
        *,
        account_name: str,
        batch_id: str,
        collect_time: datetime,
        max_articles: int,
        resume_after_url: str | None = None,
        checkpoint: Callable[[ArticleStage, str | None], None] | None = None,
    ) -> ArticleCollectResult:
        ...


class UiLockRepo(Protocol):
    def acquire(
        self,
        lock_name: str,
        owner_pipeline: str,
        owner_task_id: str,
        now: datetime,
        lease_seconds: int,
    ) -> bool:
        ...

    def release(self, lock_name: str, owner_pipeline: str, owner_task_id: str) -> bool:
        ...


class ArticleCollectLogRepo(Protocol):
    def insert_collect_log(self, record: ArticleCollectLogRecord) -> None:
        ...


class ScreenshotClient(Protocol):
    def save_screenshot(self, path: str) -> str:
        ...


class ArticleProgressRepo(Protocol):
    def get_progress(self, crawl_date, account_name: str):
        ...

    def upsert_progress(self, record: ArticleCollectProgressRecord) -> None:
        ...

    def mark_success(self, crawl_date, account_name: str, success_time: datetime | None = None) -> None:
        ...


class ArticlePollingRunner:
    def __init__(
        self,
        *,
        collect_service: ArticleCollectServiceProtocol,
        lock_repo: UiLockRepo,
        account_provider: Callable[[datetime, int], Iterable[ArticlePollingTarget]],
        log_repo: ArticleCollectLogRepo,
        screenshot_client: ScreenshotClient,
        screenshot_root: Path,
        lease_seconds: int,
        lock_acquire_timeout_seconds: int,
        max_accounts_per_ui_slice: int,
        batch_id_factory: Callable[[str], str],
        progress_repo: ArticleProgressRepo | None = None,
        next_core_group_due_provider: Callable[[], datetime | None] | None = None,
        max_core_group_block_seconds: int = 10,
        stop_requested_provider: Callable[[], bool] | None = None,
        checkpoint_now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        self.collect_service = collect_service
        self.lock_repo = lock_repo
        self.account_provider = account_provider
        self.log_repo = log_repo
        self.screenshot_client = screenshot_client
        self.screenshot_root = screenshot_root
        self.lease_seconds = lease_seconds
        self.lock_acquire_timeout_seconds = lock_acquire_timeout_seconds
        self.max_accounts_per_ui_slice = max_accounts_per_ui_slice
        self.batch_id_factory = batch_id_factory
        self.progress_repo = progress_repo
        self.next_core_group_due_provider = next_core_group_due_provider
        self.max_core_group_block_seconds = max_core_group_block_seconds
        self.stop_requested_provider = stop_requested_provider
        self.checkpoint_now_provider = checkpoint_now_provider

    def run_once(self, now: datetime) -> ArticlePollingRunResult:
        targets = sorted(
            self.account_provider(now, self.max_accounts_per_ui_slice),
            key=lambda item: (item.priority, item.account_name),
        )[: self.max_accounts_per_ui_slice]

        success_count = 0
        failed_count = 0
        lock_timeout_count = 0
        interrupted_count = 0
        link_count = 0
        raw_insert_count = 0
        duplicate_count = 0
        skipped_count = 0
        task_created_count = 0
        stop_requested_count = 0
        core_group_interrupted_count = 0
        error_code = None
        error_summary = None
        screenshot_path_value = None

        for target in targets:
            batch_id = self.batch_id_factory(target.account_name)
            start_time = now
            acquired = self.lock_repo.acquire(
                lock_name="wechat_ui",
                owner_pipeline="article",
                owner_task_id=batch_id,
                now=now,
                lease_seconds=self.lease_seconds,
            )
            if not acquired:
                lock_timeout_count += 1
                error_code = "WECHAT_UI_LOCK_TIMEOUT"
                error_summary = (
                    "Failed to acquire wechat_ui lock within "
                    f"{self.lock_acquire_timeout_seconds} seconds."
                )
                self.log_repo.insert_collect_log(
                    ArticleCollectLogRecord(
                        batch_id=batch_id,
                        account_name=target.account_name,
                        start_time=start_time,
                        end_time=now,
                        status="failed",
                        stage="open_account",
                        error_code="WECHAT_UI_LOCK_TIMEOUT",
                        error_msg=(
                            "Failed to acquire wechat_ui lock within "
                            f"{self.lock_acquire_timeout_seconds} seconds."
                        ),
                    )
                )
                continue

            try:
                resume_progress = None
                resume_after_url = None
                if self.progress_repo is not None:
                    resume_progress = self.progress_repo.get_progress(now.date(), target.account_name)
                    if resume_progress is not None and resume_progress.status == "interrupted":
                        resume_after_url = resume_progress.last_article_url

                collect_kwargs = {
                    "account_name": target.account_name,
                    "batch_id": batch_id,
                    "collect_time": now,
                    "max_articles": target.max_articles_per_round,
                }
                checkpoint = self._build_checkpoint(target.account_name, now)
                if resume_after_url is not None or checkpoint is not None:
                    collect_kwargs["resume_after_url"] = resume_after_url
                    collect_kwargs["checkpoint"] = checkpoint
                result = self.collect_service.collect_once(**collect_kwargs)
                link_count += result.link_count
                raw_insert_count += result.insert_count
                duplicate_count += result.duplicate_count
                skipped_count += result.skipped_count
                task_created_count += result.task_created_count

                if result.link_count <= 0:
                    skipped_count += 1
                    error_code = "WECHAT_ARTICLE_NO_TODAY_ARTICLE"
                    error_summary = (
                        "No same-day article links were available for this account."
                    )
                    if self.progress_repo is not None:
                        self.progress_repo.mark_success(now.date(), target.account_name, success_time=now)
                    self.log_repo.insert_collect_log(
                        ArticleCollectLogRecord(
                            batch_id=batch_id,
                            account_name=target.account_name,
                            start_time=start_time,
                            end_time=now,
                            link_count=result.link_count,
                            insert_count=result.insert_count,
                            status="skipped",
                            stage="copy_links",
                            error_code="WECHAT_ARTICLE_NO_TODAY_ARTICLE",
                            error_msg="No same-day article links were available for this account.",
                        )
                    )
                    continue

                failure_code: str | None = None
                failure_stage = "copy_links"
                failure_msg: str | None = None
                if result.insert_count + result.duplicate_count <= 0:
                    failure_code = "WECHAT_ARTICLE_NO_RAW_EVIDENCE"
                    failure_stage = "save_links"
                    failure_msg = "Copied links did not produce raw insert or duplicate evidence."

                if failure_code is not None:
                    failed_count += 1
                    error_code = failure_code
                    error_summary = failure_msg
                    self.log_repo.insert_collect_log(
                        ArticleCollectLogRecord(
                            batch_id=batch_id,
                            account_name=target.account_name,
                            start_time=start_time,
                            end_time=now,
                            link_count=result.link_count,
                            insert_count=result.insert_count,
                            status="failed",
                            stage=failure_stage,
                            error_code=failure_code,
                            error_msg=failure_msg,
                        )
                    )
                    continue

                success_count += 1
                if self.progress_repo is not None:
                    self.progress_repo.mark_success(now.date(), target.account_name, success_time=now)
                self.log_repo.insert_collect_log(
                    ArticleCollectLogRecord(
                        batch_id=batch_id,
                        account_name=target.account_name,
                        start_time=start_time,
                        end_time=now,
                        link_count=result.link_count,
                        insert_count=result.insert_count,
                        status="success",
                        stage="save_links",
                    )
                )
            except ArticleStopRequested as exc:
                interrupted_count += 1
                stop_requested_count += 1
                error_code = "ARTICLE_STOP_REQUESTED"
                error_summary = str(exc)
                self.log_repo.insert_collect_log(
                    ArticleCollectLogRecord(
                        batch_id=batch_id,
                        account_name=target.account_name,
                        start_time=start_time,
                        end_time=now,
                        status="interrupted",
                        stage=exc.stage.value,
                        error_code="ARTICLE_STOP_REQUESTED",
                        error_msg=str(exc),
                    )
                )
            except ArticleInterruptedForCoreGroup as exc:
                interrupted_count += 1
                core_group_interrupted_count += 1
                error_code = "ARTICLE_INTERRUPTED_FOR_CORE_GROUP"
                error_summary = str(exc)
                self.log_repo.insert_collect_log(
                    ArticleCollectLogRecord(
                        batch_id=batch_id,
                        account_name=target.account_name,
                        start_time=start_time,
                        end_time=now,
                        status="interrupted",
                        stage=exc.stage.value,
                        error_code="ARTICLE_INTERRUPTED_FOR_CORE_GROUP",
                        error_msg=str(exc),
                    )
                )
            except Exception as exc:
                failed_count += 1
                error_code = "WECHAT_ARTICLE_RPA_ERROR"
                error_summary = str(exc)
                screenshot_path = self._screenshot_path(batch_id, now)
                saved_screenshot_path = self.screenshot_client.save_screenshot(screenshot_path.as_posix())
                screenshot_path_value = saved_screenshot_path
                self.log_repo.insert_collect_log(
                    ArticleCollectLogRecord(
                        batch_id=batch_id,
                        account_name=target.account_name,
                        start_time=start_time,
                        end_time=now,
                        status="failed",
                        stage="copy_links",
                        error_code="WECHAT_ARTICLE_RPA_ERROR",
                        error_msg=str(exc),
                        screenshot_path=saved_screenshot_path,
                    )
                )
            finally:
                self.lock_repo.release("wechat_ui", "article", batch_id)

        return ArticlePollingRunResult(
            attempted_count=len(targets),
            success_count=success_count,
            failed_count=failed_count,
            lock_timeout_count=lock_timeout_count,
            interrupted_count=interrupted_count,
            link_count=link_count,
            raw_insert_count=raw_insert_count,
            duplicate_count=duplicate_count,
            skipped_count=skipped_count,
            task_created_count=task_created_count,
            stop_requested_count=stop_requested_count,
            core_group_interrupted_count=core_group_interrupted_count,
            error_code=error_code,
            error_summary=error_summary,
            screenshot_path=screenshot_path_value,
        )

    def _screenshot_path(self, batch_id: str, now: datetime) -> Path:
        return self.screenshot_root / "article" / now.strftime("%Y%m%d") / f"{batch_id}.png"

    def _build_checkpoint(self, account_name: str, now: datetime):
        if self.stop_requested_provider is None and (
            self.progress_repo is None
            or self.next_core_group_due_provider is None
        ):
            return None

        def checkpoint(stage: ArticleStage, last_article_url: str | None) -> None:
            if (
                self.stop_requested_provider is not None
                and self.stop_requested_provider()
            ):
                if self.progress_repo is not None:
                    self.progress_repo.upsert_progress(
                        ArticleCollectProgressRecord(
                            crawl_date=now.date(),
                            account_name=account_name,
                            stage=stage.value,
                            status="interrupted",
                            last_article_url=last_article_url,
                            retry_count=1,
                            last_error_code="ARTICLE_STOP_REQUESTED",
                            last_error_msg=(
                                "collection job stop requested at safe checkpoint"
                            ),
                        )
                    )
                raise ArticleStopRequested(stage, last_article_url)

            if (
                self.progress_repo is None
                or self.next_core_group_due_provider is None
            ):
                return
            checkpoint_time = now
            if self.checkpoint_now_provider is not None:
                checkpoint_time = self.checkpoint_now_provider()
                ensure_schedule_datetime(
                    checkpoint_time,
                    field_name="checkpoint_time",
                )
            next_core_group_due = self.next_core_group_due_provider()
            decision = should_interrupt_article_for_core_group(
                checkpoint_time=checkpoint_time,
                next_core_group_due=next_core_group_due,
            )
            if decision == ArticleUiDecision.RUN:
                return

            blocked_seconds = core_group_block_seconds(
                checkpoint_time,
                next_core_group_due,
            )
            self.progress_repo.upsert_progress(
                ArticleCollectProgressRecord(
                    crawl_date=now.date(),
                    account_name=account_name,
                    stage=stage.value,
                    status="interrupted",
                    last_article_url=last_article_url,
                    retry_count=1,
                    last_error_code="ARTICLE_INTERRUPTED_FOR_CORE_GROUP",
                    last_error_msg=(
                        "core group due; "
                        f"blocked_seconds={blocked_seconds:.3f}; "
                        f"max_core_group_block_seconds={self.max_core_group_block_seconds}"
                    ),
                )
            )
            raise ArticleInterruptedForCoreGroup(
                stage=stage,
                last_article_url=last_article_url,
                blocked_seconds=blocked_seconds,
            )

        return checkpoint
