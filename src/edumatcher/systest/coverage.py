"""The Coverage Ledger: cell registry, disposition tracking, reporting.

Tracks every cell derived from Methods A-E (design.md §11.1-§11.5) and its
disposition (``covered``, ``delegated``, ``blocked``, or ``uncovered``), and
produces the ``--coverage`` report consumed by ``pm-systest report``.

See design.md Components §15 (Coverage Ledger) and Data Models §4 (Cell ID
Scheme).
"""
