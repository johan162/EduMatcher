"""Phase 5.2c: the LALF-PS control messages, and lists of scalars.

``LogFilter`` is why ``list`` learned ``item:``. Its ``processes``, ``loggers``
and ``sessions`` are lists of plain strings, and until this phase ``list``
required ``ref:`` naming a declared record type. That is an ordinary feature
gap rather than a wire problem — ``["engine", "gateway"]`` is not a flattened
record, it is a list of names.

Adoption here is **topic constants only**. The builders keep passing ``filter``
through as a raw dict: the server parses it with ``LogFilter.from_payload``,
which deliberately accepts a bare string where a list is expected, and routing
the builder through the generated record would narrow that without anyone
asking. Same call as ``order.new`` in 5.1b.
"""

from __future__ import annotations

from typing import Any

import pytest

from edumatcher.models import message as M
from edumatcher.models.generated import log as G
from edumatcher.models.generated._runtime import MessageValidationError


class TestAListOfScalars:
    def test_the_items_are_strings_not_records(self) -> None:
        filt = G.LogFilter.from_dict({"processes": ["engine", "gateway"]})
        assert filt.processes == ["engine", "gateway"]
        assert all(isinstance(name, str) for name in filt.processes)

    def test_the_items_are_coerced(self) -> None:
        """Same ``str()`` coercion a scalar field gets, applied per element."""
        assert G.LogFilter.from_dict({"loggers": [1, 2]}).loggers == ["1", "2"]

    def test_an_absent_list_reads_as_empty(self) -> None:
        """Absent and empty are the same thing to a list.

        A strict subscript here would raise on a payload that simply had
        nothing to say — which is what the first generated binding did.
        """
        assert G.LogFilter.from_dict({}).processes == []

    def test_an_empty_filter_round_trips(self) -> None:
        assert G.LogFilter.from_dict({}).to_dict() == {
            "processes": [],
            "loggers": [],
            "sessions": [],
            "exceptions_only": False,
        }

    def test_the_default_is_a_factory_not_a_shared_list(self) -> None:
        """``= []`` on a dataclass field does not even import in Python.

        The generator emits ``field(default_factory=list)``; without it the
        module raised ``ValueError: mutable default`` at class creation.
        """
        first, second = G.LogFilter.from_dict({}), G.LogFilter.from_dict({})
        assert first.processes is not second.processes


class TestARecordMayHoldAScalarList:
    """The restriction was narrowed twice, and both times to its reason.

    5.2c allowed a list of *scalars* inside a record: it is flat, so it was
    never what "non-recursive" excluded. 5.2d went further and allowed records
    too, because what the generators cannot survive is a **cycle** rather than
    depth. The cycle check lives in ``test_msgen_log_server.py``.
    """

    def _load(self, tmp_path: Any, field: str, extra: str = "") -> None:
        from pathlib import Path

        from edumatcher.msgen.spec import load_family, load_transports

        root = Path(__file__).resolve().parents[1] / "spec"
        path = tmp_path / "fake.yaml"
        path.write_text(
            f"""
family: fake
version: 1
types:
{extra}  R:
    fields: [{field}]
messages:
  - name: m
    topic: "m.t"
    transport: [engine_pub]
    doc: {{ motivation: "fixture", published_by: [engine], since: "1.0" }}
    fields: [{{ name: x, type: nested, ref: R }}]
    encoding: {{ engine_pub: {{ frames: [topic, json_payload], include: all }} }}
""",
            encoding="utf-8",
        )
        load_family(path, load_transports(root / "transports.yaml"))

    #: A second type, referenced only by the cases that must be rejected.
    _INNER = "  Inner:\n    fields: [{ name: a, type: string }]\n"

    def test_a_scalar_list_inside_a_record_is_allowed(self, tmp_path: Any) -> None:
        """This is the narrowing: a list of strings is flat, not recursive."""
        self._load(tmp_path, "{ name: names, type: list, item: string }")

    def test_a_record_list_inside_a_record_is_allowed_since_5_2d(
        self, tmp_path: Any
    ) -> None:
        """This class asserted "still rejected" until ``log.status`` needed it.

        The narrowing went one step further in 5.2d: depth is fine, cycles are
        not. Both cases below now load.
        """
        self._load(tmp_path, "{ name: kids, type: list, ref: Inner }", self._INNER)

    def test_a_record_inside_a_record_is_allowed_since_5_2d(
        self, tmp_path: Any
    ) -> None:
        self._load(tmp_path, "{ name: kid, type: nested, ref: Inner }", self._INNER)


class TestSpecStrictness:
    def _load(self, tmp_path: Any, field: str) -> None:
        from pathlib import Path

        from edumatcher.msgen.spec import load_family, load_transports

        root = Path(__file__).resolve().parents[1] / "spec"
        path = tmp_path / "fake.yaml"
        path.write_text(
            f"""
family: fake
version: 1
types:
  R:
    fields: [{{ name: a, type: string }}]
messages:
  - name: m
    topic: "m.t"
    transport: [engine_pub]
    doc: {{ motivation: "fixture", published_by: [engine], since: "1.0" }}
    fields: [{field}, {{ name: keep, type: nested, ref: R }}]
    encoding: {{ engine_pub: {{ frames: [topic, json_payload], include: all }} }}
""",
            encoding="utf-8",
        )
        load_family(path, load_transports(root / "transports.yaml"))

    def test_ref_and_item_are_exclusive(self, tmp_path: Any) -> None:
        from edumatcher.msgen.spec import SpecError

        with pytest.raises(SpecError, match="not both"):
            self._load(tmp_path, "{ name: xs, type: list, ref: R, item: string }")

    def test_a_list_needs_one_of_them(self, tmp_path: Any) -> None:
        from edumatcher.msgen.spec import SpecError

        with pytest.raises(SpecError, match="for a list of scalars"):
            self._load(tmp_path, "{ name: xs, type: list }")

    def test_a_non_empty_list_default_is_rejected(self, tmp_path: Any) -> None:
        """A default nobody chose would appear on the wire as if they had."""
        from edumatcher.msgen.spec import SpecError

        with pytest.raises(SpecError, match=r"only default a list may declare"):
            self._load(
                tmp_path,
                "{ name: xs, type: list, item: string, required: false, "
                'default: ["a"] }',
            )

    def test_item_is_only_for_lists(self, tmp_path: Any) -> None:
        from edumatcher.msgen.spec import SpecError

        with pytest.raises(SpecError, match="only meaningful for type: list"):
            self._load(tmp_path, "{ name: xs, type: string, item: string }")


class TestTheControlMessages:
    @pytest.mark.parametrize(
        "frames, topic",
        [
            (M.make_log_renew_msg("S1"), "log.renew"),
            (M.make_log_unsubscribe_msg("S1"), "log.unsubscribe"),
            (M.make_log_status_request_msg("S1"), "log.status_request"),
            (M.make_log_subscribe_msg("S1"), "log.subscribe"),
            (M.make_log_backfill_request_msg("S1", 5), "log.backfill_request"),
        ],
    )
    def test_each_publishes_its_declared_topic(
        self, frames: list[bytes], topic: str
    ) -> None:
        assert M.decode(frames)[0] == topic

    def test_a_keepalive_is_byte_identical(self) -> None:
        frames = M.make_log_renew_msg("S1")
        _topic, payload = M.decode(frames)
        assert set(payload) == {"sub_id", "timestamp"}
        assert G.LogRenew.from_dict(payload).sub_id == "S1"

    def test_subscribe_omits_what_the_caller_did_not_set(self) -> None:
        """The server applies its own defaults and cannot tell an omitted
        ``lease_sec`` from one that happens to equal the default."""
        _topic, payload = M.decode(M.make_log_subscribe_msg("S1"))
        assert payload == {"sub_id": "S1", "mode": "STREAM"}

    def test_the_filter_is_canonicalised(self) -> None:
        """6.3 completed the adoption (design section 31.5): the client builder
        now validates and fills the filter to the canonical ``LogFilter`` shape
        the server reads, rather than passing the caller's partial dict raw.
        """
        _topic, payload = M.decode(
            M.make_log_subscribe_msg("S1", log_filter={"min_level": "INFO"})
        )
        assert payload["filter"] == {
            "processes": [],
            "loggers": [],
            "sessions": [],
            "exceptions_only": False,
            "min_level": "INFO",
        }

    def test_backfill_minutes_must_be_positive(self) -> None:
        with pytest.raises(MessageValidationError, match="minutes"):
            G.LogBackfillRequest.from_dict({"sub_id": "S1", "minutes": 0}).validate()


class TestNoHotPathBuilderOnlyWhereARecordLives:
    """A scalar list does not block ``make_*_unchecked``; a record does."""

    def test_a_flat_control_message_keeps_its_builder(self) -> None:
        assert hasattr(G, "make_log_renew_unchecked")

    def test_the_one_carrying_a_record_does_not(self) -> None:
        assert not hasattr(G, "make_log_subscribe_unchecked")


class TestListRulesApplyToEveryKindOfList:
    """A regression caught by 5.2c's review, not by the build.

    The "a list may not be nullable" rule from 5.1e lived inside the *record*
    branch of the loader. When ``list`` learned ``item:``, a scalar list took a
    different branch and slipped past it — the rule was still tested, but only
    for record lists, so nothing noticed.
    """

    def _load(self, tmp_path: Any, field: str) -> None:
        from pathlib import Path

        from edumatcher.msgen.spec import load_family, load_transports

        root = Path(__file__).resolve().parents[1] / "spec"
        path = tmp_path / "fake.yaml"
        path.write_text(
            f"""
family: fake
version: 1
messages:
  - name: m
    topic: "m.t"
    transport: [engine_pub]
    doc: {{ motivation: "fixture", published_by: [engine], since: "1.0" }}
    fields: [{field}]
    encoding: {{ engine_pub: {{ frames: [topic, json_payload], include: all }} }}
""",
            encoding="utf-8",
        )
        load_family(path, load_transports(root / "transports.yaml"))

    def test_a_scalar_list_may_not_be_nullable_either(self, tmp_path: Any) -> None:
        from edumatcher.msgen.spec import SpecError

        with pytest.raises(SpecError, match="may not be nullable"):
            self._load(
                tmp_path,
                "{ name: xs, type: list, item: string, required: false, "
                "nullable: true }",
            )

    @pytest.mark.parametrize("rule", ["max_len: 4", "gt: 0", "pattern: '^a'"])
    def test_a_scalar_rule_on_a_list_is_rejected(
        self, tmp_path: Any, rule: str
    ) -> None:
        """It would silently do nothing, which is the worst of the options."""
        from edumatcher.msgen.spec import SpecError

        with pytest.raises(SpecError, match="is a scalar rule"):
            self._load(
                tmp_path,
                f"{{ name: xs, type: list, item: string, validate: {{ {rule} }} }}",
            )

    def test_the_list_rules_still_load(self, tmp_path: Any) -> None:
        self._load(
            tmp_path,
            "{ name: xs, type: list, item: string, "
            "validate: { min_items: 1, max_items: 3 } }",
        )
