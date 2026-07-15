from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from app.rpa.desktop_probe import WechatHealth, WechatHealthStatus
from app.services.wechat_health_monitor import WechatHealthMonitor
from app.storage.collection_event_repo import NewCollectionEvent
from app.storage.wechat_health_repo import (
    MysqlWechatHealthRepo,
    NewWechatHealthCheck,
    WechatHealthRecord,
)


ZONE = ZoneInfo("Asia/Shanghai")
NOW = datetime(2026, 7, 10, 9, 30, tzinfo=ZONE)


class Result:
    def __init__(self, *, rows=None, lastrowid=None) -> None:
        self.rows = rows or []
        self.lastrowid = lastrowid

    def mappings(self):
        return self

    def first(self):
        return self.rows[0] if self.rows else None


class Connection:
    def __init__(self, results) -> None:
        self.results = iter(results)
        self.executions = []

    def execute(self, statement, params=None):
        self.executions.append((str(statement), params))
        return next(self.results)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class Engine:
    def __init__(self, results) -> None:
        self.connection = Connection(results)
        self.begin_count = 0

    def begin(self):
        self.begin_count += 1
        return self.connection


class FakeHealthRepo:
    def __init__(self, records=None) -> None:
        self.records = list(records or [])
        self.inserted = []

    def insert_check(self, check: NewWechatHealthCheck) -> WechatHealthRecord:
        self.inserted.append(check)
        latest = self.latest_check(check.hostname)
        failures = (
            0
            if check.status is WechatHealthStatus.OK
            else (0 if latest is None else latest.consecutive_failure_count) + 1
        )
        saved = WechatHealthRecord(
            id=len(self.records) + 1,
            worker_id=check.worker_id,
            hostname=check.hostname,
            status=check.status,
            detected_version=check.detected_version,
            consecutive_failure_count=failures,
            message=check.message,
            checked_at=check.checked_at,
        )
        self.records.append(saved)
        return saved

    def latest_check(self, hostname: str) -> WechatHealthRecord | None:
        matches = [record for record in self.records if record.hostname == hostname]
        return None if not matches else matches[-1]

    def consecutive_failure_count(self, hostname: str) -> int:
        latest = self.latest_check(hostname)
        return 0 if latest is None else latest.consecutive_failure_count


class DesktopProbe:
    def __init__(self, order, result=None, error=None) -> None:
        self.order = order
        self.result = result or WechatHealth(
            status=WechatHealthStatus.OK,
            message="desktop ok",
            version="4.1.8.107",
        )
        self.error = error

    def check(self) -> WechatHealth:
        self.order.append("desktop")
        if self.error is not None:
            raise self.error
        return self.result


class BooleanProbe:
    def __init__(self, name, order, result=True, error=None) -> None:
        self.name = name
        self.order = order
        self.result = result
        self.error = error
        self.calls = 0

    def check(self) -> bool:
        self.calls += 1
        self.order.append(self.name)
        if self.error is not None:
            raise self.error
        return self.result


class UiLockRepo:
    def __init__(self, owner=None, expire_time=None) -> None:
        self.owner = owner
        self.expire_time = expire_time
        self.calls = []

    def current_owner(self, lock_name: str, now=None) -> str | None:
        self.calls.append((lock_name, now))
        if (
            self.expire_time is not None
            and now is not None
            and self.expire_time <= now
        ):
            return None
        return self.owner


class EventRepo:
    def __init__(self) -> None:
        self.events = []

    def append_event(self, event: NewCollectionEvent) -> int:
        self.events.append(event)
        return len(self.events)


def health_record(**changes) -> WechatHealthRecord:
    values = {
        "id": 1,
        "worker_id": "collector-1",
        "hostname": "wechat-host",
        "status": WechatHealthStatus.OK,
        "detected_version": "4.1.8.107",
        "consecutive_failure_count": 0,
        "message": "healthy",
        "checked_at": NOW - timedelta(minutes=1),
    }
    values.update(changes)
    return WechatHealthRecord(**values)


def build_monitor(
    *, desktop_result=None, owner=None, lock_expire_time=None, records=None
):
    order = []
    repo = FakeHealthRepo(records)
    event_repo = EventRepo()
    window_probe = BooleanProbe("window", order)
    login_probe = BooleanProbe("login", order)
    rpa_probe = BooleanProbe("rpa", order)
    monitor = WechatHealthMonitor(
        desktop_probe=DesktopProbe(order, desktop_result),
        window_probe=window_probe,
        login_probe=login_probe,
        rpa_probe=rpa_probe,
        ui_lock_repo=UiLockRepo(owner, lock_expire_time),
        health_repo=repo,
        event_repo=event_repo,
        hostname="wechat-host",
        worker_id="collector-1",
        check_login_interval_seconds=300,
    )
    return monitor, repo, event_repo, order, window_probe, login_probe, rpa_probe


@pytest.mark.parametrize(
    "desktop_status",
    [WechatHealthStatus.NOT_RUNNING, WechatHealthStatus.VERSION_MISMATCH],
)
def test_shallow_failure_is_saved_and_short_circuits_deep_checks(desktop_status) -> None:
    monitor, repo, _, order, window, login, rpa = build_monitor(
        desktop_result=WechatHealth(
            status=desktop_status,
            message="shallow failed",
            version="4.1.11.1" if desktop_status is WechatHealthStatus.VERSION_MISMATCH else None,
        )
    )

    result = monitor.run_check(NOW)

    assert result.status is desktop_status
    assert result.deep_check_deferred is False
    assert order == ["desktop"]
    assert window.calls == login.calls == rpa.calls == 0
    assert len(repo.inserted) == 1
    assert monitor.can_collect(NOW) is False


@pytest.mark.parametrize(
    ("failed_probe", "expected_status", "expected_order"),
    [
        ("rpa", WechatHealthStatus.RPA_UNAVAILABLE, ["desktop", "rpa"]),
        ("window", WechatHealthStatus.WINDOW_UNAVAILABLE, ["desktop", "rpa", "window"]),
        ("login", WechatHealthStatus.NOT_LOGGED_IN, ["desktop", "rpa", "window", "login"]),
        (None, WechatHealthStatus.OK, ["desktop", "rpa", "window", "login"]),
    ],
)
def test_deep_checks_run_in_order_and_cover_remaining_health_states(
    failed_probe, expected_status, expected_order
) -> None:
    monitor, _, _, order, window, login, rpa = build_monitor()
    probes = {"window": window, "login": login, "rpa": rpa}
    if failed_probe is not None:
        probes[failed_probe].result = False

    result = monitor.run_check(NOW)

    assert result.status is expected_status
    assert result.deep_check_deferred is False
    assert order == expected_order
    assert monitor.latest_status is expected_status
    assert monitor.can_collect(NOW) is (expected_status is WechatHealthStatus.OK)


def test_ui_busy_defers_all_deep_checks_without_refreshing_full_health() -> None:
    previous = health_record(consecutive_failure_count=2)
    monitor, repo, event_repo, order, window, login, rpa = build_monitor(
        owner="group", records=[previous]
    )

    result = monitor.run_check(NOW)

    assert result.status is WechatHealthStatus.OK
    assert result.checked_at == previous.checked_at
    assert result.consecutive_failure_count == 2
    assert result.deep_check_deferred is True
    assert order == ["desktop"]
    assert window.calls == login.calls == rpa.calls == 0
    assert repo.inserted == []
    assert len(repo.records) == 1
    assert monitor.ui_lock_repo.calls == [("wechat_ui", NOW)]
    assert len(event_repo.events) == 1
    event = event_repo.events[0]
    assert event.event_type == "wechat_health_deep_check_deferred"
    assert event.actor_type == "worker"
    assert "group" not in event.message


def test_ui_busy_without_history_fails_closed_and_does_not_fake_ok() -> None:
    monitor, repo, event_repo, _, _, _, _ = build_monitor(owner="article")

    result = monitor.run_check(NOW)

    assert result.status is WechatHealthStatus.RPA_UNAVAILABLE
    assert result.checked_at == NOW
    assert result.deep_check_deferred is True
    assert repo.records == []
    assert len(event_repo.events) == 1
    assert monitor.can_collect(NOW) is False


def test_deferred_check_does_not_extend_stale_ok_freshness() -> None:
    stale = health_record(checked_at=NOW - timedelta(seconds=601))
    monitor, repo, _, _, _, _, _ = build_monitor(owner="group", records=[stale])

    deferred = monitor.run_check(NOW)

    assert deferred.checked_at == stale.checked_at
    assert repo.records == [stale]
    assert monitor.can_collect(NOW) is False


def test_expired_ui_lock_runs_full_check_and_refreshes_stale_ok() -> None:
    stale = health_record(checked_at=NOW - timedelta(seconds=601))
    monitor, repo, _, order, _, _, _ = build_monitor(
        owner="group",
        lock_expire_time=NOW,
        records=[stale],
    )

    refreshed = monitor.run_check(NOW)

    assert refreshed.status is WechatHealthStatus.OK
    assert refreshed.checked_at == NOW
    assert refreshed.deep_check_deferred is False
    assert order == ["desktop", "rpa", "window", "login"]
    assert len(repo.inserted) == 1
    assert monitor.can_collect(NOW) is True


@pytest.mark.parametrize(
    ("checked_at", "expected"),
    [
        (NOW - timedelta(seconds=600), True),
        (NOW - timedelta(seconds=601), False),
        (NOW + timedelta(microseconds=1), False),
    ],
)
def test_collection_gate_uses_two_interval_inclusive_boundary(checked_at, expected) -> None:
    monitor, _, _, _, _, _, _ = build_monitor(records=[health_record(checked_at=checked_at)])
    assert monitor.can_collect(NOW) is expected


def test_recovered_health_resets_failure_count_and_reenables_collection() -> None:
    failed = health_record(
        status=WechatHealthStatus.NOT_LOGGED_IN,
        consecutive_failure_count=3,
    )
    monitor, _, _, _, _, _, _ = build_monitor(records=[failed])

    recovered = monitor.run_check(NOW)

    assert recovered.status is WechatHealthStatus.OK
    assert recovered.consecutive_failure_count == 0
    assert monitor.can_collect(NOW) is True


def test_probe_exception_fails_closed_without_leaking_exception_text() -> None:
    monitor, _, _, _, _, login, _ = build_monitor()
    login.error = RuntimeError(
        "<b>raw</b> 13812345678 wxid_secret123 https://mp.weixin.qq.com/s/secret"
    )

    result = monitor.run_check(NOW)

    assert result.status is WechatHealthStatus.NOT_LOGGED_IN
    assert "raw" not in result.message
    assert "13812345678" not in result.message
    assert "wxid_secret123" not in result.message
    assert "https://" not in result.message


@pytest.mark.parametrize("now", [datetime(2026, 7, 10, 9, 30), datetime(2026, 7, 10, 1, 30, tzinfo=timezone.utc)])
def test_monitor_requires_exact_shanghai_zoneinfo(now) -> None:
    monitor, _, _, _, _, _, _ = build_monitor()
    with pytest.raises(ValueError, match="Asia/Shanghai"):
        monitor.run_check(now)
    with pytest.raises(ValueError, match="Asia/Shanghai"):
        monitor.can_collect(now)


def new_check(**changes) -> NewWechatHealthCheck:
    values = {
        "worker_id": "collector-1",
        "hostname": "wechat-host",
        "status": WechatHealthStatus.NOT_LOGGED_IN,
        "detected_version": "4.1.8.107",
        "message": "<b>失败</b> 13812345678 wxid_secret123 https://mp.weixin.qq.com/s/secret",
        "checked_at": NOW,
    }
    values.update(changes)
    return NewWechatHealthCheck(**values)


def db_row(**changes):
    values = {
        "id": 7,
        "worker_id": "collector-1",
        "hostname": "wechat-host",
        "status": "not_logged_in",
        "detected_version": "4.1.8.107",
        "consecutive_failure_count": 2,
        "message": "safe",
        "checked_at": datetime(2026, 7, 10, 9, 20),
    }
    values.update(changes)
    return values


def test_repo_insert_locks_latest_host_row_and_increments_failure_count() -> None:
    engine = Engine([Result(rows=[db_row()]), Result(lastrowid=8)])

    saved = MysqlWechatHealthRepo(engine).insert_check(new_check())

    assert saved.id == 8
    assert saved.consecutive_failure_count == 3
    assert saved.checked_at == NOW
    assert isinstance(saved.checked_at.tzinfo, ZoneInfo)
    assert engine.begin_count == 1
    select_sql, select_params = engine.connection.executions[0]
    assert "hostname = :hostname" in select_sql
    assert "checked_at DESC, id DESC" in select_sql
    assert "FOR UPDATE" in select_sql
    assert select_params == {"hostname": "wechat-host"}
    insert_sql, insert_params = engine.connection.executions[1]
    assert "INSERT INTO wechat_client_health_check" in insert_sql
    assert insert_params["consecutive_failure_count"] == 3
    assert insert_params["checked_at"] == datetime(2026, 7, 10, 9, 30)
    assert "<" not in insert_params["message"]
    assert "13812345678" not in insert_params["message"]
    assert "wxid_secret123" not in insert_params["message"]
    assert "https://" not in insert_params["message"]


def test_repo_rejects_older_check_than_latest_without_insert() -> None:
    engine = Engine([Result(rows=[db_row(checked_at=NOW.replace(tzinfo=None))])])

    with pytest.raises(ValueError, match="checked_at"):
        MysqlWechatHealthRepo(engine).insert_check(
            new_check(checked_at=NOW - timedelta(seconds=1))
        )

    assert len(engine.connection.executions) == 1


def test_repo_allows_equal_checked_at_and_uses_next_id() -> None:
    engine = Engine(
        [
            Result(rows=[db_row(checked_at=NOW.replace(tzinfo=None))]),
            Result(lastrowid=8),
        ]
    )

    saved = MysqlWechatHealthRepo(engine).insert_check(new_check(checked_at=NOW))

    assert saved.id == 8
    assert saved.checked_at == NOW
    assert saved.consecutive_failure_count == 3


def test_repo_allows_newer_checked_at() -> None:
    engine = Engine(
        [
            Result(
                rows=[
                    db_row(
                        checked_at=(NOW - timedelta(seconds=1)).replace(
                            tzinfo=None
                        )
                    )
                ]
            ),
            Result(lastrowid=8),
        ]
    )

    saved = MysqlWechatHealthRepo(engine).insert_check(new_check(checked_at=NOW))

    assert saved.checked_at == NOW


def test_repo_ok_resets_failure_count() -> None:
    engine = Engine([Result(rows=[db_row(consecutive_failure_count=9)]), Result(lastrowid=9)])
    saved = MysqlWechatHealthRepo(engine).insert_check(
        new_check(status=WechatHealthStatus.OK, message="healthy")
    )
    assert saved.consecutive_failure_count == 0


def test_repo_sanitizes_detected_version_on_write_and_return() -> None:
    engine = Engine([Result(rows=[]), Result(lastrowid=10)])
    raw_version = "<b>4.1.8.107</b>\x00"

    saved = MysqlWechatHealthRepo(engine).insert_check(
        new_check(detected_version=raw_version)
    )

    persisted = engine.connection.executions[1][1]["detected_version"]
    assert persisted == saved.detected_version
    assert "<" not in persisted
    assert ">" not in persisted
    assert "\x00" not in persisted
    assert "4.1.8.107" in persisted


def test_repo_latest_uses_stable_order_and_restores_shanghai_zoneinfo() -> None:
    engine = Engine(
        [
            Result(
                rows=[
                    db_row(
                        status="ok",
                        consecutive_failure_count=0,
                        checked_at=datetime(2026, 7, 10, 1, 20, tzinfo=timezone.utc),
                    )
                ]
            )
        ]
    )

    latest = MysqlWechatHealthRepo(engine).latest_check("wechat-host")

    assert latest is not None
    assert latest.status is WechatHealthStatus.OK
    assert latest.checked_at == datetime(2026, 7, 10, 9, 20, tzinfo=ZONE)
    assert isinstance(latest.checked_at.tzinfo, ZoneInfo)
    sql, params = engine.connection.executions[0]
    assert "checked_at DESC, id DESC" in sql
    assert "LIMIT 1" in sql
    assert "FOR UPDATE" not in sql
    assert params == {"hostname": "wechat-host"}


def test_repo_consecutive_failure_count_uses_latest_full_check() -> None:
    engine = Engine([Result(rows=[{"consecutive_failure_count": 4}])])
    assert MysqlWechatHealthRepo(engine).consecutive_failure_count("wechat-host") == 4
    sql, _ = engine.connection.executions[0]
    assert "checked_at DESC, id DESC" in sql
    assert "LIMIT 1" in sql


@pytest.mark.parametrize(
    "changes",
    [
        {"status": "unknown"},
        {"hostname": ""},
        {"hostname": "h" * 256},
        {"worker_id": "w" * 101},
        {"detected_version": "v" * 101},
        {"checked_at": datetime(2026, 7, 10, 9, 30)},
        {"checked_at": datetime(2026, 7, 10, 1, 30, tzinfo=timezone.utc)},
    ],
)
def test_repo_rejects_invalid_new_check(changes) -> None:
    with pytest.raises((TypeError, ValueError)):
        MysqlWechatHealthRepo(Engine([])).insert_check(new_check(**changes))


def test_repo_rejects_boolean_failure_count_from_database() -> None:
    engine = Engine([Result(rows=[db_row(consecutive_failure_count=True)])])
    with pytest.raises(ValueError, match="consecutive_failure_count"):
        MysqlWechatHealthRepo(engine).latest_check("wechat-host")


def test_repo_rejects_oversized_message_from_database() -> None:
    engine = Engine([Result(rows=[db_row(message="x" * 1001)])])
    with pytest.raises(ValueError, match="message"):
        MysqlWechatHealthRepo(engine).latest_check("wechat-host")
