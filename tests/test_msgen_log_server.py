"""Phase 5.2d: pm-log-srv's ten outbound topics.

Two of the IDL's declared exclusions stood in the way, and they resolved in
opposite directions — which is the point of asking about each one separately.

* ``log.notify`` carried a **map**, ``{"INFO": 3, "ERROR": 1}``. Design section
  15.4 already said a spec that appears to need a map is describing a message
  that should have been a list of records, and that was true here: the key was
  a value. It is now ``[{"level": "INFO", "count": 3}, ...]``.
* ``log.status`` needs a record **two levels deep** — a subscription, carrying
  its own filter. That one was the rule being broader than its reason. What the
  generators cannot survive is a *cycle*, not depth, so the loader now rejects
  cycles and emits types in dependency order.
"""

from __future__ import annotations

from typing import Any

import pytest

from edumatcher.models.generated import log as G
from edumatcher.models.generated._runtime import MessageValidationError


def _filter() -> dict[str, Any]:
    return {
        "processes": ["engine"],
        "loggers": [],
        "sessions": [],
        "exceptions_only": False,
    }


def _status() -> dict[str, Any]:
    return {
        "sub_id": "S1",
        "mode": "STREAM",
        "filter": _filter(),
        "lease_sec": 30.0,
        "lease_remaining_sec": 12.5,
        "age_sec": 90.0,
        "pending_rows": 0,
        "pending_count": 0,
        "sent_rows": 42,
        "sent_messages": 7,
        "dropped_rows": 0,
        "renewals": 3,
    }


class TestARecordTwoLevelsDeep:
    """``log.status`` is why the depth restriction became a cycle check."""

    def test_a_subscription_carries_its_own_filter(self) -> None:
        status = G.SubscriptionStatus.from_dict(_status())
        assert isinstance(status.filter, G.LogFilter)
        assert status.filter.processes == ["engine"]

    def test_the_message_holds_the_subscription(self) -> None:
        payload = {
            "sub_id": "S1",
            "server": "log-1",
            "proto": "1.0",
            "subscribers": 1,
            "active_backfills": 0,
            "last_seq": 99,
            "inbox_dropped": 0,
            "subscription": _status(),
            "timestamp": 1700000000.0,
        }
        parsed = G.LogStatus.from_dict(payload)
        assert parsed.subscription is not None
        assert parsed.subscription.filter.processes == ["engine"]
        assert parsed.to_dict() == payload

    def test_no_subscription_is_null_not_absent(self) -> None:
        """Asking for status without one is legal; null says "you have none".

        An absent key would say "the server declined to tell you", which is a
        different thing.
        """
        payload = {
            "sub_id": "S1",
            "server": "log-1",
            "proto": "1.0",
            "subscribers": 0,
            "active_backfills": 0,
            "last_seq": 0,
            "inbox_dropped": 0,
            "subscription": None,
            "timestamp": 1700000000.0,
        }
        emitted = G.LogStatus.from_dict(payload).to_dict()
        assert "subscription" in emitted
        assert emitted["subscription"] is None

    def test_the_inner_record_is_defined_first(self) -> None:
        """Types are emitted in dependency order, not declaration order.

        The generated dataclasses reference each other by name at class
        definition time, so a type must be written after everything it embeds.
        """
        from pathlib import Path

        source = (
            Path(__file__).resolve().parents[1]
            / "src/edumatcher/models/generated/log.py"
        ).read_text(encoding="utf-8")
        assert source.index("class LogFilter:") < source.index(
            "class SubscriptionStatus:"
        )

    def test_validation_reaches_the_inner_record(self) -> None:
        bad = {**_status(), "filter": {"min_level": "X" * 40}}
        with pytest.raises(MessageValidationError, match="min_level"):
            G.SubscriptionStatus.from_dict(bad).validate()


class TestCyclesAreRejectedNotDepth:
    def _load(self, tmp_path: Any, types: str) -> None:
        from pathlib import Path

        from edumatcher.msgen.spec import load_family, load_transports

        root = Path(__file__).resolve().parents[1] / "spec"
        path = tmp_path / "fake.yaml"
        path.write_text(
            f"""
family: fake
version: 1
types:
{types}
messages:
  - name: m
    topic: "m.t"
    transport: [engine_pub]
    doc: {{ motivation: "fixture", since: "1.0" }}
    fields: [{{ name: x, type: nested, ref: Outer }}]
    encoding: {{ engine_pub: {{ frames: [topic, json_payload], include: all }} }}
""",
            encoding="utf-8",
        )
        load_family(path, load_transports(root / "transports.yaml"))

    _INNER = "  Inner:\n    fields: [{ name: a, type: string }]\n"

    def test_depth_is_allowed(self, tmp_path: Any) -> None:
        self._load(
            tmp_path,
            self._INNER
            + "  Outer:\n    fields: [{ name: i, type: nested, ref: Inner }]\n",
        )

    def test_declaration_order_does_not_matter(self, tmp_path: Any) -> None:
        """The loader sorts topologically, so a spec may read top-down."""
        self._load(
            tmp_path,
            "  Outer:\n    fields: [{ name: i, type: nested, ref: Inner }]\n"
            + self._INNER,
        )

    def test_a_self_reference_is_rejected(self, tmp_path: Any) -> None:
        from edumatcher.msgen.spec import SpecError

        with pytest.raises(SpecError, match=r"cycle \(Outer -> Outer\)"):
            self._load(
                tmp_path,
                "  Outer:\n    fields: [{ name: me, type: nested, ref: Outer }]\n",
            )

    def test_a_mutual_cycle_names_the_path(self, tmp_path: Any) -> None:
        """The error should say which types form the loop, not just that one does."""
        from edumatcher.msgen.spec import SpecError

        with pytest.raises(SpecError, match=r"Outer -> Inner -> Outer"):
            self._load(
                tmp_path,
                "  Outer:\n    fields: [{ name: i, type: nested, ref: Inner }]\n"
                "  Inner:\n    fields: [{ name: o, type: nested, ref: Outer }]\n",
            )

    def test_a_cycle_through_a_list_is_caught_too(self, tmp_path: Any) -> None:
        from edumatcher.msgen.spec import SpecError

        with pytest.raises(SpecError, match="cycle"):
            self._load(
                tmp_path,
                "  Outer:\n    fields: [{ name: xs, type: list, ref: Inner }]\n"
                "  Inner:\n    fields: [{ name: o, type: nested, ref: Outer }]\n",
            )

    def test_a_type_used_only_by_another_type_counts_as_used(
        self, tmp_path: Any
    ) -> None:
        """``LogFilter`` is embedded by a record, not by any message directly."""
        self._load(
            tmp_path,
            self._INNER
            + "  Outer:\n    fields: [{ name: i, type: nested, ref: Inner }]\n",
        )


class TestTheMapBecameAListOfRecords:
    def test_levels_is_a_list(self) -> None:
        payload = {
            "sub_id": "S1",
            "count": 4,
            "levels": [{"level": "INFO", "count": 3}, {"level": "ERROR", "count": 1}],
            "last_seq": 99,
            "server_last_seq": 99,
            "timestamp": 1700000000.0,
        }
        parsed = G.LogNotify.from_dict(payload)
        assert [each.level for each in parsed.levels] == ["INFO", "ERROR"]
        assert parsed.to_dict() == payload

    def test_the_server_emits_that_shape(self) -> None:
        """Driven through the real publisher rather than asserted on the spec."""
        from pathlib import Path

        source = (
            Path(__file__).resolve().parents[1] / "src/edumatcher/log_srv/pubsub.py"
        ).read_text(encoding="utf-8")
        assert "dict(sub.pending_levels)" not in source
        assert '{"level": level, "count": count}' in source

    def test_a_negative_count_is_rejected(self) -> None:
        with pytest.raises(MessageValidationError, match="count"):
            G.LevelCount.from_dict({"level": "INFO", "count": -1}).validate()


class TestTheRowShapeIsSharedByBothPaths:
    """One ``LogRow`` for live and backfill, so the seam has no shape change."""

    def _row(self) -> dict[str, Any]:
        return {
            "seq": 7,
            "client_ts": 1700000000.0,
            "server_ts": 1700000000.5,
            "process": "engine",
            "instance": "i1",
            "pid": 42,
            "host": "h1",
            "session": "s1",
            "level": "INFO",
            "logger": "edumatcher.engine",
            "module": "main",
            "line": 100,
            "has_exception": False,
            "truncated": False,
            "message": "started",
        }

    def test_a_live_batch_round_trips(self) -> None:
        payload = {
            "sub_id": "S1",
            "rows": [self._row()],
            "row_count": 1,
            "seq_from": 7,
            "seq_to": 7,
            "server_last_seq": 7,
            "dropped": 0,
            "timestamp": 1700000000.0,
        }
        assert G.LogEvent.from_dict(payload).to_dict() == payload

    def test_a_backfill_chunk_uses_the_same_record(self) -> None:
        payload = {
            "sub_id": "S1",
            "request_id": "R1",
            "chunk": 0,
            "rows": [self._row()],
            "row_count": 1,
            "done": True,
            "total_sent": 1,
            "truncated": False,
            "last_seq": 7,
            "timestamp": 1700000000.0,
        }
        parsed = G.LogBackfill.from_dict(payload)
        assert isinstance(parsed.rows[0], G.LogRow)
        assert parsed.to_dict() == payload

    def test_a_live_batch_is_never_empty(self) -> None:
        """The server skips a flush with nothing to send, so the spec says so."""
        payload = {
            "sub_id": "S1",
            "rows": [],
            "row_count": 0,
            "seq_from": 0,
            "seq_to": 0,
            "server_last_seq": 0,
            "dropped": 0,
            "timestamp": 1700000000.0,
        }
        with pytest.raises(MessageValidationError, match="rows"):
            G.LogEvent.from_dict(payload).validate()


class TestTheTopicsAreAllDeclared:
    def test_every_server_topic_has_a_builder(self) -> None:
        for name in (
            "topic_log_subscribe_ack",
            "topic_log_renew_ack",
            "topic_log_unsubscribe_ack",
            "topic_log_status",
            "topic_log_backfill",
            "topic_log_event",
            "topic_log_notify",
            "topic_log_lease_expired",
            "topic_log_error",
        ):
            assert hasattr(G, name), name

    def test_the_server_uses_them(self) -> None:
        from pathlib import Path

        source = (
            Path(__file__).resolve().parents[1] / "src/edumatcher/log_srv/pubsub.py"
        ).read_text(encoding="utf-8")
        assert 'f"log.' not in source
        assert "topic_log_subscribe_ack(sub_id)" in source

    def test_the_family_declares_every_lalf_ps_topic(self) -> None:
        """Five inbound control messages plus ten outbound."""
        assert len(G.FAMILY_TOPICS) == 15


class TestTheGraphWalkItself:
    """A cycle check is only as good as the graph it walks.

    Probed during 5.2d's holistic review rather than derived from a failure —
    these are the shapes a future spec could take that no family uses yet.
    """

    def _load(self, tmp_path: Any, types: str) -> Any:
        from pathlib import Path

        from edumatcher.msgen.spec import load_family, load_transports

        root = Path(__file__).resolve().parents[1] / "spec"
        path = tmp_path / "fake.yaml"
        path.write_text(
            f"""
family: fake
version: 1
types:
{types}
messages:
  - name: m
    topic: "m.t"
    transport: [engine_pub]
    doc: {{ motivation: "fixture", since: "1.0" }}
    fields: [{{ name: x, type: nested, ref: Outer }}]
    encoding: {{ engine_pub: {{ frames: [topic, json_payload], include: all }} }}
""",
            encoding="utf-8",
        )
        return load_family(path, load_transports(root / "transports.yaml"))

    def test_a_diamond_emits_the_shared_type_once_and_first(
        self, tmp_path: Any
    ) -> None:
        """Two types embedding a third must not emit it twice."""
        family = self._load(
            tmp_path,
            "  C:\n    fields: [{ name: v, type: string }]\n"
            "  A:\n    fields: [{ name: c, type: nested, ref: C }]\n"
            "  B:\n    fields: [{ name: c, type: nested, ref: C }]\n"
            "  Outer:\n    fields: [{ name: a, type: nested, ref: A },"
            " { name: b, type: nested, ref: B }]\n",
        )
        names = [each.name for each in family.types]
        assert names.count("C") == 1
        assert names.index("C") < names.index("A")
        assert names.index("A") < names.index("Outer")

    def test_a_three_deep_chain_declared_in_reverse_sorts(self, tmp_path: Any) -> None:
        family = self._load(
            tmp_path,
            "  Outer:\n    fields: [{ name: m, type: nested, ref: Mid }]\n"
            "  Mid:\n    fields: [{ name: i, type: nested, ref: Inner }]\n"
            "  Inner:\n    fields: [{ name: v, type: string }]\n",
        )
        assert [each.name for each in family.types] == ["Inner", "Mid", "Outer"]

    def test_a_three_type_cycle_is_caught(self, tmp_path: Any) -> None:
        """Not just self-reference and mutual pairs."""
        from edumatcher.msgen.spec import SpecError

        with pytest.raises(SpecError, match=r"Outer -> Mid -> Inner -> Outer"):
            self._load(
                tmp_path,
                "  Outer:\n    fields: [{ name: m, type: nested, ref: Mid }]\n"
                "  Mid:\n    fields: [{ name: i, type: nested, ref: Inner }]\n"
                "  Inner:\n    fields: [{ name: o, type: nested, ref: Outer }]\n",
            )
