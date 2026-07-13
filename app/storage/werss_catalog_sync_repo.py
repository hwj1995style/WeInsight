from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
import hashlib
import json
from urllib.parse import quote

from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.integrations.werss_catalog import WeRSSCatalogItem, normalize_werss_source_name


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
    feed_url: str | None
    source_id: str | None
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
    audit_required: bool
    audit_digest: str


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
    by_name: dict[str, list[CatalogRow]] = {}
    for row in rows:
        by_name.setdefault(normalize_werss_source_name(row.account_name), []).append(row)
    claimed: set[int] = set()
    seen_ids = {item.source_id for item in items} | {item.source_id for item in excluded_items}
    changes: list[CatalogChange] = []
    inserts: list[CatalogInsert] = []
    summary = CatalogSyncSummary(excluded=len(excluded_items))
    audit_required = False
    conflict_source_ids: list[str] = []

    for item in items:
        normalized_name = normalize_werss_source_name(item.name)
        feed_url = fixed_feed_url(item.source_id)
        candidate = by_id.get(item.source_id)
        if candidate is None:
            candidate = by_feed.get(feed_url)
        if candidate is None:
            name_candidates = by_name.get(normalized_name, [])
            if len(name_candidates) > 1:
                summary = replace(summary, conflicts=summary.conflicts + 1)
                audit_required = True
                conflict_source_ids.append(item.source_id)
                continue
            candidate = name_candidates[0] if name_candidates else None
        if candidate is not None and (
            candidate.id in claimed
            or candidate.werss_source_id not in (None, item.source_id)
        ):
            summary = replace(summary, conflicts=summary.conflicts + 1)
            audit_required = True
            conflict_source_ids.append(item.source_id)
            continue
        status = "active" if item.enabled else "disabled"
        if candidate is None:
            inserts.append(CatalogInsert(normalized_name, feed_url, item.source_id, status, now))
            summary = replace(summary, created=summary.created + 1)
            audit_required = True
            continue
        claimed.add(candidate.id)
        restored = candidate.upstream_status in {"missing", "excluded"}
        disabled = status == "disabled" and candidate.upstream_status != "disabled"
        materially_updated = (
            candidate.account_name != normalized_name
            or candidate.feed_url != feed_url
            or candidate.werss_source_id != item.source_id
            or (candidate.upstream_status != status and not restored and not disabled)
        )
        if restored:
            summary = replace(summary, restored=summary.restored + 1)
            audit_required = True
        elif disabled:
            summary = replace(summary, disabled=summary.disabled + 1)
            audit_required = True
        elif materially_updated:
            summary = replace(summary, updated=summary.updated + 1)
            audit_required = True
        if materially_updated or restored or disabled or candidate.upstream_last_seen_at != now or candidate.upstream_missing_at is not None:
            changes.append(CatalogChange(candidate.id, normalized_name, feed_url, item.source_id, status, now, None))

    for item in excluded_items:
        normalized_name = normalize_werss_source_name(item.name)
        feed_url = fixed_feed_url(item.source_id)
        candidate = by_id.get(item.source_id)
        if candidate is None:
            candidate = by_feed.get(feed_url)
        if candidate is None:
            name_candidates = by_name.get(normalized_name, [])
            if len(name_candidates) > 1:
                summary = replace(summary, conflicts=summary.conflicts + 1)
                audit_required = True
                conflict_source_ids.append(item.source_id)
                continue
            candidate = name_candidates[0] if name_candidates else None
        if candidate is None:
            continue
        if candidate.id in claimed or candidate.werss_source_id not in (None, item.source_id):
            summary = replace(summary, conflicts=summary.conflicts + 1)
            audit_required = True
            conflict_source_ids.append(item.source_id)
            continue
        claimed.add(candidate.id)
        if (
            candidate.account_name != normalized_name
            or candidate.feed_url != feed_url
            or candidate.werss_source_id != item.source_id
            or candidate.upstream_status != "excluded"
            or candidate.upstream_last_seen_at != now
            or candidate.upstream_missing_at is not None
        ):
            changes.append(CatalogChange(
                candidate.id, normalized_name, feed_url, item.source_id,
                "excluded", now, None,
            ))
        if (
            candidate.account_name != normalized_name
            or candidate.feed_url != feed_url
            or candidate.werss_source_id != item.source_id
            or candidate.upstream_status != "excluded"
            or candidate.upstream_missing_at is not None
        ):
            audit_required = True

    excluded_source_ids = {item.source_id for item in excluded_items}
    for candidate in rows:
        should_exclude = (
            normalize_werss_source_name(candidate.account_name) == _EXCLUDED_NAME
            or candidate.werss_source_id in excluded_source_ids
        )
        if should_exclude:
            if candidate.upstream_status != "excluded" and candidate.id not in claimed:
                changes.append(_status_change(candidate, "excluded", now, candidate.upstream_missing_at))
                audit_required = True
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
            audit_required = True

    changes.sort(key=lambda change: change.row_id)
    audit_digest = _planned_final_state_digest(
        rows,
        tuple(changes),
        tuple(inserts),
        tuple(conflict_source_ids),
    )
    return CatalogSyncPlan(
        tuple(changes), tuple(inserts), summary, audit_required, audit_digest
    )


def _planned_final_state_digest(
    rows: tuple[CatalogRow, ...],
    changes: tuple[CatalogChange, ...],
    inserts: tuple[CatalogInsert, ...],
    conflict_source_ids: tuple[str, ...],
) -> str:
    changes_by_id = {change.row_id: change for change in changes}
    final_rows: list[list[object]] = []
    for row in rows:
        change = changes_by_id.get(row.id)
        source_id = row.werss_source_id if change is None else change.source_id
        missing_at = (
            row.upstream_missing_at if change is None else change.missing_at
        )
        final_rows.append([
            source_id or f"legacy:{row.id}",
            normalize_werss_source_name(
                row.account_name if change is None else change.name
            ),
            row.feed_url if change is None else change.feed_url,
            row.upstream_status if change is None else change.status,
            None if missing_at is None else missing_at.isoformat(),
        ])
    for insert in inserts:
        final_rows.append([
            insert.source_id,
            normalize_werss_source_name(insert.name),
            insert.feed_url,
            insert.status,
            None,
        ])
    payload = {
        "final_rows": sorted(
            final_rows,
            key=lambda value: tuple(str(item) for item in value),
        ),
        "conflict_source_ids": sorted(set(conflict_source_ids)),
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _status_change(row: CatalogRow, status: str, seen: datetime | None, missing: datetime | None) -> CatalogChange:
    return CatalogChange(row.id, row.account_name, row.feed_url, row.werss_source_id, status, seen, missing)


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
                rows_by_id = {row.id: row for row in rows}
                name_counts: dict[str, int] = {}
                for row in rows:
                    name_counts[row.account_name] = name_counts.get(row.account_name, 0) + 1
                for change in plan.changes:
                    original = rows_by_id[change.row_id]
                    self._apply_change(
                        connection,
                        change,
                        original=original,
                        original_name_is_unique=name_counts.get(
                            original.account_name, 0
                        ) == 1,
                        new_name_was_unused=name_counts.get(change.name, 0) == 0,
                    )
                for insert in plan.inserts:
                    self._insert(connection, insert)
                if plan.audit_required:
                    self._append_audit_if_changed(
                        connection, plan.summary, plan.audit_digest
                    )
                transaction.commit()
                finalized = True
                return plan.summary
            except BaseException:
                if not finalized:
                    transaction.rollback()
                raise
            finally:
                try:
                    connection.execute(
                        text("SELECT RELEASE_LOCK('weinsight:werss-catalog-sync')")
                    )
                except Exception:
                    try:
                        connection.invalidate()
                    except Exception:
                        pass

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
    def _apply_change(
        connection,
        change: CatalogChange,
        *,
        original: CatalogRow,
        original_name_is_unique: bool,
        new_name_was_unused: bool,
    ) -> None:
        if (
            original.account_name != change.name
            and original_name_is_unique
            and new_name_was_unused
        ):
            rename_params = {"old_name": original.account_name, "new_name": change.name}
            connection.execute(text("""
                UPDATE wechat_article_raw
                SET account_name = :new_name
                WHERE account_name = :old_name
            """), rename_params)
            connection.execute(text("""
                UPDATE wechat_article_collect_log
                SET account_name = :new_name
                WHERE account_name = :old_name
            """), rename_params)
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

    @staticmethod
    def _append_audit_if_changed(
        connection,
        summary: CatalogSyncSummary,
        catalog_digest: str,
    ) -> None:
        metrics_json = json.dumps(
            {
                "created": summary.created,
                "updated": summary.updated,
                "disabled": summary.disabled,
                "missing": summary.missing,
                "restored": summary.restored,
                "excluded": summary.excluded,
                "conflicts": summary.conflicts,
                "catalog_digest": catalog_digest,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        previous = connection.execute(text("""
            SELECT metrics_json
            FROM wechat_collection_job_event
            WHERE event_type = 'werss_catalog_sync_changed'
              AND actor_type = 'system'
              AND actor_name = 'werss-catalog-sync'
            ORDER BY id DESC
            LIMIT 1
            FOR UPDATE
        """)).mappings().first()
        if previous is not None:
            try:
                previous_metrics = json.loads(previous.get("metrics_json") or "")
            except (TypeError, ValueError, json.JSONDecodeError):
                previous_metrics = {}
            if previous_metrics.get("catalog_digest") == catalog_digest:
                return
        connection.execute(text("""
            INSERT INTO wechat_collection_job_event (
                job_id, run_id, target_run_id, worker_id, level, event_type,
                stage, message, metrics_json, actor_type, actor_name
            ) VALUES (
                NULL, NULL, NULL, NULL, 'info', :event_type,
                'catalog_sync', :message, :metrics_json, 'system', :actor_name
            )
        """), {
            "event_type": "werss_catalog_sync_changed",
            "message": "WeRSS catalog synchronization changed source configuration.",
            "metrics_json": metrics_json,
            "actor_name": "werss-catalog-sync",
        })
