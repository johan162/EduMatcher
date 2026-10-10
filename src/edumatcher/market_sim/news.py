"""News and rumours: what they say in public, and what they do to values.

A ``NewsDesk`` generates headlines at random (Poisson arrivals per trading
day, per scope) and takes the instructor's; either way it returns the public
``news.event`` payloads and, separately, the moves of the log true values -
the part nobody sees.

Lifecycle: confirmed news moves the value when it is published. A rumour
moves nothing; it is later CONFIRMED (the move happens then) or RETRACTED
(nothing happens), each as a new event pointing back at the rumour. A
generated rumour resolves on its own after a random stretch of trading time;
an injected one waits for the instructor. Rumours still open at the close
stay open overnight.

Sector and market news move each symbol by its beta to that factor.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, replace
from typing import Any, NamedTuple

from edumatcher.market_sim.model import SymbolParams


class KindProfile(NamedTuple):
    scopes: tuple[str, ...]
    weight: float  # relative frequency among the kinds of a scope
    impact_mean: float  # log move
    impact_std: float


KINDS: dict[str, KindProfile] = {
    "EARNINGS": KindProfile(("SYMBOL",), 4.0, 0.0, 0.05),
    "GUIDANCE": KindProfile(("SYMBOL",), 2.0, 0.0, 0.03),
    "MNA": KindProfile(("SYMBOL",), 0.5, 0.06, 0.06),
    "REGULATORY": KindProfile(("SYMBOL", "SECTOR"), 1.0, -0.01, 0.04),
    "PRODUCT": KindProfile(("SYMBOL",), 2.0, 0.005, 0.02),
    "LEGAL": KindProfile(("SYMBOL",), 1.0, -0.01, 0.03),
    "MANAGEMENT": KindProfile(("SYMBOL",), 1.0, 0.0, 0.02),
    "MACRO": KindProfile(("SECTOR", "MARKET"), 1.0, 0.0, 0.015),
}

_GOOD = {
    "EARNINGS": "{t} beats earnings expectations",
    "GUIDANCE": "{t} raises its outlook",
    "MNA": "{t} receives a takeover offer",
    "REGULATORY": "Regulator clears {t}",
    "PRODUCT": "{t} launch draws strong demand",
    "LEGAL": "{t} wins a court ruling",
    "MANAGEMENT": "{t} names a highly regarded new CEO",
    "MACRO": "Upbeat data lifts {t}",
}
_BAD = {
    "EARNINGS": "{t} misses earnings estimates",
    "GUIDANCE": "{t} cuts its outlook",
    "MNA": "Takeover talks for {t} collapse",
    "REGULATORY": "Regulator opens an investigation into {t}",
    "PRODUCT": "{t} recalls a flagship product",
    "LEGAL": "{t} loses a major lawsuit",
    "MANAGEMENT": "{t} CEO resigns unexpectedly",
    "MACRO": "Weak data weighs on {t}",
}


@dataclass(frozen=True)
class NewsConfig:
    #: Generated events per trading day, for the whole exchange, per scope.
    rate_symbol: float = 6.0
    rate_sector: float = 0.5
    rate_market: float = 0.3
    #: Share of generated news that starts as a rumour.
    rumour_share: float = 0.3
    #: Chance a generated rumour is confirmed rather than retracted.
    rumour_confirm: float = 0.6
    #: Trading time (days) before a generated rumour resolves: uniform range.
    rumour_delay_min: float = 0.02
    rumour_delay_max: float = 0.15


@dataclass
class Rumour:
    news_id: str
    scope: str
    targets: list[str]
    kind: str
    sentiment: float
    impact: float
    headline: str
    #: Trading days until it resolves on its own; None waits for the instructor.
    remaining: float | None
    confirm: bool


def _sector_of(params: dict[str, SymbolParams]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for sym, p in sorted(params.items()):
        out.setdefault(p.sector, []).append(sym)
    return out


class NewsDesk:
    def __init__(
        self,
        params: dict[str, SymbolParams],
        cfg: NewsConfig,
        seed: int,
        *,
        epoch: int = 0,
        seq: int = 0,
        rumours: list[Rumour] | None = None,
    ) -> None:
        self.params = params
        self.cfg = cfg
        self.sectors = _sector_of(params)
        self.rng = random.Random(f"{seed}:{epoch}:news")
        self.seq = seq
        self.rumours: dict[str, Rumour] = {r.news_id: r for r in rumours or []}

    # --- the wire --------------------------------------------------------------------
    def _event(
        self,
        r: Rumour,
        status: str,
        now: float,
        *,
        credibility: float | None = None,
        related: str = "",
        news_id: str | None = None,
    ) -> dict[str, Any]:
        return {
            "id": news_id or r.news_id,
            "ts_ns": int(now * 1e9),
            "scope": r.scope,
            "targets": list(r.targets),
            "kind": r.kind,
            "status": status,
            "headline": r.headline,
            "sentiment": round(r.sentiment, 3),
            "credibility": None if credibility is None else round(credibility, 3),
            "related_id": related,
        }

    def _next_id(self) -> str:
        self.seq += 1
        return f"N{self.seq}"

    def moves(self, scope: str, targets: list[str], impact: float) -> dict[str, float]:
        """The log moves a confirmed piece of news makes."""
        if scope == "SYMBOL":
            return {s: impact for s in targets if s in self.params}
        if scope == "SECTOR":
            return {
                s: impact * self.params[s].beta_sector
                for sector in targets
                for s in self.sectors.get(sector, [])
            }
        return {s: impact * p.beta_market for s, p in self.params.items()}

    def headline(
        self, kind: str, scope: str, targets: list[str], sentiment: float
    ) -> str:
        if scope == "MARKET":
            subject = "markets"
        elif scope == "SECTOR":
            subject = " and ".join(
                t.replace("_", " ").title() + " stocks" for t in targets
            )
        else:
            subject = ", ".join(targets)
        text = (_GOOD if sentiment >= 0 else _BAD)[kind].format(t=subject)
        return text[:200]

    # --- publishing ----------------------------------------------------------------------
    def publish(
        self,
        *,
        scope: str,
        targets: list[str],
        kind: str,
        sentiment: float,
        impact: float,
        headline: str,
        rumour: bool,
        credibility: float | None,
        now: float,
        resolve_in: float | None = None,
        confirm: bool = True,
    ) -> tuple[dict[str, Any], dict[str, float]]:
        """Publish one headline: (event, log moves). A rumour moves nothing yet."""
        r = Rumour(
            news_id=self._next_id(),
            scope=scope,
            targets=list(targets),
            kind=kind,
            sentiment=sentiment,
            impact=impact,
            headline=headline or self.headline(kind, scope, targets, sentiment),
            remaining=resolve_in,
            confirm=confirm,
        )
        if rumour:
            r.headline = ("Rumour: " + r.headline)[:200]
            self.rumours[r.news_id] = r
            cred = 0.5 if credibility is None else credibility
            return self._event(r, "RUMOUR", now, credibility=cred), {}
        return self._event(r, "CONFIRMED", now), self.moves(scope, targets, impact)

    def resolve(
        self, news_id: str, confirm: bool, now: float
    ) -> tuple[dict[str, Any], dict[str, float]] | None:
        """Confirm or retract an open rumour; None when there is no such rumour."""
        r = self.rumours.pop(news_id, None)
        if r is None:
            return None
        base = r.headline.removeprefix("Rumour: ")
        resolved = replace(r, headline=base)
        if confirm:
            event = self._event(
                resolved, "CONFIRMED", now, related=news_id, news_id=self._next_id()
            )
            return event, self.moves(r.scope, r.targets, r.impact)
        resolved.headline = ("Retracted: " + base)[:200]
        event = self._event(
            resolved, "RETRACTED", now, related=news_id, news_id=self._next_id()
        )
        return event, {}

    # --- the random generator ----------------------------------------------------------
    def tick(
        self, dt_days: float, now: float
    ) -> list[tuple[dict[str, Any], dict[str, float]]]:
        """Advance trading time: resolve due rumours, maybe publish new news."""
        out = []
        for r in list(self.rumours.values()):
            if r.remaining is None:
                continue
            r.remaining -= dt_days
            if r.remaining <= 0:
                done = self.resolve(r.news_id, r.confirm, now)
                if done is not None:
                    out.append(done)
        for scope, rate in (
            ("SYMBOL", self.cfg.rate_symbol),
            ("SECTOR", self.cfg.rate_sector),
            ("MARKET", self.cfg.rate_market),
        ):
            if rate > 0 and self.rng.random() < 1.0 - math.exp(-rate * dt_days):
                out.append(self._generate(scope, now))
        return out

    def _generate(
        self, scope: str, now: float
    ) -> tuple[dict[str, Any], dict[str, float]]:
        rng = self.rng
        kinds = [(k, p) for k, p in KINDS.items() if scope in p.scopes]
        kind, profile = rng.choices(kinds, weights=[p.weight for _, p in kinds])[0]
        if scope == "SYMBOL":
            targets = [rng.choice(sorted(self.params))]
        elif scope == "SECTOR":
            targets = [rng.choice(sorted(self.sectors))]
        else:
            targets = []
        impact = max(-1.0, min(1.0, rng.gauss(profile.impact_mean, profile.impact_std)))
        # Public tone: the sign of the impact, its size blurred.
        sentiment = max(
            -1.0, min(1.0, impact / (2 * profile.impact_std) + rng.gauss(0.0, 0.15))
        )
        if sentiment == 0.0:
            sentiment = math.copysign(0.01, impact)
        rumour = rng.random() < self.cfg.rumour_share
        confirm = rng.random() < self.cfg.rumour_confirm
        # Credibility informs, but not perfectly.
        credibility = rng.uniform(0.4, 0.9) if confirm else rng.uniform(0.1, 0.6)
        return self.publish(
            scope=scope,
            targets=targets,
            kind=kind,
            sentiment=sentiment,
            impact=impact,
            headline="",
            rumour=rumour,
            credibility=credibility,
            now=now,
            resolve_in=rng.uniform(
                self.cfg.rumour_delay_min, self.cfg.rumour_delay_max
            ),
            confirm=confirm,
        )
