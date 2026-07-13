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
        account_name="测试公众号", werss_source_id="MP1", upstream_status="active",
        last_article_time=NOW - timedelta(minutes=5),
        last_success_collect_time=NOW - timedelta(minutes=5), article_count=1,
        pending_parse_count=0, pending_analyze_count=0, failed_count=0,
        last_collect_status="success", last_error=None, updated_at=NOW,
    )
    values.update(changes)
    return ArticleSourceStatusRecord(**values)


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({"upstream_status": "excluded", "last_collect_status": "failed"}, "excluded"),
        ({"upstream_status": "missing", "last_collect_status": "failed"}, "missing"),
        ({"upstream_status": "disabled", "last_collect_status": "failed"}, "disabled"),
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
