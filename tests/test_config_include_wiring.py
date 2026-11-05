"""An authored config split with ``include:`` must behave like the single file."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from edumatcher.config_artifact import content_digest
from edumatcher.config_deploy import compile_config, resolve_example
from edumatcher.config_show.cli import main as config_show_main
from edumatcher.cverifier import layer1_yaml


def _split(source: Path, target: Path) -> Path:
    """Write *source* to *target* with symbols and participants in own files."""
    raw = yaml.safe_load(source.read_text(encoding="utf-8"))
    for key in ("symbols", "participants"):
        (target / f"{key}.yaml").write_text(
            yaml.safe_dump({key: raw.pop(key)}, sort_keys=False), encoding="utf-8"
        )
    raw = {"include": ["symbols.yaml", "participants.yaml"], **raw}
    main = target / "engine_config.yaml"
    main.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    return main


@pytest.mark.parametrize("example", ["s3-basic", "s3-basic-nomm"])
def test_split_config_compiles_to_the_same_content(
    tmp_path: Path, example: str
) -> None:
    source = resolve_example(example)
    whole = tmp_path / "whole"
    whole.mkdir()
    (whole / "engine_config.yaml").write_text(source.read_text(encoding="utf-8"))
    split = tmp_path / "split"
    split.mkdir()
    main = _split(whole / "engine_config.yaml", split)

    expected = compile_config(whole / "engine_config.yaml")
    actual = compile_config(main)

    assert actual.engine.symbols
    assert content_digest(actual) == content_digest(expected)


def test_verifier_reports_a_broken_include_as_y005(tmp_path: Path) -> None:
    main = tmp_path / "engine_config.yaml"
    main.write_text("include: [missing.yaml]\n", encoding="utf-8")
    results, data = layer1_yaml.load(main)
    assert data is None
    assert [r.code for r in results] == ["Y005"]
    assert "missing.yaml" in results[0].message


def test_verifier_returns_the_merged_mapping(tmp_path: Path) -> None:
    (tmp_path / "s.yaml").write_text("symbols: {AAA: {}}\n", encoding="utf-8")
    main = tmp_path / "engine_config.yaml"
    main.write_text("include: [s.yaml]\n", encoding="utf-8")
    results, data = layer1_yaml.load(main)
    assert results == []
    assert data == {"symbols": {"AAA": {}}}


def test_config_show_reads_included_files(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    main = _split(resolve_example("s3-basic"), tmp_path)
    assert config_show_main(["--file", str(main), "--width", "100"]) == 0
    assert "participants" in capsys.readouterr().out.lower()


def test_config_show_bad_include_exits_three(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    main = tmp_path / "engine_config.yaml"
    main.write_text("include: [missing.yaml]\n", encoding="utf-8")
    assert config_show_main(["--file", str(main)]) == 3
    assert "missing.yaml" in capsys.readouterr().err


def _broken_split(tmp_path: Path) -> Path:
    (tmp_path / "symbols.yaml").write_text(
        "symbols:\n  AAA: {tick_decimals: two}\n", encoding="utf-8"
    )
    main = tmp_path / "engine_config.yaml"
    main.write_text(
        "include: [symbols.yaml]\nparticipants:\n  - {id: T1, role: TRADER}\n",
        encoding="utf-8",
    )
    return main


def test_verifier_findings_name_the_included_file(tmp_path: Path) -> None:
    from edumatcher.cverifier.cli import run

    results, _ = run(_broken_split(tmp_path))
    in_symbols = [r for r in results if r.path.startswith("symbols.AAA")]
    assert in_symbols
    assert {r.file for r in in_symbols} == {"symbols.yaml"}
    assert all(r.file == "" for r in results if r.path.startswith("participants"))


def test_verifier_text_and_json_show_the_file(tmp_path: Path) -> None:
    import json

    from edumatcher.cverifier.cli import run
    from edumatcher.cverifier.formatter import format_json, format_text
    from edumatcher.cverifier.models import RiskSummary, VerificationReport

    main = _broken_split(tmp_path)
    results, _ = run(main)
    report = VerificationReport(
        file=str(main),
        results=results,
        summary={"errors": 1, "warnings": 0, "info": 0},
        risk_summary=RiskSummary(),
        verdict="ERROR",
    )
    assert "  in symbols.yaml" in format_text(report, color=False)
    checks = json.loads(format_json(report))["checks"]
    assert any(c["file"] == "symbols.yaml" for c in checks)


def test_config_show_lists_included_files(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    main = _split(resolve_example("s3-basic"), tmp_path)
    assert config_show_main(["--file", str(main), "--width", "140"]) == 0
    assert "includes: symbols.yaml, participants.yaml" in capsys.readouterr().out
