"""pm-news: the instructor's news desk.

Publish a headline (optionally as a rumour), confirm or retract a rumour,
play a timed scenario, or watch the news as it comes out. Commands go to
pm-market-sim, which accepts them only from an ADMIN participant and replies
on ``sim.command_ack.<ID>``.

Usage examples:
  pm-news --id OPS01 inject --symbol AAPL --kind EARNINGS --sentiment 0.8 --impact 0.08
  pm-news --id OPS01 inject --sector TECH --kind REGULATORY --sentiment -0.6 \\
      --impact -0.05 --rumour --credibility 0.4
  pm-news --id OPS01 confirm N12
  pm-news --id OPS01 play docs/examples/ref_data/s150-nominal-setup/news-earnings.yaml
  pm-news list
"""

from __future__ import annotations

import argparse
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
import zmq

from edumatcher.config import (
    ENGINE_PUB_ADDR,
    ENGINE_PULL_ADDR,
    SIM_PUB_ADDR,
    SIM_PULL_ADDR,
)
from edumatcher.market_sim.news import KINDS
from edumatcher.messaging.bus import get_context, make_pusher
from edumatcher.models.generated import news as N
from edumatcher.models.generated import sim as G
from edumatcher.models.generated._runtime import MessageValidationError
from edumatcher.models.generated.session import TOPIC_SESSION_STATE
from edumatcher.models.generated.system import topic_session_status
from edumatcher.models.message import decode, make_session_state_request_msg

ACK_TIMEOUT_SEC = 3.0


class NewsError(Exception):
    pass


class Desk:
    """One connection to pm-market-sim: commands out, acks and news in."""

    def __init__(self, gateway_id: str) -> None:
        ctx = get_context()
        self.gateway_id = gateway_id.upper()
        self.push: zmq.Socket[bytes] = ctx.socket(zmq.PUSH)
        self.push.setsockopt(zmq.LINGER, 1000)
        self.push.connect(SIM_PULL_ADDR)
        self.sub: zmq.Socket[bytes] = ctx.socket(zmq.SUB)
        self.sub.connect(SIM_PUB_ADDR)
        self.sub.setsockopt(
            zmq.SUBSCRIBE, G.topic_sim_command_ack(self.gateway_id).encode()
        )
        time.sleep(0.3)  # let the subscription take before the first command

    def close(self) -> None:
        self.push.close()
        self.sub.close(linger=0)

    def send(self, action: str, **fields: Any) -> dict[str, Any]:
        command_id = uuid.uuid4().hex[:16]
        try:
            frames = G.make_sim_command(
                command_id=command_id,
                gateway_id=self.gateway_id,
                action=action,
                **fields,
            )
        except MessageValidationError as exc:
            raise NewsError(str(exc)) from exc
        self.push.send_multipart(frames)
        deadline = time.monotonic() + ACK_TIMEOUT_SEC
        while time.monotonic() < deadline:
            if self.sub.poll(100):
                _, payload = decode(self.sub.recv_multipart())
                if payload.get("command_id") == command_id:
                    if not payload.get("accepted"):
                        raise NewsError(f"refused: {payload.get('reason', '')}")
                    return payload
        raise NewsError("no answer from pm-market-sim (is it running?)")


def news_request(
    *,
    symbol: list[str] | None = None,
    sector: list[str] | None = None,
    market: bool = False,
    kind: str,
    sentiment: float,
    impact: float,
    headline: str = "",
    rumour: bool = False,
    credibility: float | None = None,
) -> dict[str, Any]:
    scopes = [bool(symbol), bool(sector), market]
    if sum(scopes) != 1:
        raise NewsError("name exactly one of --symbol, --sector or --market")
    scope, targets = (
        ("SYMBOL", symbol)
        if symbol
        else ("SECTOR", sector) if sector else ("MARKET", [])
    )
    if credibility is not None and not rumour:
        raise NewsError("--credibility is for rumours (--rumour)")
    req: dict[str, Any] = {
        "scope": scope,
        "targets": [t.upper() for t in targets or []],
        "kind": kind.upper(),
        "sentiment": sentiment,
        "impact": impact,
        "headline": headline,
        "rumour": rumour,
    }
    if credibility is not None:
        req["credibility"] = credibility
    return req


def format_event(p: dict[str, Any]) -> str:
    targets = ",".join(p.get("targets") or []) or "MARKET"
    extra = ""
    if p.get("status") == "RUMOUR" and p.get("credibility") is not None:
        extra = f" (credibility {p['credibility']:.0%})"
    if p.get("related_id"):
        extra += f" [re {p['related_id']}]"
    return (
        f"{time.strftime('%H:%M:%S')} {p['id']:>5} {p['status']:<9} {p['kind']:<10} "
        f"{targets:<12} {p['sentiment']:+.2f}  {p['headline']}{extra}"
    )


def watch(duration: float) -> int:
    sub = get_context().socket(zmq.SUB)
    sub.connect(SIM_PUB_ADDR)
    sub.setsockopt(zmq.SUBSCRIBE, N.TOPIC_NEWS_EVENT.encode())
    end = time.monotonic() + duration if duration > 0 else None
    try:
        while end is None or time.monotonic() < end:
            if sub.poll(200):
                _, payload = decode(sub.recv_multipart())
                print(format_event(payload), flush=True)
    except KeyboardInterrupt:
        pass
    finally:
        sub.close(linger=0)
    return 0


# --- scenarios ------------------------------------------------------------------
@dataclass
class Step:
    phase: str | None  # None: relative to the start of play
    after_sec: float
    action: str
    news: dict[str, Any] | None
    ref: str | None  # the step name a confirm/retract refers to
    name: str | None


_STEP_KEYS = {"at", "name", "inject", "confirm", "retract"}
_INJECT_KEYS = {
    "symbol",
    "sector",
    "market",
    "kind",
    "sentiment",
    "impact",
    "headline",
    "rumour",
    "credibility",
}
PHASES = ("PRE_OPEN", "OPENING_AUCTION", "CONTINUOUS", "CLOSING_AUCTION", "CLOSED")


def load_scenario(path: Path) -> list[Step]:
    """A scenario: timed steps, each at ``after_sec`` seconds into a session
    phase (or into the play), injecting news or resolving an earlier rumour::

        version: 1
        steps:
          - at: {phase: CONTINUOUS, after_sec: 30}
            name: rumour
            inject: {symbol: AAPL, kind: MNA, sentiment: 0.7, impact: 0.12,
                     rumour: true, credibility: 0.5}
          - at: {phase: CONTINUOUS, after_sec: 150}
            confirm: rumour
    """
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise NewsError(f"cannot read {path}: {exc}") from exc
    if not isinstance(raw, dict) or raw.get("version") != 1:
        raise NewsError(f"{path}: a mapping with version: 1 is required")
    steps_raw = raw.get("steps")
    if not isinstance(steps_raw, list) or not steps_raw:
        raise NewsError(f"{path}: steps must be a non-empty list")
    steps: list[Step] = []
    names: set[str] = set()
    for i, body in enumerate(steps_raw, 1):
        where = f"{path}: step {i}"
        if not isinstance(body, dict):
            raise NewsError(f"{where}: must be a mapping")
        unknown = set(body) - _STEP_KEYS
        if unknown:
            raise NewsError(f"{where}: unknown key(s) {', '.join(sorted(unknown))}")
        at = body.get("at") or {}
        if not isinstance(at, dict) or set(at) - {"phase", "after_sec"}:
            raise NewsError(f"{where}: at takes phase and after_sec")
        phase = at.get("phase")
        if phase is not None and phase not in PHASES:
            raise NewsError(f"{where}: phase must be one of {', '.join(PHASES)}")
        after = at.get("after_sec", 0)
        if isinstance(after, bool) or not isinstance(after, (int, float)) or after < 0:
            raise NewsError(f"{where}: after_sec must be a number >= 0")
        actions = [k for k in ("inject", "confirm", "retract") if k in body]
        if len(actions) != 1:
            raise NewsError(f"{where}: exactly one of inject, confirm, retract")
        name = body.get("name")
        news = ref = None
        if actions[0] == "inject":
            spec = body["inject"]
            if not isinstance(spec, dict) or set(spec) - _INJECT_KEYS:
                raise NewsError(
                    f"{where}: inject takes {', '.join(sorted(_INJECT_KEYS))}"
                )
            sym, sec = spec.get("symbol"), spec.get("sector")
            try:
                news = news_request(
                    symbol=[sym] if isinstance(sym, str) else sym,
                    sector=[sec] if isinstance(sec, str) else sec,
                    market=bool(spec.get("market", False)),
                    kind=str(spec.get("kind", "")),
                    sentiment=float(spec.get("sentiment", 0.0)),
                    impact=float(spec.get("impact", 0.0)),
                    headline=str(spec.get("headline", "")),
                    rumour=bool(spec.get("rumour", False)),
                    credibility=spec.get("credibility"),
                )
            except (NewsError, TypeError, ValueError) as exc:
                raise NewsError(f"{where}: {exc}") from exc
            if news["kind"] not in KINDS:
                raise NewsError(f"{where}: kind must be one of {', '.join(KINDS)}")
            if name:
                names.add(str(name))
        else:
            ref = str(body[actions[0]])
            if ref not in names:
                raise NewsError(f"{where}: {actions[0]} names no earlier step {ref!r}")
        steps.append(
            Step(
                phase,
                float(after),
                {
                    "inject": "NEWS_INJECT",
                    "confirm": "NEWS_CONFIRM",
                    "retract": "NEWS_RETRACT",
                }[actions[0]],
                news,
                ref,
                str(name) if name else None,
            )
        )
    return steps


def play(desk: Desk, steps: list[Step]) -> int:
    """Run the steps as their phases come round. The phase already under way
    when the play starts counts from the start of the play."""
    sub = get_context().socket(zmq.SUB)
    sub.connect(ENGINE_PUB_ADDR)
    sub.setsockopt(zmq.SUBSCRIBE, TOPIC_SESSION_STATE.encode())
    status_topic = topic_session_status(desk.gateway_id)
    sub.setsockopt(zmq.SUBSCRIBE, status_topic.encode())
    push = make_pusher(ENGINE_PULL_ADDR)
    time.sleep(0.3)  # let the subscriptions take before asking
    try:
        push.send_multipart(make_session_state_request_msg(desk.gateway_id))
    except zmq.Again:
        pass  # engine not up: the steps wait for its transitions
    push.close(linger=0)
    started = time.monotonic()
    phase_at: dict[str | None, float] = {None: started}
    ids: dict[str, str] = {}
    pending = list(steps)
    try:
        while pending:
            while sub.poll(100):
                topic, payload = decode(sub.recv_multipart())
                state = str(payload.get("state", "")).upper()
                if topic == status_topic:
                    phase_at.setdefault(state, started)
                else:
                    phase_at[state] = time.monotonic()
            now = time.monotonic()
            for step in list(pending):
                start = phase_at.get(step.phase)
                if start is None or now < start + step.after_sec:
                    continue
                pending.remove(step)
                if step.action == "NEWS_INJECT":
                    ack = desk.send(step.action, news=step.news)
                    if step.name:
                        ids[step.name] = ack["news_id"]
                else:
                    assert step.ref is not None
                    ack = desk.send(step.action, news_id=ids[step.ref])
                print(f"{time.strftime('%H:%M:%S')} {step.action} -> {ack['news_id']}")
    except KeyboardInterrupt:
        return 130
    finally:
        sub.close(linger=0)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="EduMatcher news desk (instructor)")
    from edumatcher.cli_version import add_version_argument

    add_version_argument(parser, "pm-news")
    parser.add_argument("--id", help="ADMIN participant ID the commands come from")
    sub = parser.add_subparsers(dest="command", required=True)
    inject = sub.add_parser("inject", help="Publish a headline")
    where = inject.add_mutually_exclusive_group(required=True)
    where.add_argument("--symbol", action="append", help="Symbol (repeatable)")
    where.add_argument("--sector", action="append", help="Sector (repeatable)")
    where.add_argument("--market", action="store_true", help="The whole market")
    inject.add_argument("--kind", required=True, choices=sorted(KINDS))
    inject.add_argument(
        "--sentiment", type=float, required=True, help="-1 to 1, public"
    )
    inject.add_argument(
        "--impact",
        type=float,
        required=True,
        help="Log move of the true value when confirmed (0.10 ~ +10.5%%), secret",
    )
    inject.add_argument("--headline", default="", help="Default: written for you")
    inject.add_argument("--rumour", action="store_true", help="Publish as a rumour")
    inject.add_argument("--credibility", type=float, default=None, help="0 to 1")
    confirm = sub.add_parser("confirm", help="Confirm a rumour (the value moves)")
    confirm.add_argument("news_id")
    retract = sub.add_parser("retract", help="Retract a rumour (nothing moves)")
    retract.add_argument("news_id")
    play_p = sub.add_parser("play", help="Play a timed scenario")
    play_p.add_argument("scenario", type=Path)
    list_p = sub.add_parser("list", help="Print the news as it is published")
    list_p.add_argument("--duration", type=float, default=0.0, help="0 = until Ctrl-C")
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "list":
        raise SystemExit(watch(args.duration))
    if not args.id:
        parser.error("--id (an ADMIN participant) is required")
    try:
        if args.command == "play":
            steps = load_scenario(args.scenario)
            desk = Desk(args.id)
            try:
                raise SystemExit(play(desk, steps))
            finally:
                desk.close()
        desk = Desk(args.id)
        try:
            if args.command == "inject":
                req = news_request(
                    symbol=args.symbol,
                    sector=args.sector,
                    market=args.market,
                    kind=args.kind,
                    sentiment=args.sentiment,
                    impact=args.impact,
                    headline=args.headline,
                    rumour=args.rumour,
                    credibility=args.credibility,
                )
                ack = desk.send("NEWS_INJECT", news=req)
            else:
                action = "NEWS_CONFIRM" if args.command == "confirm" else "NEWS_RETRACT"
                ack = desk.send(action, news_id=args.news_id.upper())
        finally:
            desk.close()
    except NewsError as exc:
        print(f"pm-news: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    print(ack["news_id"])


if __name__ == "__main__":
    main()
