#!/usr/bin/env python3
"""One-time migration: build questions.json and answers.json from the Markdown quizzes.

Reads the 30-question self-study checks (``../self-study-30-questions``) and the
20-question quizzes (``../quiz-20-questions``, whose plaintext key must be
decrypted first) and writes the whole bank as ONE questions file and ONE answers
file. Area, difficulty, numerical and tag classification lives in the tables
below. Two things are carried over from an existing bank rather than rebuilt:
each Markdown question's ``book_refs`` (refined per question after the first
migration) and every question written directly in the bank (``source_file`` is
null). Once the Markdown sources are retired, the JSON files are the source of
truth and this script is no longer needed.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
KC = HERE.parent
BOOK_VERSION_FILE = KC.parent / "version.toml"
L = "ABCDE"
OPT = re.compile(r"(?m)^- \[ \] ([A-E])\. (.*)$")
DETAIL = re.compile(r"(?m)^- \*\*([A-E]) — (?:true|false)\.\*\* (.*)$")
KEY_ROW = re.compile(r"(?m)^\| (\d+) \| ([A-E, ]+) \|(?: \| (\d+) \| ([A-E, ]+) \|)?$")
# Option letters in notes; "A" is converted only where it is not the article.
TOK = re.compile(r"(?<![\w\-&/.'])([A-E])(?![\w\-&+])")
A_REF = re.compile(
    r"A(?=( false| true| is | states| reverses| describes| claims| has |'s|:|\)|,"
    r"| and [B-E]\b| or [B-E]\b|\.?$))"
)

AREA_NAMES: dict[str, str] = {
    "capital-listings": "Capital & Listings",
    "history-language": "Market History & Language",
    "participants-venues": "Participants & Venues",
    "order-types": "Order Types & Time in Force",
    "book-matching": "Order Book & Matching",
    "ticks-pricing": "Tick Sizes & Pricing",
    "market-making": "Market Making & Liquidity",
    "auctions-sessions": "Auctions & Trading Sessions",
    "implied-orders": "Implied Orders",
    "indexes-benchmarks": "Indexes & Benchmarks",
    "risk-controls": "Risk Controls & Circuit Breakers",
    "clearing-settlement": "Clearing, Settlement & Options",
    "regulation-surveillance": "Regulation, Surveillance & Abuse",
    "technology": "Exchange Technology",
    "fragmentation-routing": "Fragmentation, Routing & Other Venues",
}
CODE: dict[str, str] = {
    "cap": "capital-listings",
    "his": "history-language",
    "par": "participants-venues",
    "ord": "order-types",
    "bk": "book-matching",
    "tick": "ticks-pricing",
    "mm": "market-making",
    "auc": "auctions-sessions",
    "imp": "implied-orders",
    "idx": "indexes-benchmarks",
    "risk": "risk-controls",
    "clr": "clearing-settlement",
    "reg": "regulation-surveillance",
    "tech": "technology",
    "frag": "fragmentation-routing",
}

# Areas per variant, questions 1..N in order.
AREAS: dict[str, str] = {
    "KC-01": "cap cap par par cap his his ord ord ord ord ord bk bk bk tick bk bk mm mm auc auc auc idx idx risk risk clr reg tech",
    "KC-02": "cap par par reg his ord ord ord ord ord imp ord bk bk bk tick tick bk bk mm auc auc idx idx risk risk risk risk reg risk",
    "KC-03": "cap cap par his his his par cap ord ord ord bk bk bk tick bk bk mm mm auc auc idx idx risk clr clr reg reg tech clr",
    "KC-04": "cap cap par reg his tech ord ord ord ord bk bk bk tick bk bk mm auc risk reg reg risk tech tech frag frag frag frag tech clr",
    "KC-05": "cap tech tech tech tech par cap ord bk bk tick bk auc idx risk clr reg risk tech tech tech frag tech tech tech tech tech tech frag clr",
    "KC-06": "par par his bk bk tick bk mm auc auc idx risk risk risk clr reg reg tech tech frag frag frag frag tech clr tech tech tech tech bk",
    "KC-07": "cap his par reg ord bk bk tick bk mm auc idx risk clr reg reg risk tech tech tech tech tech frag tech tech tech frag tech clr bk",
    "KC-08": "cap his par par cap ord ord bk bk tick bk mm auc auc idx risk risk risk clr reg reg risk tech tech tech tech tech clr frag clr",
    "KC-09": " ".join(["imp"] * 30),
    "QZ-01": "cap cap his par reg par cap ord ord bk auc auc idx risk risk risk risk clr tech clr",
    "QZ-02": "ord ord ord ord bk bk bk mm bk tick auc ord auc imp auc reg reg reg risk clr",
    "QZ-03": "risk risk risk risk tech tech tech tech tech tech frag frag frag frag frag frag tech tech tech tech",
    "QZ-04": "par par par par par cap ord mm mm clr clr clr reg reg tech idx clr clr clr clr",
    "QZ-05": "his his his tick cap cap cap his clr tech tech tech tech clr auc tick tech frag frag par",
    "QZ-06": "par mm cap reg bk tech tech frag reg reg risk clr par cap tech frag tick frag reg ord",
    "QZ-07": " ".join(["imp"] * 20),
}

NUMERICAL: set[str] = set("""
KC-01-02 KC-01-14 KC-01-16 KC-01-19 KC-01-21 KC-01-24 KC-01-28 KC-02-08 KC-02-14 KC-02-17 KC-03-05 KC-03-09 KC-03-13
KC-03-14 KC-03-23 KC-03-26 KC-04-08 KC-04-14 KC-04-18 KC-05-01 KC-05-09 KC-05-13 KC-05-14 KC-05-30 KC-06-03 KC-06-04
KC-06-05 KC-06-06 KC-06-08 KC-06-30 KC-07-11 KC-07-30 KC-08-08 KC-08-13 KC-08-30
KC-09-02 KC-09-03 KC-09-08 KC-09-09 KC-09-10 KC-09-11 KC-09-14 KC-09-15 KC-09-16 KC-09-17 KC-09-19 KC-09-20 KC-09-21
KC-09-22 KC-09-27 KC-09-28 QZ-05-05 QZ-06-03
QZ-07-02 QZ-07-04 QZ-07-05 QZ-07-07 QZ-07-09 QZ-07-10 QZ-07-11 QZ-07-12 QZ-07-14 QZ-07-15 QZ-07-16 QZ-07-17
""".split())

HARD: set[str] = set("""
KC-01-14 KC-01-21 KC-03-13 KC-05-13 KC-07-11 KC-08-13 KC-05-30 KC-06-30 KC-07-30 KC-08-30
KC-09-05 KC-09-06 KC-09-10 KC-09-12 KC-09-14 KC-09-15 KC-09-17 KC-09-20 KC-09-21 KC-09-22 KC-09-26 KC-09-27 KC-09-28 KC-09-29
QZ-07-06 QZ-07-08 QZ-07-09 QZ-07-10 QZ-07-12 QZ-07-15 QZ-07-16 QZ-07-17 QZ-07-18
KC-01-22 KC-02-21 KC-06-09 QZ-04-13
KC-02-26 KC-04-16 KC-04-20 KC-04-22 KC-04-29 KC-05-08 KC-06-23 KC-07-05 KC-07-17 KC-07-28 KC-08-06 KC-08-07
KC-08-11 KC-08-22 KC-08-23 KC-08-25 KC-08-28 KC-08-29 QZ-02-12
""".split())

EASY: set[str] = set("""
QZ-06-03 KC-09-01 QZ-07-01
QZ-02-05 KC-01-13 KC-02-13 KC-07-06 QZ-02-01 KC-01-12 KC-02-12 QZ-01-09 KC-01-18 QZ-02-07
KC-02-04 KC-02-06 KC-04-04 KC-07-04 QZ-01-05 QZ-06-04 QZ-03-18 KC-07-07 QZ-06-18 KC-01-08 KC-01-09 KC-01-10
QZ-02-02 KC-02-07 KC-01-15 KC-03-12 KC-01-30 QZ-03-05 KC-05-02 QZ-06-07
""".split())
EASY_AREAS = {"capital-listings", "history-language", "participants-venues"}

CROSS_CUTTING = {"KC-05-30", "KC-06-30", "KC-07-30", "KC-08-30", "QZ-06-05", "QZ-06-19"}
CASE = re.compile(
    r"Knight|Flash Crash|Barings|Leeson|GameStop|Lehman|FTX|Mizuho|Facebook|BATS|Black Monday|"
    r"\b1987\b|\b1929\b|Sarao|Herstatt|NYSE halt|March 2020|COVID|China's|Le Maire|Brady"
)

BOOK_REFS: dict[str, list[str]] = {
    "capital-listings": [
        "01-foundation/01-before-the-exchange-how-companies-raise-capital.md",
        "01-foundation/06-listing-and-delisting-mechanics.md",
    ],
    "history-language": [
        "01-foundation/02-what-is-a-financial-exchange-and-why-does-it-exist.md",
        "01-foundation/03-the-language-of-the-market-a-short-history.md",
    ],
    "participants-venues": [
        "01-foundation/04-the-participants.md",
        "01-foundation/05-a-brief-tour-of-real-world-exchanges.md",
    ],
    "order-types": [
        "02-orders-and-matching/01-the-order-the-fundamental-unit.md",
        "02-orders-and-matching/02-order-types-the-vocabulary-of-intent.md",
        "02-orders-and-matching/03-time-in-force-how-long-should-the-order-live.md",
    ],
    "book-matching": [
        "02-orders-and-matching/04-the-order-book-the-exchange-s-memory.md",
        "02-orders-and-matching/05-price-time-priority-the-fairness-rule.md",
        "02-orders-and-matching/07-the-matching-engine-the-heart-of-the-exchange.md",
        "02-orders-and-matching/08-the-life-of-a-trade.md",
    ],
    "ticks-pricing": ["02-orders-and-matching/06-tick-sizes-and-fractional-ticks.md"],
    "market-making": [
        "02-orders-and-matching/09-market-makers-the-providers-of-liquidity.md"
    ],
    "auctions-sessions": [
        "02-orders-and-matching/10-the-opening-and-closing-auction.md",
        "02-orders-and-matching/11-trading-sessions-the-day-in-the-life-of-a-market.md",
    ],
    "implied-orders": [
        "02-orders-and-matching/13-implied-orders-and-synthetic-liquidity.md",
        "02-orders-and-matching/14-multi-layer-implied-orders-and-the-combinatorial-wall.md",
    ],
    "indexes-benchmarks": [
        "02-orders-and-matching/15-indexes.md",
        "02-orders-and-matching/16-benchmark-integrity.md",
    ],
    "risk-controls": [
        "03-risk-and-compliance/01-pre-trade-risk-controls-before-the-matching-engine.md",
        "03-risk-and-compliance/02-risk-controls-protecting-the-market.md",
        "03-risk-and-compliance/03-self-match-prevention-when-you-would-trade-with-yourself.md",
        "03-risk-and-compliance/08-a-cautionary-tale-knight-capital-august-1-2012.md",
    ],
    "clearing-settlement": [
        "03-risk-and-compliance/05-clearing-and-settlement-when-the-trade-becomes-real.md",
        "04-technology-and-infrastructure/14-options-mechanics-exercise-assignment-and-expiry.md",
    ],
    "regulation-surveillance": [
        "03-risk-and-compliance/04-drop-copy-the-shadow-record.md",
        "03-risk-and-compliance/06-trade-busting-and-clearly-erroneous-trades.md",
        "03-risk-and-compliance/07-regulatory-surveillance-exchanges-are-not-passive.md",
    ],
    "technology": [
        "04-technology-and-infrastructure/01-speed-bumps-leveling-the-playing-field.md",
        "04-technology-and-infrastructure/02-the-technology-architecture.md",
        "04-technology-and-infrastructure/03-conformance-testing-and-onboarding.md",
        "04-technology-and-infrastructure/04-primary-and-secondary-sites-resilience-architecture.md",
        "04-technology-and-infrastructure/05-load-balancing-distributing-the-work.md",
        "04-technology-and-infrastructure/06-market-data-architecture-how-the-market-sees-itself.md",
        "04-technology-and-infrastructure/11-latency-and-co-location-the-speed-dimension.md",
        "04-technology-and-infrastructure/12-operational-observability-and-incident-response.md",
        "04-technology-and-infrastructure/13-corporate-actions-when-the-instrument-changes.md",
        "04-technology-and-infrastructure/15-determinism-replay-and-persistence-the-exchange-must-not-forget.md",
        "04-technology-and-infrastructure/16-reference-data-the-exchange-s-ground-truth.md",
    ],
    "fragmentation-routing": [
        "04-technology-and-infrastructure/07-market-data-economics.md",
        "04-technology-and-infrastructure/08-smart-order-routing-and-market-fragmentation.md",
        "04-technology-and-infrastructure/09-fixed-income.md",
        "04-technology-and-infrastructure/10-cryptocurrency-and-digital-asset-venues.md",
    ],
}


def parse_questions(path: Path) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    for part in re.split(r"(?m)^(?=### \d+\. )", path.read_text(encoding="utf-8")):
        m = re.match(r"### (\d+)\. (.*)", part)
        if not m:
            continue
        opts = dict(OPT.findall(part))
        assert sorted(opts) == list(L), (path, m[1])
        pre = part.split("\n- [ ]", 1)[0].split("\n")[1:]
        lines = [s.strip() for s in pre if s.strip() and not s.startswith("<div")]
        scenario = " ".join(
            s[1:-1] if s.startswith("*") and s.endswith("*") else s for s in lines
        )
        out[int(m[1])] = {
            "title": m[2].strip(),
            "scenario": scenario or None,
            "options": opts,
        }
    return out


def parse_key_table(text: str) -> dict[int, list[str]]:
    key: dict[int, list[str]] = {}
    for m in KEY_ROW.finditer(text):
        key[int(m[1])] = m[2].split(", ")
        if m[3]:
            key[int(m[3])] = m[4].split(", ")
    return key


def parse_details(text: str) -> dict[int, dict[str, str]]:
    details: dict[int, dict[str, str]] = {}
    for block in re.split(r"(?m)^(?=### \d+\. )", text):
        m = re.match(r"### (\d+)\. ", block)
        if m:
            found = dict(DETAIL.findall(block))
            if found:
                details[int(m[1])] = found
    return details


def load_sources() -> list[dict[str, Any]]:
    raw: list[dict[str, Any]] = []
    for v in range(1, 10):
        base = f"0{v}-implied-orders" if v == 9 else f"0{v}-exchange-concepts"
        qfile = f"self-study-30-questions/{base}.md"
        ktext = (KC / f"self-study-30-questions/{base}-answer-key.md").read_text(
            encoding="utf-8"
        )
        key = parse_key_table(ktext)
        notes = {
            int(m[1]): m[2]
            for m in re.finditer(r"(?m)^- \*\*Q(\d+)\([A-E, ]+\):\*\* (.*)$", ktext)
        }
        details = parse_details(ktext)
        for n, q in parse_questions(KC / qfile).items():
            raw.append(
                q
                | {
                    "source": "knowledge_check",
                    "prefix": "KC",
                    "file": qfile,
                    "variant": v,
                    "number": n,
                    "key": key[n],
                    "note": notes.get(n),
                    "detail": details.get(n),
                }
            )
    ktext = (KC / "quiz-20-questions/exchange-quiz-answer-keys.md").read_text(
        encoding="utf-8"
    )
    for section in re.split(r"(?m)^(?=# Variant \d)", ktext)[1:]:
        m = re.match(r"# Variant (\d)", section)
        assert m
        v = int(m[1])
        key = parse_key_table(section)
        notes = {
            int(m[1]): m[2]
            for m in re.finditer(r"(?m)^- \*\*Q(\d+):\*\* (.*)$", section)
        }
        details = parse_details(section)
        qfile = f"quiz-20-questions/0{v}-exchange-quiz.md"
        for n, q in parse_questions(KC / qfile).items():
            detail = details.get(n)
            if detail:  # quiz bullets repeat the statement text before the explanation
                detail = {
                    c: e.removeprefix(q["options"][c] + ". ") for c, e in detail.items()
                }
            raw.append(
                q
                | {
                    "source": "quiz",
                    "prefix": "QZ",
                    "file": qfile,
                    "variant": v,
                    "number": n,
                    "key": key[n],
                    "note": notes.get(n),
                    "detail": detail,
                }
            )
    return raw


def letters_to_ids(note: str, qid: str) -> str:
    """Replace option letters in a note with {statement_id} placeholders."""

    def sub(m: re.Match[str]) -> str:
        c = m[1]
        if c == "A":
            before = note[max(0, m.start() - 12) : m.start()]
            if not (
                A_REF.match(note, m.start())
                or re.search(r"(statement|contrary to|what) $", before)
            ):
                return c
        return "{" + f"{qid}-{L.index(c) + 1}" + "}"

    return TOK.sub(sub, note)


def classify(qid: str, text: str) -> tuple[str, str, bool, list[str]]:
    area = CODE[AREAS[qid[:5]].split()[int(qid[6:]) - 1]]
    numerical = qid in NUMERICAL
    if qid in HARD:
        difficulty = "Hard"
    elif qid in EASY or (area in EASY_AREAS and not numerical):
        difficulty = "Easy"
    else:
        difficulty = "Medium"
    tags = (["case-study"] if CASE.search(text) else []) + (
        ["cross-cutting"] if qid in CROSS_CUTTING else []
    )
    return area, difficulty, numerical, tags


def build() -> tuple[dict[str, Any], dict[str, Any]]:
    m = re.search(r'version\s*=\s*"([^"]+)"', BOOK_VERSION_FILE.read_text())
    assert m
    questions: list[dict[str, Any]] = []
    answers: list[dict[str, Any]] = []
    for q in load_sources():
        qid = f"{q['prefix']}-{q['variant']:02d}-{q['number']:02d}"
        text = " ".join([q["title"], q["scenario"] or "", *q["options"].values()])
        area, difficulty, numerical, tags = classify(qid, text)
        questions.append(
            {
                "id": qid,
                "source": q["source"],
                "source_file": q["file"],
                "variant": q["variant"],
                "number": q["number"],
                "title": q["title"],
                "scenario": q["scenario"],
                "area": area,
                "tags": tags,
                "difficulty": difficulty,
                "numerical": numerical,
                "conventions": (
                    "implied-spread" if qid.startswith(("KC-09", "QZ-07")) else None
                ),
                "book_refs": BOOK_REFS[area],
                "statements": [
                    {"id": f"{qid}-{i + 1}", "text": q["options"][c]}
                    for i, c in enumerate(L)
                ],
            }
        )
        detail = q["detail"] or {}
        answers.append(
            {
                "question_id": qid,
                "statements": [
                    {
                        "statement_id": f"{qid}-{i + 1}",
                        "correct": c in q["key"],
                        "explanation": detail.get(c),
                    }
                    for i, c in enumerate(L)
                ],
                "note": letters_to_ids(q["note"], qid) if q["note"] else None,
                "max_points": len(q["key"]),
            }
        )
    qdoc = {
        "schema_version": "1.0",
        "book_version": m[1],
        "areas": [{"id": k, "name": v} for k, v in AREA_NAMES.items()],
        "questions": questions,
    }
    return qdoc, {"schema_version": "1.0", "answers": answers}


def merge_existing(qdoc: dict[str, Any], adoc: dict[str, Any]) -> None:
    """Keep refined book_refs and bank-native questions from the current bank."""
    qpath, apath = HERE / "questions.json", HERE / "answers.json"
    if not qpath.exists():
        return
    old_q = json.loads(qpath.read_text(encoding="utf-8"))["questions"]
    refs = {q["id"]: q["book_refs"] for q in old_q}
    for q in qdoc["questions"]:
        q["book_refs"] = refs.get(q["id"], q["book_refs"])
    native = [q for q in old_q if q["source_file"] is None]
    qdoc["questions"] += native
    if native:
        old_a = json.loads(apath.read_text(encoding="utf-8"))["answers"]
        ids = {q["id"] for q in native}
        adoc["answers"] += [a for a in old_a if a["question_id"] in ids]


def main() -> None:
    qdoc, adoc = build()
    merge_existing(qdoc, adoc)
    for name, doc in (("questions.json", qdoc), ("answers.json", adoc)):
        (HERE / name).write_text(
            json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    qs = qdoc["questions"]
    counts = Counter(q["difficulty"] for q in qs)
    print(
        f"{len(qs)} questions: {counts['Easy']} Easy, {counts['Medium']} Medium, "
        f"{counts['Hard']} Hard, {sum(q['numerical'] for q in qs)} numerical"
    )


if __name__ == "__main__":
    main()
