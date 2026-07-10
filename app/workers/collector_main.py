from __future__ import annotations

import argparse
import signal
import sys
import threading
from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler

from app.core.config import Config, load_config
from app.domain.collection_jobs import APPLICATION_TIMEZONE
from app.workers.runtime_factory import build_managed_collector_worker


_ZONE = ZoneInfo(APPLICATION_TIMEZONE)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the managed WeChat collection worker."
    )
    parser.add_argument("--config", required=True)
    parser.add_argument("--once", action="store_true")
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    runtime_builder: Callable[[Config], object] = (
        build_managed_collector_worker
    ),
    scheduler_factory=BackgroundScheduler,
    now_provider: Callable[[], datetime] | None = None,
) -> int:
    args = build_parser().parse_args(argv)
    clock = now_provider or _shanghai_now
    try:
        config = load_config(Path(args.config))
    except (KeyError, TypeError, ValueError, RuntimeError, OSError) as exc:
        print(f"config_error={type(exc).__name__}", file=sys.stderr)
        return 2
    if config.workers.collector_mode not in {"fake", "real"}:
        return 2
    try:
        worker = runtime_builder(config)
    except ValueError as exc:
        print(f"runtime_config_error={type(exc).__name__}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"runtime_start_error={type(exc).__name__}", file=sys.stderr)
        return 1

    start_now = clock()
    try:
        registered = worker.register_start(
            start_now, config.workers.heartbeat_seconds * 3
        )
    except Exception as exc:
        print(f"collector_register_error={type(exc).__name__}", file=sys.stderr)
        return 1
    if not registered:
        print("collector_register_error=duplicate_live_collector", file=sys.stderr)
        return 1

    try:
        worker.health_check_now()
        worker.heartbeat(clock())
    except Exception as exc:
        print(f"collector_health_error={type(exc).__name__}", file=sys.stderr)
        try:
            worker.mark_stopped(clock())
        except Exception:
            pass
        return 1

    stop_event = threading.Event()
    background = None
    previous_handlers: dict[int, object] = {}
    exit_code = 0
    try:
        background = scheduler_factory(timezone=APPLICATION_TIMEZONE)
        background.add_job(
            worker.heartbeat_now,
            "interval",
            seconds=config.workers.heartbeat_seconds,
            max_instances=1,
            coalesce=True,
        )
        background.add_job(
            worker.health_check_now,
            "interval",
            seconds=config.wechat.check_login_interval_seconds,
            max_instances=1,
            coalesce=True,
        )
        background.add_job(
            worker.recover_expired_now,
            "interval",
            seconds=config.workers.heartbeat_seconds,
            max_instances=1,
            coalesce=True,
        )
        previous_handlers = _install_signal_handlers(stop_event, worker)
        background.start()
        degraded_failures = 0
        while not stop_event.is_set():
            tick_result = worker.run_tick(clock())
            tick_status = getattr(tick_result, "status", None)
            degraded_failures = (
                degraded_failures + 1
                if tick_status == "degraded"
                else 0
            )
            if args.once:
                break
            stop_event.wait(
                _bounded_tick_delay(
                    tick_status,
                    degraded_failures,
                    config.workers.schedule_tick_seconds,
                )
            )
    except KeyboardInterrupt:
        stop_event.set()
        worker.request_shutdown()
    except Exception as exc:
        print(f"collector_run_error={type(exc).__name__}", file=sys.stderr)
        exit_code = 1
    finally:
        shutdown_errors: list[Exception] = []
        try:
            worker.request_shutdown()
        except Exception as exc:
            shutdown_errors.append(exc)
        try:
            worker.mark_stopping(clock())
        except Exception as exc:
            shutdown_errors.append(exc)
        if background is not None:
            try:
                background.shutdown(wait=False)
            except Exception as exc:
                shutdown_errors.append(exc)
        try:
            worker.mark_stopped(clock())
        except Exception as exc:
            shutdown_errors.append(exc)
        finally:
            _restore_signal_handlers(previous_handlers)
        if shutdown_errors:
            exit_code = 1
            for error in shutdown_errors:
                print(
                    f"collector_shutdown_error={type(error).__name__}",
                    file=sys.stderr,
                )
    return exit_code


def _install_signal_handlers(stop_event, worker) -> dict[int, object]:
    previous = {}

    def request_stop(signum, frame) -> None:
        stop_event.set()
        worker.request_shutdown()

    for signal_name in ("SIGINT", "SIGBREAK"):
        signum = getattr(signal, signal_name, None)
        if signum is None:
            continue
        previous[signum] = signal.getsignal(signum)
        signal.signal(signum, request_stop)
    return previous


def _restore_signal_handlers(previous: dict[int, object]) -> None:
    for signum, handler in previous.items():
        signal.signal(signum, handler)


def _shanghai_now() -> datetime:
    return datetime.now(_ZONE)


def _bounded_tick_delay(
    status: str | None,
    degraded_failures: int,
    base_seconds: int,
) -> int:
    if status != "degraded":
        return base_seconds
    exponent = min(max(degraded_failures, 1), 6)
    return min(60, base_seconds * (2**exponent))


if __name__ == "__main__":
    raise SystemExit(main())
