from datetime import datetime, timedelta

import pytest

from app.services.article_source_status_service import ArticleSourceStatusService
from app.storage.article_source_status_repo import ArticleSourceStatusRecord, _LIST_STATUS_SQL


NOW = datetime(2026, 7, 13, 12, 0, 0)


class FakeRepo:
    def __init__(self, records=()):
        self.records = list(records)
        self.calls = []

    def list_status_page(self, *, limit, offset):
        self.calls.append((limit, offset))
        return self.records[:limit]


def record(**changes):
    values = dict(
        source_id=42, account_name="测试公众号", werss_source_id="MP1",
        collection_enabled=True, downstream_processing_enabled=False,
        upstream_status="active",
        upstream_last_seen_at=NOW - timedelta(minutes=8),
        last_article_time=NOW - timedelta(minutes=5),
        last_success_collect_time=NOW - timedelta(minutes=5), article_count=1,
        pending_parse_count=0, pending_analyze_count=0, failed_count=0,
        last_collect_status="success", last_error=None, updated_at=NOW,
        latest_collect_log_time=NOW - timedelta(minutes=3),
    )
    values.update(changes)
    return ArticleSourceStatusRecord(**values)


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({"upstream_status": "excluded", "last_collect_status": "failed"}, "excluded"),
        ({"upstream_status": "missing", "last_collect_status": "failed"}, "missing"),
        ({"upstream_status": "disabled", "last_collect_status": "failed"}, "disabled"),
        ({"upstream_status": "unknown", "last_collect_status": "failed"}, "unknown"),
        ({"last_collect_status": "failed"}, "collect_error"),
        ({"last_success_collect_time": NOW - timedelta(minutes=21)}, "stale"),
        ({}, "normal"),
    ],
)
def test_status_priority(changes, expected):
    service = ArticleSourceStatusService(FakeRepo(), sync_interval_minutes=10)
    assert service.to_status(record(**changes), NOW).display_status == expected


def test_active_without_success_waits_for_first_cycle_and_sanitizes_error():
    service = ArticleSourceStatusService(FakeRepo(), sync_interval_minutes=10)
    row = service.to_status(record(last_success_collect_time=None, last_error="bad https://secret/a <b>x</b>"), NOW)
    assert row.display_status == "waiting_first_run"
    assert row.last_error == "bad [链接已脱敏] x"


def test_list_page_validates_and_fetches_one_extra_row():
    repo = FakeRepo([record(), record(account_name="二")])
    page = ArticleSourceStatusService(repo, 10).list_page(1, 1, NOW)
    assert len(page.items) == 1 and page.has_next
    assert repo.calls == [(2, 0)]


@pytest.mark.parametrize(("page", "size"), [(0, 20), (1, 0), (1, 101), (True, 20)])
def test_list_page_rejects_invalid_boundaries(page, size):
    with pytest.raises(ValueError):
        ArticleSourceStatusService(FakeRepo(), 10).list_page(page, size, NOW)


def test_status_query_aggregates_each_many_side_before_joining():
    sql = str(_LIST_STATUS_SQL)
    assert "raw_stats AS" in sql and "GROUP BY account_name" in sql
    assert "task_stats AS" in sql and "GROUP BY raw.account_name" in sql
    assert "ROW_NUMBER() OVER (PARTITION BY account_name" in sql
    assert "LEFT JOIN raw_stats" in sql and "LEFT JOIN task_stats" in sql and "LEFT JOIN log_latest" in sql


def test_status_query_filters_to_current_werss_sources_before_pagination():
    sql = str(_LIST_STATUS_SQL)
    werss_filter = "config.werss_source_id IS NOT NULL"
    status_filter = "config.upstream_status IN ('active', 'disabled')"
    order_by = "ORDER BY config.account_name, config.id"

    assert werss_filter in sql
    assert status_filter in sql
    assert sql.index(werss_filter) < sql.index(order_by)
    assert sql.index(status_filter) < sql.index(order_by)


def test_status_query_selects_switch_source_fields_explicitly():
    sql = str(_LIST_STATUS_SQL)
    assert "config.id AS source_id" in sql
    assert "config.enabled AS collection_enabled" in sql
    assert "config.downstream_clean_enabled AS downstream_processing_enabled" in sql


@pytest.mark.parametrize(
    ("account_name", "expected_mutable"),
    [("一箱蛋", False), (" 一 箱\t蛋 ", False), ("测试公众号", True)],
)
def test_downstream_processing_mutability_uses_normalized_account_name(account_name, expected_mutable):
    row = ArticleSourceStatusService(FakeRepo(), 10).to_status(record(account_name=account_name), NOW)
    assert row.source_id == 42
    assert row.collection_enabled is True
    assert row.downstream_processing_enabled is False
    assert row.downstream_processing_mutable is expected_mutable


def test_status_updated_at_uses_latest_failure_log_time():
    latest = NOW - timedelta(minutes=1)
    row = ArticleSourceStatusService(FakeRepo(), 10).to_status(
        record(updated_at=NOW - timedelta(minutes=9), latest_collect_log_time=latest), NOW
    )
    assert row.status_updated_at == latest


def test_unknown_legacy_source_is_not_reported_normal():
    row = ArticleSourceStatusService(FakeRepo(), 10).to_status(
        record(upstream_status="unknown"), NOW
    )
    assert row.display_status == "unknown"
    assert row.display_status != "normal"
