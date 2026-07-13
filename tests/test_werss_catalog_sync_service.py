from datetime import datetime

import pytest

from app.integrations.werss_catalog import WeRSSCatalogError, WeRSSCatalogItem
from app.services.werss_catalog_sync_service import WeRSSCatalogSyncService
from app.storage.werss_catalog_sync_repo import CatalogSyncSummary


NOW = datetime(2026, 7, 13, 16, 0)


class Client:
    items = ()
    error = None

    def fetch_all(self):
        if self.error:
            raise self.error
        return self.items


class Repo:
    def __init__(self):
        self.calls = []

    def sync_catalog(self, items, excluded, now):
        self.calls.append((items, excluded, now))
        return CatalogSyncSummary(created=len(items), excluded=len(excluded))


def test_sync_excludes_yixiangdan_on_server():
    client, repo = Client(), Repo()
    client.items = (
        WeRSSCatalogItem("MP1", "甲", True),
        WeRSSCatalogItem("MP2", "一箱蛋", True),
    )

    summary = WeRSSCatalogSyncService(client, repo).sync(NOW)

    assert (summary.created, summary.excluded) == (1, 1)
    assert repo.calls == [((client.items[0],), (client.items[1],), NOW)]


def test_failed_incomplete_catalog_never_enters_repository():
    client, repo = Client(), Repo()
    client.error = WeRSSCatalogError("werss_catalog_incomplete")

    with pytest.raises(WeRSSCatalogError, match="^werss_catalog_incomplete$"):
        WeRSSCatalogSyncService(client, repo).sync(NOW)

    assert repo.calls == []

