"""WP5: typed input, scenario files, the pipeline, the report and --no-tui."""

import io
from pathlib import Path

import pytest
from rich.console import Console

from edumatcher.valuation.fields import BY_KEY, FIELDS
from edumatcher.new_symbol.main import build_parser as new_symbol_parser
from edumatcher.valuation.main import CASES, case_names, main
from edumatcher.valuation.model.montecarlo import share_below
from edumatcher.valuation.model.offering import Outcome
from edumatcher.valuation.pipeline import CannotValue, run
from edumatcher.valuation.presets import load_presets
from edumatcher.valuation.report.build import (
    Code,
    Table,
    build_report,
    compare,
    listing_args,
)
from edumatcher.valuation.report.render_md import render_markdown
from edumatcher.valuation.report.render_pdf import CHAPTERS, PROSE, write_pdf
from edumatcher.valuation.report.render_rich import print_report
from edumatcher.valuation.resolve import InvalidAnswers, Source, resolve
from edumatcher.valuation.scenario_io import dump, load
from edumatcher.valuation.units import NOT_ANSWERED, ParseError, format_value, parse
from tests.test_valuation_resolve import AURORA

PRESETS = load_presets()
QUICK = {"simulation.draws": 200}  # keep Monte Carlo short in tests


@pytest.fixture(scope="module")
def aurora_run():
    return run({**AURORA, **QUICK}, PRESETS)


# -- units -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("key", "text", "value"),
    [
        ("market.tam", "40bn", 40e9),
        ("market.tam", "300m", 300e6),
        ("market.tam", "1.4md", 1.4e9),  # Swedish: miljard
        ("market.tam", "2 mdr", 2e9),
        ("market.tam", "300mkr", 300e6),  # miljoner kronor
        ("market.tam", "2.5k", 2500.0),
        ("market.tam", "90,000,000", 90e6),
        ("market.tam", "1_000", 1000.0),
        ("customers.churn", "8", 0.08),  # percentage points
        ("customers.churn", "8%", 0.08),
        ("rates.size_premium_2", "0.5", 0.005),  # never 50%
        ("investors.comps_multiple", "10x", 10.0),
        ("customers.now", "1,800", 1800),
        ("company.dual_class", "yes", True),
        ("company.dual_class", "no", False),
        ("management.last_round", "none", None),
        ("index.relax", "none", "none"),  # a choice named "none"
        ("company.name", "Aurora", "Aurora"),
    ],
)
def test_parse(key: str, text: str, value: object) -> None:
    assert parse(BY_KEY[key], text) == value


def test_empty_text_is_not_an_answer() -> None:
    assert parse(BY_KEY["customers.churn"], "  ") is NOT_ANSWERED


@pytest.mark.parametrize(
    ("key", "text"),
    [
        ("customers.churn", "high"),
        ("customers.now", "12.5"),
        ("company.dual_class", "maybe"),
        ("customers.churn", "none"),  # not optional
    ],
)
def test_parse_errors(key: str, text: str) -> None:
    with pytest.raises(ParseError):
        parse(BY_KEY[key], text)


def test_every_resolved_value_round_trips(aurora_run) -> None:
    for spec in FIELDS:
        value = aurora_run.resolved[spec.key]
        again = parse(spec, format_value(spec, value))
        if isinstance(value, float):
            assert again == pytest.approx(value, rel=1e-5), spec.key
        else:
            assert again == value, spec.key


# -- scenario files ----------------------------------------------------------------


def test_scenario_file_holds_only_the_answers() -> None:
    text = dump(AURORA)
    assert "arpu" not in text and "last_fy_revenue: 90m" in text
    assert load(text) == AURORA


def test_scenario_file_with_defaults_reproduces_the_company(aurora_run) -> None:
    text = dump(AURORA, aurora_run.resolved)
    assert "  arpu: 60,000  # preset" in text
    answers = load(text)
    assert len(answers) == len(FIELDS)
    again = resolve(answers, PRESETS)
    for key, value in aurora_run.resolved.values.items():
        if isinstance(value, float):
            assert again[key] == pytest.approx(value, rel=1e-5), key
        else:
            assert again[key] == value, key


@pytest.mark.parametrize(
    ("text", "fragment"),
    [
        ("pm_valuation: 2\n", "not a pm-valuation scenario"),
        ("company: {name: X}\n", "not a pm-valuation scenario"),
        ("pm_valuation: 1\ncompany: {nam: X}\n", "unknown field 'company.nam'"),
        ("pm_valuation: 1\ncustomers: {churn: lots}\n", "customers.churn"),
    ],
)
def test_bad_scenario_files(text: str, fragment: str) -> None:
    with pytest.raises(ValueError, match=fragment):
        load(text)


def test_yaml_booleans_are_accepted() -> None:
    assert load("pm_valuation: 1\ncompany: {dual_class: yes}\n") == {
        "company.dual_class": True
    }


# -- pipeline ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("mode", "has_scenarios", "has_mc"),
    [("deterministic", True, False), ("montecarlo", False, True), ("both", True, True)],
)
def test_modes(mode: str, has_scenarios: bool, has_mc: bool) -> None:
    result = run({**AURORA, **QUICK, "simulation.mode": mode}, PRESETS)
    assert (result.scenarios is not None, result.mc is not None) == (
        has_scenarios,
        has_mc,
    )


def test_preview_skips_the_slow_parts() -> None:
    result = run(AURORA, PRESETS, deterministic_only=True)
    assert result.scenarios is None and result.mc is None
    assert result.pricing.listing is not None


def test_uncomputable_company() -> None:
    with pytest.raises(CannotValue, match="terminal growth"):
        run({"rates.r2_override": 0.03}, PRESETS)
    with pytest.raises(InvalidAnswers):
        run({"customers.churn": 5.0}, PRESETS)


def test_derived_problems_do_not_crash_later_rules() -> None:
    """A tiny revenue rounds customers to 0; the rules that run the forecast
    must not see it (they used to divide by zero)."""
    with pytest.raises(InvalidAnswers) as caught:
        resolve({"customers.last_fy_revenue": 9.0}, PRESETS)
    assert [key for key, _ in caught.value.problems] == ["customers.now"]


# -- the report --------------------------------------------------------------------


def _section(report, title: str):
    return next(s for s in report.sections if s.title.split(". ", 1)[1] == title)


def test_report_sections(aurora_run) -> None:
    report = build_report(aurora_run, PRESETS)
    assert report.verdict == "PROCEED"
    titles = [s.title for s in report.sections]
    assert titles[0] == "1. Verdict" and titles[-1] == "19. What this model leaves out"
    assert [t.split(".")[0] for t in titles] == [str(i) for i in range(1, 20)]


def test_report_hand_off_and_s1(aurora_run) -> None:
    report = build_report(aurora_run, PRESETS)
    code = _section(report, "Next step").blocks[0]
    assert isinstance(code, Code)
    assert code.text == (
        "pm-new-symbol --symbol AURM --ipo-price 14.50 "
        "--outstanding-shares 100689655 --tick-decimals 2"
    )
    cover = _section(report, "S-1 cover").blocks[0]
    assert isinstance(cover, Table)
    rows = {row[0]: row[1] for row in cover.rows}
    assert rows["Emerging growth company"].startswith("yes")
    assert rows["Smaller reporting company"].startswith("yes")  # the revenue route


def test_postponed_report() -> None:
    result = run(
        {
            **AURORA,
            **QUICK,
            "management.min_market_cap": 1.6e9,
            "simulation.mode": "deterministic",
        },
        PRESETS,
    )
    report = build_report(result, PRESETS)
    assert report.verdict == "POSTPONE"
    titles = [s.title.split(". ", 1)[1] for s in report.sections]
    assert "Monte Carlo" not in " ".join(titles)
    text = render_markdown(report)
    assert "No listing: the IPO is postponed." in text
    assert "V012 (result): IPO postponed" in text


def test_risk_factors_come_from_warnings() -> None:
    result = run({**AURORA, **QUICK, "investors.hype": 8}, PRESETS)
    risks = _section(build_report(result, PRESETS), "Risk factors").blocks[0]
    assert any("sentiment" in item for item in risks.items)


def test_markdown_rendering(aurora_run) -> None:
    text = render_markdown(build_report(aurora_run, PRESETS))
    assert text.startswith("# Aurora Metrics Inc. (AURM) — IPO valuation\n")
    assert "## 10. DCF" in text
    assert "|---|---:|" in text  # left label, right-aligned numbers
    assert "```text\npm-new-symbol --symbol AURM" in text
    assert text.count("```") % 2 == 0


def test_rich_rendering(aurora_run) -> None:
    buffer = io.StringIO()
    print_report(build_report(aurora_run, PRESETS), Console(file=buffer, width=140))
    assert (
        "PROCEED" in buffer.getvalue() and "Fair value per share" in buffer.getvalue()
    )


@pytest.mark.parametrize("width", [80, 60])
def test_narrow_terminals_split_tables_instead_of_cutting_them(
    aurora_run, width: int
) -> None:
    buffer = io.StringIO()
    print_report(build_report(aurora_run, PRESETS), Console(file=buffer, width=width))
    lines = buffer.getvalue().splitlines()
    assert not any("…" in line for line in lines)
    assert max(len(line) for line in lines) <= width
    income = buffer.getvalue().split("Income statement")[1].split("Taxes")[0]
    assert income.count("USD m") >= 2  # split, repeating the label column
    assert "Y1 " in income and "Y10" in income


def test_wide_terminals_keep_tables_whole(aurora_run) -> None:
    buffer = io.StringIO()
    print_report(build_report(aurora_run, PRESETS), Console(file=buffer, width=200))
    headers = [line for line in buffer.getvalue().splitlines() if " Y1 " in line]
    assert len(headers) == 2  # income statement and FCFF, each in one piece
    assert all("Y10" in line for line in headers)


def _pages(pdf: Path) -> int:
    return pdf.read_bytes().count(b"/Type /Page\n")


def test_pdf_report(aurora_run, tmp_path: Path) -> None:
    target = tmp_path / "aurora.pdf"
    write_pdf(aurora_run, build_report(aurora_run, PRESETS), target)
    data = target.read_bytes()
    assert data.startswith(b"%PDF")
    assert _pages(target) >= 15  # cover, contents, summary, six chapters, appendices
    assert b"/MediaBox [ 0 0 595.2756 841.8898 ]" in data  # A4 by default


def test_pdf_report_of_a_postponed_ipo_on_letter(tmp_path: Path) -> None:
    result = run(
        {**AURORA, "management.min_market_cap": 1.6e9,
         "simulation.mode": "deterministic"},
        PRESETS,
    )  # fmt: skip
    target = tmp_path / "postponed.pdf"
    write_pdf(result, build_report(result, PRESETS), target, "letter")
    assert b"/MediaBox [ 0 0 612 792 ]" in target.read_bytes()
    assert _pages(target) >= 12


def test_every_report_section_has_a_place_and_prose_in_the_pdf(aurora_run) -> None:
    placed = [name for _, _, names in CHAPTERS for name in names]
    assert set(placed) == set(PROSE)
    for section in build_report(aurora_run, PRESETS).sections:
        title = section.title.split(". ", 1)[1]
        if title in ("Verdict", "Assumptions"):  # the summary and Appendix A
            continue
        assert any(title.startswith(name) for name in placed), title


def test_compare_lists_what_changed(aurora_run) -> None:
    other = run({**AURORA, **QUICK, "customers.churn": 0.12}, PRESETS)
    section = compare(aurora_run, other)
    changed = section.blocks[1]
    assert isinstance(changed, Table)
    labels = [row[0] for row in changed.rows]
    assert "Annual churn" in labels
    assert "Annual churn: bear" in labels  # derived from churn, so it moved too
    headlines = section.blocks[0]
    assert isinstance(headlines, Table)
    headline = {row[0]: row for row in headlines.rows}
    assert headline["Fair value per share"][3].startswith("−")


# -- the command line ----------------------------------------------------------------


def test_no_tui(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    scenario = tmp_path / "aurora.yaml"
    scenario.write_text(dump(AURORA), encoding="utf-8")
    export, save = tmp_path / "report.md", tmp_path / "full.yaml"
    pdf = tmp_path / "report.pdf"
    main(
        [
            "--load", str(scenario), "--no-tui", "--mode", "montecarlo",
            "--draws", "200", "--export", str(export),
            "--save", str(save), "--with-defaults",
            "--pdf", str(pdf), "--paper", "letter",
        ]
    )  # fmt: skip
    assert b"/MediaBox [ 0 0 612 792 ]" in pdf.read_bytes()
    out = capsys.readouterr().out
    assert "PROCEED" in out and "Monte Carlo (200 draws" in out
    assert max(len(line) for line in out.splitlines()) == 100  # on any terminal
    assert export.read_text("utf-8").startswith("# Aurora Metrics Inc.")
    saved = load(save.read_text("utf-8"))
    assert saved["simulation.mode"] == "montecarlo"
    assert len(saved) == len(FIELDS)


def test_no_tui_reports_invalid_input(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["--no-tui", "--draws", "5"])
    assert exit_info.value.code == 1
    assert "Monte Carlo draws" in capsys.readouterr().err


@pytest.mark.parametrize(
    "argv",
    [
        ["--no-tui", "--quick"],
        ["--no-tui", "--with-defaults"],
        ["--mode", "fast"],
        ["--paper", "a3"],
        ["--list"],
        ["--no-tui", "--config", "engine.yaml"],
        ["--load", "a.yaml", "--case", "tornfalk"],
        ["--market", "uk"],
        ["--case", "no-such-case"],
    ],
)
def test_usage_errors(argv: list[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(argv)
    assert exit_info.value.code == 2


def test_hand_off_parses_as_pm_new_symbol(aurora_run) -> None:
    listing = aurora_run.pricing.listing
    args = new_symbol_parser().parse_args(listing_args("AURM", listing))
    assert (args.symbol, str(args.ipo_price)) == ("AURM", "14.50")
    assert (args.outstanding_shares, args.tick_decimals) == (100689655, 2)


def test_list_hands_the_listing_to_pm_new_symbol(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr("edumatcher.new_symbol.main.main", calls.append)
    main(["--case", "tornfalk", "--no-tui", "--mode", "deterministic",
          "--list", "--config", "engine.yaml"])  # fmt: skip
    assert calls == [
        ["--symbol", "TORN", "--ipo-price", "105.00",
         "--outstanding-shares", "158095238", "--tick-decimals", "2",
         "--config", "engine.yaml"]
    ]  # fmt: skip


def test_list_refuses_a_postponed_ipo(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr("edumatcher.new_symbol.main.main", calls.append)
    with pytest.raises(SystemExit) as exit_info:
        main(["--case", "halvard", "--no-tui", "--mode", "deterministic", "--list"])
    assert exit_info.value.code == 1 and calls == []
    assert "postponed: there is nothing to list" in capsys.readouterr().err


def _case(name: str) -> dict[str, object]:
    answers = load(CASES.joinpath(f"{name}.yaml").read_text("utf-8"))
    return {**answers, "simulation.mode": "deterministic"}


def test_classroom_cases() -> None:
    """The numbers docs/training/280-ipo-valuation.md and the user guide quote."""
    assert case_names() == ["halvard", "tornfalk"]

    tornfalk = run(_case("tornfalk"), PRESETS)
    hot = tornfalk.pricing
    assert tornfalk.valuation.fair_value == pytest.approx(117.45, abs=0.005)
    assert hot.price_range == (94.5, 105.0) and hot.position == "within"
    assert hot.listing is not None and hot.listing.price == 105.0  # the maximum price
    assert hot.coverage is not None and hot.coverage == pytest.approx(11.92, abs=0.01)
    assert hot.pop == pytest.approx(0.298, abs=0.001)
    assert hot.money_left == pytest.approx(1193.1e6, rel=1e-4)

    mc = run({**_case("tornfalk"), "simulation.mode": "montecarlo"}, PRESETS).mc
    assert mc is not None
    fair = [s.fair_value for s in mc.samples]
    assert share_below(fair, 105.0) == pytest.approx(0.438, abs=0.001)

    halvard = _case("halvard")
    assert run(halvard, PRESETS).pricing.listing is None
    floors = {m: run({**halvard, "management.min_market_cap": m}, PRESETS).pricing
              for m in (2.6e9, 2.5e9, 2.4e9)}  # fmt: skip
    assert floors[2.6e9].outcome is Outcome.POSTPONED
    assert floors[2.5e9].outcome is Outcome.THIN_BOOK
    assert floors[2.4e9].listing is not None and floors[2.4e9].listing.price == 95.0
    del halvard["management.last_round"]  # the exercise: accept the down round
    down = run(halvard, PRESETS).pricing
    assert down.listing is not None and down.listing.price == 94.5
    assert down.listing.market_cap == pytest.approx(2390e6, rel=1e-3)


def test_swedish_and_us_framing() -> None:
    """--market se prices at most at the top of the range, in SEK, on a
    prospectus; --market us may price 20% above it, in USD, on an S-1."""
    se = run(_case("tornfalk"), PRESETS)
    # The same company in US dollars: a file's amounts are in its market's
    # currency, so switching the market means converting them too.
    in_usd = {"customers.last_fy_revenue": 140e6, "capital.cash": 90e6,
              "offering.shares_pre": 60e6}  # fmt: skip
    us = run({**_case("tornfalk"), **in_usd, "company.market": "us"}, PRESETS)
    assert se.resolved["company.currency"] == "SEK"
    assert se.resolved.sources["rates.risk_free"] is Source.DEFAULT
    assert (se.resolved["rates.risk_free"], se.resolved["capital.tax_rate"]) == (
        0.03,
        0.206,
    )
    assert se.pricing.listing is not None
    assert se.pricing.listing.price <= se.pricing.price_range[1]
    assert us.pricing.listing is not None
    assert us.pricing.listing.price > us.pricing.price_range[1]
    se_cover = build_report(se, PRESETS).sections[1]
    us_cover = build_report(us, PRESETS).sections[1]
    assert se_cover.title == "2. Prospectus cover" and us_cover.title == "2. S-1 cover"
    assert "Emerging growth company" not in render_markdown(build_report(se, PRESETS))
    assert "Finansinspektionen" in render_markdown(build_report(se, PRESETS))


def test_money_defaults_follow_the_market() -> None:
    se = resolve({"company.market": "se"}, PRESETS)
    us = resolve({"company.market": "us"}, PRESETS)
    assert se["customers.arpu"] == 10 * us["customers.arpu"]  # SEK per USD
    assert se["people.loaded_cost"] == pytest.approx(
        0.7 * 10 * us["people.loaded_cost"]
    )
    assert se["costs.public_company"] == 10 * us["costs.public_company"]
    # Pay and productivity both follow the salary level: same staff-cost share.
    assert se["people.headcount"] == round(us["people.headcount"] / 0.7)
    assert se["company.name"] == "Newco AB" and us["company.name"] == "Newco Inc."


def test_random_companies_fail_only_with_explanations() -> None:
    """Any in-range answers either value, or say why not; nothing crashes.

    This caught three real faults: a derived zero read by a later rule, an
    empty free float, and a price range rounded down to zero.
    """
    import random

    from edumatcher.valuation.fields import Unit

    rng = random.Random(11)
    numeric = [s for s in FIELDS if s.lo is not None and s.hi is not None]
    numeric = [s for s in numeric if not s.key.startswith("simulation.")]
    for _ in range(150):
        answers: dict[str, object] = {"simulation.mode": "deterministic"}
        for spec in rng.sample(numeric, 4):
            assert spec.lo is not None and spec.hi is not None
            top = min(spec.hi, spec.lo + rng.choice([1, 10, 1e3, 1e6, 1e9]))
            value = rng.choice([spec.lo, top, rng.uniform(spec.lo, top)])
            whole = spec.unit in (Unit.COUNT, Unit.YEARS, Unit.DAYS)
            answers[spec.key] = int(value) if whole else value
        try:
            result = run(answers, PRESETS)
        except (InvalidAnswers, CannotValue):
            continue
        render_markdown(build_report(result, PRESETS))
