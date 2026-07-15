from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from app.integrations.werss_catalog import WeRSSCatalogError
from app.workers.article_global_cycle import ArticleGlobalCycle


NOW = datetime(2026, 7, 13, 12, 0, tzinfo=ZoneInfo("Asia/Shanghai"))


class SyncService:
    def __init__(self):
        self.error = None

    def sync(self, now):
        if self.error:
            raise self.error
        return SimpleNamespace(created=1, updated=0, missing=0, excluded=0)


class SourceRepo:
    accounts = ()

    def list_active_werss_accounts(self):
        return self.accounts


class JobRepo:
    def __init__(self):
        self.calls = []

    def reconcile_system_article_job(self, target_ids, interval_minutes, now):
        self.calls.append((target_ids, interval_minutes, now))


def make_cycle():
    return ArticleGlobalCycle(SyncService(), SourceRepo(), JobRepo(), 10)


def test_cycle_syncs_then_reconciles_one_system_job_for_active_sources():
    cycle = make_cycle()
    cycle.source_repo.accounts = (
        SimpleNamespace(id=2, account_name="乙号"),
        SimpleNamespace(id=1, account_name="甲号"),
    )

    result = cycle.run(NOW)

    assert cycle.job_repo.calls == [((1, 2), 10, NOW)]
    assert result.source_count == 2
    assert result.sync_error_code is None


@pytest.mark.parametrize("error_code", ["werss_catalog_timeout", "werss_catalog_invalid"])
def test_catalog_failure_uses_last_known_active_sources(error_code):
    cycle = make_cycle()
    cycle.sync_service.error = WeRSSCatalogError(error_code)
    cycle.source_repo.accounts = (SimpleNamespace(id=1, account_name="甲号"),)

    result = cycle.run(NOW)

    assert cycle.job_repo.calls == [((1,), 10, NOW)]
    assert result.sync_error_code == error_code


def test_cycle_defensively_excludes_yixiangdan_and_accepts_empty_active_list():
    cycle = make_cycle()
    cycle.source_repo.accounts = (
        SimpleNamespace(id=1, account_name=" 一 箱 蛋 "),
    )

    result = cycle.run(NOW)

    assert cycle.job_repo.calls == [((), 10, NOW)]
    assert result.source_count == 0
