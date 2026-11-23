# Remaining Component Reviews — Workplan

Status 2026-11-22. The November 2026 review series
(`docs-design/reviews/EduMatcher-*-Review-2026-11.md`) covered the whole
runtime: engine, messaging, audit (pm-audit, pm-audit-cli), stats, EOD,
clearing, index, scheduler, monitor + health diagnosis, log server, MM bot,
config tools (pm-cverifier, pm-config-gen), all gateways (ALF, BALF, RALF, DC,
MD, API) and the ALF console.

This plan lists what is left. Each item is one component review in the style
of those documents (findings separated from test-first work packages), done
with the `component-review` skill, one at a time.

## 1. Pre-1.0 — shared or state-changing code

| # | Component | Code | Size | Why |
|---|---|---|---|---|
| CR01 | pm-audit-replay | `src/edumatcher/audit/replay/` | ~11.5k | Explicitly out of scope of the audit review (§ "not reviewed here" apart from `rawlines`). 70 % of the audit package; sim-forensics and rerun depend on it. |
| CR02 | Shared models | `src/edumatcher/models/` (not `generated/`) | ~4.2k | Price/ticks, order, combo, envelope, clock, session, reject — used by every process, so far only reviewed through their callers. Rounding, validation, defaults, round-trips. |
| CR03 | Operator commands | `commands/` (pm-admin, pm-admin-cli), `emo/` (pm-opctl-cli) | ~2.8k + 1.5k | Mutate live state (halts, cancels, phase changes); only exercised through doc reviews. |
| CR04 | Intraday new symbol | `new_symbol/` (pm-new-symbol, pm-ipo) | ~0.6k | Small, but changes the instrument set intraday across engine, MD, index and clearing. |
| CR05 | Config loading/deploy | `config.py`, `config_include.py`, `config_artifact.py`, `config_coerce.py`, `config_deploy.py` | ~1.5k | Config-tools review covered these only from the verifier/generator side; the loader is shared by every process. |

## 2. Web apps

| # | App | Size | Previous review |
|---|---|---|---|
| CR06 | dash-gui | ~15k | none |
| CR07 | config-gui | ~19.7k | none (feature workplans only) |
| CR08 | book-gui | ~7.6k | none |
| CR09 | log-gui | ~7.6k | none |
| CR10 | clearing-gui | ~5.7k | none (CG workplan only) |
| CR11 | trader-gui | ~28k | 2026-09, many changes since |
| CR12 | terminal-gui | ~21.6k | 2026-09, many changes since |

dash-gui (operator health view) and config-gui (writes files that
pm-config-deploy consumes) first.

## 3. Lower priority — tooling off the trading path

| # | Component | Size | Note |
|---|---|---|---|
| CR13 | `ai_trader`, `market_sim` (+ pm-news) | ~4.9k + 2.7k | Heavily exercised by sim-forensics; mostly tidy-up. |
| CR14 | `sim_forensics` | ~7.8k | Same. |
| CR15 | `valuation` | ~7.6k | Standalone teaching tool. |
| CR16 | `msgen`, `config_show`, `pm_help` | ~4.8k + 3.3k + 3.3k | Mostly help-text/doc vs code accuracy. |
| CR17 | Client tools: viewer, board, orders, ticker, `calf_client`, `alf_client`, `compdb`, CALF/RALF/DC spies | each < 1.4k | One combined review. |
| CR18 | `log_cli`, `log_ledger` | ~1.6k + 0.6k | Only touched by the log-server review; ledger has its own plan. |

## 4. Order and status

Recommended order: CR01 → CR02 → CR03 → CR06 → CR07, then the rest as time
allows.

| # | Status |
|---|---|
| CR01 | review written 2026-11-22: `reviews/EduMatcher-Audit-Replay-Review-2026-11.md`; WP-RPL01–10 open, Q1–Q4 pending |
| CR02 | review written 2026-11-22: `reviews/EduMatcher-Models-Review-2026-11.md`; WP-MOD01–04 and a holistic review done 2026-11-23, uncommitted; Q1–Q4 taken as recommended (to confirm) |
| CR03 | pm-admin/pm-admin-cli part: review 2026-11-23, `reviews/EduMatcher-Admin-Commands-Review-2026-11.md`; WP-ADM01–06 and holistic review done 2026-11-23, uncommitted; Q1 done as (b), Q2/Q3 as recommended (confirm); `emo/` (pm-opctl-cli) still open |
| CR04–CR18 | open |
