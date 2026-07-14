from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Protocol
from zoneinfo import ZoneInfo

from app.domain.article_downstream import ArticleBackfillCommand, ArticleBackfillSummary


_SHANGHAI = ZoneInfo("Asia/Shanghai")
_SOURCE_UNAVAILABLE = "article source is unavailable for downstream processing"


class ArticleDownstreamValidationError(ValueError):
    """Raised when a downstream management command is not safe to execute."""


class ArticleDownstreamSourceUnavailableError(LookupError):
    """Raised when a source cannot be managed through the downstream catalog."""


class ArticleDownstreamRepo(Protocol):
    def set_processing_enabled(self, source_id: int, enabled: bool) -> bool: ...

    def enqueue_backfill(
        self, command: ArticleBackfillCommand, now: datetime
    ) -> ArticleBackfillSummary: ...


class ArticleDownstreamService:
    def __init__(self, repo: ArticleDownstreamRepo) -> None:
        self.repo = repo

    def set_processing_enabled(self, source_id: int, enabled: bool) -> None:
        self._validate_source_id(source_id)
        if type(enabled) is not bool:
            raise ArticleDownstreamValidationError("enabled must be boolean")
        try:
            updated = self.repo.set_processing_enabled(source_id, enabled)
        except LookupError:
            raise ArticleDownstreamSourceUnavailableError(_SOURCE_UNAVAILABLE) from None
        if not updated:
            raise ArticleDownstreamSourceUnavailableError(_SOURCE_UNAVAILABLE)

    def backfill(
        self, command: ArticleBackfillCommand, now: datetime
    ) -> ArticleBackfillSummary:
        if not isinstance(command, ArticleBackfillCommand):
            raise ArticleDownstreamValidationError(
                "command must be ArticleBackfillCommand"
            )
        business_date = self._business_date(now)
        self._validate_command(command, business_date)
        try:
            return self.repo.enqueue_backfill(command, now)
        except LookupError:
            raise ArticleDownstreamSourceUnavailableError(_SOURCE_UNAVAILABLE) from None

    @staticmethod
    def default_backfill_dates(now: datetime) -> tuple[date, date]:
        end_date = ArticleDownstreamService._business_date(now)
        return end_date - timedelta(days=6), end_date

    @staticmethod
    def _business_date(now: datetime) -> date:
        if not isinstance(now, datetime):
            raise ArticleDownstreamValidationError("now must be datetime")
        if now.tzinfo is None or now.utcoffset() is None:
            return now.date()
        return now.astimezone(_SHANGHAI).date()

    @classmethod
    def _validate_command(
        cls, command: ArticleBackfillCommand, business_date: date
    ) -> None:
        if not isinstance(command.scope, str) or command.scope not in {
            "single", "enabled"
        }:
            raise ArticleDownstreamValidationError("scope must be single or enabled")
        if command.scope == "single":
            cls._validate_source_id(command.source_id)
        elif command.source_id is not None:
            raise ArticleDownstreamValidationError(
                "source_id must be omitted for enabled scope"
            )
        if not isinstance(command.mode, str) or command.mode not in {
            "missing_only", "force_analyze"
        }:
            raise ArticleDownstreamValidationError(
                "mode must be missing_only or force_analyze"
            )
        if type(command.force_confirmed) is not bool:
            raise ArticleDownstreamValidationError(
                "force_confirmed must be boolean"
            )
        if command.mode == "force_analyze" and not command.force_confirmed:
            raise ArticleDownstreamValidationError(
                "force_analyze requires explicit confirmation"
            )
        if type(command.start_date) is not date:
            raise ArticleDownstreamValidationError("start_date must be a calendar date")
        if type(command.end_date) is not date:
            raise ArticleDownstreamValidationError("end_date must be a calendar date")
        if command.start_date > command.end_date:
            raise ArticleDownstreamValidationError(
                "start_date must not be after end_date"
            )
        if (command.end_date - command.start_date).days + 1 > 31:
            raise ArticleDownstreamValidationError(
                "date range must contain at most 31 days"
            )
        if command.end_date > business_date:
            raise ArticleDownstreamValidationError(
                "end_date must not be in the future"
            )

    @staticmethod
    def _validate_source_id(source_id: object) -> None:
        if type(source_id) is not int or source_id < 1:
            raise ArticleDownstreamValidationError(
                "source_id must be a positive integer"
            )
