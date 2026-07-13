from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from urllib.parse import quote

from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.integrations.werss_catalog import WeRSSCatalogItem


_LOCK_NAME = "weinsight:werss-catalog-sync"
_EXCLUDED_NAME = "一箱蛋"


class WeRSSCatalogSyncBusyError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("werss_catalog_sync_busy")


@dataclass(frozen=True)
class CatalogSyncSummary:
    created: int = 0
    updated: int = 0
    disabled: int = 0
    missing: int = 0
    restored: int = 0
    excluded: int = 0
    conflicts: int = 0


@dataclass(frozen=True)
class CatalogRow:
    id: int
    account_name: str
    feed_url: str | None
    werss_source_id: str | None
    upstream_status: str
    upstream_last_seen_at: datetime | None
    upstream_missing_at: datetime | None


@dataclass(frozen=True)
class CatalogChange:
    row_id: int
    name: str
    feed_url: str
    source_id: str
    status: str
    last_seen_at: datetime | None
    missing_at: datetime | None


@dataclass(frozen=True)
class CatalogInsert:
    name: str
    feed_url: str
    source_id: str
    status: str
    last_seen_at: datetime


@dataclass(frozen=True)
class CatalogSyncPlan:
    changes: tuple[CatalogChange, ...]
    inserts: tuple[CatalogInsert, ...]
    summary: CatalogSyncSummary


def fixed_feed_url(source_id: str) -> str:
    return f"http://127.0.0.1:8001/feed/{quote(source_id, safe='')}.atom"


def plan_catalog_sync(
    rows: tuple[CatalogRow, ...],
    items: tuple[WeRSSCatalogItem, ...],
    excluded_items: tuple[WeRSSCatalogItem, ...],
    now: datetime,
) -> CatalogSyncPlan:
    by_id = {row.werss_source_id: row for row in rows if row.werss_source_id}
    by_feed = {row.feed_url: row for row in rows if row.feed_url}
    by_name = {row.account_name: row for row in rows}
    claimed: set[int] = set()
    seen_ids = {item.source_id for item in items} | {item.source_id for item in excluded_items}
    changes: list[CatalogChange] = []
    inserts: list[CatalogInsert] = []
    summary = CatalogSyncSummary(excluded=len(excluded_items))

    for item in items:
        feed_url = fixed_feed_url(item.source_id)
        candidate = by_id.get(item.source_id)
        if candidate is None:
            candidate = by_feed.get(feed_url)
        if candidate is None:
            candidate = by_name.get(item.name)
        if candidate is not None and (
            candidate.id in claimed
            or candidate.werss_source_id not in (None, item.source_id)
        ):
            summary = replace(summary, conflicts=summary.conflicts + 1)
            continue
        status = "active" if item.enabled else "disabled"
        if candidate is None:
            inserts.append(CatalogInsert(item.name, feed_url, item.source_id, status, now))
            summary = replace(summary, created=summary.created + 1)
            continue
        claimed.add(candidate.id)
        restored = candidate.upstream_status in {"missing", "excluded"}
        disabled = status == "disabled" and candidate.upstream_status != "disabled"
        materially_updated = (
            candidate.account_name != item.name
            or candidate.feed_url != feed_url
            or candidate.werss_source_id != item.source_id
            or (candidate.upstream_status != status and not restored and not disabled)
        )
        if restored:
            summary = replace(summary, restored=summary.restored + 1)
        elif disabled:
            summary = replace(summary, disabled=summary.disabled + 1)
        elif materially_updated:
            summary = replace(summary, updated=summary.updated + 1)
        if materially_updated or restored or disabled or candidate.upstream_last_seen_at != now or candidate.upstream_missing_at is not None:
            changes.append(CatalogChange(candidate.id, item.name, feed_url, item.source_id, status, now, None))

    excluded_source_ids = {item.source_id for item in excluded_items}
    for candidate in rows:
        should_exclude = (
            candidate.account_name == _EXCLUDED_NAME
            or candidate.werss_source_id in excluded_source_ids
        )
        if should_exclude:
            if candidate.upstream_status != "excluded" and candidate.id not in claimed:
                changes.append(_status_change(candidate, "excluded", now, candidate.upstream_missing_at))
                if not excluded_items:
                    summary = replace(summary, excluded=summary.excluded + 1)
            continue
        if (
            candidate.werss_source_id
            and candidate.werss_source_id not in seen_ids
            and candidate.upstream_status not in {"missing", "excluded"}
            and candidate.id not in claimed
        ):
            changes.append(_status_change(candidate, "missing", candidate.upstream_last_seen_at, candidate.upstream_missing_at or now))
            summary = replace(summary, missing=summary.missing + 1)

    changes.sort(key=lambda change: change.row_id)
    return CatalogSyncPlan(tuple(changes), tuple(inserts), summary)


def _status_change(row: CatalogRow, status: str, seen: datetime | None, missing: datetime | None) -> CatalogChange:
    return CatalogChange(row.id, row.account_name, row.feed_url or "", row.werss_source_id or "", status, seen, missing)


class MysqlWeRSSCatalogSyncRepo:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def sync_catalog(
        self,
        items: tuple[WeRSSCatalogItem, ...],
        excluded: tuple[WeRSSCatalogItem, ...],
        now: datetime,
    ) -> CatalogSyncSummary:
        with self.engine.connect() as connection:
            transaction = connection.begin()
            finalized = False
            try:
                acquired = connection.execute(
                    text("SELECT GET_LOCK('weinsight:werss-catalog-sync', 0)")
                ).scalar_one()
                if acquired != 1:
                    transaction.rollback()
                    finalized = True
                    raise WeRSSCatalogSyncBusyError()
                rows = self._locked_rows(connection)
                plan = plan_catalog_sync(rows, items, excluded, now)
                for change in plan.changes:
                    self._apply_change(connection, change)
                for insert in plan.inserts:
                    self._insert(connection, insert)
                transaction.commit()
                finalized = True
                return plan.summary
            except BaseException:
                if not finalized:
                    transaction.rollback()
                raise
            finally:
                connection.execute(
                    text("SELECT RELEASE_LOCK('weinsight:werss-catalog-sync')")
                )

    @staticmethod
    def _locked_rows(connection) -> tuple[CatalogRow, ...]:
        result = connection.execute(text("""
            SELECT id, account_name, feed_url, werss_source_id, upstream_status,
                   upstream_last_seen_at, upstream_missing_at
            FROM wechat_public_account_config
            FOR UPDATE
        """)).mappings().all()
        return tuple(CatalogRow(
            int(row["id"]), str(row["account_name"]), row.get("feed_url"),
            row.get("werss_source_id"), str(row.get("upstream_status", "unknown")),
            row.get("upstream_last_seen_at"), row.get("upstream_missing_at"),
        ) for row in result)

    @staticmethod
    def _apply_change(connection, change: CatalogChange) -> None:
        connection.execute(text("""
            UPDATE wechat_public_account_config
            SET account_name = :account_name, feed_url = :feed_url,
                werss_source_id = :werss_source_id, upstream_status = :upstream_status,
                upstream_last_seen_at = :upstream_last_seen_at,
                upstream_missing_at = :upstream_missing_at,
                update_time = CURRENT_TIMESTAMP
            WHERE id = :id
        """), {
            "id": change.row_id, "account_name": change.name,
            "feed_url": change.feed_url, "werss_source_id": change.source_id,
            "upstream_status": change.status,
            "upstream_last_seen_at": change.last_seen_at,
            "upstream_missing_at": change.missing_at,
        })

    @staticmethod
    def _insert(connection, insert: CatalogInsert) -> None:
        connection.execute(text("""
            INSERT INTO wechat_public_account_config (
                account_name, account_type, feed_url, source_type, werss_source_id,
                upstream_status, upstream_last_seen_at, enabled, priority,
                poll_interval_minutes, request_timeout_seconds, daily_window_start,
                daily_window_end, collect_today_only
            ) VALUES (
                :account_name, 'subscription', :feed_url, 'rss', :werss_source_id,
                :upstream_status, :upstream_last_seen_at, :enabled, :priority,
                :poll_interval_minutes, :request_timeout_seconds, :daily_window_start,
                :daily_window_end, :collect_today_only
            )
        """), {
            "account_name": insert.name, "feed_url": insert.feed_url,
            "werss_source_id": insert.source_id, "upstream_status": insert.status,
            "upstream_last_seen_at": insert.last_seen_at, "enabled": 1,
            "priority": 10, "poll_interval_minutes": 10,
            "request_timeout_seconds": 30, "daily_window_start": "00:00:00",
            "daily_window_end": "23:59:59", "collect_today_only": 1,
        })
