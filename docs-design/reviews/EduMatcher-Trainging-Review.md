# Training Guide Review — 2026-11-06

**Scope:** `docs/books/training-guide/` — the index and chapters 00–20 (chapters 21–29 are
covered in the section "Chapters 21–29" at the end of this document).

**Question asked:** is everything a complete beginner needs included, is the language clear,
and above all is every instruction *correct*? For the opening chapters the bar was "100 %
verified".

**Method:** every chapter was *run*, not read. Each exercise's commands were extracted from
the markdown and executed against a real exchange, and the output was compared with what
the chapter says. The exchange ran in an isolated sandbox (a private network namespace
created with `unshare -rn`, its own `EDUMATCHER_DATA_DIR`, consoles driven through `tmux`),
so the running simulation container on the developer machine was never touched. The Python
route (Route D, Poetry checkout) was exercised; the container route was checked against the
shipped image (`ghcr.io/johan162/edumatcher-ai-sim:0.76.0`, throwaway container, no network)
and `deployment/`.

**Result in one line:** the guide was mostly accurate on *what a command prints*, and
repeatedly wrong on *what state the learner is in when they type it* — consoles that died
with an engine restart, orders that survived one, a participant ID that was already in use,
reference prices that history had moved. Most fixes are about state.

---

## 1. What was changed (resolved)

### 1.1 Product fixes made during the review

| Fix | Where | Test |
|-----|-------|------|
| `pm-admin` `BOOK` returned stale snapshots: `ExchangeCommandClient.book_depth()` returned the first queued `book.snapshot.<SYM>` *broadcast*, not the reply to its own request. After N book changes it showed the state N snapshots ago. Fixed with `_discard_pending()` before the request. | `src/edumatcher/commands/client.py` | `TestBookDepthIgnoresStaleSnapshots` in `tests/test_commands.py` |
| `CANCEL_SYM` and the admin gateway kill (`KILL\|GW=`) left the surviving leg of a half-filled quote (`INACTIVE_*_FILLED`) in the book, although both report that they clear quotes. The leg is no longer in the `QuoteIndex`, and both handlers skipped quote-origin orders. Both now call the existing `_cancel_orphaned_quote_legs()`. | `src/edumatcher/engine/main.py` | `tests/test_engine_mass_cancel_inactive_quote.py` |

### 1.2 Documentation corrected (all chapters 00–20)

Grouped by kind; the full per-chapter list is in the commit history of the guide.

- **Container route could not follow chapters 01–02.** The container opens in `/`, has no
  editor and discards its own file system on `restart`. Added "Where to keep your working
  files" (`~/.edumatcher/data/training` on the host = `/data/training` in the container).
- **Open consoles die with an engine restart** (`AUTH_REQUIRED` / `Gateway not connected`),
  and the guide restarts the engine dozens of times. Added "After every engine restart" to the
  index and a reminder at each restart.
- **State that leaks between chapters.** Leftover 1-lot orders from chapter 01 survive every
  restart; chapter 02 Exercises 6–8 replace the manual quotes chapter 03 needs; chapter 06
  empties the books; chapter 07 started from the wrong phase; chapter 11's collar predictions
  depended on a persisted reference price. Each now has an explicit starting-state check or a
  reset step.
- **Commands that could not work as written:** chapter 02 Exercises 6 and 7 (bot refused with
  `Gateway already connected`, then `no reference price available`); chapter 05 Exercise 5
  (TSLA book); chapter 10 Exercise 5 (cancelling an OCO that had already completed);
  chapter 11 Exercises 7–8 and chapter 19 (`pm-admin-cli` vs an open `pm-admin`, same ID);
  chapter 14 (`docs/examples/…` paths exist only in a repository checkout).
- **Wrong or imprecise statements:** image count (6 → 7), "fixed" ports, `QLEGS` columns,
  advisory lists, the auction tie-break wording, "`CONTINUOUS` → `CLOSED` takes two steps"
  (the engine accepts it directly), `stats-cli trades` being "the last N" (it is the first N,
  oldest first), the combo/SMP description, chapter 20 Exercise 10 (a sell at the same bid
  does not move the close, so `--redo` showed no difference).

## 2. Open questions

Each entry says what was observed, where, and a suggested direction. None of them was
changed unilaterally.

### Q1. `pm-audit` sometimes records nothing for the first seconds — cause not found

**Observed.** After starting `pm-audit`, trades made 4–15 s later were not in `audit.log` /
on the terminal in several runs, while later trades in the same run were. In one run
(chapter 16, Exercise 6) the log stayed at 0 bytes for ~100 s although a raw SUB socket on
`:5556` received the same events. A controlled run (a trade every 3 s for 36 s after start)
captured 11 of 12 trades, missing only the first.

**Where.** `src/edumatcher/audit/main.py`: `_add_to_buffer` arms the flush timer only when
the buffer goes from empty to one message (`buffer_len == 1`); the flush interval is 10 s;
`_flush_locked` writes both the file and the terminal. Chapters 06 (Exercise 1), 13
(Exercise 3) and 16 (Exercise 6) depend on seeing audit output promptly.

**Not established.** Whether this is a startup (slow-joiner) effect, a timer race on the
first message, or an artefact of how the sandbox started the process. The guide now says
"batches, wait a few seconds" and "start `pm-audit` before you trade".

**Suggested.** Reproduce with a script that starts `pm-audit` and publishes known events at
fixed offsets; if a loss is confirmed, treat it as an audit-completeness defect (the
audit trail is "the one process whose job is to miss nothing").

### Q2. Orphaned quote legs on disconnect and on the global kill switch

**Observed.** The fix in §1.1 covers `CANCEL_SYM` and the *admin* gateway kill. The same
orphan can remain after a participant disconnects with `CANCEL_QUOTES_ONLY` / `CANCEL_ALL`
(`_handle_gateway_disconnect`, `engine/main.py` ≈ L4248) and after the participant's own
`risk.kill_switch` (`_handle_kill_switch`, ≈ L4346); both use the `QuoteIndex`-only path.
`tests/test_engine_quote_entry_fill.py::test_x8a_a_partly_filled_bid_rests_its_remainder…`
documents the leftover remainder as deliberate *until a new quote replaces it*.

**Question.** Is "the remainder survives a disconnect" intended? A market maker whose
process dies keeps one-sided exposure resting, which `disconnect_behaviour: CANCEL_QUOTES_ONLY`
is meant to prevent.

**Suggested.** Apply `_cancel_orphaned_quote_legs()` in those two paths, or state the
exception in the participant and operator guides.

### Q3. Self-match prevention at combo entry — intended?

**Observed.** An AON combo whose first leg would meet the submitter's own resting order is
rejected at entry with `INSUFFICIENT_LIQUIDITY` (`COMBO FAILED … Leg 0 (AAPL) REJECTED`) under
*every* SMP policy except `NONE`, and with `NONE` (or no `SMP=` when the gateway has no
default) both legs fill, the AAPL leg against the submitter's own offer. Because the
fillable-quantity check discounts own liquidity first
(`OrderBook.fillable_quantity`, `engine/order_book.py` ≈ L1436), `CANCEL_AGGRESSOR`,
`CANCEL_RESTING` and `CANCEL_BOTH` cannot differ in this setup.

**Why it matters.** The guide's chapter 10 Exercise 13B (and its checkpoint) said the three
policies give different results. It now describes the actual behaviour.

**Question.** Is discounting own liquidity in the entry check the intended design, and are
the policies expected to differ anywhere for combos (for example for a *resting* combo whose
child later meets an own order)?

### Q4. Consoles never reconnect after an engine restart

**Observed.** An open `pm-alf-console` answers every order with `AUTH_REQUIRED  Gateway not
connected: <ID>`; an open `pm-admin` answers `KILL` with `Gateway not connected: GW_ADMIN`
and `GATEWAYS` lists even itself as `no`. Some read-only commands (`SYMBOLS`, `SCHEDULE`,
`SESSION`, `BOOK`) keep working, which makes the failure look intermittent. The consoles
only print `heartbeat dropped: engine unreachable`.

**Question.** Should the consoles re-authenticate when the engine returns (a heartbeat
already tells them it is gone)? The guide documents the workaround ("restart the console").

### Q5. `pm-admin` and `pm-admin-cli` cannot run together

**Observed.** Both log on as the configured ADMIN participant. While one is open the other
fails with `Auth refused: Gateway already connected: GW_ADMIN`. The guide told readers to
"keep both terminals open" and then used both.

**Suggested.** Add a second ADMIN identity to the example configurations for one-shot CLI
use, or let `pm-admin-cli` use a distinct session id. Otherwise leave the guide's warning.

### Q6. One documented "reset the exchange" recipe

**Observed.** Three different resets are in use:

| Reset | Removes | Used in |
|-------|---------|---------|
| `rm $EDUMATCHER_DATA_DIR/book_stats.json` (engine stopped) | persisted reference prices and last trades | chapter 11 Exercise 11 |
| `pm-opctl-cli clear --state --yes` | also `gtc_orders.json`, `stats.db`, `clearing.db` | chapter 17 note, chapter 20 tip |
| `pm-opctl-cli clear --all` | additionally logs and audit | FAQ in the Quick Start |

`clear --state` prints a warning that 30 `pm-*` processes "appear to be running" when the
exchange is up, and deleting `clearing.db` under a running `pm-clearing` leaves later
`pm-clearing-cli` calls with no database until it is restarted.

**Suggested.** A short "Starting over" section in chapter 00 or 16 listing what each reset
removes and which processes must be stopped first, linked from the chapters that need it.

### Q7. `pm-clearing-cli symbols` reports `traded_qty` twice the traded volume

**Observed.** After 800 shares were traded in AAPL, `pm-clearing-cli symbols` showed
`traded_qty 1600` and `traded_notional 236642`, while `pm-clearing-cli daily` showed 800 per
gateway and `pm-stats-cli daily` showed `volume 800`. The symbol total looks like the sum
over both sides of every trade.

**Question.** Is the symbol-level figure meant to be gross of both counterparties? If not,
this is a defect in the `symbols` aggregation; if so, chapter 12 should say so.

### Q8. `STATUS` on a trader console reports quote legs for a participant that never quoted

**Observed.** `TRADER01` (no `MARKET_MAKER` role, never sent `QUOTE`) showed
`Cached quote legs 6` / `Active quote legs 1`. The console appears to cache quote legs seen
in public broadcasts. Cosmetic, but chapter 08 describes `STATUS` as "your gateway".

### Q9. Installed version string in the Poetry environment

`pm-engine --version` and `pm-eod --version` printed `0.73.0` while the repository is at
0.76.0 (container image `0.76.0`). Probably a stale editable-install metadata; worth a
`poetry install` before the next release check.

### Q10. Examples are not reachable by name on packaged installs

**Observed.** `pm-config-deploy --example s150-nominal` works everywhere, but
`pm-ai-swarm --swarm docs/examples/…/swarm.yaml` and `pm-news play docs/examples/news/…`
need a repository checkout. On a container or `pipx` install the files live under
`site-packages/docs/examples`. The guide now computes the path with
`examples_root()`.

**Suggested.** Accept a bare example name for `--swarm` and `pm-news play` (the way
`--example` works), or have `pm-config-deploy --example` also copy `swarm.yaml` next to
`market_sim.yaml` in `ref_data/`.

### Q11. Noise in normal use

- `WARNING … pm-monitor at tcp://127.0.0.1:5610 not accepting beacons (N dropped so far)` is
  printed by every hand-started process, once a minute, for as long as it runs; and
  `heartbeat dropped: engine unreachable` appears at every engine restart. The guide now
  calls both harmless. Should the health reporter stay quiet (DEBUG) when no monitor is
  configured or running?
- A hand-edited artifact makes `pm-engine` print a full Python traceback; the message the
  guide wants the learner to read is its last line (`ArtifactError … edit the source and run
  pm-config-deploy`). A one-line error would be friendlier.

### Q12. Swarm rate versus its budget

`swarm.yaml` sets `budget: 40` "order actions per second for the whole swarm"; the status
line reported `45.1/s` at `t=60s`. Is the budget a target, a per-second average, or a hard
cap? Chapter 14 now says "a budget of about 40".

### Q13. Persisted `DAY` orders and collars create hidden history

Two design facts made the guide hard to keep correct, independent of the fixes above:

1. `DAY` orders (and quote legs) survive an engine restart on the same business day, so a
   learner's test orders reappear in later chapters.
2. The reference price and last trade are persisted in `book_stats.json`; the *dynamic* collar
   (±% of last trade) rejects any order outside the band, buys below the market included.
   Chapter 11's table of six predictions was only reproducible after deleting that file.

Both are documented behaviour (Operator's Guide, Persistence); the question is whether the
example configurations used for teaching should ship with collars that tolerate a learner's
history (for example a wider `dynamic_band_pct`).

## 3. What was not verified

- The **container route** end to end for chapters 04 onwards (Python route only); the
  Multipass route; the `pipx` install; the real `curl | bash` installer.
- Chapter 14: the retracted-rumour and chip-race scenarios were not played to the end (their
  YAML was checked against the text); chapter 10 Exercises 14B and 15B.
- The full `mkdocs build` of the site.
- `scripts/checkdocs.py` reports two `Y005` errors in
  `operator-guide/part-2-configure/005-the-configuration-file.md` (snippets that reference
  `/tmp/symbols.yaml` and `/tmp/desk-keys.yaml`); they predate this review.

## 4. Chapters 21–29

Same method as before: every command block was extracted and run against a sandbox
exchange (private network namespace; for `pm-valuation --list` also a private PID
namespace, because that command refuses to run while *any* `pm-engine` exists on the
machine). The chapters are numbered 21–29 in the guide and live in files `200`–`280`.

| Ch. | File | Result | Fixes made to the chapter |
|-----|------|--------|---------------------------|
| 21 Drop-copy replay | `200` | Run; gap detector fires as described | `seq` is **one engine-wide counter** (both counterparties of a fill get consecutive numbers) and restarts at 1 with the engine; a subscriber filtered to one gateway sees "gaps" on every event |
| 22 CommandClient & MM bot | `210` | Run | `pm-admin` / MM console open ⇒ `connect()` returns `accepted: False` *without raising* (reads still work, writes fail); Exercise 4's bot could not start (`no reference price available`) without `--initial_min/--initial_max` and its quoted log lines needed them |
| 23 RALF | `220` | Run (all exercises, Python + C + raw sockets) | Examples path on packaged installs; port 5580 clash with the simulation container; how to make a trade without market makers; exact `ERR` lines per Exercise 7 input; `UNSUB` sends no reply; replay arrives before `SUB`; backup file name `ch22` → `ch23` |
| 24 CALF | `230` | Run (Python, C, `nc`, `pm-calf-spy` variants, STATE fan-out, AUCTION/INDIC/CB) | Port 5570 clash; start-order hint (`Connection refused`); 30 s replay window makes Exercise 6's hit/miss time-dependent; empty uncross is also published (`EQQTY=0`); recipe for a non-empty auction; backup name |
| 25 API gateway | `240` | Run (every REST call, WebSocket, examples, Exercise 12 script) | **API keys are random** (`--seed` does not fix them) but the chapter used fixed `key-*-demo` names ⇒ shell variables `KEY_TRADER/KEY_OPS/KEY_RO` read from the config; history endpoints are oldest-first; `209.50` bid for AAPL was marketable ⇒ `140.00`; illegal session transition gives `503 ENGINE_TIMEOUT`, not `409`; `authenticated` frame carries `stream_seq` + `orders.snapshot`; Exercise 12's "omit `--price` ⇒ 400" is stopped by argparse first; backup name |
| 26 Market index | `250` | Run (split, dividend, add, delist, history, exports, second index) | `INDEX` prints one line (latest update) and no constituents ⇒ Exercise 7 verifies through `pm-index-cli events`; `pm-admin` has no `INDEX` command (use `pm-alf-console --id OPS01`); `INDEX\|HISTORY` needs `INDEX=<id>` on a fresh console; `TO=` date is exclusive; Exercise 10 never deployed the new config (second index silently absent); nothing is published before the first trade; backup name |
| 27 ALF gateway | `260` | Run (nc-style sessions, Python client + library, C client, KILL, all error codes) | State from earlier chapters (partly filled quote legs survive `KILL`, see Q2); `0.0.0.0` bind; `AMENDED` price format; `REJECT_CODE` for `AUTH_FAILED` is `UNKNOWN`; examples path; backup name |
| 28 BALF gateway | `270` | Run (all four code blocks, parser self-tests, reject codes, duplicate logon, heartbeat timeout 5 s) | Exercise 4B's "80 shares stay on the book" is false once the script exits (disconnect cancels them); `REJECT_NEW` default and the exact heartbeat timeline; state reset; examples path; backup name |
| 29 IPO valuation | `280` | Run non-interactively: report figures, Monte Carlo (deterministic, reproduces 110.48 / 43.8 %), the Halvard floor table, `--list` (both variants), opening auction at 120.00 with fills 1000 / 600 + 400 / 200 expired | Seed-quote line in Exercise 7 depends on the deployed config; `--list` refuses while any `pm-engine` runs on the machine; examples path |

### Open questions from chapters 21–29

#### Q14. A session transition that is illegal *from the current phase* gets no reply

**Observed.** `POST /api/v1/admin/session/transition {"to_state":"CONTINUOUS"}` while the
market is already `CONTINUOUS` waits three seconds and returns `503 ENGINE_TIMEOUT`.
The reference documents `409 TRANSITION_REJECTED` for "the engine refused" and the
gateway code comment says the engine "now says so instead of leaving the caller to
infer it from a timeout".

**Where.** `engine/main.py::_handle_session_transition`: the *sessions disabled* and
*unknown state* branches call `_reply_session_transition(..., False, reason=...)`; the
`to_state not in allowed` branch only logs a warning and returns. `pm-admin-cli session`
also times out (it waits for the broadcast), which the operator guide describes as
intended for the CLI.

**Suggested.** Reply `accepted=False, reason="Invalid transition X → Y (allowed: …)"` in
that branch. The REST route already turns it into 409; the CLI could then stop waiting.

#### Q15. `INDEX|HISTORY` `TO=` is the start of the day

`FROM=2026-11-06|TO=2026-11-06` returns nothing for records written that day;
`TO=2026-11-07` returns them. The operator and participant guides do not say whether
`TO` is inclusive. Either make a date-only `TO` cover the whole day or document it
(the training chapter now does).

#### Q16. `INDEX` on the console shows one index, and `pm-index` forgets the session phase

- `INDEX` prints the single most recent `index.update`, so with two indices only the
  one that published last appears (`EDU100` hides `TECH2` because `TECH2` is throttled
  to 2 s). The training chapter and the participant guide describe `INDEX` as listing
  "the indices".
- A `pm-index` started (or `--reset`) after the market opened reports
  `session_state=PRE_OPEN` in every update and in the daily roll-up
  (`close_session_state PRE_OPEN`) until the next session change, because it only learns
  the phase from the broadcast.
- `pm-admin` has no `INDEX` command although the guide says "any gateway role".

#### Q17. Expiry message for `ATO` orders

An `ATO` remainder that expires at the end of the opening auction is reported as
`EXPIRED … (DAY order — trading day ended)`. The reason text is wrong for the order type
and for the moment (the day has not ended).

#### Q18. Generated API keys cannot be predicted or fixed

`pm-config-gen --seed N` makes the rest of the configuration reproducible but the keys
are random (`key-trader01-r0yzyj`). Every example in the REST documentation therefore
uses placeholder keys that cannot be pasted. Options: derive them from the seed, accept
`--api-gateway-key GW=KEY`, or print them when generating.

#### Q19. Drop-copy `seq` is global, but the feed is per participant

`DropCopyPublisher` has one process-wide counter, shared by all recipients, and it
restarts at 1 with the engine. A real consumer subscribes to its own gateway topic
(`drop_copy.event.<GW>`) and then sees a stride-2 sequence in a two-party market, so
it cannot use `seq` for gap detection, which is what the protocol document and
chapter 21 promise. Is a per-recipient counter intended? (The replay buffer is already
keyed by recipient.)

#### Q20. `KILL` and restored quote legs (evidence for Q2)

Reproduced through the ALF gateway: `MM01` quoted three symbols in chapter 26, filled
one leg each, and the engine was restarted. In chapter 27, `KILL` answered
`KILL_ACK|ACCEPTED=TRUE|ORDERS=0|QUOTES=2` but `ORDERS` still listed
`MSFT SELL 1000 REMAINING=660` for `MM01`. This is the same surviving leg as in Q2, now
hit by the participant's own kill switch, which the chapter describes as "cancel all
resting orders and active quotes".

#### Q21. Examples are only on a checkout, and compiler-based exercises need tools

Chapters 23–25, 27, 28 and 29 refer to `docs/examples/…` (RALF, CALF, REST, ALF, BALF
and the reference data). The files ship in the wheel (`pyproject.toml` includes them),
so `examples_root().parent` finds them, and the chapters now say so. The container image
has no `make`/`cc`, which the C examples need. Consider shipping the compiled C
examples, or saying in each chapter that the C exercise is optional.

### What was not verified in chapters 21–29

- Chapter 24 Exercise 4D (Automated Corridor Expansion): needs a scenario whose
  reopening indicative lands outside the corridor; not played. Exercise 4E with a
  non-default `tick_decimals`.
- Chapter 28 Exercise 6 with `duplicate_session_policy: EVICT_OLD`.
- Chapter 29: the interactive interview (`F3/F5/F9`, `b`, `c`, pick-lists). The same
  inputs were applied through saved case files, which reproduced the chapter's numbers,
  but the key bindings and the 120-column layout were not driven. `--pdf` and the `p`
  key were not run. `pm-opctl-cli stop` / `start` (used in Exercise 7) were not run on
  purpose: they act on every `pm-*` process on the machine, which would include the
  running simulation.
- Chapter 22 Exercise 6 (the student-written automation script) is a design exercise.
- Chapter 27 `RATE_LIMITED`; chapter 23 `BAD_MESSAGE` / `SLOW_CLIENT` (hard to trigger by hand).

---

## 5. Second pass — container route (2026-11-13)

**Scope:** the whole guide again, this time along the **primary educational
path, Route A (containers)**, which the first pass had checked only for
chapters 00–03. The pipx/VM/Poetry routes are kept as they are and not
expanded. A second goal: every exercise must earn its place.

**Method:** the curl install was reproduced from `deployment/curl/` into a
scratch directory (`./edumatcher.sh start`), with the exchange image built from
`develop` (0.78.4) and the released GUI images. Every command was typed into
`./edumatcher.sh shell` windows driven through `tmux`, working files in
`/data/training`.

### 5.1 Progress

| Ch. | Result |
|-----|--------|
| index | Dangling sentence in "After every engine restart" fixed |
| 00 | Seven web apps, not six (Clearing GUI, 8096, `CLEARING_GUI_PORT`), eight images. **New step:** `pm-opctl-cli clear --state --yes` after `pm-opctl-cli stop` — the demo profile leaves `book_stats.json` (AAPL restored at 22.88 instead of the configured 150.00), `stats.db` and `clearing.db` full of trades in AAPL/MSFT/TSLA. The early `pm-engine --verbose` (started on `s10-basic`) removed |
| 01 | Prerequisite no longer says `pm-setup`. Exercise 4: removing only `GW_ADMIN` gives **no** `M013` (`ADMIN_CLI` is also ADMIN) — remove both. Counts are 4 gateways, not 3. Container paths in expected output. Scheduler before 09:00 waits for `PRE_OPEN`; `--now` takes ~20 s. Skipping a phase gives `TIMEOUT` (now said). A hand-edited artifact now gives one line, no traceback |
| 02 | 7 gateways; a healthy `pm-mm-bot` prints nothing without `--verbose`; return-to-manual recipe also restarts the trader console |
| 03 | `ACK` precedes `FILL`; clearing prints at once (product fix below); **Exercise 7 removed** (bot re-quoting: contradicted the chapter's prerequisite and repeats chapter 02/09), and the `pm-viewer` aside (not introduced until chapter 18) |
| 04, 05 | Ran unchanged; stale prerequisite in 04 |
| 06 | Ran unchanged; "about 20 s" |
| 07 | ATO remainder now expires `(Opening auction ended)` (Q17 fixed in the product); misplaced "reopen the market" reminder |
| 08 | **Exercise 4 merged into 3** (both were `ORDERS`), **Exercise 8 removed** (repeat of chapter 01 Exercise 11); Exercise 5 (was 6) never created the `TRADER02` order it cancels |
| 09 | Exercises 7 and 8 swapped: `QBOOT` is now introduced (and leaves `Q004` resting) before the single-leg `CANCEL` uses it. `QLEGS` `ACTIVE`/`RECENT` after a partial fill described correctly; `KILL` exercise quotes first so both counts are non-zero |
| 10 | 15 → 14 exercises. Ex. 4 merged into Ex. 3 (it repeated the clean-up cancel); cut: OCO stop-limit/trailing variants (chapter 05), basket "ten-leg" instructor extension, stop-limit combo variant, auction/ATO-ATC combo steps, `market_maker_combos` extension. **DAY combo parents do persist** on a same-day restart (the chapter said not). `POS` introduced for recording positions; average-cost caveat for P&L |
| 11 | State reset (`clear --state`) moved to Ex. 1 — every collar/breaker prediction depends on it. Cut: "open the admin console" (chapter 01) and the console `HALT` exercise (repeat of the CLI one). Breaker halt = `halt_duration_ns` **plus a random 0–30 s**; reopening log lines added. `KILL` exercise stages orders first. Risk-level exercise ends with `KILL\|GW=TRADER01` (its resting bids skewed chapter 12's market maker). Duplicated paragraph removed |
| 12 | Ex. 8 + 9 merged. `pm-mm-bot` needs `--initial_*` after the reset. Clearing writes in 5 s batches. EOD marks normally equal the live marks (clearing re-marks every position on each trade) — the "find a changed mark" checkpoint rewritten. A same-day reopen **changes today's `daily` row**; only `eod` is fixed |
| 13 | 7 → 4 exercises: `pm-viewer`/`pm-orders`/`pm-board` left to chapter 18, the engine restart (only to see a log line) dropped. Expected `pm-dc-spy` output added |
| 14 | Starts with `clear --state`; **ends by returning to the learner's own configuration** (nothing did before, yet chapters 15–20 assume it). Scenarios verified: JPM +1.5 % on the rumour, +18 % on confirmation; ENERGY dip and recovery; NVDA +11 %, AMD −7 % |
| 15 | Ex. 4 (read the `vwap` column) and Ex. 7 (CSV export) merged into neighbours |
| 16 | One restart for a GTC and a DAY order together; 145.00 instead of 140.00 (chapter 11's L2 collar). Stats/audit exercises (repeats of 13/15) replaced by a paragraph |
| 17 | `clear --state` is now a step of Ex. 3; 11 gateways, not 10; `HALT_SYM` pulls the TSLA quote, so re-quote |
| 18 | Rebuilt on the running capstone stack: no second `pm-clearing`/`pm-stats`/`pm-audit`; prerequisites said "chapters 01–03" |
| 19 | `CANCEL_SYM` and `SESSION\|STATE=` exercises removed (used since chapters 06–08); `QCANCEL` places its own quote |
| 20 | Ran unchanged; Ex. 5 re-quotes before the sell (`INACTIVATE_ON_ANY_FILL`) |
| 21 | One gap script instead of two (the first could not show a gap); recipe for `TRADER01` fills; replay-limits reading exercise folded into the background |
| 22 | Ex. 5 (empty-book bootstrap) folded into Ex. 4, Ex. 6 (re-write Ex. 2) into Ex. 2 as the idempotency check. `-v` does print each `QUOTE sent` |
| 23 | **No `nc` in the container**: a `tcp` bash helper (`/dev/tcp`) introduced and used by 24 and 27; `-v` for the listening line |
| 24 | Ex. 4 merged into Ex. 2, 4E (`REF`) into 2B, 4D (ACE, impossible with this config) turned into a note; changelog notes ("as of CALF 1.0.0") removed; `pm-calf-spy '*'` *skips* CB/DEPTH/INDEX |
| 25 | `pm-admin --id OPS01` must be closed before the admin REST calls (`ENGINE_AUTH`); illegal transition is now `409 TRANSITION_REJECTED`, not `503`; Ex. 11 (replaces the config) moved last and given its deploy/restart |
| 26 | After the split the market maker must re-quote at half price (else the index jumps +54 %); `pm-alf-console --id OPS01` needs `pm-admin` closed; Ex. 9 (export) merged into 8 |
| 27 | Container has no `ss`/`lsof`/`netstat`/`nc`/`telnet`; one-liner waits before `EXIT` |
| 28 | Ex. 2 points to chapter 27's; sessions are disabled in this config (no "open the market") |
| 29 | `pm-opctl-cli start` (starts a whole profile with a clock-driven scheduler) replaced by the manual start |

### 5.2 Product fixes

| Fix | Where | Test |
|-----|-------|------|
| `pm-mm-bot` exited with code 1 and **no output** when it could not start (no reference price, auth refused, every symbol excluded): all its messages were INFO, shown only with `--verbose`. Startup failures, auth rejection and "excluded from quoting" are now WARNING. | `src/edumatcher/mm_bot/bot.py` | `test_mm_bot_multi.py::…::test_a_startup_failure_is_visible_without_verbose` |
| `pm-clearing --print-every N` printed the table *before* the triggering trade was applied (trades are batched): after the first trade nothing was printed, after the second the table showed the state after the first. It now flushes the batch before printing. | `src/edumatcher/clearing/main.py` | `test_clearing_main.py::TestPrintEvery` |
| `pm-opctl-cli clear` always warned "1 pm-* process(es) appear to be running" — it counted itself. | `src/edumatcher/emo/cli.py` | `test_emo_cli.py::test_running_process_detection_ignores_itself` |
| `pm-clearing` recorded **every gateway session twice** (`pm-clearing-cli sessions`), and would record a refused connect as a session: the engine echoes inbound commands (`system.gateway_connect`) onto PUB for the audit trail, and clearing subscribed to them as well as to `system.gateway_auth.*`. It now uses the broadcasts only. | `src/edumatcher/clearing/main.py` | `test_clearing_advanced_integration.py::…::test_echoed_connect_command_does_not_record_a_second_session` |
| `pm-audit --terminal` printed nothing until the buffer flushed (up to 10 s) — the "pm-audit captured nothing at first" mystery of the first pass. It now prints each entry on arrival. | `src/edumatcher/audit/main.py` | `test_audit_main_runtime.py::test_terminal_prints_each_line_before_the_flush` |
| `pm-mm-bot` never asked for the book at start-up, so on a quiet book it found no reference: a restarted `MM01 --all-symbols` failed on 141 of 150 symbols. It now sends `book.snapshot_request` per symbol (2 of 150 failed, both with empty books). | `src/edumatcher/mm_bot/bot.py` | `test_mm_bot_multi.py::…::test_a_quiet_book_is_asked_for_and_seeds_the_reference_price` |
| `pm-ticker` showed the day's high/low/open from `stats.db` in raw ticks (`H:41995.00`, change `-99.00%`). | `src/edumatcher/ticker/main.py` | `test_stats_and_orders.py::TestQueryDailyStats::test_returns_row_for_today_in_display_prices` |
| A cold `pm-api-gwy` refused its **first order** with `503 SYMBOLS_NOT_READY`: authentication requested the symbols but did not wait for them. It now waits (up to the handshake timeout). | `src/edumatcher/api_gateway/engine_client.py` | `test_api_gateway_runtime.py::test_authentication_waits_for_the_symbols_snapshot` |
| `pm-alf-gwy` refused lines sent behind `HELLO` before `WELCOME` with the false "HELLO must be the first message" — so the documented `printf … \| nc` probe never worked. It now holds them until the logon completes. | `src/edumatcher/alf_gwy/gateway.py` | `test_alf_gwy_gateway_unit.py::test_lines_sent_behind_hello_are_handled_after_welcome` |

Answered from the first pass: Q8 (`STATUS` quote legs) and Q17 (ATO expiry
text) no longer reproduce. Q14 (illegal transition → `TIMEOUT`) still does.
Out-of-scope findings went to `EduMatcher-For-Later-ToDo.md` as L003–L015 (L009 is Q14's console half: REST now answers `409`, the consoles still `TIMEOUT`).
