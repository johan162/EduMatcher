"""Tests for quizgen.py: selection filters, rendering, key correctness and the CLI."""

from __future__ import annotations

import json
import random
import re
import sys
from pathlib import Path
from typing import Any

import pytest

BANK_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BANK_DIR))

import quizgen  # noqa: E402

AREAS = [
    {"id": "order-types", "name": "Order Types & Time in Force"},
    {"id": "implied-orders", "name": "Implied Orders"},
]


def make_question(
    qid: str, *, area: str, difficulty: str, numerical: bool, source: str
) -> dict[str, Any]:
    return {
        "id": qid,
        "source": source,
        "source_file": "x.md",
        "variant": 1,
        "number": int(qid[-2:]),
        "title": f"Title {qid}",
        "scenario": "Scenario: a test setup." if numerical else None,
        "area": area,
        "tags": [],
        "difficulty": difficulty,
        "numerical": numerical,
        "conventions": "implied-spread" if area == "implied-orders" else None,
        "book_refs": ["x.md"],
        "statements": [
            {"id": f"{qid}-{i}", "text": f"Statement {qid}-{i}"} for i in range(1, 6)
        ],
    }


def make_answer(qid: str, correct: set[int]) -> dict[str, Any]:
    return {
        "question_id": qid,
        "statements": [
            {
                "statement_id": f"{qid}-{i}",
                "correct": i in correct,
                "explanation": f"Why {qid}-{i}" if i == 1 else None,
            }
            for i in range(1, 6)
        ],
        "note": f"{{{qid}-2}} is the second statement.",
        "max_points": len(correct),
    }


@pytest.fixture
def bank_files(tmp_path: Path) -> tuple[Path, Path]:
    questions, answers = [], []
    combos = [
        ("order-types", "Easy", False, "quiz"),
        ("order-types", "Medium", True, "knowledge_check"),
        ("implied-orders", "Hard", True, "knowledge_check"),
        ("implied-orders", "Medium", False, "quiz"),
    ]
    for n in range(1, 21):
        area, difficulty, numerical, source = combos[n % 4]
        prefix = "QZ" if source == "quiz" else "KC"
        qid = f"{prefix}-01-{n:02d}"
        questions.append(
            make_question(
                qid,
                area=area,
                difficulty=difficulty,
                numerical=numerical,
                source=source,
            )
        )
        answers.append(make_answer(qid, {1, 3} if n % 2 else {2, 4, 5}))
    qpath, apath = tmp_path / "questions.json", tmp_path / "answers.json"
    qpath.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "book_version": "1.0.0",
                "areas": AREAS,
                "questions": questions,
            }
        )
    )
    apath.write_text(json.dumps({"schema_version": "1.0", "answers": answers}))
    return qpath, apath


def select(bank: quizgen.Bank, **kw: Any) -> list[quizgen.Question]:
    args: dict[str, Any] = {
        "count": 5,
        "difficulties": quizgen.DIFFICULTIES,
        "numerical": "include",
        "sources": quizgen.SOURCES["both"],
        "areas": None,
        "rng": random.Random(1),
    }
    args.update(kw)
    return quizgen.select_questions(bank, **args)


def test_filters_are_respected(bank_files: tuple[Path, Path]) -> None:
    bank = quizgen.load_bank(bank_files[0])
    assert all(q["difficulty"] == "Hard" for q in select(bank, difficulties=("Hard",)))
    assert all(q["numerical"] for q in select(bank, numerical="only"))
    assert not any(q["numerical"] for q in select(bank, numerical="exclude"))
    assert all(q["source"] == "quiz" for q in select(bank, sources=("quiz",)))
    picked = select(bank, areas=("implied-orders",))
    assert {q["area"] for q in picked} == {"implied-orders"}


def test_not_enough_questions_raises(bank_files: tuple[Path, Path]) -> None:
    bank = quizgen.load_bank(bank_files[0])
    with pytest.raises(ValueError, match="not enough questions: 5 match"):
        select(bank, count=6, difficulties=("Hard",))


def test_selection_is_in_area_order_and_seeded(bank_files: tuple[Path, Path]) -> None:
    bank = quizgen.load_bank(bank_files[0])
    first = select(bank, count=10, rng=random.Random(7))
    again = select(bank, count=10, rng=random.Random(7))
    assert [q["id"] for q in first] == [q["id"] for q in again]
    order = [q["area"] for q in first]
    assert order == sorted(order, key=["order-types", "implied-orders"].index)


def test_key_letters_follow_shuffled_statements(bank_files: tuple[Path, Path]) -> None:
    bank = quizgen.load_bank(bank_files[0])
    answers = quizgen.load_answers(bank_files[1])
    items = quizgen.build_items(select(bank, count=10), answers, random.Random(3))
    for item in items:
        shown = [item.question["statements"][k]["id"] for k in item.order]
        truth = {s["statement_id"]: s["correct"] for s in item.answer["statements"]}
        expected = [quizgen.LETTERS[i] for i, sid in enumerate(shown) if truth[sid]]
        assert item.correct_letters() == expected


def test_rendered_quiz_and_key(bank_files: tuple[Path, Path]) -> None:
    bank = quizgen.load_bank(bank_files[0])
    answers = quizgen.load_answers(bank_files[1])
    items = quizgen.build_items(select(bank, count=8), answers, random.Random(3))
    quiz = quizgen.render_quiz(items, "Test quiz")
    key = quizgen.render_key(items, bank, "Test quiz", "--seed 1")

    assert len(re.findall(r"(?m)^### \d+\. ", quiz)) == 8
    assert len(re.findall(r"(?m)^- \[ \] [A-E]\. ", quiz)) == 40
    assert "- There are 8 questions." in quiz
    assert ("## Conventions" in quiz) == any(i.question["conventions"] for i in items)
    assert "— true" not in quiz and "Why " not in quiz  # no answers leak into the quiz

    max_points = sum(i.answer["max_points"] for i in items)
    assert f"**MAX: {max_points}p, PASS: {int(max_points * 0.7)}p**" in key
    for n, item in enumerate(items, 1):
        assert (
            f"| {n} | {', '.join(item.correct_letters())} | {item.question['id']} |"
            in key
        )
    assert "{" not in key.split("## Explanations")[1]  # every placeholder resolved
    letter = items[0].letter_of(f"{items[0].question['id']}-2")
    assert f"**Note:** {letter} is the second statement." in key


def test_cli_writes_quiz_and_key(bank_files: tuple[Path, Path], tmp_path: Path) -> None:
    out = tmp_path / "exam.md"
    argv = ["--count", "6", "--seed", "5", "--output", str(out)]
    argv += ["--questions", str(bank_files[0]), "--answers", str(bank_files[1])]
    assert quizgen.main(argv) == 0
    key = (tmp_path / "exam-answer-key.md").read_text()
    assert "--seed 5" in key
    first = out.read_text()
    assert quizgen.main(argv) == 0
    assert out.read_text() == first  # same seed, same quiz


def test_cli_rejects_bad_input(bank_files: tuple[Path, Path], tmp_path: Path) -> None:
    files = ["--questions", str(bank_files[0]), "--answers", str(bank_files[1])]
    out = ["--output", str(tmp_path / "q.md")]
    assert quizgen.main(["--difficulty", "Tricky", *files, *out]) == 2
    assert quizgen.main(["--area", "nowhere", *files, *out]) == 2
    assert quizgen.main(["--count", "99", *files, *out]) == 1
    missing = [
        "--questions",
        str(bank_files[0]),
        "--answers",
        str(tmp_path / "none.json"),
    ]
    assert quizgen.main([*missing, *out]) == 2


@pytest.mark.skipif(
    not (BANK_DIR / "answers.json").exists(), reason="answers.json is encrypted"
)
def test_real_bank_is_consistent() -> None:
    bank = quizgen.load_bank(BANK_DIR / "questions.json")
    answers = quizgen.load_answers(BANK_DIR / "answers.json")
    ids = [q["id"] for q in bank.questions]
    assert len(ids) == len(set(ids)) == len(answers)
    area_ids = {a["id"] for a in bank.areas}
    for q in bank.questions:
        a = answers[q["id"]]
        assert q["area"] in area_ids
        assert [s["id"] for s in q["statements"]] == [
            s["statement_id"] for s in a["statements"]
        ]
        assert a["max_points"] == sum(s["correct"] for s in a["statements"]) >= 1
        for ref in re.findall(r"\{([^}]+)\}", a["note"] or ""):
            assert ref.startswith(q["id"] + "-")


def test_cli_exclusions(bank_files: tuple[Path, Path], tmp_path: Path) -> None:
    files = ["--questions", str(bank_files[0]), "--answers", str(bank_files[1])]
    out = tmp_path / "q.md"
    key = tmp_path / "q-answer-key.md"
    base = ["--count", "5", "--seed", "2", "--output", str(out), *files]

    assert quizgen.main([*base, "--exclude-area", "implied-orders"]) == 0
    assert "Implied Orders" not in key.read_text()
    assert "--area order-types" in key.read_text()

    assert quizgen.main([*base, "--exclude-difficulty", "Hard,Easy"]) == 0
    assert "| Hard |" not in key.read_text() and "| Easy |" not in key.read_text()

    assert quizgen.main([*base, "--numerical", "exclude"]) == 0
    assert "*Scenario:" not in out.read_text()  # only numerical fixtures have one

    everything = "order-types,implied-orders"
    assert quizgen.main([*base, "--exclude-area", everything]) == 2
    assert quizgen.main([*base, "--exclude-area", "nowhere"]) == 2
