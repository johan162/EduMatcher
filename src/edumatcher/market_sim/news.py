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

What can happen is ``STORIES``: everyday news that goes either way (an
earnings beat or miss) and events that go one way and are big (a fire at the
main plant, a drug trial that fails), some only in their own industry.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, replace
from typing import Any, NamedTuple

from edumatcher.market_sim.model import SymbolParams
from edumatcher.market_sim.sectors import industry_of

#: Default headlines by kind, good and bad: what an injected headline without
#: text of its own says.
_GOOD = {
    "EARNINGS": "{t} beats earnings expectations",
    "GUIDANCE": "{t} raises its outlook",
    "MNA": "{t} receives a takeover offer",
    "REGULATORY": "Regulator clears {t}",
    "PRODUCT": "{t} launch draws strong demand",
    "LEGAL": "{t} wins a court ruling",
    "MANAGEMENT": "{t} names a highly regarded new CEO",
    "MACRO": "Upbeat data lifts {t}",
    "OPERATIONS": "{t} restores full production",
    "RESEARCH": "{t} reports a research breakthrough",
    "CONTRACT": "{t} wins a major long-term contract",
    "ESG": "{t} wins environmental approval for its expansion",
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
    "OPERATIONS": "{t} hit by a major operational disruption",
    "RESEARCH": "{t} research programme hits a dead end",
    "CONTRACT": "{t} loses a major customer",
    "ESG": "{t} hit by environmental protests",
}

KINDS: tuple[str, ...] = tuple(_GOOD)


class Story(NamedTuple):
    """One kind of thing that can happen, for the random generator."""

    kind: str
    scope: str
    weight: float  # relative frequency among the stories that can happen
    impact_mean: float  # log move
    impact_std: float
    #: Headlines for a good (impact >= 0) and a bad outcome. A story with only
    #: one of them always moves the value that way.
    good: str
    bad: str
    #: Sectors or industries it can happen to; empty: any.
    where: tuple[str, ...] = ()
    #: ``{x}`` in the headline is |impact| times this: the bigger the number,
    #: the bigger the move.
    x_scale: float = 0.0


def _both(kind: str, scope: str, weight: float, mean: float, std: float) -> Story:
    return Story(kind, scope, weight, mean, std, _GOOD[kind], _BAD[kind])


def _event(
    kind: str,
    weight: float,
    mean: float,
    std: float,
    text: str,
    where: tuple[str, ...] = (),
    x_scale: float = 0.0,
    scope: str = "SYMBOL",
) -> Story:
    """A one-way story: good when its mean is, bad otherwise."""
    good, bad = (text, "") if mean > 0 else ("", text)
    return Story(kind, scope, weight, mean, std, good, bad, where, x_scale)


_MAKERS = ("TECH", "INDUSTRIALS", "MATERIALS")
_B2B = ("TECH", "INDUSTRIALS", "MATERIALS", "ENERGY")

# Headline slots: {t} the symbol or sector, {site} a place it works from,
# {product} a thing it makes (a story that names one only happens to industries
# that make something), {x} the number scaled from the impact.
STORIES: tuple[Story, ...] = (
    # Everyday news, either way.
    _both("EARNINGS", "SYMBOL", 4.0, 0.0, 0.05),
    _both("GUIDANCE", "SYMBOL", 2.0, 0.0, 0.03),
    _both("MNA", "SYMBOL", 0.5, 0.06, 0.06),
    _both("REGULATORY", "SYMBOL", 1.0, -0.01, 0.04),
    _both("PRODUCT", "SYMBOL", 2.0, 0.005, 0.02),
    _both("LEGAL", "SYMBOL", 1.0, -0.01, 0.03),
    _both("MANAGEMENT", "SYMBOL", 1.0, 0.0, 0.02),
    _both("REGULATORY", "SECTOR", 1.0, -0.01, 0.04),
    _both("MACRO", "SECTOR", 1.0, 0.0, 0.015),
    _both("MACRO", "MARKET", 1.0, 0.0, 0.015),
    # Events: they go one way, and they are big. Any industry...
    _event("OPERATIONS", 0.8, -0.05, 0.02, "Fire ravages {t}'s main {site}"),
    _event("OPERATIONS", 0.4, -0.035, 0.015, "Flooding shuts {t}'s {site} for weeks"),
    _event("OPERATIONS", 0.4, -0.03, 0.015, "Cyber-attack disrupts {t}'s operations"),
    _event("OPERATIONS", 0.4, -0.025, 0.01, "Workers strike at {t}'s {site}"),
    _event(
        "OPERATIONS",
        0.3,
        0.02,
        0.01,
        "{t} reopens its {site} weeks ahead of schedule",
    ),
    _event(
        "RESEARCH",
        0.8,
        -0.05,
        0.02,
        "{t} writes off its flagship R&D project after it hits a dead end",
        _MAKERS + ("HEALTHCARE", "AUTOS", "COMMUNICATION"),
    ),
    _event(
        "ESG",
        0.5,
        -0.03,
        0.015,
        "Environmental protests delay {t}'s new {site} by {x} months",
        x_scale=400,
    ),
    _event(
        "ESG",
        0.3,
        -0.02,
        0.01,
        "{t} fined for breaking environmental rules at its {site}",
    ),
    _event(
        "ESG",
        0.3,
        0.025,
        0.01,
        "{t} wins approval for its new {site} after a long permit battle",
    ),
    _event(
        "PRODUCT", 0.6, -0.06, 0.025, "{t} recalls its {product} over a safety defect"
    ),
    # ...industries that sell to other businesses or engineer things...
    _event(
        "RESEARCH",
        0.8,
        0.05,
        0.025,
        "{t} breakthrough makes its next {product} {x} % more efficient",
        _MAKERS,
        400,
    ),
    _event(
        "CONTRACT",
        1.4,
        0.045,
        0.02,
        "{t} signs a ${x} bn long-term deal with a major new customer",
        _B2B,
        100,
    ),
    _event(
        "CONTRACT", 0.6, -0.05, 0.02, "{t} loses its largest customer to a rival", _B2B
    ),
    # ...and one industry.
    _event(
        "RESEARCH",
        0.6,
        0.07,
        0.03,
        "{t} breakthrough lifts next-generation chip performance by {x} %",
        ("SEMICONDUCTORS",),
        500,
    ),
    _event(
        "RESEARCH",
        0.4,
        -0.06,
        0.02,
        "{t}'s next-generation chip slips a year after a design flaw",
        ("SEMICONDUCTORS",),
    ),
    _event(
        "OPERATIONS",
        0.3,
        -0.04,
        0.015,
        "Contamination at {t}'s wafer plant forces it to scrap weeks of output",
        ("SEMICONDUCTORS",),
    ),
    _event(
        "OPERATIONS",
        0.5,
        -0.03,
        0.015,
        "Outage takes {t}'s cloud services offline for hours",
        ("SOFTWARE",),
    ),
    _event(
        "RESEARCH",
        0.6,
        0.08,
        0.04,
        "{t}'s lead drug succeeds in a late-stage trial",
        ("PHARMA",),
    ),
    _event(
        "RESEARCH",
        0.5,
        -0.10,
        0.04,
        "{t}'s lead drug fails a late-stage trial",
        ("PHARMA",),
    ),
    _event(
        "REGULATORY",
        0.3,
        0.05,
        0.02,
        "Regulator approves {t}'s new drug ahead of schedule",
        ("PHARMA",),
    ),
    _event(
        "RESEARCH",
        0.5,
        0.05,
        0.02,
        "{t} unveils a battery with {x} % more range",
        ("AUTOS",),
        600,
    ),
    _event(
        "PRODUCT",
        0.4,
        -0.06,
        0.02,
        "{t} recalls {x},000 vehicles over a brake defect",
        ("AUTOS",),
        5000,
    ),
    _event(
        "OPERATIONS",
        0.4,
        -0.035,
        0.015,
        "Parts shortage idles {t}'s assembly lines",
        ("AUTOS",),
    ),
    _event(
        "OPERATIONS",
        0.5,
        -0.03,
        0.015,
        "IT outage grounds {t}'s fleet for a day",
        ("AIRLINES",),
    ),
    _event(
        "OPERATIONS",
        0.3,
        -0.04,
        0.015,
        "{t} orders fleet-wide engine inspections after an in-flight failure",
        ("AIRLINES",),
    ),
    _event(
        "CONTRACT",
        0.6,
        0.05,
        0.02,
        "{t} wins a ${x} bn defence contract",
        ("AEROSPACE",),
        200,
    ),
    _event(
        "PRODUCT",
        0.4,
        -0.06,
        0.02,
        "{t} halts deliveries after quality-control lapses",
        ("AEROSPACE",),
    ),
    _event(
        "OPERATIONS", 0.4, 0.05, 0.02, "{t} strikes a major new oil find", ("ENERGY",)
    ),
    _event("ESG", 0.4, -0.05, 0.02, "{t} oil spill: clean-up costs mount", ("ENERGY",)),
    _event(
        "ESG", 0.3, -0.08, 0.03, "Wildfire blamed on {t}'s power lines", ("UTILITIES",)
    ),
    _event(
        "OPERATIONS",
        0.4,
        -0.03,
        0.015,
        "Data breach exposes millions of {t} customer records",
        ("FINANCIALS", "COMMUNICATION", "SOFTWARE"),
    ),
    # Events of a whole sector.
    _event(
        "OPERATIONS",
        0.4,
        -0.02,
        0.01,
        "Supply-chain disruption hits {t}",
        scope="SECTOR",
    ),
    _event(
        "OPERATIONS",
        0.5,
        -0.03,
        0.015,
        "Hurricane shuts Gulf of Mexico refineries, hitting {t}",
        ("ENERGY",),
        scope="SECTOR",
    ),
    _event(
        "REGULATORY",
        0.4,
        -0.03,
        0.015,
        "New export curbs on advanced chips hit {t}",
        ("TECH",),
        scope="SECTOR",
    ),
    _event(
        "REGULATORY",
        0.4,
        -0.025,
        0.01,
        "Drug-pricing reform weighs on {t}",
        ("HEALTHCARE",),
        scope="SECTOR",
    ),
    _event(
        "OPERATIONS",
        0.3,
        -0.02,
        0.01,
        "Port strike snarls supply chains for {t}",
        ("INDUSTRIALS",),
        scope="SECTOR",
    ),
)

#: Where things happen, by industry or sector.
_SITES: dict[str, tuple[str, ...]] = {
    "SEMICONDUCTORS": ("chip fab", "wafer plant", "packaging plant"),
    "SOFTWARE": ("data centre", "development centre"),
    "PHARMA": ("drug plant", "research campus", "vaccine plant"),
    "AUTOS": ("assembly plant", "battery plant", "parts warehouse"),
    "AIRLINES": ("maintenance hub", "flight-operations centre"),
    "AEROSPACE": ("final-assembly plant", "engine plant"),
    "TECH": ("data centre", "assembly plant", "distribution centre"),
    "COMMUNICATION": ("data centre", "network operations centre", "studio"),
    "CONSUMER_DISC": ("distribution centre", "fulfilment centre", "factory"),
    "CONSUMER_STAPLES": ("bottling plant", "food-processing plant", "warehouse"),
    "ENERGY": ("refinery", "offshore platform", "LNG terminal"),
    "FINANCIALS": ("data centre", "operations centre"),
    "HEALTHCARE": ("device factory", "distribution centre", "data centre"),
    "INDUSTRIALS": ("assembly plant", "component plant", "distribution centre"),
    "MATERIALS": ("chemical plant", "mine", "smelter"),
    "UTILITIES": ("power station", "gas pipeline", "substation"),
    "REAL_ESTATE": ("flagship tower", "logistics park", "data centre"),
}
_DEFAULT_SITES = ("main plant", "warehouse")
#: What gets made, by industry or sector; empty: nothing to recall or improve.
_PRODUCTS: dict[str, tuple[str, ...]] = {
    "SEMICONDUCTORS": ("processor", "AI accelerator", "memory chip"),
    "SOFTWARE": (),
    "PHARMA": ("blood-pressure drug", "best-selling vaccine"),
    "AUTOS": ("best-selling SUV", "electric pickup"),
    "AIRLINES": (),
    "AEROSPACE": ("jet engine", "satellite"),
    "TECH": ("smartphone", "laptop", "server"),
    "COMMUNICATION": (),
    "CONSUMER_DISC": ("best-selling appliance", "running shoe"),
    "CONSUMER_STAPLES": ("baby formula", "snack brand", "cleaning spray"),
    "ENERGY": (),
    "FINANCIALS": (),
    "HEALTHCARE": ("heart device", "insulin pump", "diagnostic test"),
    "INDUSTRIALS": ("excavator", "industrial robot", "heat pump"),
    "MATERIALS": ("specialty coating", "fertiliser", "battery material"),
    "UTILITIES": (),
    "REAL_ESTATE": (),
}
_DEFAULT_PRODUCTS = ("flagship product",)


def _vocab(
    table: dict[str, tuple[str, ...]],
    default: tuple[str, ...],
    industry: str,
    sector: str,
) -> tuple[str, ...]:
    for key in (industry, sector):
        if key in table:
            return table[key]
    return default


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

    @staticmethod
    def _subject(scope: str, targets: list[str]) -> str:
        if scope == "MARKET":
            return "markets"
        if scope == "SECTOR":
            return " and ".join(
                t.replace("_", " ").title() + " stocks" for t in targets
            )
        return ", ".join(targets)

    def headline(
        self, kind: str, scope: str, targets: list[str], sentiment: float
    ) -> str:
        subject = self._subject(scope, targets)
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
        if scope == "SYMBOL":
            targets = [rng.choice(sorted(self.params))]
            sector = self.params[targets[0]].sector
            industry = industry_of(targets[0], sector)
        elif scope == "SECTOR":
            targets = [rng.choice(sorted(self.sectors))]
            sector = industry = targets[0]
        else:
            targets, sector, industry = [], "", ""
        sites = _vocab(_SITES, _DEFAULT_SITES, industry, sector)
        products = _vocab(_PRODUCTS, _DEFAULT_PRODUCTS, industry, sector)
        stories = [
            s
            for s in STORIES
            if s.scope == scope
            and (not s.where or industry in s.where or sector in s.where)
            and (products or "{product}" not in s.good + s.bad)
        ]
        story = rng.choices(stories, weights=[s.weight for s in stories])[0]
        impact = max(-1.0, min(1.0, rng.gauss(story.impact_mean, story.impact_std)))
        if story.good and story.bad:
            size = 2 * story.impact_std
        else:  # an event goes its one way, and its sentiment says how far
            impact = math.copysign(abs(impact), 1.0 if story.good else -1.0)
            size = abs(story.impact_mean) + story.impact_std
        # Public tone: the sign of the impact, its size blurred.
        sentiment = max(-1.0, min(1.0, impact / size + rng.gauss(0.0, 0.15)))
        if not (story.good and story.bad):  # a fire never sounds good
            sentiment = math.copysign(abs(sentiment), impact)
        if sentiment == 0.0:
            sentiment = math.copysign(0.01, impact)
        text = story.good if impact >= 0 else story.bad
        headline = text.format(
            t=self._subject(scope, targets),
            site=rng.choice(sites),
            product=rng.choice(products) if products else "",
            x=max(1, round(abs(impact) * story.x_scale)),
        )[:200]
        rumour = rng.random() < self.cfg.rumour_share
        confirm = rng.random() < self.cfg.rumour_confirm
        # Credibility informs, but not perfectly.
        credibility = rng.uniform(0.4, 0.9) if confirm else rng.uniform(0.1, 0.6)
        return self.publish(
            scope=scope,
            targets=targets,
            kind=story.kind,
            sentiment=sentiment,
            impact=impact,
            headline=headline,
            rumour=rumour,
            credibility=credibility,
            now=now,
            resolve_in=rng.uniform(
                self.cfg.rumour_delay_min, self.cfg.rumour_delay_max
            ),
            confirm=confirm,
        )
