from datetime import datetime
from zoneinfo import ZoneInfo

from app.services.event_retention_service import EventCleanupResult, EventRetentionPolicy, EventRetentionService
from app.storage.event_retention_repo import _rule, _subtract_months


ZONE = ZoneInfo("Asia/Shanghai")


class Repo:
    def __init__(self) -> None:
        self.calls = []

    def cleanup(self, now, policy, *, dry_run):
        self.calls.append((now, policy, dry_run))
        return EventCleanupResult(True, dry_run, {"info": 3})


def test_month_retention_uses_calendar_month_end() -> None:
    assert _subtract_months(datetime(2026, 5, 31, 12, tzinfo=ZONE), 3) == datetime(2026, 2, 28, 12, tzinfo=ZONE)


def test_rules_are_disjoint_and_preserve_audit_events() -> None:
    cutoff = datetime(2026, 7, 1, tzinfo=ZONE)
    verbose, _ = _rule("verbose", cutoff)
    info, _ = _rule("info", cutoff)
    error, _ = _rule("warning_error", cutoff)
    audit, _ = _rule("audit", cutoff)
    assert "collection_target_started" in verbose
    assert "NOT IN" in info and "job_created" in info
    assert "level IN ('warning','error')" in error and "NOT IN" in error
    assert "event_type IN" in audit and "job_created" in audit


def test_service_forwards_dry_run_without_mutating_policy() -> None:
    repo = Repo()
    policy = EventRetentionPolicy()
    now = datetime(2026, 7, 15, 9, tzinfo=ZONE)
    result = EventRetentionService(repo, policy).run(now, dry_run=True)
    assert result.total == 3
    assert repo.calls == [(now, policy, True)]
