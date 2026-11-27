"""The worker, its jobs and the job API (Audit GUI AG9, design §7.3, §8,
§11.2 scenarios 8 and 10).

Most tests run the worker's job code in this process (``run_jobs``: the
test app starts no worker); the ones about the process itself -- killing
it, and the API never reconstructing -- start the real worker process.
"""

from __future__ import annotations

import os
import signal
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from edumatcher.audit.service import build as build_module
from edumatcher.audit.service import generations, worker
from edumatcher.audit.service.session import AuditService, WorkerLauncher
from tests.audit_gui_world import World, build, make_audit_app, run_jobs
from tests.test_api_gateway_audit import _all_events, _get, _post


def _pin(app: Any) -> dict[str, Any]:
    status, body = _post(app, "/snapshots", {"collection_id": "world"})
    assert status == 201, body
    return body


def _job(app: Any, job_id: str) -> dict[str, Any]:
    status, body = _get(app, f"/jobs/{job_id}")
    assert status == 200, body
    return body


def _until(check: Any, what: str, timeout: float = 30.0) -> Any:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        got = check()
        if got:
            return got
        time.sleep(0.05)
    raise AssertionError(f"timed out waiting for {what}")


@pytest.fixture(scope="module")
def base(tmp_path_factory: pytest.TempPathFactory) -> World:
    return build(tmp_path_factory.mktemp("audit-world"))


@pytest.fixture
def app(base: World, tmp_path: Path) -> Any:
    """A fresh derivative store per test, over the shared recorded world."""
    application = make_audit_app(base)
    application.state.audit = AuditService(
        application.state.audit.collections.values(), tmp_path / "store"
    )
    return application


def _snapshot_dir(app: Any, sid: str) -> Path:
    return Path(app.state.audit.store) / "snapshots" / sid


def _scratch(app: Any) -> list[Path]:
    root = Path(app.state.audit.store) / "scratch"
    return sorted(root.iterdir()) if root.exists() else []


# --- Preparing ------------------------------------------------------------------


def test_pinning_queues_prepare_and_reads_wait_for_it(app: Any) -> None:
    body = _pin(app)
    sid = body["snapshot_id"]
    assert body["generation"] is None
    prepare = body["prepare"]
    assert (prepare["kind"], prepare["state"], prepare["progress"]) == (
        "prepare",
        "queued",
        None,
    )
    status, err = _get(app, f"/events?snapshot_id={sid}")
    assert (status, err["error"]["code"], err["error"]["job_id"]) == (409, "NOT_PREPARED", prepare["job_id"])  # fmt: skip
    assert run_jobs(app) == 1
    job = _job(app, prepare["job_id"])
    assert (job["state"], job["result_id"], job["reason"]) == (
        "succeeded",
        prepare["job_id"],
        None,
    )
    status, result = _get(app, f"/results/{prepare['job_id']}")
    assert status == 200 and result["content"]["generation"] == 1
    status, snap = _get(app, f"/snapshots/{sid}")
    assert (snap["generation"], snap["prepare"]["state"]) == (1, "succeeded")
    status, page = _get(app, f"/events?snapshot_id={sid}")
    assert (status, page["generation"]) == (200, 1)
    assert _scratch(app) == []


def test_each_job_kind_is_accepted_and_identical_requests_share_a_job(app: Any) -> None:
    sid = _pin(app)["snapshot_id"]
    run_jobs(app)
    for kind in ("prepare", "verify", "forensics_import"):
        status, job = _post(app, "/jobs", {"kind": kind, "snapshot_id": sid})
        assert status == 202, job
    status, a = _post(app, "/jobs", {"kind": "verify", "snapshot_id": sid})
    status, b = _post(app, "/jobs", {"kind": "verify", "snapshot_id": sid})
    assert a["job_id"] == b["job_id"]
    # A prepared snapshot's prepare is answered by the job that prepared it.
    status, again = _post(app, "/jobs", {"kind": "prepare", "snapshot_id": sid})
    assert (again["state"], again["result_id"]) == ("succeeded", again["job_id"])


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({"kind": "reindex", "snapshot_id": "s-0123456789abcdef0123"}, "kind"),
        ({"kind": "verify", "snapshot_id": "s-0123456789abcdef0123", "options": {"force": True}}, "options.force"),  # fmt: skip
        ({"kind": "prepare", "snapshot_id": "s-0123456789abcdef0123", "options": {"deep": 1}}, None),  # fmt: skip
        (
            {
                "kind": "prepare",
                "snapshot_id": "s-0123456789abcdef0123",
                "path": "/etc",
            },
            None,
        ),
    ],
)
def test_unknown_kinds_and_options_are_400(
    app: Any, body: dict[str, Any], field: str | None
) -> None:
    status, err = _post(app, "/jobs", body)
    assert (status, err["error"]["code"]) == (400, "VALIDATION")
    if field == "options.force":
        assert err["error"]["field"] == field


def test_jobs_of_unknown_things_are_404(app: Any) -> None:
    status, err = _post(
        app, "/jobs", {"kind": "verify", "snapshot_id": "s-0123456789abcdef0123"}
    )
    assert (status, err["error"]["code"]) == (404, "UNKNOWN_SNAPSHOT")
    for method, path in (
        ("GET", "/jobs/j-nope"),
        ("POST", "/jobs/j-nope/cancel"),
        ("GET", "/results/j-nope"),
    ):
        status, err = _get(app, path) if method == "GET" else _post(app, path, {})
        assert (status, err["error"]["code"]) == (404, "UNKNOWN_JOB"), path


def test_a_result_is_only_for_a_succeeded_job(app: Any) -> None:
    sid = _pin(app)["snapshot_id"]
    run_jobs(app)
    status, job = _post(app, "/jobs", {"kind": "verify", "snapshot_id": sid})
    status, err = _get(app, f"/results/{job['job_id']}")
    assert (status, err["error"]["code"], err["error"]["state"]) == (
        409,
        "JOB_NOT_SUCCEEDED",
        "queued",
    )


# --- Generations: rebuilds never move a reader (scenario 8) ------------------------


def test_a_rebuild_publishes_a_new_generation_and_keeps_the_previous(app: Any) -> None:
    sid = _pin(app)["snapshot_id"]
    run_jobs(app)
    for expected in (2, 3):
        status, job = _post(app, "/jobs", {"kind": "prepare", "snapshot_id": sid, "options": {"force": True}})  # fmt: skip
        assert status == 202
        run_jobs(app)
        assert (
            _get(app, f"/results/{job['job_id']}")[1]["content"]["generation"]
            == expected
        )
    gens = sorted(p.name for p in (_snapshot_dir(app, sid) / "generations").iterdir())
    assert gens == ["2", "3"]


def test_a_read_during_a_rebuild_stays_on_its_generation(app: Any) -> None:
    sid = _pin(app)["snapshot_id"]
    run_jobs(app)
    whole = _all_events(app, sid)
    status, first = _get(app, f"/events?snapshot_id={sid}&limit=100")
    assert first["generation"] == 1
    _post(
        app,
        "/jobs",
        {"kind": "prepare", "snapshot_id": sid, "options": {"force": True}},
    )
    run_jobs(app)
    status, second = _get(app, f"/events?snapshot_id={sid}&limit=1000&after={first['next_cursor']}")  # fmt: skip
    assert (status, second["generation"]) == (200, 1)
    assert [e["key"] for e in first["events"] + second["events"]][: len(whole)] == [e["key"] for e in whole][: 100 + second["count"]]  # fmt: skip
    # Two rebuilds later the first generation is gone: said so, not moved.
    for _ in range(2):
        _post(
            app,
            "/jobs",
            {"kind": "prepare", "snapshot_id": sid, "options": {"force": True}},
        )
        run_jobs(app)
    status, err = _get(
        app, f"/events?snapshot_id={sid}&limit=1000&after={first['next_cursor']}"
    )
    assert (status, err["error"]["code"], err["error"]["generation"]) == (
        409,
        "GENERATION_EXPIRED",
        1,
    )


# --- Cancel, time-out, failure: nothing partial (scenario 10) -----------------------


def test_cancelling_a_running_prepare_publishes_nothing(
    app: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(worker.STALL_ENV, "20")
    body = _pin(app)
    job_id = body["prepare"]["job_id"]
    runner = threading.Thread(target=run_jobs, args=(app,))
    runner.start()
    _until(
        lambda: _job(app, job_id)["state"] == "running" and _scratch(app),
        "the job to run",
    )
    status, after = _post(app, f"/jobs/{job_id}/cancel", {})
    assert (status, after["state"]) == (202, "running")
    runner.join(timeout=20)
    job = _job(app, job_id)
    assert (job["state"], job["reason"]) == ("cancelled", "CANCELLED")
    assert generations.current(_snapshot_dir(app, body["snapshot_id"])) is None
    assert _scratch(app) == []


def test_a_job_out_of_time_fails_and_publishes_nothing(app: Any) -> None:
    body = _pin(app)
    worker.run_pending(app.state.audit.store, timeout_s=0.0)
    job = _job(app, body["prepare"]["job_id"])
    assert (job["state"], job["reason"]) == ("failed", "TIMEOUT")
    assert generations.current(_snapshot_dir(app, body["snapshot_id"])) is None
    assert _scratch(app) == []


def test_a_failed_rebuild_keeps_the_last_generation_and_a_retry_is_clean(
    app: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    sid = _pin(app)["snapshot_id"]
    run_jobs(app)
    snapshot_dir = _snapshot_dir(app, sid)
    before = sorted(p.name for p in (snapshot_dir / "generations" / "1").iterdir())

    def broken(snapshot: Any, out: Path, report: Any) -> dict[str, Any]:
        out.mkdir(parents=True)
        (out / "events.db").write_text("half written")
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(worker, "build_generation", broken)
    status, job = _post(app, "/jobs", {"kind": "prepare", "snapshot_id": sid, "options": {"force": True}})  # fmt: skip
    run_jobs(app)
    failed = _job(app, job["job_id"])
    assert (failed["state"], failed["reason"]) == ("failed", "JOB_ERROR")
    assert "disk on fire" in failed["detail"]
    assert generations.current(snapshot_dir) == 1
    assert (
        sorted(p.name for p in (snapshot_dir / "generations" / "1").iterdir()) == before
    )
    assert _scratch(app) == []
    assert _get(app, f"/events?snapshot_id={sid}")[0] == 200
    monkeypatch.setattr(worker, "build_generation", build_module.build_generation)
    status, retry = _post(app, "/jobs", {"kind": "prepare", "snapshot_id": sid, "options": {"force": True}})  # fmt: skip
    assert retry["job_id"] != job["job_id"]
    run_jobs(app)
    assert generations.current(snapshot_dir) == 2
    assert sorted(p.name for p in (snapshot_dir / "generations").iterdir()) == [
        "1",
        "2",
    ]


def test_too_little_disk_is_unavailable(app: Any) -> None:
    body = _pin(app)
    worker.run_pending(app.state.audit.store, min_free_mb=10**12)
    job = _job(app, body["prepare"]["job_id"])
    assert (job["state"], job["reason"]) == ("unavailable", "DISK_LOW")


# --- verify and forensics_import ------------------------------------------------------


def test_verify_reports_each_pinned_file_and_the_manifest_now(tmp_path: Path) -> None:
    world = build(tmp_path / "w", rotated=True)
    app = make_audit_app(world)
    sid = _pin(app)["snapshot_id"]
    run_jobs(app)
    status, job = _post(app, "/jobs", {"kind": "verify", "snapshot_id": sid})
    run_jobs(app)
    content = _get(app, f"/results/{job['job_id']}")[1]["content"]
    assert {f["state"] for f in content["files"]} == {"ok"}
    assert content["manifest"]["state"] == "absent" and content["checked_at"]
    part = next(world.data.glob("audit/audit-*.log"))
    part.write_text(part.read_text().replace("TRADER02", "TRADER09", 1))
    status, job = _post(app, "/jobs", {"kind": "verify", "snapshot_id": sid})
    run_jobs(app)
    states = {f["name"]: f["state"] for f in _get(app, f"/results/{job['job_id']}")[1]["content"]["files"]}  # fmt: skip
    assert states[f"audit/{part.name}"] == "changed"


def test_forensics_import_checks_a_report_against_the_snapshot(tmp_path: Path) -> None:
    world = build(tmp_path / "w", forensics_report=True)
    app = make_audit_app(world)
    sid = _pin(app)["snapshot_id"]
    run_jobs(app)
    status, job = _post(app, "/jobs", {"kind": "forensics_import", "snapshot_id": sid})
    run_jobs(app)
    content = _get(app, f"/results/{job['job_id']}")[1]["content"]
    assert (content["available"], content["inputs_match"]) == (True, True)
    assert content["sha256"] == content["pinned_sha256"]
    assert content["statuses"]["FAIL"] == 1
    assert world.forensics_report is not None
    world.forensics_report.unlink()
    status, job = _post(app, "/jobs", {"kind": "forensics_import", "snapshot_id": sid})
    run_jobs(app)
    gone = _job(app, job["job_id"])
    assert (gone["state"], gone["reason"]) == ("unavailable", "NOT_ATTACHED")


# --- The real worker process ------------------------------------------------------


@pytest.fixture
def launched(base: World, tmp_path: Path) -> Iterator[Any]:
    """The app with a real worker process, as the gateway runs it."""
    application = make_audit_app(base)
    store = tmp_path / "store"
    launcher = WorkerLauncher(store)
    application.state.audit = AuditService(application.state.audit.collections.values(), store, launcher)  # fmt: skip
    try:
        yield application
    finally:
        launcher.stop()


def test_killing_the_worker_fails_its_job_with_a_reason(
    launched: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(worker.STALL_ENV, "60")
    started = time.monotonic()
    body = _pin(launched)
    job_id = body["prepare"]["job_id"]
    running = _until(lambda: (j := _job(launched, job_id))["state"] == "running" and j, "the worker to run it")  # fmt: skip
    assert running["heartbeat_at"]
    # The worker beats while it works.
    beat = running["heartbeat_at"]
    _until(
        lambda: _job(launched, job_id)["heartbeat_at"] != beat,
        "a second heartbeat",
        3.0,
    )
    assert time.monotonic() - started < 15
    service = launched.state.audit
    pid = service.launcher.pid
    assert pid is not None and _until(lambda: _scratch(launched), "its scratch")
    os.kill(pid, signal.SIGKILL)
    _until(lambda: service.launcher.pid != pid or not service.launcher.alive(pid), "the worker to die")  # fmt: skip
    job = _job(launched, job_id)  # the read reconciles
    assert (job["state"], job["reason"]) == ("failed", "WORKER_LOST")
    assert _scratch(launched) == []
    assert generations.current(_snapshot_dir(launched, body["snapshot_id"])) is None


def test_the_api_process_never_reconstructs(
    launched: Any, base: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every read is served from the worker's generation: the replay
    pipeline and the market build are poisoned in this (the API) process."""
    from edumatcher.audit.replay import facts, pipeline
    from edumatcher.audit.service import market

    def poisoned(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("the API process reconstructed")

    monkeypatch.setattr(facts, "normalise", poisoned)
    monkeypatch.setattr(pipeline.Reconstruction, "__init__", poisoned)
    monkeypatch.setattr(market.MarketModel, "__init__", poisoned)
    monkeypatch.setattr(build_module, "build_generation", poisoned)
    t0 = time.monotonic()
    body = _pin(launched)
    ack = time.monotonic() - t0
    sid = body["snapshot_id"]
    _until(
        lambda: _job(launched, body["prepare"]["job_id"])["state"] == "succeeded",
        "prepare",
    )
    assert ack < 5
    for path in (
        f"/events?snapshot_id={sid}",
        f"/findings?snapshot_id={sid}",
        f"/market/AAA/heatmap?snapshot_id={sid}",
        f"/market/AAA/lifelines?snapshot_id={sid}",
        f"/stories/order/{base.orders['layer_1']}?snapshot_id={sid}",
    ):
        status, page = _get(launched, path)
        assert status == 200, (path, page)
    # Job acknowledgement: well under a second once pinned.
    t0 = time.monotonic()
    status, _ = _post(launched, "/jobs", {"kind": "verify", "snapshot_id": sid})
    assert status == 202 and time.monotonic() - t0 < 1.0


def test_a_job_never_carries_a_host_path(app: Any, base: World) -> None:
    sid = _pin(app)["snapshot_id"]
    run_jobs(app)
    status, job = _post(app, "/jobs", {"kind": "verify", "snapshot_id": sid})
    run_jobs(app)
    status, result = _get(app, f"/results/{job['job_id']}")
    assert str(base.data) not in str(job) + str(result)
