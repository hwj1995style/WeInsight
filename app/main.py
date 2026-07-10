from __future__ import annotations

import argparse
import socket
import sys
import time
from datetime import date, datetime
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

from app.core.config import load_config
from app.domain.collection_jobs import APPLICATION_TIMEZONE
from app.domain.group_analysis_rules import load_analysis_rule_set
from app.domain.report_lifecycle import ReportLifecycle
from app.pipelines.group_analysis_service import GroupAnalysisService, GroupDailyReportService
from app.pipelines.group_daily_report_query_service import (
    DailyReportNotFoundError,
    GroupDailyReportQueryService,
)
from app.pipelines.article_daily_report_query_service import (
    ArticleDailyReportNotFoundError,
    ArticleDailyReportQueryService,
)
from app.pipelines.summary_daily_report_query_service import SummaryDailyReportQueryService
from app.pipelines.summary_daily_report_service import SummaryDailyReportService
from app.pipelines.trial_monitor_report_service import TrialMonitorReportService
from app.domain.ai_analysis import AiAnalysisServiceInput
from app.pipelines.ai_analysis_service import AiAnalysisService, load_ai_analysis_config
from app.pipelines.group_pipeline_service import GroupPipelineService
from app.pipelines.article_core_group_due_provider import ReadOnlyCoreGroupDueProvider
from app.pipelines.group_polling_runner import GroupPollingRunner, GroupPollingTarget
from app.pipelines.article_collect_service import ArticleCollectService
from app.pipelines.article_parse_service import ArticleParseService, PlaywrightArticleParser
from app.pipelines.article_analysis_service import ArticleAnalysisService
from app.pipelines.article_transient_extractor import PlaywrightArticleTransientExtractor
from app.pipelines.article_polling_runner import ArticlePollingRunner, ArticlePollingTarget
from app.rpa.desktop_probe import WechatDesktopProbe, WechatHealthStatus
from app.rpa.screenshots import DesktopScreenshotClient
from app.rpa.wxauto_client import WxautoArticleRpaClient, WxautoGroupRpaClient, WxautoNotAvailableError
from app.pipelines.group_clean_service import GroupCleanService
from app.pipelines.group_collect_service import GroupCollectService
from app.storage.db import create_mysql_engine
from app.storage.article_config_repo import MysqlArticleAccountConfigRepo
from app.storage.article_log_repo import MysqlArticleCollectLogRepo
from app.storage.article_route_cache_repo import MysqlArticleRouteCacheRepo
from app.storage.article_parse_repo import MysqlArticleParseRepo
from app.storage.article_analysis_repo import MysqlArticleAnalysisRepo
from app.storage.article_progress_repo import MysqlArticleProgressRepo
from app.storage.article_raw_repo import MysqlArticleRawRepo
from app.storage.article_runtime_metrics_repo import MysqlArticleRuntimeMetricsRepo
from app.storage.article_task_admin_repo import MysqlArticleTaskAdminRepo
from app.storage.group_analysis_repo import MysqlGroupAnalysisRepo
from app.storage.article_daily_report_query_repo import MysqlArticleDailyReportQueryRepo
from app.storage.summary_daily_report_query_repo import MysqlSummaryDailyReportQueryRepo
from app.storage.group_clean_repo import MysqlGroupCleanRepo
from app.storage.group_daily_report_query_repo import MysqlGroupDailyReportQueryRepo
from app.storage.group_repo import (
    MysqlGroupCollectLogRepo,
    MysqlGroupConfigRepo,
    MysqlGroupMessageRepo,
    MysqlGroupStatusRepo,
)
from app.storage.group_runtime_metrics_repo import MysqlGroupRuntimeMetricsRepo
from app.storage.group_runtime_summary_repo import MysqlGroupRuntimeSummaryRepo
from app.storage.group_task_admin_repo import MysqlGroupTaskAdminRepo
from app.storage.lock_repo import MysqlUiLockRepo
from app.storage.worker_heartbeat_repo import MysqlWorkerHeartbeatRepo
from app.storage.schema import read_init_sql
from app.services.managed_mode_guard import (
    HeldUiLockAdapter,
    ManagedModeActiveError,
    ManagedModeGuard,
    WechatUiBusyError,
    WechatUiLeaseLostError,
    WechatUiReleaseError,
)


_ZONE = ZoneInfo(APPLICATION_TIMEZONE)


def main() -> int:
    parser = argparse.ArgumentParser(prog="weinsight")
    parser.add_argument(
        "command",
        choices=[
            "check-config",
            "print-init-sql",
            "wechat-health",
            "collect-group-once",
            "run-group-scheduler",
            "run-article-scheduler",
            "group-config-list",
            "group-config-upsert",
            "group-config-disable",
            "article-account-list",
            "article-account-upsert",
            "article-account-disable",
            "article-rpa-probe",
            "collect-article-once",
            "parse-article-once",
            "analyze-article-once",
            "article-runtime-metrics",
            "article-task-failed-list",
            "article-task-retry-failed",
            "group-status",
            "clean-group-once",
            "analyze-group-once",
            "group-daily-report-once",
            "group-daily-report-list",
            "group-daily-report-show",
            "group-daily-report-export",
            "article-daily-report-list",
            "article-daily-report-show",
            "article-daily-report-export",
            "summary-daily-report-show",
            "summary-daily-report-export",
            "trial-monitor-report",
            "ai-analysis-sample",
            "run-group-pipeline-once",
            "group-runtime-summary",
            "group-runtime-metrics",
            "group-task-list",
            "group-task-reset",
            "group-task-reset-date",
            "group-task-failed-list",
            "group-task-retry-failed",
        ],
    )
    parser.add_argument("--config", default="config/config.dev.yaml")
    parser.add_argument("--group-name")
    parser.add_argument("--account-name")
    parser.add_argument("--account-type", default="subscription")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--core", action="store_true")
    parser.add_argument("--priority", type=int, default=5)
    parser.add_argument("--poll-interval-seconds", type=int)
    parser.add_argument("--poll-interval-minutes", type=int)
    parser.add_argument("--daily-window-start")
    parser.add_argument("--daily-window-end")
    parser.add_argument("--max-articles-per-round", type=int)
    parser.add_argument("--backtrack-pages", type=int, default=10)
    parser.add_argument("--extra-backtrack-pages", type=int, default=30)
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--hours", type=int, default=24)
    parser.add_argument("--date")
    parser.add_argument("--source")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--ai-config", default="config/ai_analysis.yaml")
    parser.add_argument("--task-type")
    parser.add_argument("--status")
    parser.add_argument("--ref-id")
    parser.add_argument("--output")
    parser.add_argument("--rules-config", default="config/group_analysis_rules.yaml")
    parser.add_argument("--skip-collect", action="store_true")
    parser.add_argument("--remark")
    args = parser.parse_args()

    if args.command == "check-config":
        config = load_config(Path(args.config))
        print(f"env={config.app.env}")
        print(f"wechat_pc_version={config.wechat.pc_version}")
        print(f"group_limit={config.pipelines.group.core_group_limit}")
        print(f"article_limit={config.pipelines.article.account_limit}")
        return 0

    if args.command == "print-init-sql":
        print(read_init_sql())
        return 0

    if args.command == "wechat-health":
        config = load_config(Path(args.config))
        health = check_wechat_health(config)
        print(f"wechat_health_status={health.status.value}")
        print(f"message={health.message}")
        if health.version is not None:
            print(f"version={health.version}")
        return 0 if health.status == WechatHealthStatus.OK else 1

    if args.command == "group-config-list":
        config = load_config(Path(args.config))
        repo = build_real_group_config_repo(config)
        for record in repo.list_groups():
            print(
                " ".join(
                    [
                        f"group_name={record.group_name}",
                        f"enabled={1 if record.enabled else 0}",
                        f"is_core_group={1 if record.is_core_group else 0}",
                        f"priority={record.priority}",
                        f"poll_interval_seconds={record.poll_interval_seconds}",
                    ]
                )
            )
        return 0

    if args.command == "group-config-upsert":
        if not args.group_name:
            parser.error("--group-name is required for group-config-upsert")
        config = load_config(Path(args.config))
        repo = build_real_group_config_repo(config)
        repo.upsert_group_config(
            group_name=args.group_name,
            enabled=True,
            priority=args.priority,
            poll_interval_seconds=args.poll_interval_seconds or config.pipelines.group.poll_interval_seconds,
            backtrack_pages=args.backtrack_pages,
            extra_backtrack_pages=args.extra_backtrack_pages,
            is_core_group=args.core,
            remark=args.remark,
        )
        print(f"group_config_upserted={args.group_name}")
        return 0

    if args.command == "group-config-disable":
        if not args.group_name:
            parser.error("--group-name is required for group-config-disable")
        config = load_config(Path(args.config))
        repo = build_real_group_config_repo(config)
        repo.disable_group(args.group_name)
        print(f"group_config_disabled={args.group_name}")
        return 0

    if args.command == "article-account-list":
        config = load_config(Path(args.config))
        repo = build_real_article_account_config_repo(config)
        for record in repo.list_accounts():
            print(
                " ".join(
                    [
                        f"account_name={record.account_name}",
                        f"account_type={record.account_type}",
                        f"enabled={1 if record.enabled else 0}",
                        f"priority={record.priority}",
                        f"poll_interval_minutes={record.poll_interval_minutes}",
                        f"daily_window_start={record.daily_window_start}",
                        f"daily_window_end={record.daily_window_end}",
                        f"max_articles_per_round={record.max_articles_per_round}",
                        f"collect_today_only={1 if record.collect_today_only else 0}",
                        f"dedup_key={record.dedup_key}",
                        f"last_success_collect_time={_format_optional(record.last_success_collect_time)}",
                    ]
                )
            )
        return 0

    if args.command == "article-account-upsert":
        if not args.account_name:
            parser.error("--account-name is required for article-account-upsert")
        config = load_config(Path(args.config))
        repo = build_real_article_account_config_repo(config)
        repo.upsert_account_config(
            account_name=args.account_name,
            account_type=args.account_type,
            enabled=True,
            priority=args.priority,
            poll_interval_minutes=args.poll_interval_minutes or config.pipelines.article.account_poll_interval_minutes,
            daily_window_start=args.daily_window_start or "07:30",
            daily_window_end=args.daily_window_end or "19:30",
            max_articles_per_round=args.max_articles_per_round or config.pipelines.article.max_articles_per_account,
            collect_today_only=config.pipelines.article.collect_today_only,
            dedup_key=config.pipelines.article.dedup_key,
            remark=args.remark,
        )
        print(f"article_account_upserted={args.account_name}")
        return 0

    if args.command == "article-account-disable":
        if not args.account_name:
            parser.error("--account-name is required for article-account-disable")
        config = load_config(Path(args.config))
        repo = build_real_article_account_config_repo(config)
        repo.disable_account(args.account_name)
        print(f"article_account_disabled={args.account_name}")
        return 0

    if args.command == "article-rpa-probe":
        if not args.account_name:
            parser.error("--account-name is required for article-rpa-probe")
        config = load_config(Path(args.config))
        ensure_wechat_health(config)
        try:
            probe = build_real_article_rpa_probe(config)
            result = probe.probe_account(args.account_name)
        except WxautoNotAvailableError as exc:
            print(f"rpa_error={exc}", file=sys.stderr)
            return 1
        print(
            " ".join(
                [
                    "article_rpa_probe",
                    f"status={result['status']}",
                    f"account_found={result['account_found']}",
                    f"link_count={result['link_count']}",
                    f"message={result['message']}",
                ]
            )
        )
        return 0 if result["status"] == "ok" else 1

    if args.command == "collect-article-once":
        if not args.account_name:
            parser.error("--account-name is required for collect-article-once")
        config = load_config(Path(args.config))
        guard, guard_error = _build_managed_guard_for_cli(config)
        if guard_error is not None:
            return guard_error
        now = _shanghai_now()
        owner_task_id = f"manual-article-{uuid4().hex}"

        def collect_article():
            ensure_wechat_health(config)
            runner = build_real_article_poc_runner(
                config,
                account_name=args.account_name,
                max_articles_per_round=(
                    args.max_articles_per_round
                    or config.pipelines.article.max_articles_per_account
                ),
                lock_repo=HeldUiLockAdapter("article"),
            )
            return runner.run_once(now)

        try:
            result = guard.run_manual(
                "article", owner_task_id, now, collect_article
            )
        except WxautoNotAvailableError as exc:
            print(f"rpa_error={exc}", file=sys.stderr)
            return 1
        except WechatUiBusyError:
            print("managed_mode_error=wechat_ui_busy", file=sys.stderr)
            return 3
        except WechatUiLeaseLostError:
            print("managed_mode_error=wechat_ui_lease_lost", file=sys.stderr)
            return 3
        except WechatUiReleaseError:
            print("managed_mode_error=wechat_ui_release_failed", file=sys.stderr)
            return 1
        except Exception as exc:
            print(
                f"managed_guard_error={type(exc).__name__}",
                file=sys.stderr,
            )
            return 1
        print(f"account_name={args.account_name}")
        print(f"attempted_count={result.attempted_count}")
        print(f"success_count={result.success_count}")
        print(f"failed_count={result.failed_count}")
        print(f"lock_timeout_count={result.lock_timeout_count}")
        print(f"link_count={result.link_count}")
        print(f"raw_insert_count={result.raw_insert_count}")
        print(f"duplicate_count={result.duplicate_count}")
        print(f"skipped_count={result.skipped_count}")
        print(f"task_created_count={result.task_created_count}")
        return 0 if result.failed_count == 0 and result.lock_timeout_count == 0 else 1

    if args.command == "parse-article-once":
        config = load_config(Path(args.config))
        service = build_real_article_parse_service(config)
        result = service.parse_once(limit=args.limit, parse_time=datetime.now())
        print(f"read_count={result.read_count}")
        print(f"success_count={result.success_count}")
        print(f"failed_count={result.failed_count}")
        return 0

    if args.command == "analyze-article-once":
        config = load_config(Path(args.config))
        service = build_real_article_analysis_service(config)
        result = service.analyze_once(limit=args.limit, analyze_time=datetime.now())
        print(f"read_count={result.read_count}")
        print(f"success_count={result.success_count}")
        print(f"failed_count={result.failed_count}")
        return 0

    if args.command == "article-runtime-metrics":
        config = load_config(Path(args.config))
        repo = build_real_article_runtime_metrics_repo(config)
        try:
            metrics = repo.get_metrics(hours=args.hours)
        except ValueError as exc:
            print(f"article_metrics_error={exc}", file=sys.stderr)
            return 1
        print(
            " ".join(
                [
                    "article_runtime_metrics",
                    f"window_hours={metrics.window_hours}",
                    f"account_total_count={metrics.account_total_count}",
                    f"account_enabled_count={metrics.account_enabled_count}",
                    f"collect_success_count={metrics.collect_success_count}",
                    f"collect_failed_count={metrics.collect_failed_count}",
                    f"collect_skipped_count={metrics.collect_skipped_count}",
                    f"collect_total_count={metrics.collect_total_count}",
                ]
            )
        )
        if metrics.latest_error_summary is not None:
            print(f"latest_error_summary={metrics.latest_error_summary}")
        for backlog in metrics.task_backlogs:
            print(
                " ".join(
                    [
                        "article_task_backlog",
                        f"task_type={backlog.task_type}",
                        f"status={backlog.status}",
                        f"count={backlog.count}",
                    ]
                )
            )
        return 0

    if args.command == "run-article-scheduler":
        if not args.once:
            parser.error("--once is required for run-article-scheduler in development")
        config = load_config(Path(args.config))
        guard, guard_error = _build_managed_guard_for_cli(config)
        if guard_error is not None:
            return guard_error
        now = _shanghai_now()
        guard_error = _ensure_scheduler_allowed_for_cli(guard, now)
        if guard_error is not None:
            return guard_error
        ensure_wechat_health(config)
        try:
            runner = build_real_article_scheduler_runner(config)
        except WxautoNotAvailableError as exc:
            print(f"rpa_error={exc}", file=sys.stderr)
            return 1
        now = _shanghai_now()
        guard_error = _ensure_scheduler_allowed_for_cli(guard, now)
        if guard_error is not None:
            return guard_error
        result = runner.run_once(now)
        print(f"attempted_count={result.attempted_count}")
        print(f"success_count={result.success_count}")
        print(f"failed_count={result.failed_count}")
        print(f"lock_timeout_count={result.lock_timeout_count}")
        print(f"interrupted_count={result.interrupted_count}")
        return 0 if result.failed_count == 0 and result.lock_timeout_count == 0 else 1

    if args.command == "article-task-failed-list":
        config = load_config(Path(args.config))
        repo = build_real_article_task_admin_repo(config)
        try:
            tasks = repo.list_failed_tasks(task_type=args.task_type, limit=args.limit)
        except ValueError as exc:
            print(f"article_task_error={exc}", file=sys.stderr)
            return 1
        for task in tasks:
            print(
                " ".join(
                    [
                        "failed_task",
                        f"id={task.id}",
                        f"task_type={task.task_type}",
                        f"ref_type={task.ref_type}",
                        f"ref_id={task.ref_id}",
                        f"status={task.status}",
                        f"retry_count={task.retry_count}",
                        f"next_run_time={_format_optional(task.next_run_time)}",
                        f"error_summary={_format_optional(task.error_summary)}",
                        f"update_time={_format_optional(task.update_time)}",
                    ]
                )
            )
        return 0

    if args.command == "article-task-retry-failed":
        config = load_config(Path(args.config))
        repo = build_real_article_task_admin_repo(config)
        try:
            reset_count = repo.retry_failed_tasks(task_type=args.task_type, limit=args.limit)
        except ValueError as exc:
            print(f"article_task_error={exc}", file=sys.stderr)
            return 1
        print(f"task_type={_format_optional(args.task_type)}")
        print(f"limit={args.limit}")
        print(f"reset_count={reset_count}")
        return 0

    if args.command == "group-status":
        if not args.group_name:
            parser.error("--group-name is required for group-status")
        config = load_config(Path(args.config))
        repo = build_real_group_status_repo(config)
        status = repo.get_group_status(args.group_name)
        if status is None:
            print(f"group_status_not_found={args.group_name}")
            return 1
        print(f"group_name={status.group_name}")
        print(f"enabled={1 if status.enabled else 0}")
        print(f"is_core_group={1 if status.is_core_group else 0}")
        print(f"priority={status.priority}")
        print(f"poll_interval_seconds={status.poll_interval_seconds}")
        print(f"last_collect_batch_id={_format_optional(status.last_collect_batch_id)}")
        print(f"last_success_collect_time={_format_optional(status.last_success_collect_time)}")
        print(f"consecutive_fail_count={status.consecutive_fail_count}")
        print(f"cursor_error_msg={_format_optional(status.cursor_error_msg)}")
        print(f"latest_log_status={_format_optional(status.latest_log_status)}")
        print(f"latest_log_read_count={_format_optional(status.latest_log_read_count)}")
        print(f"latest_log_insert_count={_format_optional(status.latest_log_insert_count)}")
        print(f"latest_log_duplicate_count={_format_optional(status.latest_log_duplicate_count)}")
        print(f"latest_log_error_code={_format_optional(status.latest_log_error_code)}")
        print(f"latest_log_screenshot_path={_format_optional(status.latest_log_screenshot_path)}")
        print(f"ui_lock_owner_pipeline={_format_optional(status.ui_lock_owner_pipeline)}")
        print(f"ui_lock_owner_task_id={_format_optional(status.ui_lock_owner_task_id)}")
        return 0

    if args.command == "group-runtime-summary":
        config = load_config(Path(args.config))
        repo = build_real_group_runtime_summary_repo(config)
        summary = repo.get_summary(limit=args.limit)
        print(
            " ".join(
                [
                    "group_config",
                    f"total_count={summary.config.total_count}",
                    f"enabled_count={summary.config.enabled_count}",
                    f"core_enabled_count={summary.config.core_enabled_count}",
                ]
            )
        )
        print(
            " ".join(
                [
                    "ui_lock",
                    f"status={summary.ui_lock.status}",
                    f"owner_pipeline={_format_optional(summary.ui_lock.owner_pipeline)}",
                    f"owner_task_id={_format_optional(summary.ui_lock.owner_task_id)}",
                    f"expire_time={_format_optional(summary.ui_lock.expire_time)}",
                ]
            )
        )
        for backlog in summary.task_backlogs:
            print(
                " ".join(
                    [
                        "task_backlog",
                        f"task_type={backlog.task_type}",
                        f"status={backlog.status}",
                        f"count={backlog.count}",
                    ]
                )
            )
        for log in summary.latest_collect_logs:
            print(
                " ".join(
                    [
                        "latest_collect",
                        f"source_name={log.source_name}",
                        f"batch_id={log.batch_id}",
                        f"status={log.status}",
                        f"read_count={log.read_count}",
                        f"insert_count={log.insert_count}",
                        f"duplicate_count={log.duplicate_count}",
                        f"error_code={_format_optional(log.error_code)}",
                        f"screenshot_path={_format_optional(log.screenshot_path)}",
                    ]
                )
            )
        return 0

    if args.command == "group-runtime-metrics":
        config = load_config(Path(args.config))
        repo = build_real_group_runtime_metrics_repo(config)
        try:
            metrics = repo.get_metrics(hours=args.hours)
        except ValueError as exc:
            print(f"group_metrics_error={exc}", file=sys.stderr)
            return 1
        print(
            " ".join(
                [
                    "runtime_metrics",
                    f"window_hours={metrics.window_hours}",
                    f"collect_success_count={metrics.collect_success_count}",
                    f"collect_failed_count={metrics.collect_failed_count}",
                    f"collect_total_count={metrics.collect_total_count}",
                    f"collect_failure_rate={metrics.collect_failure_rate:.4f}",
                    f"daily_report_count={metrics.daily_report_count}",
                ]
            )
        )
        for backlog in metrics.task_backlogs:
            print(
                " ".join(
                    [
                        "task_backlog",
                        f"task_type={backlog.task_type}",
                        f"status={backlog.status}",
                        f"count={backlog.count}",
                    ]
                )
            )
        return 0

    if args.command == "group-task-list":
        config = load_config(Path(args.config))
        repo = build_real_group_task_admin_repo(config)
        tasks = repo.list_tasks(
            task_type=args.task_type,
            status=args.status,
            ref_id=args.ref_id,
            limit=args.limit,
        )
        for task in tasks:
            print(
                " ".join(
                    [
                        "task",
                        f"id={task.id}",
                        f"task_type={task.task_type}",
                        f"ref_type={task.ref_type}",
                        f"ref_id={task.ref_id}",
                        f"status={task.status}",
                        f"retry_count={task.retry_count}",
                        f"next_run_time={_format_optional(task.next_run_time)}",
                        f"error_msg={_format_optional(task.error_msg)}",
                        f"update_time={_format_optional(task.update_time)}",
                    ]
                )
            )
        return 0

    if args.command == "group-task-reset":
        if not args.task_type:
            parser.error("--task-type is required for group-task-reset")
        if not args.ref_id:
            parser.error("--ref-id is required for group-task-reset")
        config = load_config(Path(args.config))
        repo = build_real_group_task_admin_repo(config)
        try:
            reset_count = repo.reset_task(task_type=args.task_type, ref_id=args.ref_id)
        except ValueError as exc:
            print(f"group_task_error={exc}", file=sys.stderr)
            return 1
        print(f"task_type={args.task_type}")
        print(f"ref_id={args.ref_id}")
        print(f"reset_count={reset_count}")
        return 0

    if args.command == "group-task-reset-date":
        if not args.date:
            parser.error("--date is required for group-task-reset-date")
        config = load_config(Path(args.config))
        repo = build_real_group_task_admin_repo(config)
        report_date = _parse_date(args.date)
        reset_count = repo.reset_daily_report_date(report_date)
        print("task_type=group_daily_report")
        print(f"ref_id={report_date.isoformat()}")
        print(f"reset_count={reset_count}")
        return 0

    if args.command == "group-task-failed-list":
        config = load_config(Path(args.config))
        repo = build_real_group_task_admin_repo(config)
        try:
            tasks = repo.list_failed_tasks(task_type=args.task_type, limit=args.limit)
        except ValueError as exc:
            print(f"group_task_error={exc}", file=sys.stderr)
            return 1
        for task in tasks:
            print(
                " ".join(
                    [
                        "failed_task",
                        f"id={task.id}",
                        f"task_type={task.task_type}",
                        f"ref_type={task.ref_type}",
                        f"ref_id={task.ref_id}",
                        f"status={task.status}",
                        f"retry_count={task.retry_count}",
                        f"next_run_time={_format_optional(task.next_run_time)}",
                        f"error_summary={_format_optional(task.error_summary)}",
                        f"update_time={_format_optional(task.update_time)}",
                    ]
                )
            )
        return 0

    if args.command == "group-task-retry-failed":
        config = load_config(Path(args.config))
        repo = build_real_group_task_admin_repo(config)
        try:
            reset_count = repo.retry_failed_tasks(task_type=args.task_type, limit=args.limit)
        except ValueError as exc:
            print(f"group_task_error={exc}", file=sys.stderr)
            return 1
        print(f"task_type={_format_optional(args.task_type)}")
        print(f"limit={args.limit}")
        print(f"reset_count={reset_count}")
        return 0

    if args.command == "clean-group-once":
        config = load_config(Path(args.config))
        service = build_real_group_clean_service(config)
        result = service.clean_once(limit=args.limit, clean_time=datetime.now())
        print(f"read_count={result.read_count}")
        print(f"success_count={result.success_count}")
        print(f"failed_count={result.failed_count}")
        return 0

    if args.command == "analyze-group-once":
        config = load_config(Path(args.config))
        service = build_real_group_analysis_service(config, Path(args.rules_config))
        result = service.analyze_once(limit=args.limit, analyze_time=datetime.now())
        print(f"read_count={result.read_count}")
        print(f"success_count={result.success_count}")
        print(f"failed_count={result.failed_count}")
        return 0

    if args.command == "group-daily-report-once":
        if not args.date:
            parser.error("--date is required for group-daily-report-once")
        report_date = _parse_date(args.date)
        now = _shanghai_now()
        try:
            lifecycle = ReportLifecycle.manual_for_date(report_date, now, "cli")
        except ValueError as exc:
            print(f"report_error={exc}", file=sys.stderr)
            return 1
        config = load_config(Path(args.config))
        service = build_real_group_daily_report_service(config)
        result = service.generate_once(
            report_date=report_date,
            group_name=args.group_name,
            generate_time=now.replace(tzinfo=None),
            lifecycle=lifecycle,
        )
        print(f"report_date={result.report_date.isoformat()}")
        print(f"generated_count={result.generated_count}")
        return 0

    if args.command == "group-daily-report-list":
        if not args.date:
            parser.error("--date is required for group-daily-report-list")
        config = load_config(Path(args.config))
        service = build_real_group_daily_report_query_service(config)
        report_date = _parse_date(args.date)
        reports = service.list_reports(report_date=report_date, group_name=args.group_name, limit=args.limit)
        for report in reports:
            print(
                " ".join(
                    [
                        f"report_date={report.report_date.isoformat()}",
                        f"group_name={report.group_name}",
                        f"title={report.title}",
                        f"message_count={report.message_count}",
                        f"sender_count={report.sender_count}",
                        f"demand_count={report.demand_count}",
                        f"supply_count={report.supply_count}",
                        f"contact_count={report.contact_count}",
                        f"peak_hour={_format_optional(report.peak_hour)}",
                        f"generate_time={_format_optional(report.generate_time)}",
                    ]
                )
            )
        return 0

    if args.command == "group-daily-report-show":
        if not args.date:
            parser.error("--date is required for group-daily-report-show")
        if not args.group_name:
            parser.error("--group-name is required for group-daily-report-show")
        config = load_config(Path(args.config))
        service = build_real_group_daily_report_query_service(config)
        report = service.get_report(report_date=_parse_date(args.date), group_name=args.group_name)
        if report is None:
            print(f"daily_report_not_found={args.date} {args.group_name}")
            return 1
        print(report.markdown_body)
        return 0

    if args.command == "group-daily-report-export":
        if not args.date:
            parser.error("--date is required for group-daily-report-export")
        if not args.group_name:
            parser.error("--group-name is required for group-daily-report-export")
        config = load_config(Path(args.config))
        service = build_real_group_daily_report_query_service(config)
        try:
            result = service.export_report(
                report_date=_parse_date(args.date),
                group_name=args.group_name,
                output_path=Path(args.output or "runtime/reports/group"),
            )
        except DailyReportNotFoundError as exc:
            print(f"daily_report_error={exc}", file=sys.stderr)
            return 1
        print(f"export_path={result.export_path}")
        print(f"bytes_written={result.bytes_written}")
        return 0

    if args.command == "article-daily-report-list":
        if not args.date:
            parser.error("--date is required for article-daily-report-list")
        config = load_config(Path(args.config))
        service = build_real_article_daily_report_query_service(config)
        report_date = _parse_date(args.date)
        reports = service.list_reports(report_date=report_date, account_name=args.account_name, limit=args.limit)
        for report in reports:
            print(
                " ".join(
                    [
                        f"report_date={report.report_date.isoformat()}",
                        f"account_name={report.account_name}",
                        f"title={report.title}",
                        f"article_count={report.article_count}",
                        f"avg_content_length={report.avg_content_length}",
                        f"generate_time={_format_optional(report.generate_time)}",
                    ]
                )
            )
        return 0

    if args.command == "article-daily-report-show":
        if not args.date:
            parser.error("--date is required for article-daily-report-show")
        if not args.account_name:
            parser.error("--account-name is required for article-daily-report-show")
        config = load_config(Path(args.config))
        service = build_real_article_daily_report_query_service(config)
        report = service.get_report(report_date=_parse_date(args.date), account_name=args.account_name)
        if report is None:
            print(f"article_daily_report_not_found={args.date} {args.account_name}")
            return 1
        print(report.markdown_body)
        return 0

    if args.command == "article-daily-report-export":
        if not args.date:
            parser.error("--date is required for article-daily-report-export")
        if not args.account_name:
            parser.error("--account-name is required for article-daily-report-export")
        config = load_config(Path(args.config))
        service = build_real_article_daily_report_query_service(config)
        try:
            result = service.export_report(
                report_date=_parse_date(args.date),
                account_name=args.account_name,
                output_path=Path(args.output or "runtime/reports/article"),
            )
        except ArticleDailyReportNotFoundError as exc:
            print(f"article_daily_report_error={exc}", file=sys.stderr)
            return 1
        print(f"export_path={result.export_path}")
        print(f"bytes_written={result.bytes_written}")
        return 0

    if args.command == "summary-daily-report-show":
        if not args.date:
            parser.error("--date is required for summary-daily-report-show")
        config = load_config(Path(args.config))
        service = build_real_summary_daily_report_service(config)
        report_date = _parse_date(args.date)
        draft = service.generate(report_date=report_date, generate_time=datetime.now())
        print(draft.markdown_body)
        return 0

    if args.command == "summary-daily-report-export":
        if not args.date:
            parser.error("--date is required for summary-daily-report-export")
        config = load_config(Path(args.config))
        service = build_real_summary_daily_report_service(config)
        report_date = _parse_date(args.date)
        try:
            draft = service.generate(report_date=report_date, generate_time=datetime.now())
            export_path = _resolve_summary_daily_report_export_path(
                Path(args.output or "runtime/reports/summary"),
                report_date,
            )
            export_path.parent.mkdir(parents=True, exist_ok=True)
            payload = draft.markdown_body
            export_path.write_text(payload, encoding="utf-8")
        except OSError as exc:
            print(f"summary_daily_report_error={exc}", file=sys.stderr)
            return 1
        print(f"export_path={export_path}")
        print(f"bytes_written={len(payload.encode('utf-8'))}")
        return 0

    if args.command == "trial-monitor-report":
        config = load_config(Path(args.config))
        service = build_real_trial_monitor_report_service(config)
        try:
            report = service.generate(hours=args.hours, generate_time=datetime.now())
        except ValueError as exc:
            print(f"trial_monitor_report_error={exc}", file=sys.stderr)
            return 1
        print(
            " ".join(
                [
                    "trial_monitor_report",
                    f"hours={report.hours}",
                    f"group_success_count={report.group_success_count}",
                    f"group_failed_count={report.group_failed_count}",
                    f"group_backlog_count={report.group_backlog_count}",
                    f"article_success_count={report.article_success_count}",
                    f"article_failed_count={report.article_failed_count}",
                    f"article_backlog_count={report.article_backlog_count}",
                    f"ui_lock_timeout_count={report.ui_lock_timeout_count}",
                ]
            )
        )
        return 0

    if args.command == "ai-analysis-sample":
        if not args.source:
            parser.error("--source is required for ai-analysis-sample")
        if not args.date:
            parser.error("--date is required for ai-analysis-sample")
        if not args.dry_run:
            parser.error("--dry-run is required for ai-analysis-sample")
        service = build_real_ai_analysis_service(Path(args.ai_config))
        report_date = _parse_date(args.date)
        try:
            result = service.analyze_sample(
                AiAnalysisServiceInput(
                    source=args.source,
                    source_date=report_date,
                    title=f"{report_date.isoformat()} {args.source} AI dry-run sample",
                    summary_text="dry-run only",
                    structured_features={"source": args.source, "source_date": report_date.isoformat()},
                )
            )
        except ValueError as exc:
            print(f"ai_analysis_error={exc}", file=sys.stderr)
            return 1
        print(
            " ".join(
                [
                    "ai_analysis_sample",
                    f"source={result.source}",
                    f"dry_run={1 if result.dry_run else 0}",
                    f"input_field_count={result.input_field_count}",
                    f"provider={result.provider}",
                    f"prompt_version={result.prompt_version}",
                    f"model_version={result.model_version}",
                    f"model_called={1 if result.model_called else 0}",
                ]
            )
        )
        return 0

    if args.command == "run-group-pipeline-once":
        if not args.date:
            parser.error("--date is required for run-group-pipeline-once")
        if not args.skip_collect and not args.group_name:
            parser.error("--group-name is required unless --skip-collect is set")
        report_date = _parse_date(args.date)
        now = _shanghai_now()
        try:
            lifecycle = ReportLifecycle.manual_for_date(report_date, now, "cli")
        except ValueError as exc:
            print(f"report_error={exc}", file=sys.stderr)
            return 1
        config = load_config(Path(args.config))
        if not args.skip_collect:
            ensure_wechat_health(config)
        try:
            service = build_real_group_pipeline_service(
                config,
                Path(args.rules_config),
                include_collect=not args.skip_collect,
            )
            result = service.run_once(
                report_date=report_date,
                group_name=args.group_name,
                skip_collect=args.skip_collect,
                limit=args.limit,
                run_time=now.replace(tzinfo=None),
                batch_id=f"pipeline-{uuid4().hex}",
                lifecycle=lifecycle,
            )
        except WxautoNotAvailableError as exc:
            print(f"rpa_error={exc}", file=sys.stderr)
            return 1
        _print_pipeline_result(result)
        return 0 if result.status == "success" else 1

    if args.command == "collect-group-once":
        if not args.group_name:
            parser.error("--group-name is required for collect-group-once")
        config = load_config(Path(args.config))
        guard, guard_error = _build_managed_guard_for_cli(config)
        if guard_error is not None:
            return guard_error
        now = _shanghai_now()
        owner_task_id = f"manual-{uuid4().hex}"

        def collect_group():
            ensure_wechat_health(config)
            service = build_real_group_collect_service(config)
            return service.collect_once(
                group_name=args.group_name,
                batch_id=owner_task_id,
                collect_time=now,
            )

        try:
            result = guard.run_manual(
                "group", owner_task_id, now, collect_group
            )
        except WxautoNotAvailableError as exc:
            print(f"rpa_error={exc}", file=sys.stderr)
            return 1
        except WechatUiBusyError:
            print("managed_mode_error=wechat_ui_busy", file=sys.stderr)
            return 3
        except WechatUiLeaseLostError:
            print("managed_mode_error=wechat_ui_lease_lost", file=sys.stderr)
            return 3
        except WechatUiReleaseError:
            print("managed_mode_error=wechat_ui_release_failed", file=sys.stderr)
            return 1
        except Exception as exc:
            print(
                f"managed_guard_error={type(exc).__name__}",
                file=sys.stderr,
            )
            return 1
        print(f"group_name={result.group_name}")
        print(f"batch_id={result.batch_id}")
        print(f"read_count={result.read_count}")
        print(f"insert_count={result.insert_count}")
        print(f"duplicate_count={result.duplicate_count}")
        return 0

    if args.command == "run-group-scheduler":
        config = load_config(Path(args.config))
        guard, guard_error = _build_managed_guard_for_cli(config)
        if guard_error is not None:
            return guard_error
        guard_error = _ensure_scheduler_allowed_for_cli(
            guard, _shanghai_now()
        )
        if guard_error is not None:
            return guard_error
        ensure_wechat_health(config)
        try:
            runner = build_real_group_polling_runner(config)
        except WxautoNotAvailableError as exc:
            print(f"rpa_error={exc}", file=sys.stderr)
            return 1

        while True:
            now = _shanghai_now()
            guard_error = _ensure_scheduler_allowed_for_cli(guard, now)
            if guard_error is not None:
                return guard_error
            result = runner.run_once(now)
            print(f"attempted_count={result.attempted_count}")
            print(f"success_count={result.success_count}")
            print(f"failed_count={result.failed_count}")
            print(f"lock_timeout_count={result.lock_timeout_count}")
            if args.once:
                return 0
            time.sleep(config.pipelines.group.poll_interval_seconds)

    return 2


def check_wechat_health(config):
    return WechatDesktopProbe(expected_version=config.wechat.pc_version).check()


def ensure_wechat_health(config) -> None:
    health = check_wechat_health(config)
    if health.status != WechatHealthStatus.OK:
        raise RuntimeError(f"WeChat health check failed: {health.status.value} - {health.message}")


def build_managed_mode_guard(config) -> ManagedModeGuard:
    engine = create_mysql_engine(config.mysql)
    return ManagedModeGuard(
        heartbeat_repo=MysqlWorkerHeartbeatRepo(engine),
        ui_lock_repo=MysqlUiLockRepo(engine),
        hostname=socket.gethostname(),
        collector_heartbeat_ttl_seconds=(
            config.workers.heartbeat_seconds * 3
        ),
        ui_lease_seconds=config.pipelines.ui_resource.lock_lease_seconds,
        ui_heartbeat_interval_seconds=(
            config.pipelines.ui_resource.lock_heartbeat_interval_seconds
        ),
    )


def _build_managed_guard_for_cli(config):
    try:
        return build_managed_mode_guard(config), None
    except Exception as exc:
        print(
            f"managed_guard_error={type(exc).__name__}",
            file=sys.stderr,
        )
        return None, 1


def _ensure_scheduler_allowed_for_cli(guard, now: datetime) -> int | None:
    try:
        guard.ensure_scheduler_allowed(now)
    except ManagedModeActiveError:
        print("managed_mode_error=collector_active", file=sys.stderr)
        return 3
    except Exception as exc:
        print(
            f"managed_guard_error={type(exc).__name__}",
            file=sys.stderr,
        )
        return 1
    return None


def _shanghai_now() -> datetime:
    return datetime.now(_ZONE)


def build_real_group_collect_service(config) -> GroupCollectService:
    engine = create_mysql_engine(config.mysql)
    repo = MysqlGroupMessageRepo(engine)
    rpa = WxautoGroupRpaClient()
    return GroupCollectService(rpa=rpa, repo=repo)


def build_real_group_clean_service(config) -> GroupCleanService:
    engine = create_mysql_engine(config.mysql)
    repo = MysqlGroupCleanRepo(engine)
    return GroupCleanService(repo=repo)


def build_real_group_analysis_service(config, rules_config_path: Path) -> GroupAnalysisService:
    engine = create_mysql_engine(config.mysql)
    repo = MysqlGroupAnalysisRepo(engine)
    rule_set = load_analysis_rule_set(rules_config_path)
    return GroupAnalysisService(repo=repo, rule_set=rule_set)


def build_real_group_daily_report_service(config) -> GroupDailyReportService:
    engine = create_mysql_engine(config.mysql)
    repo = MysqlGroupAnalysisRepo(engine)
    return GroupDailyReportService(repo=repo)


def build_real_group_daily_report_query_service(config) -> GroupDailyReportQueryService:
    engine = create_mysql_engine(config.mysql)
    repo = MysqlGroupDailyReportQueryRepo(engine)
    return GroupDailyReportQueryService(repo=repo)


def build_real_article_daily_report_query_service(config) -> ArticleDailyReportQueryService:
    engine = create_mysql_engine(config.mysql)
    repo = MysqlArticleDailyReportQueryRepo(engine)
    return ArticleDailyReportQueryService(repo=repo)


def build_real_summary_daily_report_service(config) -> SummaryDailyReportService:
    engine = create_mysql_engine(config.mysql)
    repo = MysqlSummaryDailyReportQueryRepo(engine)
    query_service = SummaryDailyReportQueryService(repo=repo)
    return SummaryDailyReportService(query_service=query_service)


def build_real_trial_monitor_report_service(config) -> TrialMonitorReportService:
    engine = create_mysql_engine(config.mysql)
    return TrialMonitorReportService(
        group_metrics_repo=MysqlGroupRuntimeMetricsRepo(engine),
        article_metrics_repo=MysqlArticleRuntimeMetricsRepo(engine),
    )


def build_real_ai_analysis_service(ai_config_path: Path) -> AiAnalysisService:
    return AiAnalysisService(config=load_ai_analysis_config(ai_config_path))


def build_real_group_pipeline_service(config, rules_config_path: Path, include_collect: bool) -> GroupPipelineService:
    engine = create_mysql_engine(config.mysql)
    group_analysis_repo = MysqlGroupAnalysisRepo(engine)
    rule_set = load_analysis_rule_set(rules_config_path)
    collect_service = _DisabledCollectService()
    if include_collect:
        collect_service = GroupCollectService(
            rpa=WxautoGroupRpaClient(),
            repo=MysqlGroupMessageRepo(engine),
        )
    return GroupPipelineService(
        collect_service=collect_service,
        clean_service=GroupCleanService(repo=MysqlGroupCleanRepo(engine)),
        analysis_service=GroupAnalysisService(
            repo=group_analysis_repo,
            rule_set=rule_set,
        ),
        daily_report_service=GroupDailyReportService(repo=group_analysis_repo),
    )


def build_real_group_config_repo(config) -> MysqlGroupConfigRepo:
    engine = create_mysql_engine(config.mysql)
    return MysqlGroupConfigRepo(engine)


def build_real_article_account_config_repo(config) -> MysqlArticleAccountConfigRepo:
    engine = create_mysql_engine(config.mysql)
    return MysqlArticleAccountConfigRepo(engine)


def build_real_article_rpa_client(config) -> WxautoArticleRpaClient:
    engine = create_mysql_engine(config.mysql)
    route_cache_repo = (
        MysqlArticleRouteCacheRepo(engine) if config.pipelines.article.route_cache_enabled else None
    )
    return WxautoArticleRpaClient(
        route_cache_repo=route_cache_repo,
        route_cache_enabled=config.pipelines.article.route_cache_enabled,
        route_probe_enabled=config.pipelines.article.route_probe_enabled,
        route_probe_failure_threshold=config.pipelines.article.route_probe_failure_threshold,
        route_entry_labels=config.pipelines.article.route_entry_labels,
        link_extract_methods=config.pipelines.article.link_extract_methods,
        close_browser_after_extract=True,
        open_account_search_fallback_enabled=True,
    )


def build_real_article_rpa_probe(config) -> WxautoArticleRpaClient:
    return build_real_article_rpa_client(config)


def build_real_article_poc_runner(
    config,
    *,
    account_name: str,
    max_articles_per_round: int,
    lock_repo=None,
) -> ArticlePollingRunner:
    engine = create_mysql_engine(config.mysql)
    group_config_repo = MysqlGroupConfigRepo(engine)
    collect_service = ArticleCollectService(
        rpa=build_real_article_rpa_client(config),
        raw_repo=MysqlArticleRawRepo(engine),
    )

    def account_provider(now: datetime, limit: int):
        return [
            ArticlePollingTarget(
                account_name=account_name,
                priority=1,
                poll_interval_minutes=config.pipelines.article.account_poll_interval_minutes,
                max_articles_per_round=max_articles_per_round,
            )
        ]

    return ArticlePollingRunner(
        collect_service=collect_service,
        lock_repo=(
            MysqlUiLockRepo(engine) if lock_repo is None else lock_repo
        ),
        account_provider=account_provider,
        log_repo=MysqlArticleCollectLogRepo(engine),
        screenshot_client=DesktopScreenshotClient(),
        screenshot_root=Path(config.runtime.screenshot_dir),
        lease_seconds=config.pipelines.ui_resource.lock_lease_seconds,
        lock_acquire_timeout_seconds=config.pipelines.ui_resource.lock_acquire_timeout_seconds,
        max_accounts_per_ui_slice=1,
        batch_id_factory=lambda selected_account_name: f"article-{uuid4().hex}",
        progress_repo=MysqlArticleProgressRepo(engine),
        next_core_group_due_provider=ReadOnlyCoreGroupDueProvider(
            group_config_repo=group_config_repo,
            poll_interval_seconds=config.pipelines.group.poll_interval_seconds,
            now_provider=_shanghai_now,
        ),
        max_core_group_block_seconds=config.pipelines.ui_resource.max_core_group_block_seconds,
        checkpoint_now_provider=_shanghai_now,
    )


def build_real_article_scheduler_runner(config) -> ArticlePollingRunner:
    engine = create_mysql_engine(config.mysql)
    article_config_repo = MysqlArticleAccountConfigRepo(engine)
    group_config_repo = MysqlGroupConfigRepo(engine)
    collect_service = ArticleCollectService(
        rpa=build_real_article_rpa_client(config),
        raw_repo=MysqlArticleRawRepo(engine),
    )

    def account_provider(now: datetime, limit: int):
        return [
            ArticlePollingTarget(
                account_name=record.account_name,
                priority=record.priority,
                poll_interval_minutes=record.poll_interval_minutes,
                max_articles_per_round=record.max_articles_per_round,
            )
            for record in article_config_repo.list_due_accounts(now, limit)
        ]

    return ArticlePollingRunner(
        collect_service=collect_service,
        lock_repo=MysqlUiLockRepo(engine),
        account_provider=account_provider,
        log_repo=MysqlArticleCollectLogRepo(engine),
        screenshot_client=DesktopScreenshotClient(),
        screenshot_root=Path(config.runtime.screenshot_dir),
        lease_seconds=config.pipelines.ui_resource.lock_lease_seconds,
        lock_acquire_timeout_seconds=config.pipelines.ui_resource.lock_acquire_timeout_seconds,
        max_accounts_per_ui_slice=config.pipelines.article.max_accounts_per_ui_slice,
        batch_id_factory=lambda selected_account_name: f"article-{uuid4().hex}",
        progress_repo=MysqlArticleProgressRepo(engine),
        next_core_group_due_provider=ReadOnlyCoreGroupDueProvider(
            group_config_repo=group_config_repo,
            poll_interval_seconds=config.pipelines.group.poll_interval_seconds,
            now_provider=_shanghai_now,
        ),
        max_core_group_block_seconds=config.pipelines.ui_resource.max_core_group_block_seconds,
        checkpoint_now_provider=_shanghai_now,
    )


def build_real_article_parse_service(config) -> ArticleParseService:
    engine = create_mysql_engine(config.mysql)
    return ArticleParseService(
        repo=MysqlArticleParseRepo(engine),
        parser=PlaywrightArticleParser(
            timeout_ms=config.pipelines.article.rpa_timeout_seconds * 1000,
            browser_executable_path=config.pipelines.article.browser_executable_path,
        ),
    )


def build_real_article_analysis_service(config) -> ArticleAnalysisService:
    engine = create_mysql_engine(config.mysql)
    return ArticleAnalysisService(
        repo=MysqlArticleAnalysisRepo(engine),
        extractor=PlaywrightArticleTransientExtractor(
            timeout_ms=config.pipelines.article.rpa_timeout_seconds * 1000,
            browser_executable_path=config.pipelines.article.browser_executable_path,
            image_quote_note_enabled=config.pipelines.article.image_quote_note_enabled,
        ),
        price_items_preview_limit=config.pipelines.article.price_items_json_preview_limit,
        egg_price_extraction_enabled=config.pipelines.article.egg_price_extraction_enabled,
    )


def build_real_article_runtime_metrics_repo(config) -> MysqlArticleRuntimeMetricsRepo:
    engine = create_mysql_engine(config.mysql)
    return MysqlArticleRuntimeMetricsRepo(engine)


def build_real_article_task_admin_repo(config) -> MysqlArticleTaskAdminRepo:
    engine = create_mysql_engine(config.mysql)
    return MysqlArticleTaskAdminRepo(engine)


def build_real_group_status_repo(config) -> MysqlGroupStatusRepo:
    engine = create_mysql_engine(config.mysql)
    return MysqlGroupStatusRepo(engine)


def build_real_group_runtime_summary_repo(config) -> MysqlGroupRuntimeSummaryRepo:
    engine = create_mysql_engine(config.mysql)
    return MysqlGroupRuntimeSummaryRepo(engine)


def build_real_group_runtime_metrics_repo(config) -> MysqlGroupRuntimeMetricsRepo:
    engine = create_mysql_engine(config.mysql)
    return MysqlGroupRuntimeMetricsRepo(engine)


def build_real_group_task_admin_repo(config) -> MysqlGroupTaskAdminRepo:
    engine = create_mysql_engine(config.mysql)
    return MysqlGroupTaskAdminRepo(engine)


def build_real_group_polling_runner(config) -> GroupPollingRunner:
    engine = create_mysql_engine(config.mysql)
    message_repo = MysqlGroupMessageRepo(engine)
    collect_service = GroupCollectService(rpa=WxautoGroupRpaClient(), repo=message_repo)
    group_config_repo = MysqlGroupConfigRepo(engine)

    def group_provider(now: datetime, limit: int):
        return [
            GroupPollingTarget(
                group_name=record.group_name,
                priority=record.priority,
                poll_interval_seconds=record.poll_interval_seconds,
            )
            for record in group_config_repo.list_due_groups(now, limit)
        ]

    return GroupPollingRunner(
        collect_service=collect_service,
        lock_repo=MysqlUiLockRepo(engine),
        group_provider=group_provider,
        log_repo=MysqlGroupCollectLogRepo(engine),
        screenshot_client=DesktopScreenshotClient(),
        screenshot_root=Path("runtime/screenshots"),
        lease_seconds=config.pipelines.ui_resource.lock_lease_seconds,
        lock_acquire_timeout_seconds=config.pipelines.ui_resource.lock_acquire_timeout_seconds,
        max_groups_per_round=config.pipelines.group.max_group_per_round,
        batch_id_factory=lambda group_name: f"group-{uuid4().hex}",
    )


def _format_optional(value) -> str:
    return "" if value is None else str(value)


def _resolve_summary_daily_report_export_path(output_path: Path, report_date: date) -> Path:
    if output_path.suffix.lower() == ".md":
        return output_path
    return output_path / report_date.isoformat() / "summary.md"


def _parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


class _DisabledCollectService:
    def collect_once(self, group_name: str, batch_id: str, collect_time: datetime):
        raise RuntimeError("collect stage is disabled")


def _print_pipeline_result(result) -> None:
    print(f"pipeline_status={result.status}")
    if result.failed_stage is not None:
        print(f"failed_stage={result.failed_stage}")
    if result.error_msg is not None:
        print(f"error_msg={result.error_msg}")
    for stage in result.stages:
        parts = [f"stage={stage.stage}", f"status={stage.status}"]
        for key, value in stage.metrics.items():
            parts.append(f"{key}={value}")
        if stage.error_msg is not None:
            parts.append(f"error_msg={stage.error_msg}")
        print(" ".join(parts))


if __name__ == "__main__":
    raise SystemExit(main())
