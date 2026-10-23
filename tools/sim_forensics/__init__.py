"""sim_forensics — check a finished simulation run's records against each other.

A long ``edumatcher-sim`` run is a randomized test without assertions: the
engine's output is recorded independently by pm-stats, pm-clearing, pm-audit,
pm-monitor and the gateways. Each check here is an oracle over those records
(a balance that must hold, two stores that must agree, a rule the matching
must obey) and reports PASS, FAIL with sample rows, SKIPPED when its data is
absent, or ERROR when the check itself broke.

Checks are written to be independent of the component they check: they
recompute from the rawest record available (engine trade ids, not a
recorder's receive order) and never call the recorder's own code.

Background and check catalogue: docs-design/EduMatcher-Sim-Forensics-Workplan.md.

Usage
-----
    make forensics DATA=~/.edumatcher-sim/data OUT=~/.edumatcher-sim/forensics/run1
    PYTHONPATH=tools poetry run python -m sim_forensics --data DIR --out DIR [--check F1 ...]
    PYTHONPATH=tools poetry run python -m sim_forensics --list
"""
