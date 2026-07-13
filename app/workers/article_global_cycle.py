from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from app.integrations.werss_catalog import WeRSSCatalogError
from app.storage.werss_catalog_sync_repo import WeRSSCatalogSyncBusyError


class CatalogSync(Protocol):
    def sync(self, now: datetime): ...


class ActiveSourceRepo(Protocol):
    def list_active_werss_accounts(self): ...


class SystemJobRepo(Protocol):
    def reconcile_system_article_job(
        self, target_ids: tuple[int, ...], interval_minutes: int, now: datetime
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class ArticleGlobalCycleResult:
    source_count: int
    sync_error_code: str | None = None


class ArticleGlobalCycle:
    def __init__(
        self,
        sync_service: CatalogSync,
        source_repo: ActiveSourceRepo,
        job_repo: SystemJobRepo,
        interval_minutes: int,
    ) -> None:
        self.sync_service = sync_service
        self.source_repo = source_repo
        self.job_repo = job_repo
        self.interval_minutes = interval_minutes

    def run(self, now: datetime) -> ArticleGlobalCycleResult:
        error_code = None
        try:
            self.sync_service.sync(now)
        except (WeRSSCatalogError, WeRSSCatalogSyncBusyError) as exc:
            error_code = getattr(exc, "code", str(exc))

        accounts = self.source_repo.list_active_werss_accounts()
        target_ids = tuple(
            sorted(
                int(account.id)
                for account in accounts
                if account.id is not None
                and "".join(account.account_name.split()) != "一箱蛋"
            )
        )
        self.job_repo.reconcile_system_article_job(
            target_ids, self.interval_minutes, now
        )
        return ArticleGlobalCycleResult(len(target_ids), error_code)
