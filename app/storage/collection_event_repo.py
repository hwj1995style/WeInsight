from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from html.parser import HTMLParser
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.domain.collection_jobs import APPLICATION_TIMEZONE
from app.domain.desensitize import mask_phone, mask_wechat_id


_ZONE = ZoneInfo(APPLICATION_TIMEZONE)
_URL_PATTERN = re.compile(
    r"(?:https?://[^\s<>\"']+|(?:www\.)?mp\.weixin\.qq\.com(?:/[^\s<>\"']*)?)",
    re.IGNORECASE,
)
_LEVELS = frozenset({"debug", "info", "warning", "error"})
_ACTOR_TYPES = frozenset({"admin", "system", "worker"})


@dataclass(frozen=True, slots=True)
class NewCollectionEvent:
    job_id: int | None
    run_id: int | None
    target_run_id: int | None
    worker_id: str | None
    level: str
    event_type: str
    stage: str | None
    message: str
    metrics_json: str
    actor_type: str
    actor_name: str


@dataclass(frozen=True, slots=True)
class CollectionEvent:
    id: int
    job_id: int | None
    run_id: int | None
    target_run_id: int | None
    level: str
    event_type: str
    stage: str | None
    message: str
    metrics_json: str
    actor_type: str
    actor_name: str
    create_time: datetime


def sanitize_output(value: str, *, maximum: int = 1000) -> str:
    if not isinstance(value, str):
        raise TypeError("message must be a string")
    parser = _PlainTextExtractor()
    parser.feed(value)
    parser.close()
    plain = "".join(parser.parts).replace("<", "＜").replace(">", "＞")
    without_controls = "".join(
        " " if unicodedata.category(character) == "Cc" else character
        for character in plain
    )
    without_urls = _URL_PATTERN.sub("[链接已脱敏]", without_controls)
    return mask_wechat_id(mask_phone(without_urls))[:maximum]


class _PlainTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


class MysqlCollectionEventRepo:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def append_event(self, event: NewCollectionEvent) -> int:
        _validate_new_event(event)
        params = {
            "job_id": event.job_id,
            "run_id": event.run_id,
            "target_run_id": event.target_run_id,
            "worker_id": event.worker_id,
            "level": event.level,
            "event_type": event.event_type,
            "stage": event.stage,
            "message": sanitize_output(event.message),
            "metrics_json": _canonical_metrics(event.metrics_json),
            "actor_type": event.actor_type,
            "actor_name": event.actor_name,
        }
        with self.engine.begin() as connection:
            result = connection.execute(_INSERT_EVENT, params)
            return int(result.lastrowid)

    def list_events(
        self,
        run_id: int | None,
        after_id: int | None,
        limit: int,
    ) -> list[CollectionEvent]:
        _optional_identity(run_id, "run_id")
        _optional_identity(after_id, "after_id")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500")
        conditions: list[str] = []
        params: dict[str, Any] = {"limit": limit}
        if run_id is not None:
            conditions.append("run_id = :run_id")
            params["run_id"] = run_id
        if after_id is not None:
            conditions.append("id > :after_id")
            params["after_id"] = after_id
        where = "" if not conditions else "WHERE " + " AND ".join(conditions)
        statement = text(
            f"""
            SELECT
                id, job_id, run_id, target_run_id, level, event_type,
                stage, message, metrics_json, actor_type, actor_name,
                create_time
            FROM wechat_collection_job_event
            {where}
            ORDER BY id ASC
            LIMIT :limit
            """
        )
        with self.engine.begin() as connection:
            rows = connection.execute(statement, params).mappings().all()
        return [_event_from_row(row) for row in rows]


def _validate_new_event(event: object) -> None:
    if not isinstance(event, NewCollectionEvent):
        raise TypeError("event must be NewCollectionEvent")
    _optional_identity(event.job_id, "job_id")
    _optional_identity(event.run_id, "run_id")
    _optional_identity(event.target_run_id, "target_run_id")
    _optional_text(event.worker_id, "worker_id", 100)
    if event.level not in _LEVELS:
        raise ValueError("level is invalid")
    _required_text(event.event_type, "event_type", 100)
    _optional_text(event.stage, "stage", 50)
    if not isinstance(event.message, str):
        raise TypeError("message must be a string")
    _canonical_metrics(event.metrics_json)
    if event.actor_type not in _ACTOR_TYPES:
        raise ValueError("actor_type is invalid")
    _required_text(event.actor_name, "actor_name", 100)


def _canonical_metrics(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError("metrics_json must be a string")
    try:
        decoded = json.loads(value, parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("metrics_json must be a JSON object") from exc
    if not isinstance(decoded, dict):
        raise ValueError("metrics_json must be a JSON object")
    try:
        return json.dumps(
            decoded,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("metrics_json must contain JSON values") from exc


def _event_from_row(row) -> CollectionEvent:
    return CollectionEvent(
        id=int(row["id"]),
        job_id=_optional_int(row.get("job_id")),
        run_id=_optional_int(row.get("run_id")),
        target_run_id=_optional_int(row.get("target_run_id")),
        level=str(row["level"]),
        event_type=str(row["event_type"]),
        stage=None if row.get("stage") is None else str(row["stage"]),
        message=str(row["message"]),
        metrics_json="{}" if row.get("metrics_json") is None else str(row["metrics_json"]),
        actor_type=str(row["actor_type"]),
        actor_name="" if row.get("actor_name") is None else str(row["actor_name"]),
        create_time=_db_datetime(row["create_time"]),
    )


def _optional_int(value: object) -> int | None:
    return None if value is None else int(value)


def _optional_identity(value: object, field: str) -> None:
    if value is not None and (
        isinstance(value, bool) or not isinstance(value, int) or value < 1
    ):
        raise ValueError(f"{field} must be a positive integer or None")


def _required_text(value: object, field: str, maximum: int) -> None:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{field} must be a non-empty trimmed string")
    if len(value) > maximum:
        raise ValueError(f"{field} must be at most {maximum} characters")


def _optional_text(value: object, field: str, maximum: int) -> None:
    if value is None:
        return
    _required_text(value, field, maximum)


def _db_datetime(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError("database datetime value must be datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=_ZONE)
    return value.astimezone(_ZONE)


_INSERT_EVENT = text(
    """
    INSERT INTO wechat_collection_job_event (
        job_id, run_id, target_run_id, worker_id, level, event_type,
        stage, message, metrics_json, actor_type, actor_name
    ) VALUES (
        :job_id, :run_id, :target_run_id, :worker_id, :level, :event_type,
        :stage, :message, :metrics_json, :actor_type, :actor_name
    )
    """
)
