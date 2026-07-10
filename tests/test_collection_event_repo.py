from __future__ import annotations

import json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from app.storage.collection_event_repo import (
    MysqlCollectionEventRepo,
    NewCollectionEvent,
    _canonical_metrics,
)


ZONE = ZoneInfo("Asia/Shanghai")


class Result:
    def __init__(self, *, rows=None, lastrowid=None) -> None:
        self.rows = rows or []
        self.lastrowid = lastrowid

    def mappings(self):
        return self

    def all(self):
        return self.rows


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


def new_event(**changes):
    values = {
        "job_id": 7,
        "run_id": 41,
        "target_run_id": 501,
        "worker_id": "collector-1",
        "level": "error",
        "event_type": "target_failed",
        "stage": "navigate",
        "message": (
            "手机号13812345678 微信wxid_secret123 详情"
            "https://mp.weixin.qq.com/s/secret"
        ),
        "metrics_json": '{"insert_count":2,"read_count":3}',
        "actor_type": "worker",
        "actor_name": "collector-1",
    }
    values.update(changes)
    return NewCollectionEvent(**values)


def test_append_event_desensitizes_urls_and_canonicalizes_metrics() -> None:
    engine = Engine([Result(lastrowid=88)])

    event_id = MysqlCollectionEventRepo(engine).append_event(new_event())

    assert event_id == 88
    assert engine.begin_count == 1
    sql, params = engine.connection.executions[0]
    assert "wechat_collection_job_event" in sql
    assert "138****5678" in params["message"]
    assert "wxid_secret123" not in params["message"]
    assert "https://" not in params["message"]
    assert "mp.weixin.qq.com" not in params["message"]
    assert params["metrics_json"] == '{"insert_count":2,"read_count":3}'


def test_append_event_truncates_sanitized_message_to_column_limit() -> None:
    engine = Engine([Result(lastrowid=89)])
    MysqlCollectionEventRepo(engine).append_event(new_event(message="安" * 1200))
    assert len(engine.connection.executions[0][1]["message"]) == 1000


def test_append_event_masks_bare_wechat_article_url() -> None:
    engine = Engine([Result(lastrowid=90)])
    MysqlCollectionEventRepo(engine).append_event(
        new_event(message="见 mp.weixin.qq.com/s/secret")
    )
    message = engine.connection.executions[0][1]["message"]
    assert "mp.weixin.qq.com" not in message
    assert "secret" not in message
    assert "qq.com" not in message
    assert "[链接已脱敏]" in message


def test_append_event_stores_plain_text_without_html_or_control_characters() -> None:
    engine = Engine([Result(lastrowid=91)])
    MysqlCollectionEventRepo(engine).append_event(
        new_event(message="<script>alert(1)</script> &lt;b&gt;safe&lt;/b&gt;\x00\x1f")
    )
    message = engine.connection.executions[0][1]["message"]
    assert "<" not in message
    assert ">" not in message
    assert "&lt;" not in message
    assert "\x00" not in message
    assert "\x1f" not in message
    assert "alert(1)" in message
    assert "safe" in message


@pytest.mark.parametrize(
    "metrics",
    ["[]", '"text"', "null", "not-json", '{"x":NaN}'],
)
def test_append_event_rejects_non_object_or_nonstandard_metrics(metrics) -> None:
    with pytest.raises(ValueError, match="metrics_json"):
        MysqlCollectionEventRepo(Engine([])).append_event(
            new_event(metrics_json=metrics)
        )


@pytest.mark.parametrize(
    ("value", "expected_bytes"),
    [
        ("a" * 65_527, 65_535),
        ("汉" * 21_842, 65_534),
    ],
    ids=("ascii", "utf8-chinese"),
)
def test_canonical_metrics_accepts_mysql_text_utf8_boundary(
    value, expected_bytes
) -> None:
    source = json.dumps(
        {"x": value}, ensure_ascii=False, separators=(",", ":")
    )
    canonical = _canonical_metrics(source)
    assert len(canonical.encode("utf-8")) == expected_bytes


@pytest.mark.parametrize(
    "value",
    ["a" * 65_528, "汉" * 21_843],
    ids=("ascii", "utf8-chinese"),
)
def test_canonical_metrics_rejects_mysql_text_utf8_overflow(value) -> None:
    source = json.dumps(
        {"x": value}, ensure_ascii=False, separators=(",", ":")
    )
    with pytest.raises(ValueError, match="65535.*UTF-8"):
        _canonical_metrics(source)


@pytest.mark.parametrize("field", ["job_id", "run_id", "target_run_id"])
def test_append_event_rejects_boolean_ids(field) -> None:
    with pytest.raises(ValueError, match=field):
        MysqlCollectionEventRepo(Engine([])).append_event(
            new_event(**{field: True})
        )


def test_list_events_uses_bound_stable_incremental_page() -> None:
    engine = Engine(
        [
            Result(
                rows=[
                    {
                        "id": 12,
                        "job_id": 7,
                        "run_id": 41,
                        "target_run_id": 501,
                        "level": "info",
                        "event_type": "target_finished",
                        "stage": None,
                        "message": "完成",
                        "metrics_json": "{}",
                        "actor_type": "worker",
                        "actor_name": "collector-1",
                        "create_time": datetime(2026, 7, 10, 9, 30),
                    }
                ]
            )
        ]
    )

    events = MysqlCollectionEventRepo(engine).list_events(41, 10, 20)

    assert events[0].create_time == datetime(2026, 7, 10, 9, 30, tzinfo=ZONE)
    sql, params = engine.connection.executions[0]
    assert "run_id = :run_id" in sql
    assert "id > :after_id" in sql
    assert "ORDER BY id ASC" in sql
    assert "LIMIT :limit" in sql
    assert params == {"run_id": 41, "after_id": 10, "limit": 20}


def test_list_events_none_run_means_all_runs_not_null_run_only() -> None:
    engine = Engine([Result(rows=[])])
    assert MysqlCollectionEventRepo(engine).list_events(None, None, 50) == []
    sql, params = engine.connection.executions[0]
    assert "run_id =" not in sql
    assert "run_id IS NULL" not in sql
    assert "id >" not in sql
    assert params == {"limit": 50}


@pytest.mark.parametrize("limit", [0, 501, True])
def test_list_events_rejects_invalid_limit(limit) -> None:
    with pytest.raises(ValueError, match="limit"):
        MysqlCollectionEventRepo(Engine([])).list_events(None, None, limit)


def test_list_events_requires_real_shanghai_zone_from_database() -> None:
    aware_engine = Engine(
        [
            Result(
                rows=[
                    {
                        "id": 12,
                        "job_id": None,
                        "run_id": None,
                        "target_run_id": None,
                        "level": "info",
                        "event_type": "worker_started",
                        "stage": None,
                        "message": "started",
                        "metrics_json": "{}",
                        "actor_type": "system",
                        "actor_name": "system",
                        "create_time": datetime(2026, 7, 10, 1, 30, tzinfo=timezone.utc),
                    }
                ]
            )
        ]
    )
    event = MysqlCollectionEventRepo(aware_engine).list_events(None, None, 1)[0]
    assert event.create_time == datetime(2026, 7, 10, 9, 30, tzinfo=ZONE)
    assert isinstance(event.create_time.tzinfo, ZoneInfo)
