"""pm-audit-replay — reconstruct and narrate what the exchange did.

``pm-audit-cli`` answers *"which events match this filter?"*; this package
answers *"what happened, in order, and why?"*. It reads the same immutable
JSONL audit trail through the same parser, recovers the causal structure the
trail records, and renders it.

The layering is deliberate and is what keeps the prose generator from becoming
a pile of ``if topic == ...`` branches (design section 4):

* **Event** — one audit line. ``audit.query.AuditEntry``.
* **Fact** — an Event with its units, clocks and topic resolved. Adds no
  information; removes ambiguity. ``facts``.
* **Episode** — a set of causally connected Facts with one business meaning.
* **Narrative** — prose or NDJSON, a pure function of the episode graph.

See docs-design/EduMatcher-Audit-Replay.md.
"""
