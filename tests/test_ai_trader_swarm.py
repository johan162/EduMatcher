from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

import edumatcher.ai_trader.swarm as swarm_main

from edumatcher.ai_trader.preset import get_preset
from edumatcher.ai_trader.swarm import (
    MAX_RESTARTS_PER_HOUR,
    RESTART_BACKOFF_MIN,
    Supervisor,
    WorkerJob,
    assign_symbols,
    build_gateway_ids,
    default_worker_count,
    missing_participants,
    split_blocks,
    resolve_settings,
    select_symbols,
)
from edumatcher.ai_trader.worker import AgentSpec


@pytest.fixture(autouse=True)
def _all_bots_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    """main() checks bot ids against the deployed config; tests have none."""
    monkeypatch.setattr(swarm_main, "missing_participants", lambda _ids, _cfg: [])


def _fake_parser(namespace: argparse.Namespace) -> argparse.ArgumentParser:
    """A stand-in for build_parser() whose parse_args() ignores argv."""
    parser = argparse.ArgumentParser()
    parser.parse_args = lambda *a, **kw: namespace
    return parser


class TestSwarmHelpers:
    def test_build_gateway_ids(self) -> None:
        ids = build_gateway_ids("AI", 1, 3)
        assert ids == ["AI001", "AI002", "AI003"]

    def test_build_gateway_ids_design_limit_sorts_numerically(self) -> None:
        ids = build_gateway_ids("AI", 1, 500)
        assert len(ids) == 500
        assert ids[0] == "AI001" and ids[-1] == "AI500"
        assert ids == sorted(ids)

    @pytest.mark.parametrize(
        ("start", "count"), [(0, 1), (1, 0), (1, 1000), (999, 2), (-5, 3)]
    )
    def test_build_gateway_ids_out_of_range(self, start: int, count: int) -> None:
        with pytest.raises(ValueError, match="out of range"):
            build_gateway_ids("AI", start, count)

    def test_assign_symbols_more_bots_than_symbols(self) -> None:
        mapping = assign_symbols(
            ["AI001", "AI002", "AI003", "AI004"],
            ["AAPL", "MSFT"],
        )
        assert mapping == {
            "AI001": ["AAPL"],
            "AI002": ["MSFT"],
            "AI003": ["AAPL"],
            "AI004": ["MSFT"],
        }

    def test_assign_symbols_fewer_bots_covers_every_symbol(self) -> None:
        symbols = [f"S{i:03d}" for i in range(150)]
        mapping = assign_symbols(build_gateway_ids("AI", 1, 10), symbols)
        traded = sorted(sym for syms in mapping.values() for sym in syms)
        assert traded == symbols
        assert all(len(syms) == 15 for syms in mapping.values())

    def test_assign_symbols_per_agent_stacks_evenly(self) -> None:
        symbols = [f"S{i:03d}" for i in range(300)]
        mapping = assign_symbols(build_gateway_ids("AI", 1, 500), symbols, 10)
        assert all(len(v) == 10 and len(set(v)) == 10 for v in mapping.values())
        assert mapping["AI001"] == symbols[:10]
        assert mapping["AI031"] == symbols[:10]  # wraps after 30 agents
        load = Counter(sym for v in mapping.values() for sym in v)
        assert set(load) == set(symbols)
        assert max(load.values()) - min(load.values()) <= 1

    def test_assign_symbols_per_agent_is_raised_to_cover(self) -> None:
        symbols = [f"S{i:03d}" for i in range(150)]
        mapping = assign_symbols(build_gateway_ids("AI", 1, 20), symbols, 2)
        assert all(len(v) == 8 for v in mapping.values())
        assert {s for v in mapping.values() for s in v} == set(symbols)

    def test_assign_symbols_per_agent_capped_by_universe(self) -> None:
        mapping = assign_symbols(["AI001"], ["AAPL", "MSFT"], 10)
        assert mapping == {"AI001": ["AAPL", "MSFT"]}

    def test_missing_participants(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        class _Cfg:
            allowed_fix_gateways = frozenset({"AI001", "TRADER01"})

        monkeypatch.setattr(swarm_main, "load_engine_config", lambda _p: _Cfg())
        missing = missing_participants(["AI001", "AI002"], tmp_path / "cfg.yaml")
        assert missing == ["AI002"]

    @pytest.mark.parametrize(
        ("agents", "cpus", "expected"),
        [(500, 8, 5), (500, 4, 3), (20, 8, 1), (1, 16, 1), (500, 1, 1)],
    )
    def test_default_worker_count(self, agents: int, cpus: int, expected: int) -> None:
        assert default_worker_count(agents, cpus) == expected

    def test_split_blocks_contiguous_and_even(self) -> None:
        specs = _specs(500)
        blocks = split_blocks(specs, 3)
        assert [len(b) for b in blocks] == [167, 167, 166]
        assert [s for b in blocks for s in b] == specs
        assert blocks[1][0].gateway_id == "AI168"

    def test_split_blocks_never_empty(self) -> None:
        assert [len(b) for b in split_blocks(_specs(2), 5)] == [1, 1]

    def test_select_symbols(self) -> None:
        deployed = ["AAPL", "MSFT", "TSLA"]
        assert select_symbols(deployed, [], []) == deployed
        assert select_symbols(deployed, ["TSLA", "AAPL"], ["AAPL"]) == ["TSLA"]
        assert select_symbols(deployed, [], ["MSFT"]) == ["AAPL", "TSLA"]

    def test_select_symbols_rejects_unknown(self) -> None:
        with pytest.raises(ValueError, match="NOPE"):
            select_symbols(["AAPL"], ["NOPE"], [])


def _specs(n: int) -> list[AgentSpec]:
    preset = get_preset("noise-retail")
    return [
        AgentSpec(gw, preset, [], i)
        for i, gw in enumerate(build_gateway_ids("AI", 1, n))
    ]


def _deployed(monkeypatch: pytest.MonkeyPatch, symbols: list[str]) -> None:
    class _Cfg:
        allowed_symbols = frozenset(symbols)

    monkeypatch.setattr(swarm_main, "load_engine_config", lambda _p: _Cfg())


def _args(**overrides: Any) -> argparse.Namespace:
    values: dict[str, Any] = dict(
        count=2,
        prefix="AI",
        start_index=1,
        swarm=None,
        presets="scalper,contrarian",
        symbols=None,
        seed_base=1,
        duration=1.0,
        workers=0,
        budget=0.0,
        alf_host="127.0.0.1",
        alf_port=5565,
        log_level=None,
        verbose=0,
        quiet=False,
        log_target=None,
        log_file=None,
        log_failover_timeout=None,
    )
    values.update(overrides)
    return argparse.Namespace(**values)


class TestSwarmMain:
    @pytest.fixture()
    def jobs(self, monkeypatch: pytest.MonkeyPatch) -> list[list[WorkerJob]]:
        seen: list[list[WorkerJob]] = []

        class _Sup:
            def __init__(self, jobs: list[WorkerJob], duration: float) -> None:
                seen.append(jobs)

            def stop(self, *_a: object) -> None:
                return

            def run(self) -> int:
                return 0

        monkeypatch.setattr(swarm_main, "Supervisor", _Sup)
        monkeypatch.setattr(
            "edumatcher.ai_trader.swarm.signal.signal", lambda *_a: None
        )
        return seen

    def _run(self, monkeypatch: pytest.MonkeyPatch, args: argparse.Namespace) -> object:
        monkeypatch.setattr(swarm_main, "build_parser", lambda: _fake_parser(args))
        with pytest.raises(SystemExit) as exc:
            swarm_main.main()
        return exc.value.code

    def test_parse_args_logging_flags(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "sys.argv",
            ["pm-ai-swarm", "--count", "1", "-vv", "--quiet", "--log-level", "ERROR"],
        )
        args = swarm_main.build_parser().parse_args()
        assert args.count == 1
        assert args.verbose == 2
        assert args.quiet is True
        assert args.log_level == "ERROR"
        assert args.duration is None  # unset: config file or default decides
        assert swarm_main.DEFAULTS["duration"] == 0.0  # long-running by default

    def test_jobs_cover_every_agent_and_symbol(
        self, monkeypatch: pytest.MonkeyPatch, jobs: list[list[WorkerJob]]
    ) -> None:
        symbols = [f"S{i:03d}" for i in range(300)]
        _deployed(monkeypatch, symbols)
        code = self._run(
            monkeypatch, _args(count=500, workers=3, budget=900.0, verbose=1)
        )
        assert code == 0
        (job_list,) = jobs
        assert [j.name for j in job_list] == [
            "w1-AI001-AI167",
            "w2-AI168-AI334",
            "w3-AI335-AI500",
        ]
        specs = [s for j in job_list for s in j.specs]
        assert [s.gateway_id for s in specs] == build_gateway_ids("AI", 1, 500)
        assert sorted({sym for s in specs for sym in s.symbols}) == symbols
        assert [s.preset.name for s in specs[:3]] == [
            "scalper",
            "contrarian",
            "scalper",
        ]
        assert len({s.seed for s in specs}) == 500
        assert sum(j.budget or 0 for j in job_list) == pytest.approx(900.0)
        assert job_list[0].log["verbose"] == 1
        assert job_list[0].alf_port == 5565

    def test_no_budget_means_none(
        self, monkeypatch: pytest.MonkeyPatch, jobs: list[list[WorkerJob]]
    ) -> None:
        _deployed(monkeypatch, ["AAPL"])
        self._run(monkeypatch, _args())
        assert [j.budget for j in jobs[0]] == [None]

    def test_main_count_must_be_positive(self, monkeypatch: pytest.MonkeyPatch) -> None:
        assert self._run(monkeypatch, _args(count=0)) == "--count must be > 0"

    def test_main_no_symbols(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _deployed(monkeypatch, [])
        assert self._run(monkeypatch, _args()) == "No symbols available for swarm"

    def test_config_file_with_flag_overrides(
        self,
        monkeypatch: pytest.MonkeyPatch,
        jobs: list[list[WorkerJob]],
        tmp_path: Path,
    ) -> None:
        cfg = tmp_path / "swarm.yaml"
        cfg.write_text(
            "version: 1\n"
            "agents: {count: 30}\n"
            "workers: 2\n"
            "budget: 60\n"
            "composition: {scalper: 2, noise-retail: 1}\n"
            "symbols: {exclude: [MSFT]}\n"
        )
        _deployed(monkeypatch, ["AAPL", "MSFT", "TSLA"])
        self._run(
            monkeypatch,
            _args(swarm=cfg, presets=None, count=None, workers=None, budget=None),
        )
        (job_list,) = jobs
        specs = [s for j in job_list for s in j.specs]
        assert len(job_list) == 2 and len(specs) == 30
        names = [s.preset.name for s in specs]
        assert names.count("scalper") == 20 and names.count("noise-retail") == 10
        assert {sym for s in specs for sym in s.symbols} == {"AAPL", "TSLA"}
        assert sum(j.budget or 0 for j in job_list) == pytest.approx(60.0)

        jobs.clear()
        self._run(
            monkeypatch,
            _args(swarm=cfg, presets="contrarian", count=4, workers=None, budget=None),
        )
        specs = [s for j in jobs[0] for s in j.specs]
        assert [s.preset.name for s in specs] == ["contrarian"] * 4

    def test_bad_config_is_refused(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        cfg = tmp_path / "swarm.yaml"
        cfg.write_text("version: 1\nworkerz: 2\n")
        code = self._run(monkeypatch, _args(swarm=cfg))
        assert "unknown key 'workerz'" in str(code) and "workers" in str(code)

    def test_resolve_settings_precedence(self) -> None:
        from edumatcher.ai_trader.swarm_config import SwarmFile

        args = argparse.Namespace(**{k: None for k in swarm_main.DEFAULTS})
        args.count = 7
        resolve_settings(args, SwarmFile({"count": 9, "workers": 3}, None, []))
        assert (args.count, args.workers, args.prefix) == (7, 3, "AI")


class _Proc:
    def __init__(self, alive: bool = True, exitcode: int | None = None) -> None:
        self.alive = alive
        self.exitcode = exitcode
        self.name = "p"
        self.terminated = False

    def is_alive(self) -> bool:
        return self.alive

    def terminate(self) -> None:
        self.terminated = True
        self.alive = False

    def join(self, _timeout: float | None = None) -> None:
        return

    def kill(self) -> None:
        self.alive = False


class TestSupervisor:
    def _sup(
        self, monkeypatch: pytest.MonkeyPatch, duration: float = 0.0
    ) -> Supervisor:
        job = WorkerJob("w1", _specs(2), "127.0.0.1", 5565, None, {})
        sup = Supervisor([job], duration=duration)
        spawned: list[float] = []

        def _spawn(slot: Any, now: float) -> None:
            spawned.append(now)
            slot.proc = _Proc()
            slot.restart_at = None

        monkeypatch.setattr(sup, "_spawn", _spawn)
        sup.spawned = spawned  # type: ignore[attr-defined]
        return sup

    def test_crashed_worker_restarts_with_backoff(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sup = self._sup(monkeypatch)
        slot = sup.slots[0]
        slot.proc = _Proc(alive=False, exitcode=-9)
        sup._check(slot, 100.0)
        assert slot.restart_at == 100.0 + RESTART_BACKOFF_MIN
        sup._check(slot, 100.5)
        assert sup.spawned == []  # type: ignore[attr-defined]
        sup._check(slot, 101.0)
        assert sup.spawned == [101.0]  # type: ignore[attr-defined]
        slot.proc = _Proc(alive=False, exitcode=1)
        sup._check(slot, 102.0)
        assert slot.restart_at == 102.0 + 2 * RESTART_BACKOFF_MIN

    def test_gives_up_after_too_many_restarts_an_hour(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sup = self._sup(monkeypatch)
        slot = sup.slots[0]
        now = 0.0
        for _ in range(MAX_RESTARTS_PER_HOUR):
            slot.proc = _Proc(alive=False, exitcode=1)
            sup._check(slot, now)
            assert slot.restart_at is not None
            now = slot.restart_at
            sup._check(slot, now)
        slot.proc = _Proc(alive=False, exitcode=1)
        sup._check(slot, now)
        assert slot.done and slot.gave_up

    def test_restart_budget_recovers_after_an_hour(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sup = self._sup(monkeypatch)
        slot = sup.slots[0]
        slot.restarts.extend([0.0] * MAX_RESTARTS_PER_HOUR)
        slot.backoff = 60.0
        slot.proc = _Proc(alive=False, exitcode=1)
        sup._check(slot, 3601.0)
        assert not slot.done
        assert slot.restart_at == 3601.0 + RESTART_BACKOFF_MIN

    def test_worker_that_ran_its_duration_is_done(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sup = self._sup(monkeypatch, duration=60.0)
        slot = sup.slots[0]
        slot.proc = _Proc(alive=False, exitcode=0)
        sup._check(slot, 61.0)
        assert slot.done and not slot.gave_up

    def test_clean_exit_without_duration_is_restarted(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sup = self._sup(monkeypatch)
        slot = sup.slots[0]
        slot.proc = _Proc(alive=False, exitcode=0)
        sup._check(slot, 5.0)
        assert slot.restart_at is not None

    def test_stop_terminates_every_worker(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sup = self._sup(monkeypatch)
        monkeypatch.setattr(
            "edumatcher.ai_trader.swarm.time.sleep", lambda _s: sup.stop()
        )
        assert sup.run() == 0
        proc = sup.slots[0].proc
        assert isinstance(proc, _Proc) and proc.terminated
