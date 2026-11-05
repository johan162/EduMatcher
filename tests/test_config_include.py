"""Tests for the ``include:`` mechanism of authored config files."""

from __future__ import annotations

from pathlib import Path

import pytest

from edumatcher.config_include import ConfigIncludeError, load_config_mapping


def _write(directory: Path, name: str, text: str) -> Path:
    path = directory / name
    path.write_text(text, encoding="utf-8")
    return path


def test_no_include_returns_file_unchanged(tmp_path: Path) -> None:
    main = _write(tmp_path, "main.yaml", "symbols:\n  AAA: {}\n")
    loaded = load_config_mapping(main)
    assert loaded.data == {"symbols": {"AAA": {}}}
    assert loaded.files == (main,)


def test_empty_main_file_is_an_empty_mapping(tmp_path: Path) -> None:
    assert load_config_mapping(_write(tmp_path, "main.yaml", "")).data == {}


def test_includes_supply_keys_the_main_file_lacks(tmp_path: Path) -> None:
    main = _write(
        tmp_path, "main.yaml", "include: [symbols.yaml, p.yaml]\nlocale: sv\n"
    )
    sym = _write(tmp_path, "symbols.yaml", "symbols:\n  AAA: {}\n")
    par = _write(tmp_path, "p.yaml", "participants:\n  - id: P1\n")
    loaded = load_config_mapping(main)
    assert loaded.data == {
        "locale": "sv",
        "symbols": {"AAA": {}},
        "participants": [{"id": "P1"}],
    }
    assert loaded.files == (main, sym, par)


def test_lists_concatenate_main_first(tmp_path: Path) -> None:
    main = _write(
        tmp_path, "main.yaml", "include: [a.yaml, b.yaml]\nparticipants: [m]\n"
    )
    _write(tmp_path, "a.yaml", "participants: [a1, a2]\n")
    _write(tmp_path, "b.yaml", "participants: [b1]\n")
    assert load_config_mapping(main).data["participants"] == ["m", "a1", "a2", "b1"]


def test_mappings_merge_one_level_deep(tmp_path: Path) -> None:
    main = _write(tmp_path, "main.yaml", "include: [a.yaml]\nsymbols:\n  AAA: {x: 1}\n")
    _write(tmp_path, "a.yaml", "symbols:\n  BBB: {x: 2}\n")
    assert load_config_mapping(main).data["symbols"] == {
        "AAA": {"x": 1},
        "BBB": {"x": 2},
    }


def test_repeated_mapping_key_is_an_error_naming_both_files(tmp_path: Path) -> None:
    main = _write(tmp_path, "main.yaml", "include: [a.yaml]\nsymbols:\n  AAA: {}\n")
    _write(tmp_path, "a.yaml", "symbols:\n  AAA: {}\n")
    with pytest.raises(ConfigIncludeError, match=r"a\.yaml.*symbols\.AAA.*main\.yaml"):
        load_config_mapping(main)


def test_scalar_defined_twice_is_an_error(tmp_path: Path) -> None:
    main = _write(tmp_path, "main.yaml", "include: [a.yaml]\nlocale: sv\n")
    _write(tmp_path, "a.yaml", "locale: en\n")
    with pytest.raises(ConfigIncludeError, match="'locale' is already defined"):
        load_config_mapping(main)


def test_list_and_mapping_do_not_merge(tmp_path: Path) -> None:
    main = _write(tmp_path, "main.yaml", "include: [a.yaml]\nsymbols: []\n")
    _write(tmp_path, "a.yaml", "symbols: {AAA: {}}\n")
    with pytest.raises(ConfigIncludeError, match="cannot be merged"):
        load_config_mapping(main)


@pytest.mark.parametrize("entry", ["/etc/x.yaml", "../x.yaml", "sub/../../x.yaml"])
def test_absolute_and_parent_paths_are_rejected(tmp_path: Path, entry: str) -> None:
    main = _write(tmp_path, "main.yaml", f"include: ['{entry}']\n")
    with pytest.raises(ConfigIncludeError, match="relative path without"):
        load_config_mapping(main)


def test_subdirectory_include_is_allowed(tmp_path: Path) -> None:
    (tmp_path / "parts").mkdir()
    main = _write(tmp_path, "main.yaml", "include: [parts/s.yaml]\n")
    _write(tmp_path / "parts", "s.yaml", "symbols: {AAA: {}}\n")
    assert load_config_mapping(main).data == {"symbols": {"AAA": {}}}


def test_missing_include_is_an_error(tmp_path: Path) -> None:
    main = _write(tmp_path, "main.yaml", "include: [nope.yaml]\n")
    with pytest.raises(ConfigIncludeError, match="included file not found"):
        load_config_mapping(main)


def test_nested_include_is_rejected(tmp_path: Path) -> None:
    main = _write(tmp_path, "main.yaml", "include: [a.yaml]\n")
    _write(tmp_path, "a.yaml", "include: [b.yaml]\n")
    _write(tmp_path, "b.yaml", "symbols: {}\n")
    with pytest.raises(ConfigIncludeError, match="cannot be nested"):
        load_config_mapping(main)


@pytest.mark.parametrize("value", ["a.yaml", "[1, 2]", "{a: b}"])
def test_include_must_be_a_list_of_names(tmp_path: Path, value: str) -> None:
    main = _write(tmp_path, "main.yaml", f"include: {value}\n")
    with pytest.raises(ConfigIncludeError, match="list of file names"):
        load_config_mapping(main)


def test_syntax_error_in_include_names_that_file(tmp_path: Path) -> None:
    main = _write(tmp_path, "main.yaml", "include: [bad.yaml]\n")
    _write(tmp_path, "bad.yaml", "symbols: [unclosed\n")
    with pytest.raises(ConfigIncludeError, match=r"bad\.yaml: not valid YAML"):
        load_config_mapping(main)


def test_included_file_must_be_a_mapping(tmp_path: Path) -> None:
    main = _write(tmp_path, "main.yaml", "include: [a.yaml]\n")
    _write(tmp_path, "a.yaml", "- just\n- a list\n")
    with pytest.raises(ConfigIncludeError, match="must be a YAML mapping"):
        load_config_mapping(main)


def test_error_is_a_value_error(tmp_path: Path) -> None:
    main = _write(tmp_path, "main.yaml", "include: [nope.yaml]\n")
    with pytest.raises(ValueError):
        load_config_mapping(main)
