"""The Audit GUI's job store (AG9, design §7.3): states, de-duplication,
cancellation, stranded jobs, and progress only once the total is known."""

from __future__ import annotations

from pathlib import Path

import pytest

from edumatcher.audit.service.jobs import (
    ACTIVE,
    CANCELLED,
    FAILED,
    QUEUED,
    RUNNING,
    SUCCEEDED,
    WORKER_LOST,
    JobStore,
)

SID = "s-0123456789abcdef0123"


@pytest.fixture
def store(tmp_path: Path) -> JobStore:
    return JobStore(tmp_path / "jobs.db")


def test_a_new_job_is_queued_without_progress(store: JobStore) -> None:
    job, created = store.submit("prepare", SID, {})
    assert created
    assert (job.state, job.stage, job.progress) == (QUEUED, None, None)
    assert job.created_at and job.started_at is None


def test_identical_active_requests_share_one_job(store: JobStore) -> None:
    first, _ = store.submit("prepare", SID, {"force": True})
    again, created = store.submit("prepare", SID, {"force": True})
    assert (again.job_id, created) == (first.job_id, False)
    other, created = store.submit("prepare", SID, {})
    assert created and other.job_id != first.job_id
    # Once it has ended, the same request is a new job.
    store.finish(first.job_id, SUCCEEDED, result={"generation": 1})
    fresh, created = store.submit("prepare", SID, {"force": True})
    assert created and fresh.job_id != first.job_id


def test_unknown_kinds_are_refused(store: JobStore) -> None:
    with pytest.raises(ValueError):
        store.submit("reindex-everything", SID, {})


def test_a_worker_claims_the_oldest_queued_job_once(store: JobStore) -> None:
    a, _ = store.submit("prepare", SID, {})
    b, _ = store.submit("verify", SID, {})
    claimed = store.claim(4242)
    assert claimed is not None
    assert (claimed.job_id, claimed.state, claimed.worker_pid) == (
        a.job_id,
        RUNNING,
        4242,
    )
    assert claimed.started_at and claimed.heartbeat_at
    assert store.claim(4242) is not None  # b
    assert store.claim(4242) is None
    assert store.get(b.job_id).state == RUNNING  # type: ignore[union-attr]


def test_progress_is_null_until_the_total_is_known(store: JobStore) -> None:
    job, _ = store.submit("prepare", SID, {})
    store.claim(1)
    store.progress(job.job_id, "pinning", None, None)
    assert store.get(job.job_id).progress is None  # type: ignore[union-attr]
    store.progress(job.job_id, "normalising", 10, 400)
    got = store.get(job.job_id)
    assert got is not None
    assert (got.stage, got.progress) == ("normalising", (10, 400))


def test_cancelling_a_queued_job_ends_it_and_a_running_one_asks_it_to_stop(
    store: JobStore,
) -> None:
    queued, _ = store.submit("verify", SID, {})
    assert store.cancel(queued.job_id).state == CANCELLED  # type: ignore[union-attr]
    running, _ = store.submit("prepare", SID, {})
    store.claim(1)
    after = store.cancel(running.job_id)
    assert after is not None
    assert (after.state, after.cancel_requested) == (RUNNING, True)
    assert store.cancel_requested(running.job_id)
    store.finish(running.job_id, CANCELLED, reason="CANCELLED")
    ended = store.get(running.job_id)
    assert ended is not None and ended.state == CANCELLED and ended.finished_at
    assert store.cancel("j-unknown") is None


def test_a_job_whose_worker_died_is_failed_with_a_reason(store: JobStore) -> None:
    job, _ = store.submit("prepare", SID, {})
    store.claim(999_999)
    lost = store.reconcile(alive=lambda pid: False, stale_after=60.0)
    assert [j.job_id for j in lost] == [job.job_id]
    got = store.get(job.job_id)
    assert got is not None
    assert (got.state, got.reason) == (FAILED, WORKER_LOST)


def test_a_silent_worker_is_presumed_dead(store: JobStore) -> None:
    job, _ = store.submit("prepare", SID, {})
    store.claim(1)
    assert store.reconcile(alive=lambda pid: True, stale_after=60.0) == []
    lost = store.reconcile(alive=lambda pid: True, stale_after=-1.0)
    assert [j.job_id for j in lost] == [job.job_id]


def test_the_latest_successful_job_of_a_kind_is_found(store: JobStore) -> None:
    assert store.latest("prepare", SID, SUCCEEDED) is None
    a, _ = store.submit("prepare", SID, {})
    store.finish(a.job_id, SUCCEEDED, result={"generation": 1})
    b, _ = store.submit("prepare", SID, {"force": True})
    store.finish(b.job_id, SUCCEEDED, result={"generation": 2})
    latest = store.latest("prepare", SID, SUCCEEDED)
    assert latest is not None and latest.result == {"generation": 2}
    assert QUEUED in ACTIVE and RUNNING in ACTIVE
