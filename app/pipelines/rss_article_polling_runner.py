from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

from app.pipelines.article_polling_runner import ArticlePollingRunResult
from app.storage.article_log_repo import ArticleCollectLogRecord


class _RssStopRequested(RuntimeError):
    pass


class RssArticlePollingRunner:
    def __init__(self, *, collect_service, log_repo,
                 batch_id_factory: Callable[[str], str], max_concurrency: int = 1) -> None:
        self.collect_service = collect_service
        self.log_repo = log_repo
        self.batch_id_factory = batch_id_factory
        self.max_concurrency = max_concurrency

    def run(self, targets: Iterable, now: datetime,
            stop_requested_provider: Callable[[], bool] | None = None) -> ArticlePollingRunResult:
        target_list = list(targets)
        if self.max_concurrency > 1 and len(target_list) > 1:
            with ThreadPoolExecutor(max_workers=self.max_concurrency) as executor:
                parts = list(executor.map(
                    lambda target: self._run_target(target, now, stop_requested_provider),
                    target_list,
                ))
            return _aggregate(parts)
        success = failed = attempted = inserted = duplicates = tasks = stopped = 0
        last_code = last_error = None
        for target in target_list:
            attempted += 1
            batch_id = self.batch_id_factory(target.account_name)
            try:
                def after_fetch() -> None:
                    if stop_requested_provider is not None and stop_requested_provider():
                        raise _RssStopRequested("stop requested after RSS HTTP fetch")

                result = self.collect_service.collect_once(
                    target, batch_id=batch_id, collect_time=now,
                    after_fetch_checkpoint=after_fetch)
                self.log_repo.insert_collect_log(ArticleCollectLogRecord(
                    batch_id=batch_id, account_name=target.account_name, start_time=now,
                    end_time=now, status="success", stage="rss_save",
                    link_count=result.feed_item_count, insert_count=result.insert_count,
                    feed_item_count=result.feed_item_count, duplicate_count=result.duplicate_count,
                    invalid_count=result.invalid_count, http_status=result.http_status,
                    elapsed_ms=result.elapsed_ms))
                # Commit counters only after the target and its success log are durable.
                success += 1; inserted += result.insert_count
                duplicates += result.duplicate_count; tasks += result.task_created_count
            except _RssStopRequested as exc:
                stopped = 1
                last_code, last_error = "RSS_ARTICLE_STOP_REQUESTED", str(exc)
                self._try_log(ArticleCollectLogRecord(
                    batch_id=batch_id, account_name=target.account_name, start_time=now,
                    end_time=now, status="interrupted", stage="rss_fetch",
                    error_code=last_code, error_msg=str(exc)))
                break
            except Exception as exc:
                failed += 1; last_code = "RSS_ARTICLE_COLLECT_ERROR"; last_error = str(exc)
                self._try_log(ArticleCollectLogRecord(
                    batch_id=batch_id, account_name=target.account_name, start_time=now,
                    end_time=now, status="failed", stage="rss_collect",
                    error_code=last_code, error_msg=str(exc)))
            # Safe point: the HTTP operation and current target persistence/logging are complete.
            if stop_requested_provider is not None and stop_requested_provider():
                stopped = 1
                break
        return ArticlePollingRunResult(attempted_count=attempted, success_count=success,
            failed_count=failed, lock_timeout_count=0, raw_insert_count=inserted,
            duplicate_count=duplicates, task_created_count=tasks,
            stop_requested_count=stopped, error_code=last_code, error_summary=last_error)

    def _run_target(self, target, now, stop_provider) -> ArticlePollingRunResult:
        batch_id = self.batch_id_factory(target.account_name)
        try:
            def after_fetch() -> None:
                if stop_provider is not None and stop_provider():
                    raise _RssStopRequested("stop requested after RSS HTTP fetch")
            result = self.collect_service.collect_once(
                target, batch_id=batch_id, collect_time=now,
                after_fetch_checkpoint=after_fetch,
            )
            self.log_repo.insert_collect_log(ArticleCollectLogRecord(
                batch_id=batch_id, account_name=target.account_name, start_time=now,
                end_time=now, status="success", stage="rss_save",
                link_count=result.feed_item_count, insert_count=result.insert_count,
                feed_item_count=result.feed_item_count, duplicate_count=result.duplicate_count,
                invalid_count=result.invalid_count, http_status=result.http_status,
                elapsed_ms=result.elapsed_ms,
            ))
            return ArticlePollingRunResult(
                attempted_count=1, success_count=1, failed_count=0,
                lock_timeout_count=0, raw_insert_count=result.insert_count,
                duplicate_count=result.duplicate_count,
                task_created_count=result.task_created_count,
            )
        except _RssStopRequested as exc:
            self._try_log(ArticleCollectLogRecord(
                batch_id=batch_id, account_name=target.account_name, start_time=now,
                end_time=now, status="interrupted", stage="rss_fetch",
                error_code="RSS_ARTICLE_STOP_REQUESTED", error_msg=str(exc),
            ))
            return ArticlePollingRunResult(
                attempted_count=1, success_count=0, failed_count=0,
                lock_timeout_count=0, stop_requested_count=1,
                error_code="RSS_ARTICLE_STOP_REQUESTED", error_summary=str(exc),
            )
        except Exception as exc:
            self._try_log(ArticleCollectLogRecord(
                batch_id=batch_id, account_name=target.account_name, start_time=now,
                end_time=now, status="failed", stage="rss_collect",
                error_code="RSS_ARTICLE_COLLECT_ERROR", error_msg=str(exc),
            ))
            return ArticlePollingRunResult(
                attempted_count=1, success_count=0, failed_count=1,
                lock_timeout_count=0, error_code="RSS_ARTICLE_COLLECT_ERROR",
                error_summary=str(exc),
            )

    def _try_log(self, record: ArticleCollectLogRecord) -> None:
        try:
            self.log_repo.insert_collect_log(record)
        except Exception:
            # Logging is best effort here: a broken log sink must not break feed isolation.
            pass


def _aggregate(parts) -> ArticlePollingRunResult:
    last = next((part for part in reversed(parts) if part.error_code), None)
    return ArticlePollingRunResult(
        attempted_count=sum(part.attempted_count for part in parts),
        success_count=sum(part.success_count for part in parts),
        failed_count=sum(part.failed_count for part in parts),
        lock_timeout_count=0,
        raw_insert_count=sum(part.raw_insert_count for part in parts),
        duplicate_count=sum(part.duplicate_count for part in parts),
        task_created_count=sum(part.task_created_count for part in parts),
        stop_requested_count=sum(part.stop_requested_count for part in parts),
        error_code=last.error_code if last else None,
        error_summary=last.error_summary if last else None,
    )
