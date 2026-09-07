"""Evidence Collectors: one component per dissemination/evidence sink.

Each Collector captures evidence from one sink (execution reports, audit
journal, stats database, clearing ledger, CALF/RALF/drop-copy spy output,
engine book snapshot, operational log, index, or process exit codes) so the
Canonicaliser and Assertion layers can reason over a uniform capture of
system behaviour.

See design.md Components §9 (Collectors).
"""
