#!/usr/bin/env python3
"""Generate a random knowledge-check quiz and its answer key from the question bank.

The bank is two files next to this script: ``questions.json`` (no answers) and
``answers.json`` (kept encrypted in git; run ``make decrypt-answers`` in
``..`` first). Each run writes a quiz Markdown file and a
matching ``-answer-key.md`` file in the layout of the original quizzes.

Example::

    ./quizgen.py --count 20 --difficulty Medium,Hard --numerical exclude \\
        --source both --seed 42 --output midterm.md
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict, cast

HERE = Path(__file__).resolve().parent
LETTERS = "ABCDE"
DIFFICULTIES = ("Easy", "Medium", "Hard")
SOURCES = {
    "quiz": ("quiz",),
    "knowledge_check": ("knowledge_check",),
    "both": ("quiz", "knowledge_check"),
}
PASS_FRACTION = 0.7
PAGE_BREAK = '<div style="page-break-after: always;"></div>'
DEFAULT_TITLE = "Exchange Concepts Knowledge Check"

CONVENTIONS = {
    "implied-spread": (
        "- Spread price S = Near month − Far month (for example S = January − February).\n"
        "- Buying one spread = buying one lot of the near month and selling one lot "
        "of the far month.\n"
        "- Prices are in US dollars per barrel with a $0.01 tick unless a question "
        "states otherwise. One lot = 1,000 barrels.\n"
        "- Unless stated otherwise, the engine is first-generation: an implied quote "
        "is built from exactly two real orders.\n"
    ),
}


class Statement(TypedDict):
    id: str
    text: str


class Question(TypedDict):
    id: str
    source: str
    source_file: str | None
    variant: int
    number: int
    title: str
    scenario: str | None
    area: str
    tags: list[str]
    difficulty: str
    numerical: bool
    conventions: str | None
    book_refs: list[str]
    statements: list[Statement]


class StatementAnswer(TypedDict):
    statement_id: str
    correct: bool
    explanation: str | None


class Answer(TypedDict):
    question_id: str
    statements: list[StatementAnswer]
    note: str | None
    max_points: int


class Area(TypedDict):
    id: str
    name: str


@dataclass
class Bank:
    areas: list[Area]
    questions: list[Question]

    def area_name(self, area_id: str) -> str:
        return next(a["name"] for a in self.areas if a["id"] == area_id)


@dataclass
class QuizItem:
    """A selected question with its statements in display order."""

    question: Question
    answer: Answer
    order: list[int]  # order[letter_index] = index into question["statements"]

    def letter_of(self, statement_id: str) -> str:
        ids = [s["id"] for s in self.question["statements"]]
        return LETTERS[self.order.index(ids.index(statement_id))]

    def correct_letters(self) -> list[str]:
        truth = {s["statement_id"]: s["correct"] for s in self.answer["statements"]}
        return [
            LETTERS[i]
            for i, k in enumerate(self.order)
            if truth[self.question["statements"][k]["id"]]
        ]


def load_bank(path: Path) -> Bank:
    data = cast(dict[str, object], json.loads(path.read_text(encoding="utf-8")))
    return Bank(
        areas=cast(list[Area], data["areas"]),
        questions=cast(list[Question], data["questions"]),
    )


def load_answers(path: Path) -> dict[str, Answer]:
    data = cast(dict[str, object], json.loads(path.read_text(encoding="utf-8")))
    return {a["question_id"]: a for a in cast(list[Answer], data["answers"])}


def select_questions(
    bank: Bank,
    *,
    count: int,
    difficulties: tuple[str, ...],
    numerical: str,
    sources: tuple[str, ...],
    areas: tuple[str, ...] | None,
    rng: random.Random,
) -> list[Question]:
    """Pick ``count`` matching questions at random, returned in book (area) order."""
    pool = [
        q
        for q in bank.questions
        if q["difficulty"] in difficulties
        and q["source"] in sources
        and (areas is None or q["area"] in areas)
        and (numerical == "include" or (numerical == "only") == q["numerical"])
    ]
    if len(pool) < count:
        raise ValueError(
            f"not enough questions: {len(pool)} match the chosen filters, {count} requested"
        )
    area_order = [a["id"] for a in bank.areas]
    picked = rng.sample(pool, count)
    return sorted(picked, key=lambda q: (area_order.index(q["area"]), q["id"]))


def build_items(
    questions: list[Question], answers: dict[str, Answer], rng: random.Random
) -> list[QuizItem]:
    items = []
    for q in questions:
        order = list(range(len(q["statements"])))
        rng.shuffle(order)
        items.append(QuizItem(q, answers[q["id"]], order))
    return items


def render_quiz(items: list[QuizItem], title: str) -> str:
    conventions = sorted({c for i in items if (c := i.question["conventions"])})
    out = [
        f"# {title}",
        "",
        "Purpose: verify that the student has read *How a Financial Exchange Works* "
        "and internalized the core principles of a modern exchange covered by the "
        "questions below.",
        "",
        "## Name/ID",
        "",
        "&nbsp;",
        "",
        "---",
        "",
        "",
        "&nbsp;",
        "",
        "## Instructions",
        "",
        f"- There are {len(items)} questions.",
        "- Each question has five statements (A-E) which may be false or true.",
        "- Select all statements you believe to be correct by clearly filling the "
        "square before the question.",
        "- Each question may have multiple correct statements (for some, all five "
        "statements may be correct).",
        "- There is always at least one correct statement.",
        "",
    ]
    if conventions:
        out += ["## Conventions", ""]
        out += [CONVENTIONS[c] for c in conventions]
    out += [
        "## Scoring",
        "",
        "- +1 point for each correct option selected.",
        "- -2 points for each incorrect option selected.",
        "- 0 points for options not selected.",
        "- Final test score is capped at a minimum of 0: if raw total is negative, "
        "recorded score is 0.",
        "- A passing score is 70% of the maximum rounded down to the nearest integer.",
        "",
        PAGE_BREAK,
        "",
        "## Questions",
        "",
    ]
    for n, item in enumerate(items, 1):
        q = item.question
        out.append(f"### {n}. {q['title']}")
        if q["scenario"]:
            out += [f"*{q['scenario']}*", ""]
        for letter, k in zip(LETTERS, item.order):
            out.append(f"- [ ] {letter}. {q['statements'][k]['text']}")
        out.append("")
    out += ["&nbsp;", "", "---", ""]
    return "\n".join(out)


def render_key(items: list[QuizItem], bank: Bank, title: str, settings: str) -> str:
    max_points = sum(i.answer["max_points"] for i in items)
    out = [
        f"# Answer Key — {title}",
        "",
        "Correct statements are listed per question. Scoring: +1 per correct "
        "selection, -2 per incorrect selection, 0 for unselected, floor of 0 overall.",
        "",
        f"Generated with: `{settings}`",
        "",
        "| Q | Correct options | Question id | Area | Difficulty |",
        "|---|---|---|---|---|",
    ]
    for n, item in enumerate(items, 1):
        q = item.question
        out.append(
            f"| {n} | {', '.join(item.correct_letters())} | {q['id']} | "
            f"{bank.area_name(q['area'])} | {q['difficulty']} |"
        )
    out += [
        "",
        f"**MAX: {max_points}p, PASS: {int(max_points * PASS_FRACTION)}p**",
        "",
    ]
    explained = [
        (n, i)
        for n, i in enumerate(items, 1)
        if i.answer["note"] or any(s["explanation"] for s in i.answer["statements"])
    ]
    if explained:
        out += ["## Explanations", ""]
    for n, item in explained:
        q = item.question
        out += [f"### {n}. {q['title']} — {', '.join(item.correct_letters())}", ""]
        answer_of = {s["statement_id"]: s for s in item.answer["statements"]}
        for letter, k in zip(LETTERS, item.order):
            st = q["statements"][k]
            ans = answer_of[st["id"]]
            line = f"- **{letter} — {'true' if ans['correct'] else 'false'}.** {st['text']}."
            if ans["explanation"]:
                line += f" {ans['explanation']}"
            out.append(line)
        if item.answer["note"]:
            note = re.sub(
                r"\{([A-Z]{2}-\d{2}-\d{2}-\d)\}",
                lambda m: item.letter_of(m[1]),
                item.answer["note"],
            )
            out += ["", f"**Note:** {note}"]
        out.append("")
    return "\n".join(out)


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Generate a random quiz and answer key from the question bank."
    )
    p.add_argument(
        "--count", type=int, default=20, help="number of questions (default 20)"
    )
    p.add_argument(
        "--difficulty",
        default="Easy,Medium,Hard",
        help="comma-separated difficulty levels to include (default all)",
    )
    p.add_argument(
        "--numerical",
        choices=("include", "exclude", "only"),
        default="include",
        help="questions that need calculations: include, exclude or only (default include)",
    )
    p.add_argument(
        "--source",
        choices=tuple(SOURCES),
        default="both",
        help="draw from quiz, knowledge_check or both (default both)",
    )
    p.add_argument(
        "--area",
        help="comma-separated area ids to restrict to (default all; see --list-areas)",
    )
    p.add_argument(
        "--exclude-area",
        help="comma-separated area ids to leave out, e.g. implied-orders",
    )
    p.add_argument(
        "--exclude-difficulty",
        help="comma-separated difficulty levels to leave out, e.g. Hard",
    )
    p.add_argument(
        "--seed", type=int, help="random seed; printed so a quiz can be regenerated"
    )
    p.add_argument("--title", default=DEFAULT_TITLE, help="quiz title")
    p.add_argument(
        "--output",
        type=Path,
        default=Path("quiz.md"),
        help="quiz file; the key is written next to it as <name>-answer-key.md",
    )
    p.add_argument("--questions", type=Path, default=HERE / "questions.json")
    p.add_argument("--answers", type=Path, default=HERE / "answers.json")
    p.add_argument(
        "--list-areas",
        action="store_true",
        help="list area ids with question counts and exit",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    bank = load_bank(args.questions)
    if args.list_areas:
        for a in bank.areas:
            n = sum(q["area"] == a["id"] for q in bank.questions)
            print(f"{a['id']:26} {n:4}  {a['name']}")
        return 0

    def split(value: str | None, normalise: bool = False) -> tuple[str, ...]:
        items = (v.strip() for v in (value or "").split(",") if v.strip())
        return tuple(v.capitalize() if normalise else v for v in items)

    known_areas = tuple(a["id"] for a in bank.areas)
    checks = (
        (split(args.difficulty, True), DIFFICULTIES, "difficulty"),
        (split(args.exclude_difficulty, True), DIFFICULTIES, "difficulty"),
        (split(args.area), known_areas, "area"),
        (split(args.exclude_area), known_areas, "area"),
    )
    for value, allowed, what in checks:
        unknown = [v for v in value if v not in allowed]
        if unknown:
            print(f"error: unknown {what}: {', '.join(unknown)}", file=sys.stderr)
            return 2
    excluded_difficulties = split(args.exclude_difficulty, True)
    difficulties = tuple(
        d for d in split(args.difficulty, True) if d not in excluded_difficulties
    )
    excluded_areas = split(args.exclude_area)
    areas: tuple[str, ...] | None = None
    if args.area or excluded_areas:
        areas = tuple(
            a for a in split(args.area) or known_areas if a not in excluded_areas
        )
    if not difficulties or areas == ():
        print("error: the exclusions leave nothing to choose from", file=sys.stderr)
        return 2
    if args.count < 1:
        print("error: --count must be at least 1", file=sys.stderr)
        return 2
    if not args.answers.exists():
        print(
            f"error: {args.answers} not found; decrypt it first "
            "(make decrypt-answers in ..)",
            file=sys.stderr,
        )
        return 2

    seed = (
        args.seed if args.seed is not None else random.SystemRandom().randrange(10**6)
    )
    rng = random.Random(seed)
    try:
        questions = select_questions(
            bank,
            count=args.count,
            difficulties=difficulties,
            numerical=args.numerical,
            sources=SOURCES[args.source],
            areas=areas,
            rng=rng,
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    items = build_items(questions, load_answers(args.answers), rng)

    settings = (
        f"--count {args.count} --difficulty {','.join(difficulties)} "
        f"--numerical {args.numerical} --source {args.source}"
        + (f" --area {','.join(areas)}" if areas else "")
        + f" --seed {seed}"
    )
    key_path = args.output.with_name(f"{args.output.stem}-answer-key.md")
    args.output.write_text(render_quiz(items, args.title), encoding="utf-8")
    key_path.write_text(render_key(items, bank, args.title, settings), encoding="utf-8")
    print(f"wrote {args.output} and {key_path} (seed {seed})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
