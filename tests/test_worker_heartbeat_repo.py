from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from app.storage.worker_heartbeat_repo import (
    MysqlWorkerHeartbeatRepo,
    WorkerHeartbeatRecord,
)


ZONE = ZoneInfo("Asia/Shanghai")
NOW = datetime(2026, 7, 10, 9, 25, tzinfo=ZONE)
START = datetime(2026, 7, 10, 8, 0, tzinfo=ZONE)


class Result:
    def __init__(self, *, scalar=None) -> None:
        self.scalar = scalar

    def scalar_one(self):
        return self.scalar


class Connection:
    def __init__(self, results) -> None:
        self.results = iter(results)
        self.executions = []
        self.events = []

    def execute(self, statement, params=None):
        self.executions.append((str(statement), params))
        self.events.append(("EXECUTE", str(statement)))
        result = next(self.results)
        if isinstance(result, BaseException):
            raise result
        return result

    def commit(self):
        self.events.append(("COMMIT", None))

    def rollback(self):
        self.events.append(("ROLLBACK", None))

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class Engine:
    def __init__(self, results) -> None:
        self.connection = Connection(results)
        self.begin_count = 0
        self.connect_count = 0

    def begin(self):
        self.begin_count += 1
        return self.connection

    def connect(self):
        self.connect_count += 1
        return self.connection


def heartbeat(**changes):
    values = {
        "worker_id": "collector-host-a-123",
        "worker_type": "collector",
        "hostname": "HOST-A",
        "process_id": 123,
        "version": "1.0.0",
        "status": "running",
        "last_heartbeat_at": NOW,
        "start_time": START,
        "last_error_summary": None,
    }
    values.update(changes)
    return WorkerHeartbeatRecord(**values)


def test_upsert_heartbeat_is_atomic_and_preserves_first_start_time() -> None:
    engine = Engine([Result()])

    MysqlWorkerHeartbeatRepo(engine).upsert_heartbeat(heartbeat())

    assert engine.begin_count == 1
    sql, params = engine.connection.executions[0]
    assert "INSERT INTO wechat_worker_heartbeat" in sql
    assert "ON DUPLICATE KEY UPDATE" in sql
    update_clause = sql.split("ON DUPLICATE KEY UPDATE", 1)[1]
    assert "start_time" not in update_clause
    assert params["last_heartbeat_at"] == datetime(2026, 7, 10, 9, 25)
    assert params["start_time"] == datetime(2026, 7, 10, 8, 0)


def test_upsert_heartbeat_sanitizes_last_error_summary() -> None:
    engine = Engine([Result()])
    MysqlWorkerHeartbeatRepo(engine).upsert_heartbeat(
        heartbeat(last_error_summary="13812345678 https://example.com/fail")
    )
    summary = engine.connection.executions[0][1]["last_error_summary"]
    assert "138****5678" in summary
    assert "https://" not in summary


def test_has_live_collector_uses_exists_ttl_hostname_status_and_exclusion() -> None:
    engine = Engine([Result(scalar=True)])

    live = MysqlWorkerHeartbeatRepo(engine).has_live_collector(
        "HOST-A", NOW, 30, exclude_worker_id="collector-self"
    )

    assert live is True
    sql, params = engine.connection.executions[0]
    assert "SELECT EXISTS" in sql
    assert "worker_type = 'collector'" in sql
    assert "hostname = :hostname" in sql
    assert "status IN ('starting', 'running', 'degraded', 'stopping')" in sql
    assert "last_heartbeat_at >= :cutoff" in sql
    assert "worker_id <> :exclude_worker_id" in sql
    assert params == {
        "hostname": "HOST-A",
        "cutoff": datetime(2026, 7, 10, 9, 24, 30),
        "exclude_worker_id": "collector-self",
    }


def test_has_live_collector_without_exclusion_omits_predicate() -> None:
    engine = Engine([Result(scalar=False)])
    assert (
        MysqlWorkerHeartbeatRepo(engine).has_live_collector("HOST-A", NOW, 30)
        is False
    )
    sql, params = engine.connection.executions[0]
    assert "exclude_worker_id" not in sql
    assert params == {
        "hostname": "HOST-A",
        "cutoff": datetime(2026, 7, 10, 9, 24, 30),
    }


def test_register_collector_start_commits_heartbeat_before_releasing_lock() -> None:
    engine = Engine(
        [
            Result(scalar=1),
            Result(scalar=False),
            Result(),
            Result(scalar=1),
        ]
    )
    repo = MysqlWorkerHeartbeatRepo(engine)

    registered = repo.register_collector_start(
        heartbeat(status="starting"), NOW, 30
    )

    assert registered is True
    assert engine.connect_count == 1
    sql = [item[0] for item in engine.connection.executions]
    assert "GET_LOCK" in sql[0]
    assert "worker_type = 'collector'" in sql[1]
    assert "worker_id <>" not in sql[1]
    assert "exclude_worker_id" not in engine.connection.executions[1][1]
    assert "INSERT INTO wechat_worker_heartbeat" in sql[2]
    assert "RELEASE_LOCK" in sql[3]
    assert "wechat_ui" not in engine.connection.executions[0][1]["lock_name"]
    events = engine.connection.events
    commit_index = events.index(("COMMIT", None))
    release_index = next(
        index
        for index, event in enumerate(events)
        if event[0] == "EXECUTE" and "RELEASE_LOCK" in event[1]
    )
    assert commit_index < release_index


def test_register_collector_start_rejects_live_peer_without_upsert() -> None:
    engine = Engine(
        [Result(scalar=1), Result(scalar=True), Result(scalar=1)]
    )

    registered = MysqlWorkerHeartbeatRepo(engine).register_collector_start(
        heartbeat(status="starting"), NOW, 30
    )

    assert registered is False
    statements = [sql for sql, _ in engine.connection.executions]
    assert not any("INSERT INTO" in sql for sql in statements)
    assert "RELEASE_LOCK" in statements[-1]
    commit_index = engine.connection.events.index(("COMMIT", None))
    release_index = next(
        index
        for index, event in enumerate(engine.connection.events)
        if event[0] == "EXECUTE" and "RELEASE_LOCK" in event[1]
    )
    assert commit_index < release_index


def test_register_collector_start_lock_failure_does_not_check_or_write() -> None:
    engine = Engine([Result(scalar=0)])
    assert (
        MysqlWorkerHeartbeatRepo(engine).register_collector_start(
            heartbeat(status="starting"), NOW, 30
        )
        is False
    )
    assert len(engine.connection.executions) == 1


def test_register_collector_start_rolls_back_then_releases_on_error() -> None:
    engine = Engine(
        [
            Result(scalar=1),
            RuntimeError("live check failed"),
            Result(scalar=1),
        ]
    )

    with pytest.raises(RuntimeError, match="live check"):
        MysqlWorkerHeartbeatRepo(engine).register_collector_start(
            heartbeat(status="starting"), NOW, 30
        )

    rollback_index = engine.connection.events.index(("ROLLBACK", None))
    release_index = next(
        index
        for index, event in enumerate(engine.connection.events)
        if event[0] == "EXECUTE" and "RELEASE_LOCK" in event[1]
    )
    assert rollback_index < release_index


@pytest.mark.parametrize(
    ("changes", "error"),
    [
        ({"worker_id": ""}, "worker_id"),
        ({"worker_type": "other"}, "worker_type"),
        ({"process_id": True}, "process_id"),
        ({"process_id": 0}, "process_id"),
        ({"status": "unknown"}, "status"),
        ({"last_heartbeat_at": datetime(2026, 7, 10, 9, 0)}, "last_heartbeat_at"),
        ({"start_time": datetime(2026, 7, 10, 1, 0, tzinfo=timezone.utc)}, "Asia/Shanghai"),
    ],
)
def test_upsert_rejects_invalid_record(changes, error) -> None:
    with pytest.raises((TypeError, ValueError), match=error):
        MysqlWorkerHeartbeatRepo(Engine([])).upsert_heartbeat(heartbeat(**changes))


@pytest.mark.parametrize("ttl", [0, True, 1.5])
def test_has_live_collector_rejects_invalid_ttl(ttl) -> None:
    with pytest.raises((TypeError, ValueError), match="ttl_seconds"):
        MysqlWorkerHeartbeatRepo(Engine([])).has_live_collector(
            "HOST-A", NOW, ttl
        )


def test_has_live_collector_rejects_wrong_timezone() -> None:
    with pytest.raises(ValueError, match="Asia/Shanghai"):
        MysqlWorkerHeartbeatRepo(Engine([])).has_live_collector(
            "HOST-A", datetime(2026, 7, 10, 1, 0, tzinfo=timezone.utc), 30
        )
