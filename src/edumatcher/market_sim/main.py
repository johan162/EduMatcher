"""pm-market-sim: publishes the market model's true value of every symbol.

The model (``market_sim.model``) steps while the exchange trades
continuously. A trading day's variance accrues over the continuous phase as
the engine reports it (its start, and the scheduler's countdown to the
close), so a day compressed with ``pm-scheduler --speed`` moves as much as a
real one; the overnight move is applied when the exchange reopens.

Values go out on pm-market-sim's own PUB socket as ``sim.value``, one batch
per step, with a ``sim.state`` heartbeat every second; ``sim.command`` comes
in on its own PULL socket, from ADMIN participants only. Both bind to
loopback by default (``EDUMATCHER_SIM_*``). The last values are saved to
``<DATA_DIR>/market_sim_state.json`` so a restart continues where the model
stood.

Usage examples:
  poetry run pm-market-sim -v
  poetry run pm-market-sim --init > market_sim.yaml
  poetry run pm-market-sim --status --id OPS01
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import signal
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import zmq

from edumatcher.config import (
    DATA_DIR,
    ENGINE_PUB_ADDR,
    ENGINE_PULL_ADDR,
    REF_DATA_DIR,
    SIM_PUB_ADDR,
    SIM_PUB_BIND_ADDR,
    SIM_PULL_ADDR,
    SIM_PULL_BIND_ADDR,
)
from edumatcher.config_artifact import load_compiled_config
from edumatcher.log_srv.config import (
    load_default_log_client_config,
    load_default_log_server_config,
    resolve_host_default,
)
from edumatcher.logclient.discovery import resolve_handler
from edumatcher.market_sim.config import (
    FILE_NAME,
    SimConfig,
    SimConfigError,
    generate_sim_config,
    load_sim_config,
)
from edumatcher.market_sim.model import ValueModel
from edumatcher.messaging.bus import (
    get_context,
    make_publisher,
    make_puller,
    make_pusher,
)
from edumatcher.market_sim.news import NewsDesk, Rumour
from edumatcher.models.generated import news as N
from edumatcher.models.generated import sim as G
from edumatcher.models.generated.book import PREFIX_BOOK_SNAPSHOT
from edumatcher.models.generated.session import TOPIC_SESSION_STATE
from edumatcher.models.generated.system import (
    TOPIC_STARTUP_RECOVERY,
    topic_session_status,
    topic_symbols,
)
from edumatcher.models.message import (
    decode,
    make_book_snapshot_request_msg,
    make_session_state_request_msg,
    make_symbols_request_msg,
)
from edumatcher.models.participant import ParticipantRole

_CLIENT_NAME = "pm-market-sim"
_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s - %(message)s"
#: Engine replies come back on topics carrying this id.
GATEWAY_ID = "MARKETSIM"
STATE_FILE = DATA_DIR / "market_sim_state.json"
#: Length of a continuous session when the engine gives no countdown to the
#: close (09:30-16:00).
DEFAULT_DAY_SEC = 6.5 * 3600
HEARTBEAT_SEC = 1.0
SAVE_SEC = 10.0
#: How long to wait for the engine's previous closes before falling back to
#: the configuration's last prices.
STARTUP_WAIT_SEC = 3.0

log = logging.getLogger(__name__)


def _parse_iso(value: Any) -> float | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


@dataclass
class SavedState:
    seq: int
    epoch: int
    values: dict[str, float]
    news_seq: int = 0
    rumours: list[Rumour] = field(default_factory=list)


def load_state(path: Path) -> SavedState | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        values = {str(k): float(v) for k, v in raw["values"].items() if float(v) > 0}
        rumours = [Rumour(**r) for r in raw.get("rumours", [])]
        return SavedState(
            int(raw["seq"]),
            int(raw["epoch"]),
            values,
            int(raw.get("news_seq", 0)),
            rumours,
        )
    except FileNotFoundError:
        return None
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        log.warning("ignoring unreadable state file %s: %s", path, exc)
        return None


def save_state(path: Path, state: SavedState) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    staged = path.with_name(path.name + ".tmp")
    staged.write_text(
        json.dumps(
            {
                "seq": state.seq,
                "epoch": state.epoch,
                "values": state.values,
                "news_seq": state.news_seq,
                "rumours": [asdict(r) for r in state.rumours],
            }
        ),
        encoding="utf-8",
    )
    os.replace(staged, path)


class MarketSim:
    """The model plus the engine's session, without sockets: callers feed it
    session events and the time, and publish what it returns."""

    def __init__(
        self,
        cfg: SimConfig,
        values: dict[str, float],
        *,
        seq: int = 0,
        epoch: int = 0,
        admins: frozenset[str] = frozenset(),
        news_seq: int = 0,
        rumours: list[Rumour] | None = None,
    ) -> None:
        self.cfg = cfg
        self.model = ValueModel(
            cfg.params,
            values,
            cfg.seed,
            overnight_fraction=cfg.overnight_fraction,
            epoch=epoch,
        )
        self.news = NewsDesk(
            cfg.params, cfg.news, cfg.seed, epoch=epoch, seq=news_seq, rumours=rumours
        )
        self.seq = seq
        self.epoch = epoch
        self.admins = admins
        self.session: str | None = None
        self.phase_since: float | None = None
        self.next_at: float | None = None
        self._last_step: float | None = None

    # --- session ----------------------------------------------------------------
    def on_session(self, state: str, next_at: float | None, now: float) -> bool:
        """Follow the engine's session; True when the phase changed."""
        state = state.upper()
        if state == self.session:
            if next_at is not None:
                self.next_at = next_at
            return False
        previous = self.session
        self.session = state
        # A phase first seen mid-way (at startup) has no known start.
        self.phase_since = now if previous is not None else None
        self.next_at = next_at
        if previous == "CLOSED":
            self.model.overnight()
            log.info("overnight move applied")
        if state == "CONTINUOUS":
            self._last_step = now
        return True

    @property
    def running(self) -> bool:
        return self.session == "CONTINUOUS"

    # --- stepping -----------------------------------------------------------------
    def due(self, now: float) -> bool:
        return (
            self.running
            and self._last_step is not None
            and now - self._last_step >= self.cfg.step_sec
        )

    def _day(self, now: float) -> tuple[float, float | None]:
        """Length of today's continuous session and how far into it ``now`` is."""
        if (
            self.phase_since is not None
            and self.next_at is not None
            and self.next_at > self.phase_since
        ):
            span = self.next_at - self.phase_since
            return span, (now - self.phase_since) / span
        return DEFAULT_DAY_SEC, None

    def step(self, now: float) -> list[list[bytes]]:
        """One model step: any news it brought, then the values."""
        assert self._last_step is not None
        # A stall (or a debugger) must not turn into one enormous move.
        dt = min(now - self._last_step, 5 * self.cfg.step_sec)
        self._last_step = now
        span, fraction = self._day(now)
        self.model.step(dt / span, fraction)
        out = [self._news_out(e, m) for e, m in self.news.tick(dt / span, now)]
        self.seq += 1
        out.append(self._values_frames(now))
        return out

    def _news_out(self, event: dict[str, Any], moves: dict[str, float]) -> list[bytes]:
        self.model.shock(moves)
        log.info(
            "news %s %s %s: %s",
            event["id"],
            event["status"],
            event["kind"],
            event["headline"],
        )
        return N.make_news_event(**event)

    def _values_frames(self, now: float) -> list[bytes]:
        return G.make_sim_value(
            seq=self.seq,
            ts_ns=int(now * 1e9),
            values=[
                {"symbol": s, "value": round(v, 4)}
                for s, v in sorted(self.model.values().items())
            ],
        )

    def state_frames(self, now: float) -> list[bytes]:
        return G.make_sim_state(
            state="RUNNING" if self.running else "PAUSED",
            session=self.session or "",
            seq=self.seq,
            ts_ns=int(now * 1e9),
            step_ns=int(self.cfg.step_sec * 1e9),
            symbols=len(self.model.params),
            seed=self.cfg.seed,
        )

    def command(self, payload: dict[str, Any], now: float) -> list[list[bytes]]:
        """Run one instructor command: the ack, preceded by any news it published."""
        gw = str(payload.get("gateway_id", "")).upper()
        cmd_id = str(payload.get("command_id", ""))

        def ack(ok: bool, reason: str, news_id: str = "") -> list[bytes]:
            return G.make_sim_command_ack(
                gateway_id=gw,
                command_id=cmd_id,
                accepted=ok,
                reason=reason[:256],
                news_id=news_id,
            )

        if gw not in self.admins:
            return [ack(False, f"{gw or '(none)'} is not an ADMIN participant")]
        action = str(payload.get("action", ""))
        if action == "STATUS":
            status = "RUNNING" if self.running else "PAUSED"
            return [
                ack(
                    True,
                    f"{status} seq={self.seq} symbols={len(self.model.params)} "
                    f"open_rumours={len(self.news.rumours)}",
                )
            ]
        if action in ("NEWS_CONFIRM", "NEWS_RETRACT"):
            news_id = str(payload.get("news_id", ""))
            done = self.news.resolve(news_id, action == "NEWS_CONFIRM", now)
            if done is None:
                return [ack(False, f"no open rumour {news_id!r}")]
            event, moves = done
            return [self._news_out(event, moves), ack(True, "published", event["id"])]
        if action == "NEWS_INJECT":
            req = payload.get("news")
            if not isinstance(req, dict):
                return [ack(False, "NEWS_INJECT needs news")]
            scope = str(req.get("scope", ""))
            targets = [str(t).upper() for t in req.get("targets") or []]
            problem = self._check_targets(scope, targets)
            if problem:
                return [ack(False, problem)]
            event, moves = self.news.publish(
                scope=scope,
                targets=targets,
                kind=str(req["kind"]),
                sentiment=float(req["sentiment"]),
                impact=float(req["impact"]),
                headline=str(req.get("headline") or ""),
                rumour=bool(req.get("rumour", False)),
                credibility=req.get("credibility"),
                now=now,
            )
            return [self._news_out(event, moves), ack(True, "published", event["id"])]
        return [ack(False, f"unknown action {action!r}")]

    def _check_targets(self, scope: str, targets: list[str]) -> str:
        if scope == "MARKET":
            return "" if not targets else "MARKET news names no targets"
        if not targets:
            return f"{scope} news needs targets"
        known = set(self.model.params) if scope == "SYMBOL" else set(self.news.sectors)
        unknown = [t for t in targets if t not in known]
        return f"unknown {scope.lower()}(s): {', '.join(unknown)}" if unknown else ""

    def saved(self) -> SavedState:
        return SavedState(
            self.seq,
            self.epoch,
            self.model.values(),
            self.news.seq,
            list(self.news.rumours.values()),
        )


def initial_values(
    cfg: SimConfig,
    saved: SavedState | None,
    prev_close: dict[str, float],
    config_price: dict[str, float],
) -> dict[str, float]:
    """Where each symbol starts: the saved value, the configured ``initial``,
    the engine's previous close, or the configuration's last price."""
    out: dict[str, float] = {}
    missing: list[str] = []
    for sym in cfg.params:
        for source in (
            saved.values if saved else {},
            cfg.initial,
            prev_close,
            config_price,
        ):
            if source.get(sym, 0) > 0:
                out[sym] = source[sym]
                break
        else:
            missing.append(sym)
    if missing:
        raise SimConfigError(
            f"no starting value for {', '.join(missing)}: give them an 'initial' "
            f"in {FILE_NAME}"
        )
    return out


def _config_prices(engine: Any) -> dict[str, float]:
    out: dict[str, float] = {}
    for sym, sc in engine.symbols.items():
        prices = [p for p in (sc.last_buy_price, sc.last_sell_price) if p]
        if prices:
            out[sym] = sum(prices) / len(prices)
    return out


class Runner:
    def __init__(self, sim: MarketSim, state_path: Path) -> None:
        self.sim = sim
        self.state_path = state_path
        self._running = True
        self.pub = make_publisher(SIM_PUB_BIND_ADDR)
        self.pull = make_puller(SIM_PULL_BIND_ADDR)
        self.push = make_pusher(ENGINE_PULL_ADDR)
        self.sub = _engine_subscriber()

    def stop(self, *_args: object) -> None:
        self._running = False

    def _ask_session(self) -> None:
        try:
            self.push.send_multipart(make_session_state_request_msg(GATEWAY_ID))
        except zmq.Again:
            pass

    def run(self) -> None:
        poller = zmq.Poller()
        poller.register(self.sub, zmq.POLLIN)
        poller.register(self.pull, zmq.POLLIN)
        next_beat = next_save = next_ask = 0.0
        try:
            while self._running:
                events = dict(poller.poll(50))
                now = time.time()
                if self.sim.session is None and now >= next_ask:
                    self._ask_session()  # until the engine answers
                    next_ask = now + 2.0
                if self.sub in events:
                    while self.sub.poll(0):
                        self._on_engine(*decode(self.sub.recv_multipart()), now)
                if self.pull in events:
                    while self.pull.poll(0):
                        topic, payload = decode(self.pull.recv_multipart())
                        if topic == G.TOPIC_SIM_COMMAND:
                            for frames in self.sim.command(payload, now):
                                self.pub.send_multipart(frames)
                if self.sim.due(now):
                    for frames in self.sim.step(now):
                        self.pub.send_multipart(frames)
                if now >= next_beat:
                    self.pub.send_multipart(self.sim.state_frames(now))
                    next_beat = now + HEARTBEAT_SEC
                if now >= next_save:
                    save_state(self.state_path, self.sim.saved())
                    next_save = now + SAVE_SEC
        finally:
            save_state(self.state_path, self.sim.saved())
            for sock in (self.pub, self.pull, self.push, self.sub):
                sock.close(linger=0)

    def _on_engine(self, topic: str, payload: dict[str, Any], now: float) -> None:
        if topic == TOPIC_SESSION_STATE:
            nxt = payload.get("next")
            at = _parse_iso(nxt.get("at")) if isinstance(nxt, dict) else None
            if self.sim.on_session(str(payload.get("state", "")), at, now):
                log.info(
                    "session %s: %s",
                    self.sim.session,
                    "running" if self.sim.running else "paused",
                )
                save_state(self.state_path, self.sim.saved())
        elif topic == topic_session_status(GATEWAY_ID):
            self.sim.on_session(str(payload.get("state", "")), None, now)
        elif topic == TOPIC_STARTUP_RECOVERY:
            log.warning("engine restarted; re-reading its session")
            self.sim.session = None  # asked again until it answers


def _engine_subscriber() -> zmq.Socket[bytes]:
    sub: zmq.Socket[bytes] = get_context().socket(zmq.SUB)
    sub.connect(ENGINE_PUB_ADDR)
    for topic in (
        TOPIC_SESSION_STATE,
        topic_session_status(GATEWAY_ID),
        topic_symbols(GATEWAY_ID),
        TOPIC_STARTUP_RECOVERY,
    ):
        sub.setsockopt(zmq.SUBSCRIBE, topic.encode())
    return sub


def engine_prev_closes(sub: zmq.Socket[bytes], wait: float) -> dict[str, float]:
    """Ask the engine for its previous closes; empty if it does not answer."""
    push = make_pusher(ENGINE_PULL_ADDR)
    deadline = time.monotonic() + wait
    next_ask = 0.0
    try:
        while time.monotonic() < deadline:
            if time.monotonic() >= next_ask:
                try:
                    push.send_multipart(make_symbols_request_msg(GATEWAY_ID))
                except zmq.Again:
                    pass
                next_ask = time.monotonic() + 0.5
            if not sub.poll(100):
                continue
            topic, payload = decode(sub.recv_multipart())
            if topic == topic_symbols(GATEWAY_ID):
                return {
                    str(e["symbol"]).upper(): float(e["prev_close"])
                    for e in payload.get("symbols", [])
                    if isinstance(e, dict) and e.get("symbol") and e.get("prev_close")
                }
    finally:
        push.close(linger=0)
    return {}


def deviations(
    values: dict[str, float], mids: dict[str, float]
) -> list[tuple[str, float]]:
    """``ln(mid / value)`` per symbol with both, widest first."""
    out = [
        (sym, math.log(mids[sym] / v))
        for sym, v in values.items()
        if v > 0 and mids.get(sym, 0) > 0
    ]
    return sorted(out, key=lambda item: -abs(item[1]))


def status(gateway_id: str, top: int, wait: float = 3.0) -> int:
    """Ask pm-market-sim where it stands and show where the market is
    furthest from the true values."""
    ctx = get_context()
    sim_sub = ctx.socket(zmq.SUB)
    sim_sub.connect(SIM_PUB_ADDR)
    for topic in (G.TOPIC_SIM_VALUE, G.topic_sim_command_ack(gateway_id)):
        sim_sub.setsockopt(zmq.SUBSCRIBE, topic.encode())
    book_sub = ctx.socket(zmq.SUB)
    book_sub.connect(ENGINE_PUB_ADDR)
    book_sub.setsockopt(zmq.SUBSCRIBE, PREFIX_BOOK_SNAPSHOT.encode())
    sim_push = ctx.socket(zmq.PUSH)
    sim_push.connect(SIM_PULL_ADDR)
    engine_push = make_pusher(ENGINE_PULL_ADDR)
    time.sleep(0.3)  # let the subscriptions take
    sim_push.send_multipart(
        G.make_sim_command(command_id="status", gateway_id=gateway_id, action="STATUS")
    )
    ack: dict[str, Any] | None = None
    values: dict[str, float] = {}
    mids: dict[str, float] = {}
    asked = False
    deadline = time.monotonic() + wait
    try:
        while time.monotonic() < deadline:
            if sim_sub.poll(50):
                topic, payload = decode(sim_sub.recv_multipart())
                if topic == G.TOPIC_SIM_VALUE:
                    values = {e["symbol"]: float(e["value"]) for e in payload["values"]}
                else:
                    ack = payload
            if values and not asked:
                for sym in values:
                    engine_push.send_multipart(make_book_snapshot_request_msg(sym))
                asked = True
            while book_sub.poll(0):
                topic, payload = decode(book_sub.recv_multipart())
                bids, asks = payload.get("bids") or [], payload.get("asks") or []
                if bids and asks:
                    sym = topic[len(PREFIX_BOOK_SNAPSHOT) :].upper()
                    mids[sym] = (float(bids[0]["price"]) + float(asks[0]["price"])) / 2
            if ack is not None:
                paused = str(ack.get("reason", "")).startswith("PAUSED")
                if (
                    paused
                    or not ack.get("accepted")
                    or (values and len(mids) >= len(values))
                ):
                    break
    finally:
        for sock in (sim_sub, book_sub, sim_push):
            sock.close(linger=0)
        engine_push.close()
    if ack is None:
        print("pm-market-sim: no answer (is it running?)")
        return 1
    if not ack.get("accepted"):
        print(f"pm-market-sim refused: {ack.get('reason', '')}")
        return 1
    print(f"pm-market-sim: {ack.get('reason', '')}")
    if not values:
        print("no values while the exchange is not trading continuously")
        return 0
    print(f"{'symbol':8} {'value':>10} {'mid':>10} {'mid/value':>10}")
    for sym, dev in deviations(values, mids)[:top]:
        print(
            f"{sym:8} {values[sym]:10.2f} {mids[sym]:10.2f} {math.exp(dev) - 1:+10.2%}"
        )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="EduMatcher market model (true values)"
    )
    from edumatcher.cli_version import add_version_argument

    add_version_argument(parser, "pm-market-sim")
    parser.add_argument(
        "--init",
        action="store_true",
        help=f"Print a {FILE_NAME} for the deployed configuration's symbols and exit",
    )
    parser.add_argument(
        "--seed", type=int, default=1, help="Seed written by --init (default: 1)"
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Show pm-market-sim's state and the widest market-vs-value gaps, and exit",
    )
    parser.add_argument(
        "--id",
        default=None,
        help="ADMIN participant ID that --status asks as",
    )
    parser.add_argument(
        "--top", type=int, default=10, help="Gaps --status lists (default: 10)"
    )
    parser.add_argument(
        "--log-level",
        choices=["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"],
        help="Logging level override (default: WARNING)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="Increase verbosity (-v: INFO, -vv: DEBUG)",
    )
    parser.add_argument(
        "-q", "--quiet", action="store_true", help="Reduce output to warnings/errors"
    )
    parser.add_argument(
        "--log-target",
        choices=["server", "stdout", "file"],
        default=None,
        help=(
            "Where this process's own operational log records go: "
            "server (default, auto-detected pm-log-srv), stdout, or file"
        ),
    )
    parser.add_argument(
        "--log-file",
        default=None,
        metavar="PATH",
        help="Operational log file path — required when --log-target file",
    )
    parser.add_argument(
        "--log-failover-timeout",
        type=float,
        default=None,
        metavar="SECONDS",
        help=(
            "Grace window before falling back to a local log file once "
            "pm-log-srv becomes unreachable (default: 30, from config)"
        ),
    )
    return parser


def _configure_logging(args: argparse.Namespace) -> None:
    if args.log_level:
        level = getattr(logging, str(args.log_level).upper(), logging.WARNING)
    elif args.verbose >= 2:
        level = logging.DEBUG
    elif args.verbose == 1:
        level = logging.INFO
    else:
        level = logging.WARNING
    client_config = load_default_log_client_config()
    server_config = load_default_log_server_config()
    handler = resolve_handler(
        log_target=args.log_target,
        log_file=args.log_file,
        client_name=_CLIENT_NAME,
        instance=None,
        host=resolve_host_default(),
        port=server_config.port,
        connect_timeout_sec=client_config.connect_timeout_sec,
        failover_timeout_sec=(
            args.log_failover_timeout
            if args.log_failover_timeout is not None
            else client_config.failover_timeout_sec
        ),
        failover_dir=client_config.failover_dir,
    )
    logging.basicConfig(level=level, format=_LOG_FORMAT, handlers=[handler])


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if args.status:
        if not args.id:
            parser.error("--status needs --id (an ADMIN participant)")
        raise SystemExit(status(str(args.id).upper(), args.top))
    compiled = load_compiled_config()
    if compiled is None:
        raise SystemExit(
            "pm-market-sim: no deployed configuration; run pm-config-deploy"
        )
    engine = compiled.engine
    if args.init:
        sys.stdout.write(generate_sim_config(sorted(engine.symbols), seed=args.seed))
        return
    _configure_logging(args)
    path = REF_DATA_DIR / FILE_NAME
    if not path.is_file():
        raise SystemExit(
            f"pm-market-sim: no {path}. Write one with `pm-market-sim --init > "
            f"{FILE_NAME}` next to your engine_config.yaml and run pm-config-deploy"
        )
    try:
        cfg = load_sim_config(path, set(engine.symbols))
        saved = load_state(STATE_FILE)
        if saved is not None and set(saved.values) != set(cfg.params):
            log.warning("saved values are for other symbols; new symbols start fresh")
        sub = _engine_subscriber()
        prev = (
            {}
            if saved and set(saved.values) >= set(cfg.params)
            else engine_prev_closes(sub, STARTUP_WAIT_SEC)
        )
        sub.close(linger=0)
        values = initial_values(cfg, saved, prev, _config_prices(engine))
    except SimConfigError as exc:
        raise SystemExit(f"pm-market-sim: {exc}") from exc
    admins = frozenset(
        gw for gw, c in engine.fix_gateways.items() if c.role == ParticipantRole.ADMIN
    )
    sim = MarketSim(
        cfg,
        values,
        seq=saved.seq if saved else 0,
        epoch=saved.epoch + 1 if saved else 0,
        admins=admins,
        news_seq=saved.news_seq if saved else 0,
        rumours=saved.rumours if saved else None,
    )
    log.info(
        "pm-market-sim: %d symbols, seed %d, %s",
        len(values),
        cfg.seed,
        f"resuming at step {sim.seq}" if saved else "fresh start",
    )
    runner = Runner(sim, STATE_FILE)
    signal.signal(signal.SIGTERM, runner.stop)
    signal.signal(signal.SIGINT, runner.stop)
    runner.run()


if __name__ == "__main__":
    main()
