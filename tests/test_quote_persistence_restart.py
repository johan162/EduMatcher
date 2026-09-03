"""
Holistic restart tests for quote-leg persistence (§5) and its interaction
with TIF=DAY persistence (§12-§13) — see
docs-design/EduMatcher-Revised-Quote-Persistence.md, §7's implementation
plan.

Unlike the unit-level tests in test_engine_durability.py and
test_engine_coverage_final.py, which exercise _shutdown()/_restore_gtc() in
isolation, these tests drive the whole intended flow end to end: a live
quote is submitted through the engine's real command handler
(_handle_quote_new), the engine is shut down, a *second* engine instance is
built from the same persisted files (mirroring two separate process runs
against one data directory), and _restore_gtc() + _load_config() are called
in run()'s actual order. This is the shape that actually verifies the
design's intent — "a quote survives a restart and does not duplicate" — not
just that each half works correctly on its own.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from edumatcher.engine.config_loader import MMQuoteSeed, SymbolConfig
from edumatcher.models.order import TIF

from .engine_harness import connect, make_engine, msgs, resting_ids, submit_quote

GW = "MM01"


def _persist_and_reopen(
    monkeypatch,
    tmp_path: Path,
    engine1,
    *,
    symbol_configs,
    gateways=(GW,),
    mm_gateways=(GW,),
):
    """Shut engine1 down (persisting to real files under tmp_path), then
    build and start a second Engine reading those same files back — the
    same on-disk contract two separate `pm-engine` process runs would use.
    """
    gtc_file = tmp_path / "gtc_orders.json"
    combos_file = tmp_path / "gtc_combos.json"
    stats_file = tmp_path / "book_stats.json"
    with (
        patch("edumatcher.engine.main.GTC_ORDERS_FILE", gtc_file),
        patch("edumatcher.engine.main.GTC_COMBOS_FILE", combos_file),
        patch("edumatcher.engine.main.BOOK_STATS_FILE", stats_file),
    ):
        engine1._shutdown()

    from edumatcher.engine.persistence import load_gtc_orders

    persisted_orders = load_gtc_orders(gtc_file)

    engine2, pub_sock2 = make_engine(
        monkeypatch,
        tmp_path,
        symbols=tuple(symbol_configs.keys()),
        symbol_configs=symbol_configs,
        gateways=gateways,
        mm_gateways=mm_gateways,
        gtc_orders=persisted_orders,
        run_seq=2,
    )
    engine2._restore_gtc()
    engine2._load_config()
    return engine2, pub_sock2


def test_gtc_quote_survives_restart_without_duplicating(monkeypatch, tmp_path):
    """A live TIF=GTC quote, submitted through the real command handler, is
    still the same two orders after a restart — not duplicated by a fresh
    config seed. Exercises §5.2 (persist) + §5.3 (QuoteIndex rebuild) +
    §5.4 (seed_once gates on the rebuilt index) together."""
    symbol_configs = {
        "AAPL": SymbolConfig(
            name="AAPL",
            market_maker_quotes=[
                MMQuoteSeed(
                    gateway_id=GW,
                    bid_price=99.95,
                    ask_price=100.05,
                    bid_qty=100,
                    ask_qty=100,
                    tif=TIF.GTC,
                    quote_id="SEED-1",
                    seed_once=True,
                )
            ],
        )
    }
    engine1, pub_sock1 = make_engine(
        monkeypatch,
        tmp_path,
        symbols=("AAPL",),
        symbol_configs=symbol_configs,
        gateways=(GW,),
        mm_gateways=(GW,),
    )
    engine1._restore_gtc()
    engine1._load_config()  # first-ever startup: seed fires
    connect(engine1, GW)

    seeded_entry = engine1._quote_index.get(GW, "AAPL")
    assert seeded_entry is not None
    seeded_ids = {seeded_entry.bid_order_id, seeded_entry.ask_order_id}
    assert resting_ids(engine1.books["AAPL"]) == seeded_ids

    engine2, _ = _persist_and_reopen(
        monkeypatch, tmp_path, engine1, symbol_configs=symbol_configs
    )

    restored_entry = engine2._quote_index.get(GW, "AAPL")
    assert restored_entry is not None
    restored_ids = {restored_entry.bid_order_id, restored_entry.ask_order_id}
    # Exactly the same two order ids — restored, not re-seeded on top.
    assert restored_ids == seeded_ids
    assert resting_ids(engine2.books["AAPL"]) == seeded_ids
    assert engine2._quote_index.active_count() == 1


def test_default_tif_day_seed_quote_survives_same_day_restart(monkeypatch, tmp_path):
    """The common case per §13.7: a seed left at the config default
    (tif: DAY) now also survives a same-day restart without needing an
    explicit tif: GTC override — closing one of the two original root
    causes in §3.1 on top of §3.2/§3.3."""
    symbol_configs = {
        "AAPL": SymbolConfig(
            name="AAPL",
            market_maker_quotes=[
                MMQuoteSeed(
                    gateway_id=GW,
                    bid_price=99.95,
                    ask_price=100.05,
                    bid_qty=100,
                    ask_qty=100,
                    tif=TIF.DAY,  # the config default — deliberately not GTC
                    quote_id="SEED-1",
                    seed_once=True,
                )
            ],
        )
    }
    engine1, _ = make_engine(
        monkeypatch,
        tmp_path,
        symbols=("AAPL",),
        symbol_configs=symbol_configs,
        gateways=(GW,),
        mm_gateways=(GW,),
    )
    engine1._restore_gtc()
    engine1._load_config()
    seeded_entry = engine1._quote_index.get(GW, "AAPL")
    assert seeded_entry is not None
    seeded_ids = {seeded_entry.bid_order_id, seeded_entry.ask_order_id}

    engine2, _ = _persist_and_reopen(
        monkeypatch, tmp_path, engine1, symbol_configs=symbol_configs
    )

    restored_entry = engine2._quote_index.get(GW, "AAPL")
    assert restored_entry is not None
    restored_ids = {restored_entry.bid_order_id, restored_entry.ask_order_id}
    assert restored_ids == seeded_ids, (
        "a same-day TIF=DAY seed quote must restore, not re-seed, on a "
        "same-day restart"
    )


def test_fully_hit_quote_is_reseeded_on_next_restart(monkeypatch, tmp_path):
    """§3.3's original gap, closed: once the quote is genuinely gone (both
    legs hit through / cancelled, or discarded as stale), seed_once must
    allow a fresh seed rather than leaving the book with no MM presence
    forever because book_stats.json remembers the symbol traded once."""
    symbol_configs = {
        "AAPL": SymbolConfig(
            name="AAPL",
            market_maker_quotes=[
                MMQuoteSeed(
                    gateway_id=GW,
                    bid_price=99.95,
                    ask_price=100.05,
                    bid_qty=100,
                    ask_qty=100,
                    tif=TIF.GTC,
                    quote_id="SEED-1",
                    seed_once=True,
                )
            ],
        )
    }
    engine1, _ = make_engine(
        monkeypatch,
        tmp_path,
        symbols=("AAPL",),
        symbol_configs=symbol_configs,
        gateways=(GW,),
        mm_gateways=(GW,),
    )
    engine1._restore_gtc()
    engine1._load_config()
    connect(engine1, GW)
    entry = engine1._quote_index.get(GW, "AAPL")
    assert entry is not None

    # Simulate the quote being fully cancelled (as if both legs were hit
    # through) before this engine instance shuts down.
    engine1._quote_index.remove(GW, "AAPL", reason="test: simulate fully hit")
    for book in engine1.books.values():
        for order in list(book.resting_orders()):
            book.cancel_order(order.id)

    engine2, _ = _persist_and_reopen(
        monkeypatch, tmp_path, engine1, symbol_configs=symbol_configs
    )

    # No quote survived to be restored, so seed_once must not block a fresh
    # seed — the book must not be left with zero MM presence indefinitely.
    fresh_entry = engine2._quote_index.get(GW, "AAPL")
    assert fresh_entry is not None, (
        "seed_once incorrectly blocked re-seeding after the prior quote "
        "was fully removed"
    )


def test_stale_day_quote_is_purged_then_reseeded_on_next_restart(monkeypatch, tmp_path):
    """The full §13.7 interaction: a same-day TIF=DAY seed quote survives
    one same-day restart untouched, but is discarded — and correctly
    re-seeded, not left absent — once the business day has rolled over."""
    symbol_configs = {
        "AAPL": SymbolConfig(
            name="AAPL",
            market_maker_quotes=[
                MMQuoteSeed(
                    gateway_id=GW,
                    bid_price=99.95,
                    ask_price=100.05,
                    bid_qty=100,
                    ask_qty=100,
                    tif=TIF.DAY,
                    quote_id="SEED-1",
                    seed_once=True,
                )
            ],
        )
    }
    engine1, _ = make_engine(
        monkeypatch,
        tmp_path,
        symbols=("AAPL",),
        symbol_configs=symbol_configs,
        gateways=(GW,),
        mm_gateways=(GW,),
    )
    engine1._restore_gtc()
    engine1._load_config()
    seeded_entry = engine1._quote_index.get(GW, "AAPL")
    assert seeded_entry is not None
    # Backdate both legs to simulate them having rested since yesterday.
    import time as _time

    yesterday_ns = int(_time.time() * 1e9) - 2 * 24 * 3600 * 1_000_000_000
    for order in engine1.books["AAPL"].resting_orders():
        order.timestamp = yesterday_ns

    engine2, _ = _persist_and_reopen(
        monkeypatch, tmp_path, engine1, symbol_configs=symbol_configs
    )

    entry = engine2._quote_index.get(GW, "AAPL")
    assert entry is not None, "a fresh seed must fire once the stale quote is purged"
    assert "AAPL" not in engine2.books or resting_ids(engine2.books["AAPL"]) == {
        entry.bid_order_id,
        entry.ask_order_id,
    }, "only the fresh seed's legs should be resting, not the stale ones"


def test_mm_vs_mm_startup_crossing(monkeypatch, tmp_path):
    """§6.2: a restored quote leg from one gateway can cross a freshly
    seeded quote from a different gateway at startup, before any
    participant connects. Not a new failure mode — the same
    startup-crossing behaviour that already applies to a trader's restored
    GTC order vs. a seed — just a new pair of counterparties."""
    # MM01's quote is submitted live (below), not config-seeded — only its
    # ask leg (99.95) survives to be persisted and restored, as engineered
    # by cancelling the bid leg before shutdown.
    mm_b_config = MMQuoteSeed(
        gateway_id="MM02",
        bid_price=100.00,  # crosses MM01's restored ask (99.95) on restart
        ask_price=100.10,
        bid_qty=100,
        ask_qty=100,
        tif=TIF.GTC,
        quote_id="B1",
        seed_once=False,  # always re-seeded, simulating "the new quote"
    )
    symbol_configs = {"AAPL": SymbolConfig(name="AAPL", market_maker_quotes=[])}
    engine1, _ = make_engine(
        monkeypatch,
        tmp_path,
        symbols=("AAPL",),
        symbol_configs=symbol_configs,
        gateways=("MM01", "MM02"),
        mm_gateways=("MM01", "MM02"),
    )
    engine1._restore_gtc()
    engine1._load_config()
    connect(engine1, "MM01")
    submit_quote(
        engine1, "MM01", bid_price=99.90, ask_price=99.95, quote_id="A1", tif="GTC"
    )
    # MM01's bid leg gets hit and removed before shutdown, so only the ask
    # leg (99.95) survives to be persisted and restored.
    entry = engine1._quote_index.get("MM01", "AAPL")
    assert entry is not None
    bid_order_id = entry.bid_order_id
    engine1.books["AAPL"].cancel_order(bid_order_id)

    symbol_configs_with_seed = {
        "AAPL": SymbolConfig(name="AAPL", market_maker_quotes=[mm_b_config])
    }
    engine2, pub_sock2 = _persist_and_reopen(
        monkeypatch,
        tmp_path,
        engine1,
        symbol_configs=symbol_configs_with_seed,
        gateways=("MM01", "MM02"),
        mm_gateways=("MM01", "MM02"),
    )

    # MM01's restored ask (99.95) and MM02's freshly-seeded bid (100.00)
    # cross — a trade must fire at startup, before any gateway connects.
    trades = msgs(pub_sock2, "trade.executed")
    assert len(trades) == 1
    assert trades[0]["symbol"] == "AAPL"
