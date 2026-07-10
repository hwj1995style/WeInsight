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
