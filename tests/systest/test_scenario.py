"""Smoke tests for the Scenario schema and loader (task 5.1), plus tests for
the load-time Scenario validators (task 5.2).

Covers just enough to verify the pydantic models and ``load_scenario`` work
correctly: a valid Scenario parses; a missing required field, a wrong type,
and an unknown field each raise :class:`ScenarioValidationError` naming the
offending field; a decimal price string round-trips as ``str`` rather than
being coerced to ``float``; and the ``Scenario``-level model validators
reject a duplicate Label or an undeclared Actor reference (Requirements
3.5, 3.10).

This is deliberately a smoke-level suite. The formal, fuller-coverage test
task for this schema is task 5.3, dispatched separately.

See requirements.md Requirement 3 (Scenario DSL), Criteria 3.1-3.3, 3.5,
3.10.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from edumatcher.systest.scenario import (
    Barrier,
    Scenario,
    ScenarioValidationError,
    Step,
    load_scenario,
)

VALID_SCENARIO_YAML = """
id: LM-023
title: "Aggressing MARKET order sweeps two LIMIT price levels"
tags: [limit, market, matching, phase1]
symbols: [TST1]
session: CONTINUOUS
actors:
  MAKER: {role: trader}
  TAKER: {role: trader}

steps:
  - id: s1
    actor: MAKER
    action: new_order
    label: M1
    order: {symbol: TST1, side: SELL, type: LIMIT, qty: 100, price: "100.00"}
    expect:
      status: NEW
      book:
        TST1: {asks: [["100.00", 100, 1]], bids: []}

  - id: s2
    actor: MAKER
    action: new_order
    label: M2
    order: {symbol: TST1, side: SELL, type: LIMIT, qty: 100, price: "100.01"}
    expect:
      status: NEW

  - barrier: quiesce

  - id: s3
    actor: TAKER
    action: new_order
    label: T1
    order: {symbol: TST1, side: BUY, type: MARKET, qty: 150}
    expect:
      status: FILLED
      fills:
        - {price: "100.00", qty: 100, maker: M1, liquidity: TAKER}
        - {price: "100.01", qty:  50, maker: M2, liquidity: TAKER}
      book:
        TST1: {asks: [["100.01", 50, 1]], bids: []}

verify:
  trades:
    - {symbol: TST1, price: "100.00", qty: 100, aggressor: BUY, maker: M1, taker: T1}
    - {symbol: TST1, price: "100.01", qty:  50, aggressor: BUY, maker: M2, taker: T1}
  positions:
    MAKER: {TST1: -150}
    TAKER: {TST1: 150}
  stats:
    TST1: {last: "100.01", high: "100.01", low: "100.00", volume: 150, trades: 2}
  dissemination:
    calf_trades: 2
    ralf_records: 2
    drop_copies: {MAKER: 2, TAKER: 2}
    audit_trade_events: 2
    ws_events: {MAKER: 3, TAKER: 2}
  invariants: [all]
"""


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "scenario.yaml"
    path.write_text(text, encoding="utf-8")
    return path


class TestValidScenarioParses:
    def test_load_scenario_returns_a_scenario(self, tmp_path: Path) -> None:
        path = _write(tmp_path, VALID_SCENARIO_YAML)
        scenario = load_scenario(path)
        assert isinstance(scenario, Scenario)
        assert scenario.id == "LM-023"
        assert scenario.symbols == ["TST1"]
        assert scenario.session == "CONTINUOUS"
        assert set(scenario.actors) == {"MAKER", "TAKER"}

    def test_steps_and_barrier_are_distinguished(self, tmp_path: Path) -> None:
        path = _write(tmp_path, VALID_SCENARIO_YAML)
        scenario = load_scenario(path)
        assert len(scenario.steps) == 4
        assert isinstance(scenario.steps[0], Step)
        assert isinstance(scenario.steps[1], Step)
        assert isinstance(scenario.steps[2], Barrier)
        assert scenario.steps[2].barrier == "quiesce"
        assert isinstance(scenario.steps[3], Step)

    def test_accepts_an_already_parsed_mapping_via_model_validate(self) -> None:
        raw = yaml.safe_load(VALID_SCENARIO_YAML)
        scenario = Scenario.model_validate(raw)
        assert scenario.title.startswith("Aggressing MARKET order")


class TestPriceStaysADecimalString:
    """Requirement 3.1: ``price`` is a decimal string, never coerced to
    ``float`` -- this is what keeps tick-vs-decimal comparisons exact."""

    def test_order_price_round_trips_as_str(self, tmp_path: Path) -> None:
        path = _write(tmp_path, VALID_SCENARIO_YAML)
        scenario = load_scenario(path)
        first_step = scenario.steps[0]
        assert isinstance(first_step, Step)
        assert first_step.order is not None
        assert first_step.order.price == "100.00"
        assert isinstance(first_step.order.price, str)

    def test_fill_expectation_price_stays_a_string(self, tmp_path: Path) -> None:
        path = _write(tmp_path, VALID_SCENARIO_YAML)
        scenario = load_scenario(path)
        last_step = scenario.steps[3]
        assert isinstance(last_step, Step)
        assert last_step.expect is not None
        assert last_step.expect.fills is not None
        assert last_step.expect.fills[0].price == "100.00"
        assert isinstance(last_step.expect.fills[0].price, str)


class TestMissingRequiredFieldRaises:
    """Requirement 3.3: a missing required field names the offending field
    and the "missing" violation kind."""

    def test_missing_id_is_rejected(self, tmp_path: Path) -> None:
        raw = yaml.safe_load(VALID_SCENARIO_YAML)
        del raw["id"]
        path = _write(tmp_path, yaml.safe_dump(raw))
        with pytest.raises(ScenarioValidationError) as exc_info:
            load_scenario(path)
        fields = [error.field for error in exc_info.value.errors]
        kinds = [error.kind for error in exc_info.value.errors]
        assert "id" in fields
        assert "missing" in kinds

    def test_missing_actor_on_step_is_rejected(self, tmp_path: Path) -> None:
        raw = yaml.safe_load(VALID_SCENARIO_YAML)
        del raw["steps"][0]["actor"]
        path = _write(tmp_path, yaml.safe_dump(raw))
        with pytest.raises(ScenarioValidationError) as exc_info:
            load_scenario(path)
        # steps[0] is a union of Step | Barrier -- pydantic reports the
        # failure against both union members it tried, so just confirm at
        # least one reported field path is under steps.0 and missing.
        assert any(
            error.field.startswith("steps.0") and error.kind == "missing"
            for error in exc_info.value.errors
        )


class TestWrongTypeRaises:
    """Requirement 3.3: a wrong-typed field names the offending field and a
    type-mismatch violation kind."""

    def test_qty_as_string_is_rejected(self, tmp_path: Path) -> None:
        raw = yaml.safe_load(VALID_SCENARIO_YAML)
        raw["steps"][0]["order"]["qty"] = "one hundred"
        path = _write(tmp_path, yaml.safe_dump(raw))
        with pytest.raises(ScenarioValidationError) as exc_info:
            load_scenario(path)
        assert any(
            "qty" in error.field and "int" in error.kind
            for error in exc_info.value.errors
        )

    def test_symbols_as_non_list_is_rejected(self, tmp_path: Path) -> None:
        raw = yaml.safe_load(VALID_SCENARIO_YAML)
        raw["symbols"] = "TST1"
        path = _write(tmp_path, yaml.safe_dump(raw))
        with pytest.raises(ScenarioValidationError) as exc_info:
            load_scenario(path)
        assert any(error.field == "symbols" for error in exc_info.value.errors)


class TestUnknownFieldRaises:
    """Requirement 3.3: ``extra="forbid"`` rejects an unrecognised field,
    identifying it as the offending field."""

    def test_unknown_top_level_field_is_rejected(self, tmp_path: Path) -> None:
        raw = yaml.safe_load(VALID_SCENARIO_YAML)
        raw["unexpected_field"] = "surprise"
        path = _write(tmp_path, yaml.safe_dump(raw))
        with pytest.raises(ScenarioValidationError) as exc_info:
            load_scenario(path)
        assert any(
            error.field == "unexpected_field" and error.kind == "extra_forbidden"
            for error in exc_info.value.errors
        )

    def test_unknown_field_in_order_payload_is_rejected(self, tmp_path: Path) -> None:
        raw = yaml.safe_load(VALID_SCENARIO_YAML)
        raw["steps"][0]["order"]["oops"] = 1
        path = _write(tmp_path, yaml.safe_dump(raw))
        with pytest.raises(ScenarioValidationError) as exc_info:
            load_scenario(path)
        assert any(
            error.field.endswith("order.oops") and error.kind == "extra_forbidden"
            for error in exc_info.value.errors
        )


class TestLoaderRejectsBeforeReturning:
    """Requirement 3.2: validation happens before any Step could be
    executed -- ``load_scenario`` either returns a fully-valid ``Scenario``
    or raises, never a partially-constructed one."""

    def test_invalid_scenario_raises_rather_than_returning_partial(
        self, tmp_path: Path
    ) -> None:
        raw = yaml.safe_load(VALID_SCENARIO_YAML)
        del raw["id"]
        path = _write(tmp_path, yaml.safe_dump(raw))
        with pytest.raises(ScenarioValidationError):
            result = load_scenario(path)
            del result  # pragma: no cover -- unreachable if raise fires first

    def test_malformed_yaml_raises_scenario_validation_error(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "bad.yaml"
        path.write_text("id: [unterminated\n  bad: yaml:::", encoding="utf-8")
        with pytest.raises(ScenarioValidationError):
            load_scenario(path)

    def test_non_mapping_root_raises_scenario_validation_error(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "list_root.yaml"
        path.write_text("- just\n- a\n- list\n", encoding="utf-8")
        with pytest.raises(ScenarioValidationError):
            load_scenario(path)


class TestDuplicateLabelRaises:
    """Requirement 3.5: two Steps declaring the same Label reject the
    Scenario at load time, naming the duplicated Label."""

    def test_duplicate_label_across_steps_is_rejected(self, tmp_path: Path) -> None:
        raw = yaml.safe_load(VALID_SCENARIO_YAML)
        # s2 already has label M2; rename it to M1 to collide with s1.
        raw["steps"][1]["label"] = "M1"
        path = _write(tmp_path, yaml.safe_dump(raw))
        with pytest.raises(ScenarioValidationError) as exc_info:
            load_scenario(path)
        errors = exc_info.value.errors
        assert any(
            error.kind == "duplicate_label"
            and error.field == "steps.1.label"
            and "M1" in error.message
            for error in errors
        )

    def test_labels_with_none_are_not_false_positive_duplicates(
        self, tmp_path: Path
    ) -> None:
        raw = yaml.safe_load(VALID_SCENARIO_YAML)
        # Both s1 and s2 drop their label, leaving label=None on each --
        # this must not be reported as a duplicate.
        del raw["steps"][0]["label"]
        del raw["steps"][1]["label"]
        path = _write(tmp_path, yaml.safe_dump(raw))
        scenario = load_scenario(path)
        assert scenario.steps[0].label is None
        assert scenario.steps[1].label is None


class TestUndeclaredActorRaises:
    """Requirement 3.10: a Step referencing an Actor not declared in
    ``actors`` rejects the Scenario at load time, naming the undeclared
    Actor and the referencing Step."""

    def test_step_actor_not_declared_is_rejected(self, tmp_path: Path) -> None:
        raw = yaml.safe_load(VALID_SCENARIO_YAML)
        raw["steps"][0]["actor"] = "GHOST"
        path = _write(tmp_path, yaml.safe_dump(raw))
        with pytest.raises(ScenarioValidationError) as exc_info:
            load_scenario(path)
        errors = exc_info.value.errors
        assert any(
            error.kind == "undeclared_actor"
            and error.field == "steps.0.actor"
            and "GHOST" in error.message
            and "s1" in error.message
            for error in errors
        )

    def test_sync_barrier_actor_not_declared_is_rejected(
        self, tmp_path: Path
    ) -> None:
        raw = yaml.safe_load(VALID_SCENARIO_YAML)
        raw["steps"][2] = {"barrier": "sync", "actors": ["GHOST"]}
        path = _write(tmp_path, yaml.safe_dump(raw))
        with pytest.raises(ScenarioValidationError) as exc_info:
            load_scenario(path)
        errors = exc_info.value.errors
        assert any(
            error.kind == "undeclared_actor"
            and error.field == "steps.2.actors.0"
            and "GHOST" in error.message
            for error in errors
        )


class TestValidScenarioStillPassesWithValidators:
    """Regression: a valid Scenario with no duplicate Labels and every
    Actor declared still loads successfully now that task 5.2's
    ``@model_validator`` checks run."""

    def test_valid_scenario_still_loads(self, tmp_path: Path) -> None:
        path = _write(tmp_path, VALID_SCENARIO_YAML)
        scenario = load_scenario(path)
        assert isinstance(scenario, Scenario)
