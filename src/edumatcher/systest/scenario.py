"""Scenario schema, parser, and validator.

Defines the pydantic models for the declarative Scenario DSL (``id``,
``title``, ``tags``, ``symbols``, ``session``, ``actors``, ``steps``, and
``verify``), the loader that parses a Scenario YAML file into those models,
and the load-time validators (duplicate Label detection, undeclared Actor
detection) that reject a malformed Scenario before any Step executes.

See design.md Data Models §1 (Scenario Schema) and Components §3 (Runner).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import Field, model_validator
from pydantic import ValidationError as PydanticValidationError

from edumatcher.api_gateway.schemas import StrictModel

__all__ = [
    "ActorDecl",
    "Barrier",
    "BookExpectation",
    "ExpectBlock",
    "FillExpectation",
    "OrderPayload",
    "Scenario",
    "ScenarioFieldError",
    "ScenarioValidationError",
    "Step",
    "VerifyBlock",
    "load_scenario",
]


class Barrier(StrictModel):
    """A ``barrier: quiesce`` or ``barrier: sync`` Step.

    ``quiesce`` waits for system-wide idle and establishes a total order
    between the Steps immediately before and after it; ``sync`` waits only
    for the named ``actors``' acknowledgements. See Requirement 3.8.
    """

    barrier: Literal["quiesce", "sync"]
    #: Required and non-empty for "sync"; ignored for "quiesce". Emptiness
    #: for "sync" is not enforced by the field type alone. ``Scenario``'s
    #: ``_check_no_undeclared_actors`` model validator does check that any
    #: named Actor here is declared in the Scenario's ``actors`` block.
    actors: list[str] = Field(default_factory=list)


class OrderPayload(StrictModel):
    """The ``order:`` block of a ``new_order``/``amend_order`` Step."""

    symbol: str
    side: Literal["BUY", "SELL"]
    type: Literal[
        "MARKET",
        "LIMIT",
        "STOP",
        "STOP_LIMIT",
        "FOK",
        "ICEBERG",
        "IOC",
        "TRAILING_STOP",
    ]
    qty: int = Field(gt=0)
    #: A decimal string, e.g. ``"100.00"``, preserved verbatim rather than
    #: parsed to ``float`` -- required for priced order types; kept as
    #: ``None`` for MARKET. Canonicalisation (Rule R6) is what normalises
    #: this to an integer tick count later; the Scenario schema itself does
    #: not perform that conversion.
    price: str | None = None
    tif: Literal["DAY", "GTC", "ATO", "ATC"] = "DAY"


class BookExpectation(StrictModel):
    """One symbol's expected book shape within an ``expect.book`` block.

    Each level is ``[price_str, qty, order_count]``, matching design
    document §6.1's YAML example (e.g. ``asks: [["100.00", 100, 1]]``).
    """

    asks: list[tuple[str, int, int]] = Field(default_factory=list)
    bids: list[tuple[str, int, int]] = Field(default_factory=list)


class FillExpectation(StrictModel):
    """One expected fill within an ``expect.fills`` list.

    ``liquidity`` is sourced directly from the fill event's
    ``liquidity_flag`` (G9) rather than inferred by joining to drop copy,
    per design document §6.1's comment on the ``LM-023`` example.
    """

    price: str
    qty: int = Field(gt=0)
    maker: str
    liquidity: Literal["MAKER", "TAKER"]


class ExpectBlock(StrictModel):
    """The ``expect:`` block of a Step.

    ``expect:`` content varies by Step (design document §6.1's examples show
    a bare ``status:``, a ``status:`` plus ``book:``, and a ``status:`` plus
    ``fills:`` plus ``book:``), so every field here is optional. This stays
    ``StrictModel`` (``extra="forbid"``): "permissive" here means every
    field is optional, not that arbitrary unknown keys are accepted -- an
    unrecognised key is still a schema violation (Requirement 3.3).
    """

    status: str | None = None
    book: dict[str, BookExpectation] | None = None
    fills: list[FillExpectation] | None = None


class Step(StrictModel):
    """One non-Barrier Scenario Step.

    ``id`` intentionally shadows the ``id`` builtin, matching design
    document Data Models §1's schema sketch.
    """

    id: str
    actor: str
    action: Literal["new_order", "cancel_order", "amend_order", "connect", "disconnect"]
    label: str | None = None
    order: OrderPayload | None = None
    expect: ExpectBlock | None = None


class VerifyBlock(StrictModel):
    """The Scenario's top-level ``verify:`` block."""

    trades: list[dict[str, Any]] = Field(default_factory=list)
    positions: dict[str, dict[str, int]] = Field(default_factory=dict)
    stats: dict[str, dict[str, Any]] = Field(default_factory=dict)
    dissemination: dict[str, Any] = Field(default_factory=dict)
    invariants: list[str] = Field(default_factory=list)


class ActorDecl(StrictModel):
    """One entry of the Scenario's ``actors:`` mapping."""

    role: Literal["trader", "market_maker", "admin"] = "trader"


@dataclass(frozen=True, slots=True)
class ScenarioFieldError:
    """One offending field extracted from a pydantic ``ValidationError``.

    ``field`` is the dot-joined location pydantic reports (e.g.
    ``"steps.0.order.qty"``); ``kind`` is pydantic's own error ``type``
    string (e.g. ``"missing"``, ``"extra_forbidden"``,
    ``"literal_error"``), which is what distinguishes "missing required
    field" from "wrong type" from "unknown field" per Requirement 3.3
    without pattern-matching on message text. The Scenario-level
    ``@model_validator`` checks (duplicate Label, undeclared Actor) mint
    ``ScenarioFieldError`` instances directly with their own ``kind``
    strings (``"duplicate_label"``, ``"undeclared_actor"``) so their
    reporting stays consistent with pydantic's own field-level errors.
    """

    field: str
    kind: str
    message: str

    def __str__(self) -> str:
        return f"{self.field}: {self.kind} ({self.message})"


class ScenarioValidationError(ValueError):
    """Raised when a Scenario file fails schema validation.

    Carries the full list of offending fields (a malformed Scenario file
    commonly fails more than one field at once), each identifying the
    field path and the violation kind, per Requirement 3.3. Also raised
    (wrapped by pydantic into a ``ValidationError`` and unwrapped again by
    ``_field_errors_from``) by ``Scenario``'s ``@model_validator`` checks
    for duplicate Labels (Requirement 3.5) and undeclared Actors
    (Requirement 3.10).
    """

    def __init__(self, errors: list[ScenarioFieldError]) -> None:
        self.errors = errors
        detail = "; ".join(str(error) for error in errors)
        super().__init__(f"Scenario validation failed: {detail}")


class Scenario(StrictModel):
    """The top-level Scenario document. See design.md Data Models §1."""

    id: str = Field(pattern=r"^[A-Z]{2}-\d{3}$")
    title: str
    tags: list[str] = Field(default_factory=list)
    symbols: list[str]
    session: Literal[
        "PRE_OPEN", "OPENING_AUCTION", "CONTINUOUS", "CLOSING_AUCTION", "CLOSED"
    ]
    actors: dict[str, ActorDecl]
    steps: list[Step | Barrier]
    verify: VerifyBlock | None = None

    @model_validator(mode="after")
    def _check_no_duplicate_labels(self) -> Scenario:
        """Requirement 3.5: reject a Scenario where two Steps share a Label.

        Only ``Step`` instances carry a ``label``; ``Barrier`` Steps are
        skipped. A ``label`` of ``None`` is "no Label declared" and never
        counts as a duplicate of another ``None``.
        """
        errors: list[ScenarioFieldError] = []
        seen_at: dict[str, tuple[int, Step]] = {}
        for index, step in enumerate(self.steps):
            if not isinstance(step, Step) or step.label is None:
                continue
            first = seen_at.get(step.label)
            if first is not None:
                first_index, first_step = first
                errors.append(
                    ScenarioFieldError(
                        field=f"steps.{index}.label",
                        kind="duplicate_label",
                        message=(
                            f"Label {step.label!r} is already declared by "
                            f"steps.{first_index} (id={first_step.id!r}); "
                            "Labels must be unique within a Scenario"
                        ),
                    )
                )
            else:
                seen_at[step.label] = (index, step)
        if errors:
            raise ScenarioValidationError(errors)
        return self

    @model_validator(mode="after")
    def _check_no_undeclared_actors(self) -> Scenario:
        """Requirement 3.10: reject a Scenario referencing an undeclared Actor.

        Covers both a ``Step.actor`` reference and a ``sync`` Barrier's
        ``actors`` list -- the latter follows the same "referencing Step"
        spirit as 3.10 and is an incremental, non-breaking extension of it.
        """
        errors: list[ScenarioFieldError] = []
        for index, step in enumerate(self.steps):
            if isinstance(step, Step):
                if step.actor not in self.actors:
                    errors.append(
                        ScenarioFieldError(
                            field=f"steps.{index}.actor",
                            kind="undeclared_actor",
                            message=(
                                f"Actor {step.actor!r} referenced by steps.{index} "
                                f"(id={step.id!r}) is not declared in this Scenario's "
                                "actors block"
                            ),
                        )
                    )
            elif step.barrier == "sync":
                for actor_index, actor in enumerate(step.actors):
                    if actor not in self.actors:
                        errors.append(
                            ScenarioFieldError(
                                field=f"steps.{index}.actors.{actor_index}",
                                kind="undeclared_actor",
                                message=(
                                    f"Actor {actor!r} referenced by steps.{index} "
                                    "(a sync barrier) is not declared in this "
                                    "Scenario's actors block"
                                ),
                            )
                        )
        if errors:
            raise ScenarioValidationError(errors)
        return self


def _field_errors_from(exc: PydanticValidationError) -> list[ScenarioFieldError]:
    errors: list[ScenarioFieldError] = []
    for error in exc.errors():
        # A Scenario-level @model_validator raises ScenarioValidationError,
        # which pydantic wraps into a "value_error" whose ctx.error is the
        # original exception -- unwrap it so the field path/kind those
        # validators minted survive rather than collapsing into a single
        # generic "value_error" entry at the root location.
        original = error.get("ctx", {}).get("error")
        if isinstance(original, ScenarioValidationError):
            errors.extend(original.errors)
            continue
        loc = ".".join(str(part) for part in error["loc"])
        errors.append(
            ScenarioFieldError(
                field=loc or "<root>", kind=error["type"], message=error["msg"]
            )
        )
    return errors


def load_scenario(path: str | Path) -> Scenario:
    """Parse and validate a Scenario YAML file.

    Validates the file against the Scenario schema before returning --
    never partially, so no Step can be executed against an invalid
    Scenario (Requirement 3.2). Raises :class:`ScenarioValidationError` on
    any schema violation (malformed YAML, a non-mapping document root, or
    a pydantic ``ValidationError``), identifying each offending field and
    the nature of the violation (Requirement 3.3).
    """
    scenario_path = Path(path)
    try:
        raw = yaml.safe_load(scenario_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ScenarioValidationError(
            [ScenarioFieldError(field="<file>", kind="invalid_yaml", message=str(exc))]
        ) from exc

    if not isinstance(raw, dict):
        raise ScenarioValidationError(
            [
                ScenarioFieldError(
                    field="<root>",
                    kind="invalid_type",
                    message=(
                        "expected a YAML mapping at the document root, got "
                        f"{type(raw).__name__}"
                    ),
                )
            ]
        )

    try:
        return Scenario.model_validate(raw)
    except PydanticValidationError as exc:
        raise ScenarioValidationError(_field_errors_from(exc)) from exc
