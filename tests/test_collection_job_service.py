from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import pytest

from app.domain.admin_results import PagedResult
from app.domain.collection_jobs import JobStatus, PipelineType
from app.services.collection_job_service import (
    CollectionJobService,
    CreateCollectionJobCommand,
    JobListFilter,
    JobNotFoundError,
    JobValidationError,
)


ZONE = ZoneInfo("Asia/Shanghai")
NOW = datetime(2026, 7, 10, 9, 0, tzinfo=ZONE)


def command(**overrides) -> CreateCollectionJobCommand:
    values = {
        "job_name": "晨间群采集",
        "pipeline_type": PipelineType.GROUP,
        "target_ids": (9, 7, 9),
        "effective_start_at": NOW,
        "effective_end_at": datetime(2026, 7, 12, 18, 0, tzinfo=ZONE),
        "daily_window_start": time(9, 0),
        "daily_window_end": time(18, 0),
        "interval_seconds": 600,
    }
    values.update(overrides)
    return CreateCollectionJobCommand(**values)


class Repo:
    def __init__(self) -> None:
        self.create_calls = []
        self.stop_calls = []
        self.delete_calls = []
        self.list_calls = []
        self.details = {}

    def create_job(self, cmd, status, next_run_at, actor):
        self.create_calls.append((cmd, status, next_run_at, actor))
        return 41

    def request_stop(self, job_id, expected_version, actor, now):
        self.stop_calls.append((job_id, expected_version, actor, now))
        return JobStatus.STOP_REQUESTED

    def soft_delete(self, job_id, expected_version, actor, now):
        self.delete_calls.append((job_id, expected_version, actor, now))
        return True

    def list_jobs(self, filters, page, page_size):
        self.list_calls.append((filters, page, page_size))
        return PagedResult([], page, page_size, 0)

    def get_job(self, job_id):
        return self.details.get(job_id)


@pytest.fixture
def repo() -> Repo:
    return Repo()


@pytest.fixture
def service(repo) -> CollectionJobService:
    return CollectionJobService(repo)


def test_create_deduplicates_ids_and_allows_now_grid(service, repo) -> None:
    job_id = service.create_job(command(), actor="admin", now=NOW)

    assert job_id == 41
    saved, status, next_run, actor = repo.create_calls[0]
    assert saved.target_ids == (7, 9)
    assert status is JobStatus.ACTIVE
    assert next_run == NOW
    assert actor == "admin"


def test_future_job_is_scheduled_even_when_window_is_current(service, repo) -> None:
    start = datetime(2026, 7, 11, 9, 0, tzinfo=ZONE)

    service.create_job(
        command(effective_start_at=start), actor="admin", now=NOW
    )

    assert repo.create_calls[0][1] is JobStatus.SCHEDULED
    assert repo.create_calls[0][2] == start


def test_started_job_is_active_even_when_daily_window_is_closed(service, repo) -> None:
    now = datetime(2026, 7, 10, 20, 0, tzinfo=ZONE)

    service.create_job(command(), actor="admin", now=now)

    assert repo.create_calls[0][1] is JobStatus.ACTIVE
    assert repo.create_calls[0][2] == datetime(
        2026, 7, 11, 9, 0, tzinfo=ZONE
    )


def test_article_job_rejects_interval_below_ten_minutes(service, repo) -> None:
    article = command(
        pipeline_type=PipelineType.ARTICLE,
        interval_seconds=599,
    )

    with pytest.raises(JobValidationError, match="at least 600"):
        service.create_job(article, actor="admin", now=NOW)

    assert repo.create_calls == []


def test_group_job_rejects_interval_below_thirty_seconds(service) -> None:
    with pytest.raises(JobValidationError, match="at least 30"):
        service.create_job(
            command(interval_seconds=29), actor="admin", now=NOW
        )


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"job_name": " "}, "job_name"),
        ({"job_name": " padded"}, "surrounding whitespace"),
        ({"target_ids": ()}, "at least one target"),
        ({"target_ids": (0,)}, "positive integer"),
        ({"target_ids": (True,)}, "positive integer"),
        ({"pipeline_type": "group"}, "pipeline_type"),
        ({"daily_window_start": "09:00"}, "daily_window_start"),
    ],
)
def test_create_validates_name_pipeline_targets_and_schedule(
    service, changes, message
) -> None:
    with pytest.raises(JobValidationError, match=message):
        service.create_job(command(**changes), actor="admin", now=NOW)


@pytest.mark.parametrize("actor", ["", " admin", "x" * 101, None])
def test_mutations_reject_invalid_actor(service, actor) -> None:
    with pytest.raises(JobValidationError, match="actor"):
        service.request_stop(
            job_id=11,
            expected_version=3,
            actor=actor,
            now=NOW,
        )


def test_create_rejects_naive_now(service) -> None:
    with pytest.raises(JobValidationError, match="now"):
        service.create_job(
            command(), actor="admin", now=NOW.replace(tzinfo=None)
        )


def test_expired_or_schedule_without_future_grid_is_rejected(service) -> None:
    with pytest.raises(JobValidationError, match="no future run"):
        service.create_job(
            command(
                effective_start_at=datetime(2026, 7, 8, 9, 0, tzinfo=ZONE),
                effective_end_at=NOW,
            ),
            actor="admin",
            now=NOW,
        )


def test_stop_and_delete_delegate_validated_optimistic_version(service, repo) -> None:
    result = service.request_stop(
        job_id=11, expected_version=3, actor="admin", now=NOW
    )
    deleted = service.delete_job(
        job_id=11, expected_version=4, actor="admin", now=NOW
    )

    assert result is JobStatus.STOP_REQUESTED
    assert deleted is True
    assert repo.stop_calls == [(11, 3, "admin", NOW)]
    assert repo.delete_calls == [(11, 4, "admin", NOW)]


@pytest.mark.parametrize(
    ("job_id", "version"),
    [(0, 1), (True, 1), (1, 0), (1, True)],
)
def test_mutations_require_positive_integer_ids_and_versions(
    service, job_id, version
) -> None:
    with pytest.raises(JobValidationError, match="positive integer"):
        service.request_stop(job_id, version, "admin", NOW)


def test_list_validates_page_and_page_size_and_passes_same_filter(service, repo) -> None:
    filters = JobListFilter(
        pipeline_type=PipelineType.GROUP,
        status=JobStatus.ACTIVE,
        name_contains="晨间",
        date=date(2026, 7, 10),
    )
    result = service.list_jobs(filters, page=2, page_size=100)

    assert result.page == 2
    assert repo.list_calls == [(filters, 2, 100)]
    with pytest.raises(JobValidationError, match="page_size"):
        service.list_jobs(filters, page=1, page_size=101)


@pytest.mark.parametrize(
    "invalid_date",
    [datetime(2026, 7, 10, 0, 0), "2026-07-10", 20260710, True],
)
def test_list_rejects_non_date_filter_values(service, repo, invalid_date) -> None:
    filters = JobListFilter(date=invalid_date)

    with pytest.raises(JobValidationError, match="date"):
        service.list_jobs(filters, page=1, page_size=20)

    assert repo.list_calls == []


def test_get_job_maps_missing_to_domain_error(service) -> None:
    with pytest.raises(JobNotFoundError):
        service.get_job(404)
