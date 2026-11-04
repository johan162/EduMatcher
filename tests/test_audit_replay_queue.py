"""``pm-audit-replay queue``: where an order stood in its level, and why it did
or did not trade (A8).

The scenario is scripted on the s1-basic example, so every position below is a
consequence of the engine's own priority rules, not of the narrator's.  The
level at the seed bid holds, in priority order, MM01's seed, then A (100) and B
(200) from TRADER02, then C (50), the order under inspection, from TRADER01.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest import mock

import pytest

import edumatcher.engine.main as engine_main
from edumatcher.audit.replay.cli import main
from edumatcher.audit.replay.queue import LevelQueue, OrderQueue
from edumatcher.audit.replay.rerun import Rerun
from edumatcher.config_deploy import deploy, resolve_example
from edumatcher.models.order import OrderType, Side
from edumatcher.models.trade import reset_trade_ids_for_tests, set_run_seq
from tests.engine_harness import order_payload
from tests.test_sim_forensics_rerun import Recorder


class Scenario:
    def __init__(self, data: Path) -> None:
        self.data = data
        self.ids: dict[str, str] = {}
        self.bid = 0.0
        self.seed_qty = 0

    def record(self, script: str = "base") -> Scenario:
        self.data.mkdir(parents=True)
        artifact = self.data.parent / "deployed" / "engine_config.json"
        compiled = deploy(resolve_example("s1-basic"), artifact)
        seed = compiled.engine.symbols["AAPL"].market_maker_quotes[0]
        self.bid = seed.bid_price_ticks / 100
        self.seed_qty = seed.bid_qty
        reset_trade_ids_for_tests()
        set_run_seq(1)
        rec = Recorder()
        with (
            mock.patch.object(
                engine_main,
                "_deployed_config",
                lambda: (compiled.engine, artifact.read_text(encoding="utf-8")),
            ),
            mock.patch.object(engine_main, "make_puller", lambda _: Recorder()),
            mock.patch.object(engine_main, "make_publisher", lambda _: rec),
            mock.patch.multiple(
                engine_main,
                GTC_ORDERS_FILE=self.data / "gtc_orders.json",
                GTC_COMBOS_FILE=self.data / "gtc_combos.json",
                BOOK_STATS_FILE=self.data / "book_stats.json",
            ),
        ):
            engine = engine_main.Engine(config_path=None)
            engine._startup(1)
        for gw in ("TRADER01", "TRADER02", "OPS01", "MM01"):
            rec.command(engine, "system.gateway_connect", {"gateway_id": gw})

        def buy(name: str, gw: str, qty: int) -> None:
            p = order_payload(Side.BUY, OrderType.LIMIT, qty, gw, price=self.bid)
            self.ids[name] = p["id"]
            rec.command(engine, "order.new", p)

        def sell(name: str, gw: str, qty: int) -> None:
            p = order_payload(Side.SELL, OrderType.LIMIT, qty, gw, price=self.bid)
            self.ids[name] = p["id"]
            rec.command(engine, "order.new", p)

        if script == "base":
            buy("A", "TRADER02", 100)
            buy("B", "TRADER02", 200)
            buy("C", "TRADER01", 50)
            rec.command(
                engine,
                "order.cancel",
                {"order_id": self.ids["A"], "gateway_id": "TRADER02"},
            )
            sell("S1", "OPS01", self.seed_qty + 150)  # the seed, then 150 of B
            sell("S2", "OPS01", 60)  # the rest of B (50), then 10 of C
            rec.command(
                engine,
                "order.cancel",
                {"order_id": self.ids["C"], "gateway_id": "TRADER01"},
            )
        elif script == "amend":
            buy("A", "TRADER02", 100)
            buy("B", "TRADER01", 200)
            buy("C", "TRADER02", 50)
            # More size loses time priority: B goes behind C.
            rec.command(
                engine,
                "order.amend",
                {"order_id": self.ids["B"], "gateway_id": "TRADER01", "qty": 300},
            )
        elif script == "iceberg":
            p = order_payload(
                Side.BUY,
                OrderType.ICEBERG,
                1000,
                "TRADER02",
                price=self.bid,
                visible_qty=100,
            )
            self.ids["X"] = p["id"]
            rec.command(engine, "order.new", p)
            buy("C", "TRADER01", 50)
            # The seed and X's 100-share slice; X's refill joins behind C.
            sell("S1", "OPS01", self.seed_qty + 100)
        elif script.startswith("stop"):
            # A sell stop-limit: armed at the seed bid, limit one tick above.
            trigger = self.bid if script == "stop" else round(self.bid - 0.5, 2)
            p = order_payload(
                Side.SELL,
                OrderType.STOP_LIMIT,
                40,
                "TRADER01",
                price=round(self.bid + 0.01, 2),
                stop_price=trigger,
            )
            self.ids["T"] = p["id"]
            rec.command(engine, "order.new", p)
            # The whole seed bid trades at the bid: the stop fires, rests.
            sell("S1", "OPS01", self.seed_qty)
            if script == "stop_cancelled":
                rec.command(
                    engine,
                    "order.cancel",
                    {"order_id": self.ids["T"], "gateway_id": "TRADER01"},
                )
        (self.data / "audit.log").write_text("".join(rec.lines))
        return self


@pytest.fixture
def scenario(tmp_path: Path) -> Scenario:
    return Scenario(tmp_path / "data").record()


def planted(scenario: Scenario, find: str, old: str, new: str) -> None:
    """Rewrite *old* to *new* on the first audit line containing *find*."""
    path = scenario.data / "audit.log"
    lines = path.read_text().splitlines(keepends=True)
    i = next(k for k, ln in enumerate(lines) if find in ln)
    lines[i] = lines[i].replace(old, new, 1)
    path.write_text("".join(lines))


def watch(scenario: Scenario, observer: Any) -> None:
    r = Rerun(scenario.data)
    r.observers.append(observer)
    r.run()


def order_text(scenario: Scenario, name: str, *, anonymise: bool = False) -> str:
    q = OrderQueue(scenario.ids[name], anonymise=anonymise)
    watch(scenario, q)
    return q.render()


class TestOrderView:
    def test_it_rests_behind_the_seed_and_both_earlier_orders(
        self, scenario: Scenario
    ) -> None:
        out = order_text(scenario, "C")
        assert "rested at" in out
        assert "4 of 4 in its level" in out
        ahead = scenario.seed_qty + 100 + 200
        assert f"{ahead:,} shares ahead" in out.replace(",", ",")

    def test_a_cancel_ahead_moves_it_up_and_says_why(self, scenario: Scenario) -> None:
        out = order_text(scenario, "C")
        assert "3 of 3 in its level" in out
        assert "cancelled by its owner" in out

    def test_a_trade_ahead_names_the_quantity_and_the_trade(
        self, scenario: Scenario
    ) -> None:
        out = order_text(scenario, "C")
        assert "traded ahead" in out
        assert "150 shares" in out

    def test_its_own_fill_is_reported_and_the_queue_is_empty_ahead(
        self, scenario: Scenario
    ) -> None:
        out = order_text(scenario, "C")
        assert "filled 10" in out
        assert "1 of 1 in its level" in out

    def test_the_verdict_for_an_order_cancelled_with_quantity_left(
        self, scenario: Scenario
    ) -> None:
        out = order_text(scenario, "C")
        last = out.strip().splitlines()[-1]
        assert last.startswith("verdict:")
        assert "cancelled by its owner with 40 of 50 shares unfilled" in last
        assert "trades at its price" in last

    def test_an_order_that_filled_at_once_has_no_queue(
        self, scenario: Scenario
    ) -> None:
        out = order_text(scenario, "S2")
        assert "never rested" in out or "filled" in out.splitlines()[-1]

    def test_an_unknown_order_is_unavailable(self, scenario: Scenario) -> None:
        q = OrderQueue("0" * 32)
        watch(scenario, q)
        assert q.rid is None
        assert "not in the trail" in q.render()

    def test_a_prefix_finds_the_order(self, scenario: Scenario) -> None:
        q = OrderQueue(scenario.ids["C"][:10])
        watch(scenario, q)
        assert q.rid is not None


class TestPriority:
    def test_an_amend_that_adds_size_sends_it_to_the_back(self, tmp_path: Path) -> None:
        sc = Scenario(tmp_path / "data").record("amend")
        out = order_text(sc, "B")
        assert "3 of 3 in its level" in out
        assert "its priority was reset" in out
        assert "TRADER02's order (50 shares) is now ahead of it" in out
        assert "4 of 4 in its level" in out.strip().splitlines()[-2]

    def test_only_the_displayed_slice_of_an_iceberg_stands_ahead(
        self, tmp_path: Path
    ) -> None:
        sc = Scenario(tmp_path / "data").record("iceberg")
        out = order_text(sc, "C")
        # The seed (1,000) and the iceberg's 100-share slice, not its 1,000.
        assert f"{sc.seed_qty + 100:,} shares ahead" in out
        # The refill joined the back of the level, behind this order.
        assert "1 of 2 in its level, 0 shares ahead" in out


class TestStops:
    """A stop waits outside the book (OrderBook.checkpoint's stop lists) until
    a trade fires it; it was reported as "never queued" (review 2026-11-05)."""

    def test_a_stop_that_fires_and_rests_is_followed_into_its_level(
        self, tmp_path: Path
    ) -> None:
        sc = Scenario(tmp_path / "data").record("stop")
        out = order_text(sc, "T")
        assert "never rested" not in out and "never queued" not in out
        assert f"armed: a STOP_LIMIT stop at {sc.bid:.2f}" in out
        assert f"triggered by a trade at {sc.bid:.2f}" in out
        assert "now a LIMIT order" in out
        assert f"rested at {sc.bid + 0.01:.2f}: 1 of 1 in its level" in out
        assert (
            out.strip()
            .splitlines()[-1]
            .startswith("verdict: still resting at the end of the trail: 1 of 1")
        )

    def test_a_stop_never_reached_is_still_armed(self, tmp_path: Path) -> None:
        sc = Scenario(tmp_path / "data").record("stop_armed")
        out = order_text(sc, "T")
        assert "rested" not in out
        assert out.strip().splitlines()[-1] == (
            f"verdict: still armed at the end of the trail; its stop "
            f"{sc.bid - 0.5:.2f} was never reached"
        )

    def test_a_stop_cancelled_while_armed_never_triggered(self, tmp_path: Path) -> None:
        sc = Scenario(tmp_path / "data").record("stop_cancelled")
        out = order_text(sc, "T")
        assert out.strip().splitlines()[-1] == (
            f"verdict: it never triggered; cancelled by its owner while armed "
            f"(its stop {sc.bid - 0.5:.2f} was never reached)"
        )


class TestTheTraceAgrees:
    def test_a_matching_trace_says_nothing(self, scenario: Scenario) -> None:
        assert "differs" not in order_text(scenario, "C")

    def test_a_trace_that_disagrees_is_reported(self, scenario: Scenario) -> None:
        planted(
            scenario,
            f'"order_id": "{scenario.ids["C"]}", "priority_seq"',
            '"priority_seq": ',
            '"priority_seq": 9',
        )
        out = order_text(scenario, "C")
        assert "engine.trace" in out and "differs" in out


class TestAnonymise:
    def test_other_gateways_become_labels_and_the_inspected_one_stays(
        self, scenario: Scenario
    ) -> None:
        out = order_text(scenario, "C", anonymise=True)
        assert "TRADER02" not in out
        assert "OPS01" not in out
        assert "MM01" not in out
        assert "TRADER01" in out or "this order" in out
        assert "gateway A" in out

    def test_it_does_not_show_how_much_of_an_iceberg_is_hidden(self) -> None:
        from edumatcher.audit.replay.queue import shares

        iceberg = {"remaining_qty": 5000, "displayed_qty": 100}
        assert shares(iceberg, anonymise=False) == 5000
        assert shares(iceberg, anonymise=True) == 100


class TestLevelView:
    def level(self, scenario: Scenario) -> str:
        q = LevelQueue("AAPL", scenario.bid)
        watch(scenario, q)
        return q.render()

    def test_it_follows_the_level_through_every_change(
        self, scenario: Scenario
    ) -> None:
        out = self.level(scenario)
        lines = out.strip().splitlines()
        assert any("rested" in ln and "100" in ln for ln in lines)
        assert any("cancelled" in ln for ln in lines)
        assert any("traded" in ln for ln in lines)
        assert lines[-1].startswith("level now empty") or "empty" in lines[-1]

    def test_it_states_the_level_after_each_change(self, scenario: Scenario) -> None:
        out = self.level(scenario)
        assert "orders," in out and "shares" in out


class TestCli:
    def run(
        self, scenario: Scenario, *args: str, capsys: pytest.CaptureFixture[str]
    ) -> tuple[int, str, str]:
        code = main(["--log-file", str(scenario.data / "audit.log"), "queue", *args])
        cap = capsys.readouterr()
        return code, cap.out, cap.err

    def test_order_view(
        self, scenario: Scenario, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code, out, _ = self.run(scenario, "--order", scenario.ids["C"], capsys=capsys)
        assert code == 0
        assert "verdict:" in out

    def test_level_view(
        self, scenario: Scenario, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code, out, _ = self.run(
            scenario,
            "--symbol",
            "AAPL",
            "--price",
            str(scenario.bid),
            capsys=capsys,
        )
        assert code == 0
        assert "traded" in out

    def test_one_view_must_be_chosen(
        self, scenario: Scenario, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code, _, err = self.run(scenario, capsys=capsys)
        assert code == 2
        assert "--order" in err

    def test_an_unknown_order_exits_one(
        self, scenario: Scenario, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code, out, _ = self.run(scenario, "--order", "f" * 32, capsys=capsys)
        assert code == 1
        assert "not in the trail" in out

    def test_a_trail_that_cannot_be_rerun_exits_three(
        self, scenario: Scenario, capsys: pytest.CaptureFixture[str]
    ) -> None:
        log = scenario.data / "audit.log"
        log.write_text(
            "".join(
                ln
                for ln in log.read_text().splitlines(True)
                if "[system.startup]" not in ln
            )
        )
        code, _, err = self.run(scenario, "--order", scenario.ids["C"], capsys=capsys)
        assert code == 3
        assert "cannot re-run" in err
