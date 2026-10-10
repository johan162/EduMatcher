# AI Traders v3 — acceptance results

One file per work package with a live acceptance run, as required by
[`EduMatcher-AI-Traders-v3-Plan.md`](../../EduMatcher-AI-Traders-v3-Plan.md) §5.
Runs were made on 2026-10-09 with ad-hoc harness scripts (not in the
repository) that start the processes, script the session with
`session.transition` messages, measure, and stop everything. Two machines:

- **device** — a 4-vCPU Linux VM, Python 3.13; one shell call is limited to
  180 s, so live runs there are short.
- **container** — a 2-vCPU Linux container, Python 3.13; used for the long
  runs (C6 soak, C7 hour, D5/E4/E6). CPU-bound at full swarm load.

| WP | File |
|---|---|
| A3 | [A3.md](A3.md) |
| B8 | [B8.md](B8.md) |
| C2 | [C2.md](C2.md) |
| C3 | [C3.md](C3.md) |
| C4 | [C4.md](C4.md) |
| C5 | [C5.md](C5.md) |
| C6 | [C6.md](C6.md) |
| C7 | [C7.md](C7.md) |
| D4/D6 | [D4.md](D4.md) |
| D5 | [D5.md](D5.md) |
| E3 | [E3.md](E3.md) |
| E4/E6 | [E4.md](E4.md) |
| E5 | [E5.md](E5.md) |
