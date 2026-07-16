from __future__ import annotations

import argparse
import signal
import sys
from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from apscheduler.schedulers import SchedulerNotRunningError
from apscheduler.schedulers.blocking import BlockingScheduler

from app.core.config import Config, load_config
from app.domain.collection_jobs import APPLICATION_TIMEZONE
from app.workers.pipeline_runtime_factory import build_pipeline_worker


_ZONE = ZoneInfo(APPLICATION_TIMEZONE)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the automatic non-UI processing pipeline worker."
    )
    parser.add_argument("--config", required=True)
    parser.add_argument("--once", action="store_true")
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    runtime_builder: Callable[[Config], object] = build_pipeline_worker,
    scheduler_factory=BlockingScheduler,
    now_provider: Callable[[], datetime] | None = None,
) -> int:
    args = build_parser().parse_args(argv)
    clock = now_provider or _shanghai_now
    try:
        config = load_config(Path(args.config))
    except Exception as exc:
        print(
            f"pipeline_config_error={type(exc).__name__}",
            file=sys.stderr,
        )
        return 2
    try:
        worker = runtime_builder(config)
    except ValueError as exc:
        print(
            f"pipeline_runtime_config_error={type(exc).__name__}",
            file=sys.stderr,
        )
        return 2
    except Exception as exc:
        print(
            f"pipeline_runtime_error={type(exc).__name__}",
            file=sys.stderr,
        )
        return 1

    scheduler = None
    previous_handlers: dict[int, object] = {}
    exit_code = 0
    primary_error: Exception | None = None
    try:
        worker.heartbeat(clock())
        worker.ensure_daily_compensation_now()
        if args.once:
            worker.run_tick_now()
            cleanup = getattr(worker, "cleanup_events_now", None)
            if callable(cleanup):
                cleanup()
        else:
            scheduler = scheduler_factory(timezone=APPLICATION_TIMEZONE)
            scheduler.add_job(
                worker.run_tick_now,
                "interval",
                seconds=config.workers.pipeline_tick_seconds,
                max_instances=1,
                coalesce=True,
            )
            scheduler.add_job(
                worker.heartbeat_now,
                "interval",
                seconds=config.workers.heartbeat_seconds,
                max_instances=1,
                coalesce=True,
            )
            scheduler.add_job(
                worker.ensure_daily_compensation_now,
                "cron",
                hour=0,
                minute=10,
                max_instances=1,
                coalesce=True,
            )
            cleanup = getattr(worker, "cleanup_events_now", None)
            if callable(cleanup):
                scheduler.add_job(
                    cleanup,
                    "interval",
                    hours=getattr(config.workers, "event_cleanup_interval_hours", 24),
                    max_instances=1,
                    coalesce=True,
                )
            previous_handlers = _install_signal_handlers()
            scheduler.start()
    except KeyboardInterrupt:
        exit_code = 0
    except Exception as exc:
        primary_error = exc
        exit_code = 1
        print(
            f"pipeline_run_error={type(exc).__name__}",
            file=sys.stderr,
        )
    finally:
        shutdown_errors: list[Exception] = []
        try:
            worker.mark_stopping(clock())
        except Exception as exc:
            shutdown_errors.append(exc)
        if scheduler is not None:
            try:
                scheduler.shutdown(wait=True)
            except SchedulerNotRunningError:
                pass
            except Exception as exc:
                shutdown_errors.append(exc)
        try:
            worker.mark_stopped(clock())
        except Exception as exc:
            shutdown_errors.append(exc)
        _restore_signal_handlers(previous_handlers)
        if shutdown_errors:
            if primary_error is None:
                exit_code = 1
            for error in shutdown_errors:
                print(
                    f"pipeline_shutdown_error={type(error).__name__}",
                    file=sys.stderr,
                )
    return exit_code


def _install_signal_handlers() -> dict[int, object]:
    previous: dict[int, object] = {}

    def interrupt(signum, frame) -> None:
        raise KeyboardInterrupt

    for signal_name in ("SIGINT", "SIGTERM", "SIGBREAK"):
        signum = getattr(signal, signal_name, None)
        if signum is None or signum in previous:
            continue
        previous[signum] = signal.getsignal(signum)
        signal.signal(signum, interrupt)
    return previous


def _restore_signal_handlers(previous: dict[int, object]) -> None:
    for signum, handler in previous.items():
        signal.signal(signum, handler)


def _shanghai_now() -> datetime:
    return datetime.now(_ZONE)


if __name__ == "__main__":
    raise SystemExit(main())
