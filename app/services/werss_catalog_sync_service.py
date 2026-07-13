from __future__ import annotations

from datetime import datetime
from typing import Protocol

from app.integrations.werss_catalog import (
    WeRSSCatalogClient,
    WeRSSCatalogItem,
    normalize_werss_source_name,
)
from app.storage.werss_catalog_sync_repo import CatalogSyncSummary


class CatalogSyncRepository(Protocol):
    def sync_catalog(
        self,
        items: tuple[WeRSSCatalogItem, ...],
        excluded: tuple[WeRSSCatalogItem, ...],
        now: datetime,
    ) -> CatalogSyncSummary: ...


class WeRSSCatalogSyncService:
    def __init__(self, client: WeRSSCatalogClient, repo: CatalogSyncRepository) -> None:
        self.client, self.repo = client, repo

    def sync(self, now: datetime) -> CatalogSyncSummary:
        catalog = self.client.fetch_all()
        excluded = tuple(
            item for item in catalog
            if normalize_werss_source_name(item.name) == "一箱蛋"
        )
        included = tuple(
            item for item in catalog
            if normalize_werss_source_name(item.name) != "一箱蛋"
        )
        return self.repo.sync_catalog(included, excluded, now)
