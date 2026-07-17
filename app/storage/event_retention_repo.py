from __future__ import annotations

import calendar
from datetime import datetime, timedelta

from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.services.event_retention_service import EventCleanupResult, EventRetentionPolicy


AUDIT_EVENTS = (
    "job_created", "job_started", "job_updated", "job_stop_requested", "job_deleted", "werss_catalog_sync_changed",
    "werss_authorization_settings_changed", "werss_authorization_settings_failed",
    "werss_authorization_test_succeeded", "werss_authorization_test_failed",
)
VERBOSE_EVENTS = ("collection_target_started", "collection_target_finished", "collection_run_claimed")
_LOCK_NAME = "weinsight_event_retention_v1"


class MysqlEventRetentionRepo:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def cleanup(self, now: datetime, policy: EventRetentionPolicy, *, dry_run: bool) -> EventCleanupResult:
        cutoffs = {
            "verbose": now - timedelta(days=policy.verbose_days),
            "info": now - timedelta(days=policy.info_days),
            "warning_error": _subtract_months(now, policy.warning_error_months),
            "audit": _subtract_months(now, policy.audit_months),
        }
        with self.engine.connect() as connection:
            acquired = int(connection.execute(text("SELECT GET_LOCK(:name, 0)"), {"name": _LOCK_NAME}).scalar() or 0) == 1
            if not acquired:
                return EventCleanupResult(False, dry_run, {})
            try:
                counts = {
                    name: self._apply_rule(connection, name, cutoff, policy, dry_run)
                    for name, cutoff in cutoffs.items()
                }
                return EventCleanupResult(True, dry_run, counts)
            finally:
                connection.execute(text("SELECT RELEASE_LOCK(:name)"), {"name": _LOCK_NAME})

    def _apply_rule(self, connection, name: str, cutoff: datetime, policy: EventRetentionPolicy, dry_run: bool) -> int:
        condition, params = _rule(name, cutoff)
        if dry_run:
            return int(connection.execute(text(f"SELECT COUNT(*) FROM wechat_collection_job_event WHERE {condition}"), params).scalar_one())
        deleted = 0
        for _ in range(policy.max_batches):
            result = connection.execute(text(f"""
                DELETE FROM wechat_collection_job_event
                WHERE id IN (
                    SELECT id FROM (
                        SELECT id FROM wechat_collection_job_event
                        WHERE {condition}
                        ORDER BY id LIMIT :batch_size
                    ) expired
                )
            """), {**params, "batch_size": policy.batch_size})
            connection.commit()
            count = int(result.rowcount or 0)
            deleted += count
            if count < policy.batch_size:
                break
        return deleted


def _rule(name: str, cutoff: datetime) -> tuple[str, dict[str, object]]:
    params: dict[str, object] = {"cutoff": cutoff.replace(tzinfo=None)}
    audit = ", ".join(f"'{item}'" for item in AUDIT_EVENTS)
    verbose = ", ".join(f"'{item}'" for item in VERBOSE_EVENTS)
    if name == "verbose":
        return f"event_type IN ({verbose}) AND level = 'info' AND create_time < :cutoff", params
    if name == "info":
        return f"level IN ('debug','info') AND event_type NOT IN ({audit}) AND event_type NOT IN ({verbose}) AND create_time < :cutoff", params
    if name == "warning_error":
        return f"level IN ('warning','error') AND event_type NOT IN ({audit}) AND create_time < :cutoff", params
    if name == "audit":
        return f"event_type IN ({audit}) AND create_time < :cutoff", params
    raise ValueError("unknown retention rule")


def _subtract_months(value: datetime, months: int) -> datetime:
    index = value.year * 12 + value.month - 1 - months
    year, month0 = divmod(index, 12)
    month = month0 + 1
    return value.replace(year=year, month=month, day=min(value.day, calendar.monthrange(year, month)[1]))
