# pm-new-symbol / pm-ipo Review — 2026-11 (pre-1.0.0)

**Scope:** `src/edumatcher/new_symbol/` at `9dc1cace` (v0.84.0): `main.py`
(135 lines, parser and output), `install.py` (122, the check–edit–validate–
write–deploy sequence), `listing.py` (151, the symbol entry and its seed
quote), `config.py` (59, which file is edited and whether it is deployed),
`guards.py` (78, running engine and saved state), `yaml_edit.py` (66, the text
edit) and `__init__.py` (29). `pm-ipo` is the same entry point
(`pyproject.toml:101-102`), and `pm-valuation --list` calls its `main` with an
argv (`valuation/main.py:157-162`). Read where they decide this tool's
behaviour, not reviewed as code of their own: `config_include.py`
(`load_config_mapping`, `_relative_file`), `config_deploy.compile_config`/
`deploy`, the verifier's obligation and seed checks
(`cverifier/layer3_semantic.py:125-335`), the engine's persistence formats
(`engine/persistence.py:90-104, 233-284, 425-445`), its seed-quote injection
(`engine/main.py:1313-1345`) and obligation precedence (`:2695-2715`,
`:4430-4450`).

**Focus:** correctness, edge-case handling, performance, and whether the
comments, `--help`, the pm-help registry, the operator guide chapter
(`docs/books/operator-guide/part-4-run-a-market/010-new-symbols.md`), the
reference manual section (`010-processes-environment-and-ports.md:2601-2638`)
and training chapter 28 (`training-guide/280-ipo-valuation.md`) say what the
code does.

**Previous work:** no earlier review. In place from its feature work and not
repeated here: the deployed source is edited, never the `ref_data/` copy
(`08fc41f6`); listing into the included file that holds the symbols
(WP-INC5, `d5c69da0`); undeployed edits detected with the multi-file digest
(WP-INC3, `f3d55a85`); the staged whole-tree verification before any write.

**Method:** every line of the files above was read. Findings marked *(repro)*
were reproduced with the installed `pm-ipo`/`pm-new-symbol` against a scratch
`EDUMATCHER_DATA_DIR`: a copy of `s3-basic-setup` deployed with
`pm-config-deploy`, a listing, a real `pm-engine` started on that data
directory and queried with `pm-admin-cli`, then the guide's correction flow.
*(measured)* means timed on this host with a copy of `s300-sim-setup`
(5 810 lines, 300 symbols). The other findings are by inspection, with line
numbers given.

Status: **Done, uncommitted (2026-11-23).** All four WPs and a holistic
review done in one go; last full suite 15 541 passed, 1 skipped. Q1 and Q2
taken as recommended without an explicit answer (to confirm). Beyond the
plan: `pm-valuation --discard-saved-state` (WP-NSY01) and the holistic
review's HR1–HR2, including a program-based running-engine check.

---

## Delivery rule: test first

Every WP follows true TDD:

1. Add one or more tests that express the externally observable behaviour
   the WP must deliver (the YAML written, the deployed artifact, the saved
   state files, lines printed, the exit code).
2. Run the focused test command and record the expected failure. The test
   must fail because the behaviour is absent, not because of an import,
   fixture or assertion mistake.
3. Implement the smallest production change that makes those tests pass.
4. Add the boundary and regression cases discovered on the way.
5. Run the WP's focused tests, then `tests/test_new_symbol.py`,
   `tests/test_valuation*.py` and `tests/test_shell_completion.py` with
   `-n logical`, then black/flake8/mypy/pyright. Do not start the next WP
   with a known failing test.

Tests are not backfilled after an implementation. A defect found while
working a WP becomes a failing regression test before its fix is written.
One WP at a time; stop after each for review and commit.

`tests/test_new_symbol.py` already deploys example copies into a `tmp_path`
data directory and calls `main` with an argv; the new tests extend it. Saved
state is written with the engine's own writers (`save_book_stats`,
`save_gtc_orders`, `save_gtc_combos`), not hand-made JSON.

## Status

Legend: ☐ not started · ◐ in progress · ☑ done (awaiting/after commit) · ⚠ blocked

| # | WP | Content | Findings | Depends on | Est. | Status | Done on |
|---|---|---|---|---|---|---|---|
| 1 | WP-NSY01 | A symbol name with saved state can be listed again, and the refusal says how | C1, D1, D3 | Q1 | 0.5 d | ☑ | 2026-11-23 |
| 2 | WP-NSY02 | Every price is refused or listed exactly; no traceback | C2 | — | 0.25 d | ☑ | 2026-11-23 |
| 3 | WP-NSY03 | The listing says which other processes still run on the old configuration | C3 | Q2 | 0.25 d | ☑ | 2026-11-23 |
| 4 | WP-NSY04 | Help texts, exit codes and guides say what the code does | D2, D4–D6 | WP-NSY01–03 | 0.25 d | ☑ | 2026-11-23 |

Suggested order: **WP-NSY01 → WP-NSY02 → WP-NSY03 → WP-NSY04**. WP-NSY01
unblocks training chapter 28's Exercise 8 and the guide's own correction
flow; WP-NSY04 goes last so the texts describe the final code.

Estimated sequential effort: about 1.25 days, excluding review time and
findings discovered on the way.

---

## 1. Overall assessment

The command is careful where it matters. It **edits the right file**: the
deployed artifact's source, never the `ref_data/` copy or a bundled example,
and into the included file that holds the symbols. It **writes nothing until
the edited tree passes** the verifier and the compiler on a staged copy, and
the text edit is checked to have changed nothing but the new symbol. The
**guards** stop a listing while the engine runs, while the source has
undeployed edits, and while saved engine state exists for the name. The
**seed quote** follows the engine's own obligation precedence. In the
end-to-end run the engine opened `NEWCO` with exactly the listed seed quote
(1000 @ 19.90 / 1000 @ 20.10), and listing while the engine ran was refused.

The defects are in three places:

- **The saved-state refusal has no working way out (C1).** Its advice,
  `pm-opctl-cli clear`, is a usage error, and the real command (`clear
  --state`) would also delete `clearing.db`, `stats.db`, the index state and
  the market model's values, far beyond the "engine state" the message names.
  Training chapter 28's Exercise 8 lists a symbol whose name the engine
  checkpointed in Exercise 7, so it always ends in this refusal.
- **Huge prices (C2)** end in a `decimal.InvalidOperation` traceback, or pass
  the exact `Decimal` checks and then collapse in the float the YAML stores, so
  the verifier rejects a seed quote the user never wrote.
- **Only the engine is guarded (C3)** although every process reads the
  configuration at start; the guide's "stop all of it" is the only
  protection.

Severity key: **High**: a listing that opens at a wrong price or with wrong
orders without a warning. **Med**: a documented flow that cannot be
completed; a refusal whose advice does not work or does more damage than it
says. **Low**: hardening, clarity, hygiene.

---

## 2. Summary of findings

| ID | Sev | Area | Finding | WP |
|----|-----|------|---------|----|
| C1 | Med | Saved state | Relisting a name the engine checkpointed is refused with advice `pm-opctl-cli clear` (a usage error; `clear --state` also wipes clearing, stats, index and market-model state); training Ex. 8 always reaches it *(repro)* | NSY01 |
| C2 | Low | Input | `--ipo-price 1e30` (or a huge seed price): `decimal.InvalidOperation` traceback; `--ipo-price 1e20`: bid and ask both float to `1e+20` and the verifier refuses the seed (S015) *(repro)* | NSY02 |
| C3 | Low | Guards | Only `pm-engine` is checked; gateways, recorders and bots that run on keep the old symbol list (e.g. pm-alf-gwy refuses the new symbol as `SYMBOL_NOT_CONFIGURED`) | NSY03 |
| D1–D6 | — | Texts | See §5 | NSY01, NSY04 |

---

## 3. Correctness findings

### C1. The saved-state refusal has no working way out *(repro)* — Med

`install.py:59-67` refuses when `guards.saved_state` finds the symbol in
`book_stats.json`, `gtc_orders.json` or `gtc_combos.json` (`guards.py:52-78`;
the formats match `engine/persistence.py:90-104, 233-284, 425-445`). The
refusal itself is right: the engine restores that state in place of the
listing. The way out is not:

```
[ERROR] the data directory holds saved state for NEWCO, which the engine would restore instead of the IPO listing:
  …/data/book_stats.json: last prices
  …/data/gtc_orders.json: 2 resting order(s)
Remove it from those files, or clear all engine state with 'pm-opctl-cli clear', before listing.
```

(The scratch flow: list `NEWCO` at 20.00, start `pm-engine` once, stop it,
remove the `NEWCO` entry from the source by hand and redeploy — the guide's
"correct a mistake" case — then list `NEWCO` at 21.00.)

- `pm-opctl-cli clear` alone is a usage error ("One of `--all` or `--state`
  options must be given").
- `clear --state` deletes `book_stats.json` and the GTC files of *every*
  symbol, and also `stats.db`, `clearing.db` (every position and the P&L
  history), `indexes/` and `market_sim_state.json`. The message calls it
  "all engine state"; the guide's warning (`010-new-symbols.md:228-238`) says
  it "discards the resting orders of every symbol".
- "Remove it from those files" means editing the engine's JSON by hand: one
  object per resting order in `gtc_orders.json`, legs inside combos.

The engine checkpoints every configured book, traded or not
(`persistence.py:250-272`), so *any* engine start after a listing records the
name. Training chapter 28 relies on relisting: Exercise 7 lists `TORN` and
runs the exchange; Exercise 8 deploys a fresh copy and runs
`pm-valuation --list` for `TORN` again (`280-ipo-valuation.md:336-347`), with
no step that removes the saved state. `pm-valuation --list` calls this same
command (`valuation/main.py:157-162`), so Exercise 8 always stops here, and
the advice it prints does not work.

**Fix.** See Q1.

### C2. Huge prices: a traceback, or a float that is no longer the price *(repro)* — Low

`listing.py:129` (`price % tick`) and `:82` (`value % tick`) use the default
`Decimal` context (28 digits); `main.py:104` catches neither
`decimal.InvalidOperation` nor anything outside its list. The payload stores
`float(price)` (`listing.py:136-137, 104-105`).

```
--ipo-price 1e30                         → decimal.InvalidOperation: [DivisionImpossible] (traceback, exit 1)
--ipo-price 123456789012345678901234567890 → same
--mm-bid-price 1e40 --mm-ask-price 2e40  → same
--ipo-price 1e20                         → S015: bid_price (1e+20) >= ask_price (1e+20)
```

With `1e20` the `Decimal` checks pass (`1e20 - 10 × 0.01` is a different,
on-grid number), but both prices round to the same float, and the verifier
refuses a seed quote the user never typed. Nothing wrong is ever written: the
verifier or the traceback stops it. The cost is a confusing message.

**Fix.** A price is listable only if its float form is exactly the
`Decimal` price (`Decimal(repr(float(p))) == p`, checked for the IPO and both
seed prices) and the `Decimal` arithmetic succeeds; otherwise refuse with
"price … cannot be represented exactly; use a smaller price or fewer
decimals". Catch `decimal.InvalidOperation` as that refusal.

### C3. Only the engine is guarded — Low

`guards.engine_running` (`guards.py:20-42`) looks for the engine's PUB port
and a `pm-engine` process. Every other process (`pm-md-gwy`, `pm-alf-gwy`,
`pm-balf-gwy`, `pm-api-gwy`, `pm-index`, `pm-clearing`, `pm-stats`,
`pm-market-sim`, `pm-ai-swarm`, `pm-mm-bot`) reads the configuration, or the
engine's symbol list, only when it starts. If an operator restarts only the
engine after a listing, those keep the old list: pm-alf-gwy, for one, refuses
an order for the new symbol with `SYMBOL_NOT_CONFIGURED` (`alf_gwy/gateway.py:
2457-2464`, a list loaded at connect). The guide's checklist step 2 ("stop the
exchange: all of it", `010-new-symbols.md:246-249`) is the only protection,
and the success line says just "Start the exchange to open trading".

**Fix.** See Q2.

---

## 4. Performance findings

Nothing here runs more than once per listing, and nothing grows with
history. A listing into a copy of `s300-sim-setup` (5 810 lines, edit only)
takes *(measured)* 4.66–4.97 s and 59 MB, where `pm-cverifier` alone takes
0.56 s. Under cProfile, `load_config_mapping` runs 15 times in one listing and
`compile_config` is about two thirds of the time: the shared compile path
parses the same file over and over. A deployed listing compiles twice (the
staged check, then `deploy`). For a one-off operator command this is
acceptable; the repeated parsing belongs to the config-loading review (CR05),
see §9.

---

## 5. Comments and docstrings

| ID | Where | Problem |
|----|-------|---------|
| D1 | `install.py:65-66` | The refusal's advice: `'pm-opctl-cli clear'` is a usage error, and "clear all engine state" understates what `clear --state` deletes (C1). |
| D2 | `main.py:60-74` (`--help`) | Nine options have no help text: `--outstanding-shares`, `--tick-decimals`, `--mm-bid-price`, `--mm-ask-price`, `--mm-bid-qty`, `--mm-ask-qty`, `--mm-tif`, `--mm-seed-once`; the description gives no exit codes (0 listed, 1 refused, 2 usage). |
| D3 | Guide `010-new-symbols.md:228-238` | "clear all engine state with `pm-opctl-cli clear` … discards the resting orders of *every* symbol": the command is incomplete and the damage understated (C1). Training `280-ipo-valuation.md:336-347` (Exercise 8) lacks the step that removes `TORN`'s saved state. |
| D4 | Guide `010-new-symbols.md` "Why it refused" | No row for an unrepresentable price (C2) or for the new saved-state option (WP-NSY01). |
| D5 | Registry `pm_help/registry.py:2557-2600`, reference manual `:2601-2638` | No exit codes; nothing on the saved-state way out. |
| D6 | Guide `010-new-symbols.md:42-45` and reference manual | Quick start ends with `pm-opctl-cli start`, but the success line printed is "Start the exchange to open trading", which a reader can take for "start `pm-engine`" (C3). |

---

## 6. Verified as correct

- **File choice.** Includes and credential files must lie under the main
  file's directory (`config_include._relative_file` refuses `..` and absolute
  paths), so the staged copy (`install.py:73-85`) carries every file the
  verifier and compiler read; `market_sim.yaml` is copied beside it.
- **Saved-state formats.** `book_stats.json` is a mapping by symbol, the GTC
  files are lists of orders and combos with `legs[].symbol`, as the guard
  parses them.
- **Seed quote.** The precedence gateway+symbol policy, then the gateway
  (whose fields default to `mm_obligation_defaults`), matches the engine
  (`engine/main.py:2695-2715`); a global per-symbol policy for an unlisted
  symbol is a verifier error (M019), so skipping it is right. A per-gateway
  `mm_obligations.<SYMBOL>` for a not-yet-listed symbol is accepted, so the
  guide's step 7 works. Obligation spreads are positive integers by
  validation, so the default seed never divides an unset value.
- **`seed_once`.** The engine skips the seed only when a live quote for that
  gateway and symbol was restored (`engine/main.py:1313-1345`), as the guide
  and the options table say.
- **End to end.** Listing into a deployed copy of `s3-basic-setup` printed
  the documented lines, and the engine opened `NEWCO` with the seed quote
  1000 @ 19.90 / 1000 @ 20.10 and the symbol in its list. Listing while the
  engine ran: refused, exit 1, nothing changed.

---

## 7. Decisions

Answers (2026-11-23, user asked for all WPs in one go): Q1 and Q2 taken as
recommended, to confirm.

| # | Question | Recommendation |
|---|---|---|
| Q1 | How can a name with saved state be listed (C1)? (a) a new `--discard-saved-state` that, with the engine stopped, removes only that symbol's entries from `book_stats.json`, `gtc_orders.json` and `gtc_combos.json` (with the engine's own loaders and atomic writers) after the staged validation passes, and says what it removed; the refusal names the option; (b) keep refusing, fix the advice to `pm-opctl-cli stop` + `pm-opctl-cli clear --state --yes` and spell out everything it deletes; training Exercise 8 gets that step | **(a)**: it removes exactly what the refusal found and nothing else; (b) works but costs every position and statistic in the data directory to correct one listing, which is the opposite of what a classroom wants between Exercises 7 and 8. The texts still mention `clear --state` as the clean-slate alternative, with its real scope. |
| Q2 | What about other processes still running (C3)? (a) warn, naming the running pm-* programs of this user (the same selection as `pm-opctl-cli kill`), and keep the success line explicit: "Start every process of the exchange"; (b) refuse like the engine guard | **(a)**: a stray `pm-alf-console` or `pm-admin` is harmless, and refusing on it would block a classroom listing for no reason; the engine is the one process whose restored state can override the listing, and it is already refused. |

---

## 8. Work packages

### WP-NSY01 — A symbol name with saved state can be listed again, and the refusal says how (C1, D1, D3; after Q1)

**Tests first** (`tests/test_new_symbol.py`):

1. Saved state for `NEWCO` written with the engine's writers (a book stats
   entry, one resting order, one combo with a `NEWCO` leg, and entries for
   another symbol): listing without the option is refused, and the message
   names `--discard-saved-state` and not `pm-opctl-cli clear`. (Fails today.)
2. The same with `--discard-saved-state`: the listing succeeds, `NEWCO`'s
   entries are gone from all three files, the other symbol's are untouched,
   and the output says what was removed. (Fails today.)
3. `--discard-saved-state` with a validation error (bad `--field`): nothing
   is removed and nothing is listed. (Fails today: no such option.)
4. `--discard-saved-state` while the engine runs (guard stubbed): refused,
   nothing removed. (Fails today.)
5. No saved state: the option changes nothing and the output does not
   mention removals, unchanged otherwise.

**Change.** `--discard-saved-state` on the parser; `guards` gains
`discard_saved_state(symbol)` using `persistence`'s loaders and
`atomic_write_text`, called in `install.add_symbol` after the staged
verification and the second engine check, before the source is replaced. The
refusal text names the option and, as the clean-slate alternative,
`pm-opctl-cli clear --state --yes` with what it deletes. D3: the guide's
warning and Training 28 Exercise 8 use the option.

**Exit criteria.** Tests 1–5 pass; `tests/test_new_symbol.py` and
`tests/test_valuation*.py` green; the scratch correction flow lists `NEWCO`
at 21.00 and the engine then opens it at 21.00.

**Outcome (2026-11-23).** Q1 taken as recommended. `--discard-saved-state`
on `pm-new-symbol`/`pm-ipo`: `guards.discard_saved_state(symbol)` removes the
symbol's `book_stats.json` entry, its resting orders, and every resting combo
with a leg in it together with that combo's leg orders in other symbols (a
combo is one order; its other legs would otherwise come back pointing at a
combo that is gone). It edits the JSON as read and writes it back with the
engine's `atomic_write_text`, so every other entry stays byte-for-byte what
the engine wrote (re-serialising through the engine's loaders could have
normalised other orders). It runs in `add_symbol` after the staged
verification and the second engine check, before the source is replaced, and
the engine check now also runs for a file that is only edited when the option
is given. The refusal names the option and gives `pm-opctl-cli clear
--state` with what it really deletes. `main` prints what was removed.

Beyond the plan: `pm-valuation --list` builds `pm-new-symbol`'s argv itself,
so the advice was unusable on training chapter 28's path; `pm-valuation` got
a `--discard-saved-state` that it passes on (test in
`tests/test_valuation_report.py`). D1, D3: the refusal text, the guide's
warning box, refusal row and options table, training Exercise 8 (now with the
option and its output, the order count marked as variable) and the
"If `--list` refuses" note. `make completion` regenerated.

Failed first: the refusal-text test (old advice), the five option tests
(`SystemExit: 2`, unknown option), the valuation pass-through (same); the
existing saved-state refusal tests passed before and after. Exit criterion:
the scratch correction flow listed `NEWCO` at 21.00 with the option
("Removed saved state for NEWCO" with the book stats and 2 resting orders),
and a real engine then opened `NEWCO` with last prices 21.00 and only the new
seed (20.90 / 21.10). Full suite: 15 528 passed, 1 skipped.

### WP-NSY02 — Every price is refused or listed exactly; no traceback (C2)

**Tests first** (`tests/test_new_symbol.py`):

1. `--ipo-price 1e30`, `--ipo-price 123456789012345678901234567890` and
   `--mm-bid-price 1e40 --mm-ask-price 2e40`: exit 1 with "cannot be
   represented exactly", no traceback. (Fails today.)
2. `--ipo-price 1e20`: the same refusal, not the verifier's S015. (Fails
   today.)
3. `--ipo-price 20.00`, `--tick-decimals 8 --ipo-price 0.00000001`: listed,
   unchanged.

**Change.** A `_exact(price)` check in `listing.py` for the IPO and both seed
prices; `decimal.InvalidOperation` turned into the same `ValueError`.

**Exit criteria.** Tests 1–3 pass; `tests/test_new_symbol.py` green.

**Outcome (2026-11-23).** `listing._check_price(label, value, tick)` is
used for the IPO price and both seed prices, computed or given: a
`decimal.InvalidOperation` (or `OverflowError`) from the modulo, or a value
whose float form is not the same number, is refused with "… cannot be
represented exactly; use a smaller price or fewer decimals"; the grid
message is unchanged. `1e30` itself floats exactly, so the modulo is what
fails; for `1e20` the IPO price is exact and the default seed bid
(`1e20 - 0.10`) is what the check catches, which is why the seed prices go
through it too. Pyright flagged a possibly unbound name on the error path in
the first version.

Failed first: the four unrepresentable-price cases (three
`decimal.InvalidOperation` tracebacks and one `CompileError` with S015) and
the `main` exit-code case; the two ordinary-price cases (including 8 decimals
at `0.00000001`) passed before and after. Full suite: 15 535 passed,
1 skipped.

### WP-NSY03 — The listing says which other processes still run on the old configuration (C3; after Q2)

**Tests first** (`tests/test_new_symbol.py`):

1. With a running pm-* program reported (selection stubbed): the listing
   succeeds and prints a warning naming it, telling the operator to restart
   it. (Fails today.)
2. None running: no warning, unchanged; the success line says to start every
   process of the exchange. (Fails today for the wording.)

**Change.** Reuse `emo.cli.pm_processes` (minus `pm-engine`, which the guard
already refuses) for the warning; reword the success line.

**Exit criteria.** Tests 1–2 pass; suites green.

**Outcome (2026-11-23).** Q2 taken as recommended. `guards.other_processes()`
lists this user's running pm-* programs other than `pm-engine` (which a
deploying listing refuses outright), through `emo.cli.pm_processes` — the
selection `pm-opctl-cli kill` and `clear` use, so it never names `npm`, an
editor or the calling shell, and never `pm-new-symbol`/`pm-valuation` itself
(this process and its ancestors are excluded). A deployed listing prints
`[WARN] still running on the configuration without X, restart them: …` on
stderr; an edit-only listing does not, since nothing was deployed. The success
line now reads "Start every process of the exchange to open trading." The
shared `data_dir` test fixture stubs `other_processes`, so no test looks at
the host's real process table.

Failed first: all three tests (no `other_processes`, no
`guards.pm_processes`). Full suite: 15 538 passed, 1 skipped.

### WP-NSY04 — Help texts, exit codes and guides say what the code does (D2, D4–D6)

**Tests first.** None for texts; `tests/test_shell_completion.py` and the
pm-help registry tests stay green.

**Change.** Help strings for every option and the exit codes (D2); the guide's
"Why it refused" rows (D4); registry and reference manual exit codes and the
saved-state option (D5); the quick start and success line wording (D6).
`make completion`. Re-walk the guide's quick start, its correction flow and
training chapter 28 Exercises 7–8 against the final code (lessons B1).

**Exit criteria.** Every D item resolved; `make _check` green; `mkdocs build`
without new warnings.

**Outcome (2026-11-23).** D2: every option has help text, and the epilog
gives the exit codes (0 listed, 1 refused with nothing changed, 2 usage). D4:
the guide's "Why it refused" table has the unrepresentable-price row and says
every refusal exits 1 and leaves the saved state alone too. D5: registry and
reference manual list `--discard-saved-state`, the exit codes and the
still-running warning; `pm-valuation`'s registry entry, guide chapter
(`020-valuation.md`) and reference manual table list its pass-through option.
D6: the quick-start output and both training-chapter outputs show the new
success line, and the guide explains the `[WARN]` line. `make completion`
regenerated.

Re-walk (lessons B1): the guide's quick start (`pm-opctl-cli stop`, list,
`pm-opctl-cli start`), its correction flow (now `--discard-saved-state`) and
training chapter 28 Exercises 7–8 (Exercise 8 with the option) against the
final code; the outputs shown are the code's own lines, the order count in
Exercise 8 marked as variable. Full suite: 15 538 passed, 1 skipped;
`mkdocs build`: the one pre-existing warning.

### Holistic review (2026-11-23)

All changes re-read as one diff (`new_symbol/`, `valuation/main.py`, the
texts), looking for interference between the WPs, and training chapter 28's
Exercises 7 and 8 walked end to end on a fresh scratch data directory with a
real `pm-engine` and a stand-in `pm-zzstray` program left running: Exercise 7
listed `TORN` through `pm-valuation --list` and the engine checkpointed it;
Exercise 8 without the option was refused with the new advice, and with
`--discard-saved-state` removed `TORN`'s book stats and its 2 resting orders,
listed it with no seed quote, deployed, and warned about `pm-zzstray`.

- **HR1 (fixed; WP-NSY01).** The saved state is removed after the staged
  verification but before the file is replaced and deployed (the safe
  order: a failed removal leaves everything untouched, and a later failure
  only loses state that the listing was going to discard anyway). An error
  after the removal did not say it had happened: a failed deploy printed only
  "written but not deployed". Errors from the replacement and the deploy now
  end with "X's saved state was already removed: …". Test: a deploy that
  raises `OSError` after a discard (failed first: the message lacked it).
- **HR2 (fixed; the existing guard, found while walking WP-NSY03's flow).**
  `engine_running` matched `(^|/)pm-engine( |$)` anywhere on any command line
  with `pgrep -f`, so a shell, `tmux` or `watch` command that merely names
  `…/bin/pm-engine` blocked every listing with "pm-engine is running": the
  walk's own wrapper shell did. The process part now uses the program-based
  `emo.cli.pm_processes` (the same selection as WP-NSY03's warning and
  `pm-opctl-cli kill`); another user's engine is still caught by the port
  probe. Tests: a real `bash -c "… /venv/bin/pm-engine …"` child is not an
  engine (failed first: three PIDs reported); a real script named
  `pm-engine` is (passed before and after). The guide's "pgrep is
  unavailable" refusal row, a message the guard can no longer produce, was
  removed.
- **Checked, no change.** WP-NSY02's price checks run in `build_listing`,
  before the saved-state check, so a bad price never discards anything. The
  engine check guards a discard even for an edit-only listing (WP-NSY01),
  while the still-running warning (WP-NSY03) is printed only for a deployed
  listing, since nothing else changed for the running processes otherwise.
  `pm_processes` excludes this process and its ancestors, so neither
  `pm-new-symbol` nor `pm-valuation --list` (which calls it in-process) names
  itself. The discarded `TORN` orders in the walk were MM01's seed legs from
  Exercise 7; under the classroom configuration (no seed for TORN) the engine
  would also have dropped them as unconfigured seeds, so removing them changes
  nothing a user relies on.

Full suite after the review: 15 541 passed, 1 skipped.

---

## 9. Out of scope, noted

- **Repeated parsing in the deploy path.** `compile_config` and its callers
  parse the same YAML about 15 times per listing (§4); a 300-symbol listing
  takes ~5 s, a deployed one roughly twice that. For CR05 (config
  loading/deploy) in the remaining-reviews workplan, not a defect.
- **pm-opctl-cli's `clear` docstring** (`emo/cli.py`, the `clear` comment)
  still explains stale state with "a `seed_once: true` quote silently failing
  to re-seed because `book_stats.json` still remembers the symbol"; the
  engine decides `seed_once` from restored quotes (`engine/main.py:1318-1337`).
  A text fix for whoever touches that module next.
