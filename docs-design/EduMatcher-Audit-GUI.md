# EduMatcher - Audit GUI: Investigation, Surveillance, and Replay Design

Version: 1.1.0-design

Date: 2026-11-27

Status: **Design proposal; not implemented.** Follows the structure and
evidence-first approach of the [Clearing GUI design](./EduMatcher-Clearing-GUI.md).
The audit reader, replay library, integrity checks, re-run, queue CLI and
`pm-sim-forensics` already exist; the application, analysis read models, job
API, and surveillance detectors below are proposed. Code takes precedence over
older design claims.

Revision 1.1 is a critical review of 1.0; section 1.3 lists its findings and
the sections it changed. The ordered implementation plan is
[EduMatcher-Audit-GUI-Workplan.md](./EduMatcher-Audit-GUI-Workplan.md).

## 1. Purpose and release boundary

The optimal audit GUI is an **evidence workbench**, not a wall of JSON and not
another live trading dashboard. It should let a reviewer move from:

> "Something unusual happened in this symbol"
>
> to "These gateways and orders explain the episode"
>
> to "Here is the recorded sequence, its uncertainty, and reproducible evidence."

The clearing GUI asks **what position or obligation resulted?** This application
asks **what happened, why, whether it was consistent, and what deserves review?**
Use `pm-clearing` and its GUI as a model for read-only access, overview-to-entity
navigation, clear units, drill-downs, and Explain mode. Do not use the clearing
ledger as a substitute for the audit trail: rejected commands, cancelled quotes,
queue priority, and causal chains often leave no execution in clearing.

### 1.1 The six questions the application must answer

| Question | Required answer and primary workspace |
|---|---|
| What analyses do we want? | Lifecycle and causality; execution quality; liquidity provision/withdrawal; participant and counterparty behaviour; symbol price formation; auction/halt episodes; recording and engine correctness. See Overview, Market, Explorer, Participants, and Findings. |
| What information should we see? | The selected evidence scope, completeness limitations, exact event sequence, order/trade relationships, measured activity and denominators, market context, and source references. Every summary must lead to its contributing events. |
| What anomalies should we discover? | Separate recording defects, exchange invariant violations, operational incidents, and behavioural candidates. A broken trade leg and a high cancellation rate are not the same kind of finding. |
| What can logs reveal about participants and symbols? | Observed trading style, counterparties, liquidity dependence, execution asymmetry, repeated responses, price impact, and regime changes. These describe gateway activity, not a person's identity or intent. |
| Can we discover suspicious symbol trading? | Yes: explainable candidate detection for layering-like episodes, repeated paired round trips and circular trading rings, aggressive price runs/reversals and momentum ignition, stop-trigger hunting, close-window and auction influence, and related patterns (section 4.2), subject to data prerequisites. None is automatically proof of abuse. |
| What deeper evidence is worth finding? | Hidden liquidity dependence, priority loss, stop/iceberg cascades, configuration effects, asymmetric access outcomes, and the difference between a participant's complaint and what the exchange recorded. See section 5. |

### 1.2 Delivery boundary

**R0 - Thin vertical slice (one session, one symbol):** source/snapshot
selection with the evidence banner, the Market workspace for one symbol
(price/trade strip, depth heatmap from recorded `book.*`/`depth.*`
observations, and order lifelines from recorded order lifecycle events), the
order/trade story drawer with raw evidence, existing replay findings, and
imported `pm-sim-forensics` results. It proves the snapshot, read-model and
drill-down contracts on the views a reviewer uses most, before the remaining
workspaces are built.

**R1 - Explain and verify:** the rest of the evidence workbench: integrity and
coverage, overview, event/episode explorer with typed filters and pivot,
descriptive participant, counterparty-flow and market-quality analytics,
simulator context (news and true value, section 6), on-demand re-run and
queue views, evidence-driven animated illustrations (section 9.11), evidence
basket, compare mode, saved views, session debrief reports, bookmarks, and
bounded evidence and notebook exports.

**R2 - Behavioural surveillance:** versioned detectors (including cycle
highlighting in the flow ring), peer/session baselines, baseline-conditioned
symbol, participant and counterparty comparisons, durable review
disposition, and ground-truth detector validation with scenario bots
(section 4.4). The R1 Findings workspace has a clearly marked behavioural
section that is unavailable until these services ship; it must not display
invented scores or empty "all clear" results.

**Later, prerequisite-dependent:** near-live in-session review (needs an
incremental episode index), cross-venue analysis, beneficial-owner
relationships, news from outside the simulator, and robust counterfactual
simulation.

This document designs the complete destination, while making the first useful
release independent of a large surveillance platform.

### 1.3 Critical review of version 1.0

Version 1.0 was strong on evidence discipline. It kept integrity, coverage,
link confidence and behavioural strength apart; it defined counting and clock
contracts; and it refused to manufacture answers. Those parts stand. As a
design for the *best* audit analysis GUI for this system, it fell short in
these ways. Each finding lists the section that now addresses it.

| # | Finding in 1.0 | Change in 1.1 |
|---|---|---|
| F1 | It was designed for a generic regulator. EduMatcher is an educational simulator (README), used by instructors, students, bot developers and engine developers. These users need session debriefs, strategy explanation and teaching, not only case surveillance. | Personas in section 1.4; Debrief reports in section 9.8; Explain mode links to the Training Guide. |
| F2 | It treated news correlation as "later, external". The simulator already publishes `news.event` (rumour, confirmed, retracted) and records the hidden true value (`value_jumps` in `market_sim_news.db`). No real venue has that ground truth. | Simulator context source in section 6; informed-trading and pre-publication analyses in sections 3.1, 4.2 and 5. |
| F3 | Detector calibration relied on "representative sessions" without labels. A simulator can generate labelled manipulation and benign look-alike episodes, so precision and recall can be measured instead of assumed. | Scenario-bot ground truth and a threshold workbench in section 4.4. |
| F4 | It lacked the two visualisations that make spoofing, layering, queue and liquidity questions readable at a glance: a **price × time depth heatmap** and **order lifelines** (each order drawn as a bar at its price from admission to its end). It had only line charts and tables. | Market workspace and the visual vocabulary in sections 9.4 and 9.10. |
| F5 | Symbols and Replay each had their own symbol × time chart with different controls. Both workspaces asked the same question at different zoom levels. | Merged into one **Market** workspace with Analyse and Replay modes (sections 9.1 and 9.4). |
| F6 | There was no working set. Reviewers collected evidence by bookmarking URLs, and exports were built from one selection. | An **evidence basket** that persists across workspaces and feeds compare, export and debrief (section 9.1). |
| F7 | Market-quality analysis was vague ("observed spread/depth"). It gave no time weighting, no effective or realized spread, and no price impact. Event-weighted spreads are biased towards busy periods. | Market-quality row in section 3.1 and the time-weighting rule in section 3.2. |
| F8 | The detector catalogue missed patterns that this venue's own features make possible and that its records reveal: stop-trigger hunting, iceberg pinging, breaker/collar gaming, momentum ignition, auction indicative steering, and positioning before news, corporate-action or index events. | Section 4.2 rows added. |
| F9 | It did not use `pm-sim-forensics`. Those checks already compare audit, stats, clearing, monitor and gateway records, and they are the strongest cross-store consistency evidence available. | Imported into the Exchange-consistency lane (sections 2, 4.1, 6). |
| F10 | It had no way to slice beyond the fixed screens, no side-by-side comparison, and no reproducible path from a GUI result to a notebook or CLI. Analysts outgrow a fixed screen set quickly. | Typed filter grammar, saved views, bounded pivot, compare mode, "copy as API/CLI" and Parquet export (sections 8, 9.1, 9.3, 9.8). |
| F11 | R1 bundled seven work packages before the first usable screen. The views reviewers use most (one symbol's market and one order's story) were not prioritised. | R0 thin slice (section 1.2) and AU-0 (section 11). |
| F12 | Everything was static. Some scenarios (circular trading, stop cascades, queue priority, auction formation) are much easier to understand when they are seen to unfold, especially for teaching. | Evidence-driven animated illustrations with playback controls and static equivalents (section 9.11); circular-trading ring detector (section 4.2). |

Design choices from 1.0 that the review **kept** deliberately: ADMIN-only,
pinned snapshots, worker isolation for re-run, deterministic narration,
transparent rules instead of ML scores, four separate confidence kinds, and
the refusal to show "all clear" without a completed eligible scan.

### 1.4 Users and their first question

| Persona | Typical first question | Primary entry point |
|---|---|---|
| Instructor after a class session | "What happened in today's session, who did what, and what should we discuss?" | Debrief report (section 9.8) -> Market -> Participants. |
| Student / bot developer | "Why did my bot's order not fill, and how did my strategy behave compared with others?" | Order story, participant profile, compare mode. Reached through an instructor-prepared extract or an ADMIN-run classroom deployment; there is no self-service access (section 2.1). |
| Engine / platform developer | "Is this a recorder gap, an engine defect, or expected behaviour?" | Integrity & Coverage, Findings (consistency lane), re-run. |
| Surveillance learner | "What does layering look like in the data, and why is this detector's alert not proof?" | Findings evidence cards on labelled scenario sessions (section 4.4), Explain mode. |
| Operator / reviewer | "What deserves review in this session, and can I export defensible evidence?" | Overview triage -> Findings -> evidence basket -> export. |

All personas use the same evidence contracts. Personas change the defaults
(landing view and Explain level), not what the backend may claim.

## 2. Audited current state

The following is a source review, not a claim that a real capture was replayed
or that performance was measured for this proposal.

| Component | Existing behaviour | Design consequence |
|---|---|---|
| `pm-audit` | Records receipt-stamped topic/payload lines, envelope metadata, recorder-start markers, rotated day parts, and zstd archives. The active writer has a configurable fsync interval. | Read retained evidence through the existing parsers. Show committed/indexed coverage, recorder restarts, and durability limits; do not promise lossless live capture. |
| Audit manifest | Chains archived-day content hashes and records retention tombstones. Verification exists in `audit/manifest.py`. | Display chain/content checks separately from source completeness. Without an independently retained head hash, chain rewriting or tail removal cannot be excluded. |
| `pm-audit-cli` and event index | Raw filtering and an optional, manually built SQLite event index. `indexed_through` identifies its snapshot horizon. | Reuse raw query vocabulary. A stale event index is not the end of the actual trail. |
| Replay pipeline | Normalises facts, orders them, reconstructs state and links, assembles episodes, derives arithmetic, and detects consistency findings. | Reuse library results; do not reconstruct business rules in TypeScript. |
| Replay JSON output | Emits episodes, beats, links, anomalies, recorded fields, resolved prices, and source references. | A useful internal model, but not a ready-made paginated browser API. Introduce typed bounded adapters. |
| Replay episode index | Separate from the raw-event index; schema/rules/detection/source metadata, atomic rebuild, no incremental build. | Expose generation identity and build status. Do not rebuild it per HTTP request or assume cheap live tailing. |
| Re-run | Drives a fresh engine from recorded configuration and inputs, compares output, handles supported timers/restarts, and reports unavailable input history. Uses patched clock/persistence state. | Run in a separate worker process, never inside the API event loop or a shared thread. Re-run is not ordinary timeline playback. |
| Queue analysis | Observes the re-run for an order or price level; reports matching-priority order, displayed quantity ahead, and iceberg/stop context. | Queue explanations require re-run eligibility. An aggregate book snapshot is not an exact queue. |
| `pm-api-gwy` | Already has ADMIN `GET /api/v1/admin/orders/{order_id}/audit` over the raw audit index, with index-horizon information. | Reuse its authentication and source-read patterns; there is no general audit workbench/job/surveillance API today. |
| Clearing GUI | Implemented read-only React SPA over authenticated clearing REST routes, with participant drawers, Explain mode, and same-origin proxy. | Follow the actual application as well as its design. The older design's statement that the GUI does not exist is no longer current. |
| Log GUI | Process-log dashboard and operational issue/explorer workflow; the tagged dashboard charts process errors and recent logs. | Reuse visual conventions, not data semantics. Process ERROR counts cannot measure audit completeness or suspicious trading. |
| Recorded market data | `pm-audit` subscribes to the engine publisher, so `book.*`, `depth.*`, `auction.indicative.*`/`auction.result.*` and `system.book_checkpoint.*` are retained alongside commands and trades. | The heatmap, spread and markout analyses use these recorded observations. Their publication cadence limits the time resolution; measure it per snapshot and show it. Do not assume every book change was published. |
| `pm-sim-forensics` | Cross-store oracles over a finished simulation run (audit, stats, clearing, monitor, gateways): PASS, FAIL with sample rows, SKIPPED, or ERROR per check. | Import results into the Exchange-consistency lane with check ID and data scope. Do not re-implement them in the GUI backend. SKIPPED and ERROR are not PASS. |
| Market simulator | Publishes `news.event` and `sim.value` on its own bus, which `pm-audit` does not record. It stores headlines and true-value jumps in `market_sim_news.db`. AI-trader gateways run named presets (strategy × execution × tempo × risk). pm-api-gwy already serves news history (`GET /api/v1/news`, any key) and live true values (`GET /api/v1/admin/sim`); no route serves true-value history. | Optional, separately labelled **simulator context** source (section 6). Not audit evidence, and absent in non-simulated sessions. Reuse the existing news reader; add only a read-only true-value history helper. |
| ECharts adoption | Existing GUIs chart with ECharts (dash, clearing, log, trader). | Use ECharts heatmap/custom series for depth heatmaps and order lifelines. A new chart framework is not needed. |

### 2.1 Identity and visibility

A **participant gateway** is the available actor dimension. Neither an order
gateway ID nor a pair of trading gateways establishes a client, beneficial owner,
human trader, common controller, or coordinated intent. Gateway identity may also
aggregate multiple strategies.

R1 is **ADMIN-only**, including exports and linked raw records. Existing ADMIN
authentication grants this application access, but the UI exposes no order,
kill-switch, configuration, or market-control actions. There is no existing
dedicated audit-reviewer role to assume.

A future least-privilege reviewer role needs real backend authorization work.
Participant self-service is not R1: hiding names in a cross-venue story is not
sufficient authorization. Queue pseudonyms and omitted reserves help prepare a
reviewed extract, not a general data-isolation guarantee.

### 2.2 Four independent kinds of confidence

Always distinguish:

1. **Integrity:** do retained bytes agree with the manifest, and was its head
   independently anchored?
2. **Coverage:** which runs, intervals, topics, source files, and contextual
   history are available; where are the proven or possible gaps?
3. **Link confidence:** existing `RECORDED`, `CERTAIN`, `STRONG`, `HEURISTIC`,
   and `NONE` labels, with their actual evidence.
4. **Behavioural strength:** how much a measured pattern meets a declared
   detector rule. This is neither link confidence nor probability of misconduct.

No single green "audit verified" badge may stand in for all four.

## 3. Analysis catalogue and measurement contracts

### 3.1 Core analyses

| Analysis | Questions | Measurements and context | Click-through |
|---|---|---|---|
| Order lifecycle | Was it accepted, amended, filled, cancelled, expired, or rejected? Why did it not trade? | Accepted state versus request, remaining quantity, fills, effective limit history, TIF, priority-changing changes, cancel origin/reason. | Order story, causal request/effect chain, exact queue when eligible. |
| Execution consistency | Do print, both fill legs, and drop copies agree? | Per-trade quantity/price/identity/liquidity-flag checks; per-order conservation. | Side-by-side messages with differing fields highlighted. |
| Participant behaviour | Who provides/takes liquidity, churns, changes style, or encounters rejects? | Distinct commands/orders, accepted/rejected counts, executed shares/value, maker/taker/auction split, lifetimes, reason mix. | Gateway profile, symbol breakdown, contributing orders. |
| Symbol microstructure | What moved the price and changed available liquidity? | Trade price/size, observed spread/depth, imbalance, aggressive flow, quote withdrawals, phases/halts. | Synchronized chart, order/participant overlays, replay. |
| Counterparty interaction | Who repeatedly trades with whom, and is that unusual given activity? | Directed buyer/seller volume and count, pair shares, reversals, graph concentration and baseline. | Pair history and exact trade/order IDs. |
| Execution quality | Are outcomes asymmetric across participants or regimes? | VWAP, effective-limit improvement, eligible quote benchmark, signed markouts, fill opportunities, queue wait. | Benchmark observation, fill, queue and later observations. |
| Session/auction behaviour | Who joins/leaves around opens, closes, halts, and uncrosses? | Phase-specific order flow, indicative/result changes, late cancels, auction allocation where supported. | Phase episode with linked commands, trades, and reference state. |
| Operations and evidence | Can we rely on this analysis? Is an apparent anomaly a missing-input problem? | Sequence gaps/discontinuities, recorder restarts, missing envelopes, clock warnings, unknown topics/scales, config/version coverage, `pm-sim-forensics` check status. | Integrity/coverage view and source lines. |
| Market quality | How tradable was the symbol, and when did that change? | Time-weighted quoted spread, depth within N ticks per side, two-sided book presence, effective spread, realized spread and price impact at declared horizons (definitions in section 3.3), per phase. | Heatmap interval, contributing trades and the quote observation each benchmark used. |
| Price discovery and information (simulator context) | Did prices track the hidden true value? Who traded in the direction of the next value jump or news, and when relative to publication? | Price minus true value over time, adjustment half-life after a news event or jump, signed gateway flow before/after publication, rumour→confirm/retract episodes. | News card, true-value overlay, the trades and orders inside the window. Simulator sessions only (section 6). |
| Strategy behaviour | Does a gateway behave as its declared bot preset or student strategy intends? Which strategies provided or consumed liquidity? | Observed style features (passive share, order size and lifetime distribution, aggression, inventory path, news reaction lag) next to the declared preset where recorded. | Participant profile and compare mode. The declared preset is a label, not evidence of behaviour. |

### 3.2 Counting, units, and time

The backend owns metric definitions; tooltips, API metadata, exports, and tests
must use the same definitions.

- Count venue executions once from canonical `trade.executed` identities within
  their run, not again from fills, drop copies, or episode membership. A
  self-gateway trade has two sides but remains one venue execution.
- Show submitted commands, admitted orders, amendments, cancel requests,
  successful owner cancellations, and system cancellations separately. An MM
  quote may create several legs; a quote update is not automatically one order.
- **Cancelled-order rate:** orders ending by owner cancellation / admitted
  orders in an explicitly defined entry cohort. Show open/censored orders and
  window-edge history. Do not equate cancel-request count with cancelled orders.
- **Message-to-trade ratio:** define the counted command families and divide by
  unique executions involving the gateway in the same scope. Zero executions
  means an undefined ratio with the numerator shown, not zero or infinity.
- **Fill ratio:** executed shares / admitted shares under a versioned amendment
  policy; do not silently reuse the final order quantity after size changes.
- **Lifetime:** admission to terminal state on one declared clock; open orders
  are right-censored. Report sample count and excluded/censored count.
- **Time weighting:** spread, depth and presence metrics are weighted by the
  time each observation was valid (until the next observation, a gap, or a
  phase change), not averaged per event. Event-weighting overstates busy
  periods. Report the covered time and the excluded time (gaps, halts,
  one-sided book) next to each value.
- **Inventory path:** cumulative signed traded shares per gateway and symbol
  inside the selected scope, starting at zero at the window start. Label it
  "net traded in window", never "position".
- Existing replay `time_to_ack`, first-fill, and completion timings are
  **receipt-clock** measurements in seconds. Label them as such. New
  engine-clock metrics need explicit input-field coverage and separate names.
  Never subtract client, engine, and recorder clocks to imply network latency.
- Order events canonically by publisher run and `eseq`, using the existing
  legacy fallback when absent. Display the ordering mode. Message ID time is
  not matching priority; matching priority must come from the engine/queue.
- Preserve timestamps in UTC and nanosecond integer values as decimal strings
  across JavaScript/JSON. Render venue timezone, date, and zone; expose exact
  source values on demand. A nanosecond field is not proof of nanosecond accuracy.
- Convert tick prices only using recorded `tick_decimals`; preserve integer
  tick values and precision. Missing scale means unavailable display money.
  Use decimal/integer arithmetic for new monetary aggregates, not binary-float
  accumulation of formatted values.
- Do not aggregate unrelated symbol quantities or unlabelled monetary units.
  Show per-symbol results; cross-symbol value comparisons require compatible,
  explicit currency/unit metadata, not an assumption of economic equivalence.

### 3.3 Benchmarks and the observation boundary

An observed best quote must be the last eligible observation **before** the
event in canonical order, with its age shown. Never use a later snapshot to
describe pre-trade liquidity. A gap, stale quote, halt, one-sided book, unknown
precision, or missing phase invalidates affected benchmarks.

For continuous trading, a proposed signed markout is
`side_sign * (mid(t + horizon) - execution_price)`, where BUY is +1 and SELL -1.
State whether this is the buyer/taker or maker perspective; show horizon,
benchmark source, age, included/excluded counts, and per-share versus total
units. It is not realized P&L. Auction prints require an auction-specific
benchmark rather than a continuous-market spread.

The market-quality measures in section 3.1 use the **taker's** side sign and
`mid(t-)`, the last eligible mid before the trade:

- effective spread `= 2 * side_sign * (execution_price - mid(t-))`;
- price impact `= 2 * side_sign * (mid(t + horizon) - mid(t-))`;
- realized spread `= effective spread - price impact`
  `= 2 * side_sign * (execution_price - mid(t + horizon))`.

All three are per share, in price units of the symbol, reported with the
horizon and as share-weighted and trade-weighted averages labelled as such.
A trade without an eligible `mid(t-)` or `mid(t + horizon)` is excluded and
counted.

No interpolation across evidence gaps. Snapshot charts are observations, not
proof that every intermediate queue state is known. A forward-looking metric
is unavailable at the end of the evidence window until its horizon is covered.

## 4. Anomalies and suspicious-pattern discovery

### 4.1 Findings have separate lanes

| Lane | Examples | What the reviewer should infer |
|---|---|---|
| Evidence quality | `ESEQ_GAP`, `SEQ_GAP`, `ESEQ_DISCONTINUITY`, `RECORDER_RESTART`, missing config/envelope, manifest failure. | Some conclusions may be unsupported. Investigate capture/history first. |
| Exchange consistency | `QTY_MISMATCH`, `FILL_AFTER_TERMINAL`, `PRICE_THROUGH_LIMIT`, trade-leg and print disagreement, broken causal chain, failed `pm-sim-forensics` checks. | Recorded facts violate a checked invariant, subject to context coverage and the check's assumptions. |
| Operational behaviour | Reject bursts, heartbeat-timeout cancellations, phase transitions, timer effects, clock disagreement. | A participant, configuration, or infrastructure issue may explain the symptom. |
| Behavioural candidates | Layering-like episodes, repeated paired round trips, close-window influence. | A declared pattern merits examination; intent and common ownership are not established. |

Reuse existing replay codes and severities, including expected window-edge
findings such as an order still open at the end. Do not relabel every warning
as an engine error. Re-run differences form a separate result with engine
versions and first divergence; they are not automatically proof of an original
engine defect.

### 4.2 Proposed behavioural detector catalogue (R2)

All rows below are **new analytics**, not existing replay capabilities. These
are detection hypotheses with explicit corroboration and counter-explanations.
Run by symbol and phase first; a venue-wide ranking is only a navigation aid.

| Candidate | Measurable trigger ingredients | Evidence one click away | Main caveat / prerequisite |
|---|---|---|---|
| Layering/spoofing-like episode | A gateway supplies large displayed size at several nearby levels; opposite-side executions occur; much of that displayed size is cancelled shortly afterwards; repeated episodes meet the configured rule. | Before/during/after displayed depth, level distance, order lifetimes, opposite-side fills, withdrawal causes, repetition count. | Requires dependable book/queue context. Legitimate MM repricing, risk limits, and halts can look similar; cancellation does not prove lack of trading intent. |
| High-rate churn / quote-stuffing-like burst | Exceptional new/amend/cancel intensity relative to the gateway's comparable baseline and symbol activity; low executed share, many short-lived orders. | Command-rate series, admitted/rejected split, quote-leg expansion, rate-limit rejects, phase context. | High activity alone does not demonstrate disruption; receipt timing cannot establish matching-engine or network harm. |
| Repeated paired round trips | A and B repeatedly trade a symbol in opposite directions within a window, with similar quantities and small net inventory change from observed trades. | Ordered pair executions, directional gross/net shares, prices, recurrence, other counterparties. | Candidate for wash-like activity only; separate gateways may be independent, and activity outside the venue/window is unknown. |
| Circular trading ring | A directed cycle of three or more gateways (A→B→C→A) trades similar quantities of one symbol within a declared window, so shares return to the starting gateway and every member's net traded in window stays within a tolerance. | Animated flow ring (section 9.11), each leg's trade and order IDs, cycle duration, prices, members' other counterparties. | Generalises paired round trips. Cycle search is bounded by window, length and minimum quantity. In a small venue with one dominant MM, rings occur by chance; compare against an activity-conditioned baseline. Not proof of common ownership. |
| Same-gateway self-trade or prevention cluster | Recorded trades with identical buy/sell gateway IDs; separately, repeated self-match-prevention outcomes. | Exact print, both orders, SMP configuration and rejection/cancellation evidence. | A prevented attempt is not an execution; shared gateway is not beneficial-owner proof. Do not assume the active policy permits such trades. |
| Price run and reversal | Concentrated signed aggressive flow, directional movement, then reversal within a declared horizon; repeated by gateway/symbol. | Every contributing print, pre-event quotes, flow share, post-event benchmark, news/context if independently supplied. | Thin books and genuine information produce similar patterns; causation is not established by timing alone. |
| Close/open-window influence | A gateway dominates price-moving activity in a configured phase-relative window, followed by reversal or a material indicative/result change. | Session schedule, phase markers, contributions, auction indications/result and later price. | Use actual session/auction semantics, not a hard-coded wall time. A last trade is not automatically the official closing price. |
| Liquidity withdrawal before stress | Unusual displayed-quantity withdrawal precedes aggressive flow, a large move, or halt, repeatedly for a gateway. | Withdrawal events/reasons, disconnects, market depth, timing and recurrence. | Can be ordinary risk control or a shared public response; no inference of private knowledge. |
| Preferential counterparty concentration | Pair volume/count share exceeds an eligible activity-conditioned baseline; repeated alternating or price-patterned trades strengthen the candidate. | Buyer/seller matrix, denominators, pair sequence, available liquidity and participation mix. | A small venue or dominant MM naturally creates concentration. Reject a baseline that assumes uniform counterparties. |
| Repeated adverse-selection asymmetry | A participant's passive fills repeatedly have adverse signed markouts versus a valid comparator cohort. | Maker/taker labels, quotes, fill sizes, markout distribution and excluded observations. | This is an outcome, not proof of front-running, information leakage, or unfair access. |
| Cross-symbol lead/lag pattern | Repeated gateway activity in one symbol precedes related-symbol moves or activity under a declared relationship and lag. | Joint timelines, relationship source, independent sessions, lag distribution. | Exploratory/later R2; requires a justified relation and enough samples. Multiple comparisons easily produce spurious leads. |
| Momentum ignition | A gateway places resting orders on one side, then sends aggressive orders on the other side that sweep levels, then trades back into its own resting orders after the move, with a quick reversal. | Ordered sweep, the gateway's resting orders before and after, other gateways' reactive flow, reversal horizon. | Separate from "price run and reversal": what defines it is that the same gateway is positioned to profit from the move it started. Requires recorded causal order of sweep and fills. |
| Stop-trigger hunting | Aggressive flow moves the last trade price across resting stop trigger prices; the triggered stop cascade (recorded trigger links) fills against the same gateway's opposite-side orders. | Stop triggers and their chain roots, which prints crossed them, the gateway's prior resting orders, cascade depth. | Stop prices are not public, so a gateway can only guess clusters. Do not assume knowledge. Benign aggressive flow also triggers stops. |
| Iceberg pinging / hidden-liquidity probing | Repeated small IOC/FOK orders at one level that each take a small fill during iceberg refills, followed by larger directional activity from the same gateway. | Probe sequence, refill events (operator-visible), fills, follow-on orders. | Refills are privileged data. Small IOC orders are also normal execution tactics. |
| Breaker / collar gaming | Orders that push the indicative or trade price to a circuit-breaker or collar boundary, followed by halt or auction participation that benefits the same gateway. | Configured thresholds in force, breaker trigger evidence, auction allocation, post-resumption price. | Thresholds come from recorded configuration only. A halt alone is not evidence of intent. |
| Auction indicative steering | Orders entered and cancelled during a call phase that move `auction.indicative` price or imbalance materially, cancelled before the uncross. | Indicative series with the gateway's order entries and cancels overlaid, final result, allocation. | Indicative cadence limits resolution. Legitimate price discovery also moves the indicative price. |
| Pre-publication positioning (simulator news or recorded index/corporate-action events) | Signed flow concentrated in the direction of a later `news.event`, true-value jump, recorded corporate action or index rebalance, before its publication time. | Event card with publication time, the gateway's flow in matched pre/post windows, comparison against a no-event baseline. | In the simulator nobody can know an event before publication, so a hit points to a timing defect, a leak, or chance. News and true-value events need the simulator context source (section 6); index and corporate-action events are in the audit trail (`index.*` topics). |

### 4.3 Detector contract and false-positive control

Each detector must declare:

- Stable ID/version, plain-language rule, required event families, phase and
  order-type eligibility, exact formulas, thresholds, time windows, minimum
  samples, clock basis, and gap/staleness policy.
- All threshold values in the result. "Large", "rapid", and "unusual" are not
  implementable rules until the selected profile gives numeric definitions.
  Profile calibration must use representative sessions and the labelled
  scenario corpus (section 4.4); this design does not invent universal
  thresholds for every symbol.
- A baseline from comparable **earlier** eligible sessions/windows or a named
  peer cohort, with source coverage and sample count. Do not learn a historical
  baseline from future data or silently pool MM and non-MM behaviour.
- Measured inputs and denominators, qualifying and non-qualifying observations,
  evidence IDs, context exclusions, and alternative explanations.
- A result state: `not_run`, `running`, `completed`, `insufficient_data`,
  `unsupported`, or `failed`. "No candidates" is valid only for a completed
  eligible scan of the displayed scope.
- Deterministic episode grouping so one burst does not create hundreds of
  redundant alerts; preserve its component candidates and underlying events.

Start with transparent rules and distributions, not opaque ML or a universal
"suspicion score". Show per-rule strength and reviewer priority separately from
the replay's existing severity. Searching thousands of gateway/symbol/windows
creates chance outliers: require recurrence/holdout-session confirmation for
escalation, and show how many comparisons the scan made. Statistical
significance must not be claimed without a justified testing procedure.

Reviewer dispositions are **unreviewed**, **in review**, **explained**,
**needs follow-up**, and **escalated**. "Explained" never deletes the evidence
or silently changes future detector thresholds. R2 stores notes, reason,
reviewer identity, timestamps, and superseded dispositions in a separate
application store, never in the audit files or derived replay database.

### 4.4 Ground-truth validation with scenario bots

A real venue can never tell whether a detector alert was "real". A simulator
can. R2 adds **scenario bots**: test-only gateway programs (or ai_trader
strategies) that reproduce one pattern from section 4.2 on purpose, with a
labelled manifest (gateway, symbol, intended episode start/end). None of the
current ai_trader presets is manipulative, so these bots are new work. Each
pattern also needs a **benign look-alike** scenario: MM repricing after a
price move, halt-driven mass cancellation, a thin-book news reaction,
legitimate IOC sweeps.

- Every detector version is run against the labelled scenario corpus as part
  of AU-7 acceptance. Report precision and recall per scenario and look-alike
  at the shipped profile, and the episode-time error.
- The **threshold workbench** (R2, Findings) re-runs one detector over pinned
  historical and scenario snapshots at several candidate thresholds and shows
  candidate counts and labelled hit/miss counts side by side. Changing a
  threshold creates a new profile version; it never rewrites old results.
- Scenario labels are stored with the scenario snapshot, never in the audit
  files. The UI shows "labelled scenario" prominently, so nobody mistakes a
  training session for a real classroom session.
- A labelled session is also teaching material: a surveillance learner can
  open the evidence card, see why the detector fired, and compare it with the
  benign look-alike.

Scenario bots exist only to test and teach surveillance. They must refuse to
run unless the deployment is marked as a simulation, and they never connect
to production gateways.

## 5. Deeper insights: what is buried in the trail?

The most useful discoveries need not involve misconduct.

| Hidden question | Useful evidence/analysis | Limit of the claim |
|---|---|---|
| Which gateway keeps a symbol tradable? | Share of observed best-price presence/displayed depth; spread/depth when present versus absent; passive execution share. | Coverage-qualified association, not proof that removing it would cause the same result. Presence needs continuous eligible observations, not event-count percentages. |
| Why does a gateway lose queue position? | Amendments, iceberg refills, price changes, orders ahead, and fills/cancels ahead in the re-run queue. | Exact only while the re-run agrees with the recorded path. |
| Are apparently random bursts one causal cascade? | Trade -> stop trigger -> child order -> trade -> breaker/auction chains; OCO/combo effects and cancellations. | Recorded links distinguish a cascade from mere temporal clustering. |
| Is reserve liquidity supporting execution? | Privileged iceberg/refill events and queue observations versus displayed size. | Operator-only information; not inferred from public aggregate depth or suitable for unrestricted export. |
| Did policy, not strategy, change behaviour? | Run/config hashes, collars, tick scales, SMP, phase restrictions, gateway-role and reject changes where recorded. | Do not assign causal impact to a config change without comparable evidence. |
| Is a "slow participant" actually clock skew or admission failure? | Separate receipt/engine/client clocks, gateway rejects, missing ACKs, heartbeat expiry and gaps. | Audit alone does not measure end-to-end network latency or unrecorded client attempts. |
| Who absorbs whom's aggressive flow? | Signed pair flows, maker/taker share, repeated markouts, symbol/phase cohorts. | Not a durable profit-transfer calculation; use clearing for positions/P&L. |
| Are bots synchronised, periodic, or stuck? | Inter-arrival distributions, repeated command templates, reject/retry loops, simultaneous symbol changes. | Shared scheduling or a common public trigger is not coordination evidence. |
| Was an MM's apparent cancellation storm exchange-driven? | Cancel reason and chain root separate owner action from halt, kill switch, heartbeat, SMP, expiry, or quote replacement. | Attribution must follow recorded causes before behavioural scoring. |
| Did the engine treat comparable orders consistently? | Same-rule order cohorts, queue priority, rejects, fills and re-run comparisons. | Different arrival position, order type, hidden quantity, or phase may explain different outcomes. |
| Can a missing fill complaint be resolved? | Effective order instructions, eligible trades, price priority, displayed queue ahead, and cancellation/expiry history. | If inputs or exact queue are unavailable, answer "not determinable from retained evidence", not "the exchange was correct". |
| Who traded on information, and who paid for it? (simulator) | Signed flow against the next true-value move and news publication; passive fills that were later on the wrong side of the true value. | Simulator-only. Value knowledge is ground truth for teaching, not something any participant could see. |
| How fast does the market absorb news? | Time from `news.event` publication to price crossing half the true-value move, by symbol, phase and depth. Rumour vs confirmed vs retracted. | Needs recorded book cadence fine enough for the horizon. Reports a distribution, not one number. |
| Did a bot behave as its preset says? | Observed style features compared with the declared preset; drift during the session. | A mismatch is a debugging hint for the bot developer, not a finding against the participant. |

The UI may call this section **Insights**, never "secrets" implying that the
system knows private intentions. Every insight links to its method and sources.

## 6. Data-source and capability matrix

| View/data | Authority available today | Proposed work | Gate/limitation |
|---|---|---|---|
| Raw events and envelope | Audit files; optional raw-event index | Bounded source-aware REST projection | Show index horizon; index is derivative, not evidence authority. |
| Narrated stories and causal graph | Replay pipeline, episode index, JSON renderer | Typed query adapters and graph neighbourhood API | Preserve confidence and unknown-topic handling. |
| Existing anomalies | Replay state/detector/index | Findings query/grouping | Display context-window effects and rule versions. |
| Integrity and retention | Manifest, archives, recorder markers | Structured verification result and coverage inventory | Chain check does not prove no lost input; retired data is unavailable. |
| Descriptive activity metrics | Commands, orders, prints and fills | New versioned aggregates, with deduplication | Not all participant metrics exist in replay stats today. |
| Historical book picture | Recorded book/depth/checkpoints | Observation timeline and provenance | No invented intermediate book or queue. |
| Exact queue / level | Existing re-run observers | Process-isolated job and structured result adapter | Full eligible history and reproducible run required. |
| Engine reproduction | Existing re-run | Job/result API; first-difference UI | Preserve unavailable reasons and version mismatch. |
| Behavioural candidates | No shipped surveillance detector model identified | R2 detectors/baselines/materialized results | Numeric profiles and coverage prerequisites required. |
| Cross-store consistency | `pm-sim-forensics` checks and their report | Import job that pins the report to the snapshot and its inputs | Data scope of each check shown; SKIPPED/ERROR stay distinct from PASS. |
| Simulator context | `market_sim_news.db` (`news_events`, `value_jumps`); ai_trader preset per gateway where the deployment records it | Read-only adapter with its own provenance and hash, joined on time only | Not audit evidence, and not recorded by `pm-audit`. Clock alignment between the simulator and the engine must be shown. Absent outside simulations; true value is ADMIN-only ground truth. |
| Scenario labels (R2) | None today | Labelled scenario manifests stored with scenario snapshots | Labels describe what the scenario bot *intended*, not what the market recorded. |
| Positions, realized P&L, settlement | Clearing/EOD ledgers and clearing REST | Contextual links to clearing GUI | Do not call audit-window net shares a complete account position. |
| External context / common ownership | Not present in audit evidence | Later authoritative integration | Never infer ownership, real-world news access, or off-venue transactions. |

R1 capability discovery reports what works **for the selected evidence
snapshot**, not only what the software supports. One old archive may support
stories but not recorded causality, normalized prices, or re-run.

## 7. Application architecture

### 7.1 Placement and reuse

Create `web-apps/audit-gui` following the implemented clearing/trader layout:

```text
audit-gui/
  apps/
    web/       React/TypeScript SPA
    serve/     static server and same-origin /api proxy
  Dockerfile
  docker-compose.yml
  Makefile
  .env.example
```

Use React Router, TanStack Query, Zustand, Zod, Tailwind, Radix/shadcn patterns,
Vitest/Testing Library, and the established shell/help/table conventions.
Use ECharts, as the other GUIs do. Its heatmap series draws the depth heatmap;
a custom series draws order lifelines; canvas rendering with server-side
binning keeps dense sessions responsive. Simple SVG is sufficient for causal
graphs and queue diagrams initially.

```text
Browser SPA
    -> same-origin /api
    -> pm-api-gwy: ADMIN auth, bounded typed queries, job control
         -> read-only pinned event/replay/analysis snapshots
         -> audit worker process: build, verify, re-run, queue, forensics
            import, debrief, export; R2 scan and threshold sweep
              -> read-only configured evidence sources
              -> private scratch + derivative results/job store
```

Use the existing Python audit libraries, not shell calls to CLI commands or
parsing terminal output. Factor small typed service adapters where current CLI
composition is needed. The browser has no SQLite, filesystem, ZMQ, or engine
connection. No separate Fastify protocol bridge is justified.

### 7.2 Evidence snapshots and derivative state

The operator configures named evidence collections and permitted locations on
the server. The browser sends opaque collection/snapshot IDs, never arbitrary
paths, SQL, shell commands, or executable engine locations.

A proposed immutable **evidence snapshot descriptor** contains:

- Collection ID and source file inventory, sizes/hashes and selected cutoffs;
  for an active file, a fixed complete-line byte cutoff copied or pinned by the
  worker. A partial trailing line is reported, not silently treated as valid.
- Relevant manifest entries/head and verification result; anchoring status and
  reference if independently supplied.
- Retained dates, selected runs, receipt-time extent, canonical extent, known
  gaps/restarts, topic coverage and recorded config/engine identifiers.
- Event/replay index generations, schema/rules/detection settings, analysis
  version/profile, worker software version, and build timestamps.
- Optional attached sources, each with its own hash and status: the imported
  `pm-sim-forensics` report and the inputs it covered; the simulator context
  database extent and measured simulator-to-engine clock offset; the
  gateway → preset mapping if recorded; and, for R2 scenario sessions, the
  labelled scenario manifest.

A report pins one descriptor; pagination, linked stories, charts and exports
must not drift onto a later generation. Existing numeric episode IDs are local
to a rebuilt index. URLs pair them with snapshot/index generation, or use
run-qualified entity/source references. An expired snapshot produces an
explicit unavailable result, not a link to a different episode.

Source files stay read-only. Derivative indexes are disposable and published
atomically. Add only the aggregate read models needed by shipped screens.
R1 does not introduce Kafka, a graph database, a new market-data recorder, or
incremental episode reconstruction.

Keep job metadata/results in a separate application-owned store. R2 review
notes share that ownership boundary, not the source/index schema. Retention of
jobs/results must be explicit; a hash cannot resurrect deleted evidence.

### 7.3 Background work and operational limits

Never build a day-long index, verify archives, or re-run in a request handler.
The existing episode index rebuild is not incremental and can be expensive.
Use bounded process workers, initially one expensive job per deployment, with
deduplication for identical snapshot/options and queue/concurrency limits.

Jobs report `queued`, `running`, `succeeded`, `failed`, `cancelled`, or
`unavailable`, with stage, measured progress, heartbeat, timestamps, and reason.
Do not fabricate a percentage before total work is known. Worker death and
service restart must resolve stranded jobs explicitly; a publish is visible
only after complete atomic result installation.

Re-run/queue use a private temporary data directory and no production sockets
or production state writes. Process isolation is required because the current
re-run patches clocks/persistence. Apply resource/time/disk limits and clean
specific scratch paths on success, failure, and cancellation. Close database
connections in `finally`/closing contexts, including disconnects and errors.

Historical views never poll entire datasets. Poll only job status while a job
is active and lightweight source status when the source chooser is open.
An optional later "new evidence available" indicator may offer a new snapshot;
it must not silently move a paused investigation. Live surveillance is not R1.

## 8. Proposed REST surface

All routes in this section are **new**, under `/api/v1/audit`, except the
explicit existing admin order route in section 2. Use existing authentication,
error envelopes and typed response conventions. All require ADMIN.

**API extensibility:** Gaps in the current audit API are not fixed constraints
on this design. Extend the API as needed to support the review, analysis, and
replay workflows, including additional endpoints, filters, response fields, or
job operations. Keep extensions consistent with the authorization, evidence,
and typed-contract requirements below; an API extension cannot recover data
that was never recorded or is no longer retained.

| Route | Purpose / required response |
|---|---|
| `GET /collections` | Configured opaque sources, retained extent, availability; no unrestricted host directory listing. |
| `GET /snapshots/{id}` | Descriptor, capabilities and per-capability unavailable reasons, integrity/coverage and index generations. |
| `POST /jobs` | Validated kind (`prepare`, `verify`, `rerun`, `queue`, `forensics_import`, `export`, `debrief`; R2 `scan`, `threshold_sweep`), configured source/snapshot ID and bounded typed options; returns 202 and job ID. |
| `GET /jobs/{id}` | Authorized job state, progress, failure/unavailable reason and result references. |
| `POST /jobs/{id}/cancel` | Cancel derivative work only; never cancel an exchange order. |
| `GET /summary?snapshot_id=` | Scope-qualified activity, evidence health, findings by lane, eligible insights. |
| `GET /events?snapshot_id=&...` | Bounded event rows, canonical key, raw fields, clock/unit metadata and source refs. |
| `GET /episodes?snapshot_id=&...` | Episode type, anchor, gateway/symbol, outcome, interval and finding counts. |
| `GET /stories/{entity_kind}/{entity_id}?snapshot_id=&run_id=` | Story beats, related entity refs, derived facts and confidence; bounded continuation. |
| `GET /graph?snapshot_id=&root=&depth=` | Bounded graph neighbourhood, edge evidence, omitted-node counts and expansion cursor. |
| `GET /participants?snapshot_id=&...` | Descriptive metrics and coverage by gateway; participant detail adds per-symbol/cohort breakdowns. |
| `GET /symbols?snapshot_id=&...` | Per-symbol activity/coverage; symbol detail adds phase, flow, price and liquidity series. |
| `GET /findings?snapshot_id=&...` | Existing consistency/evidence findings and imported `pm-sim-forensics` results; R2 candidate rows with rule/profile and measured inputs. |
| `GET /market/{symbol}/heatmap?snapshot_id=&from=&to=&bins=` | Server-binned price × time displayed depth per side from recorded observations, with observation cadence, age and gap/halt masks per bin. |
| `GET /market/{symbol}/lifelines?snapshot_id=&from=&to=&gateway=` | Bounded order lifeline segments: price, displayed quantity, start/end on the canonical clock, end reason, amendments as segment breaks. Lifelines over the cap are aggregated per level and say so. |
| `GET /market/{symbol}/quality?snapshot_id=&...` | Time-weighted spread/depth/presence and effective/realized spread series and summaries, with covered and excluded time. |
| `GET /context?snapshot_id=&kind=news\|value\|preset\|scenario_label&...` | Attached non-audit context (section 6) with source provenance and clock offset, or a stable "not available for this snapshot" reason. |
| `GET /flows?snapshot_id=&symbol=&from=&to=&bucket=` | Directed seller → buyer gateway-pair volume and trade count per time bucket, with each pair's share of both sides' activity. Feeds the counterparty matrix, Sankey and flow ring. R2 adds detector cycle overlays. |
| `POST /analyze` | Bounded pivot: enumerated measure × up to two enumerated dimensions (gateway, symbol, phase, order type, TIF, end reason, time bucket) over the typed filter. Returns a table with the same metric metadata as fixed screens. |
| `GET /frames?snapshot_id=&kind=&anchor=&from=&to=&cursor=` | Animation frames for one illustration kind (section 9.11): canonical event keys, the state change each frame applies, source badge, gap/freeze markers and skipped spans. At most 2,000 frames per page; denser spans are bucketed and flagged. |
| `GET /results/{id}` | Typed re-run, queue, verification, aggregate/scan or export result metadata and bounded content/download reference. |

Entity-specific participant/symbol detail routes may extend the two collection
routes above; the final OpenAPI schemas must enumerate them before implementation.
Do not advertise these proposals as the released API.

### 8.1 Response and query requirements

- Require `snapshot_id` for analysis reads. Return effective scope, context scope,
  generation, `as_of`, completeness/exclusion metadata and units with results.
- Use stable server cursors tied to snapshot, filters and sort. Default page
  size 100, maximum 1,000; graph default depth 1, maximum depth 3 and 200 nodes;
  at most 5,000 lifeline segments and 2,000 animation frames per response,
  with server-side aggregation and an explicit `aggregated` flag beyond that.
  These are proposed initial API limits, to be verified against fixtures.
- Support exact IDs and bounded entity lookup. A prefix with several matches
  returns a selection list, never the first match. Apply filters server-side.
- Return counts with an `exact`/`lower_bound` qualification, or no total when
  expensive. Do not present one page's length as the complete result count.
- Separate missing source/index (503), unknown retained entity (404), invalid
  filters (422), forbidden caller (403), and unsupported analysis capability.
  Capability unavailability has a stable reason, not a successful empty result.
- Include explicit partial/truncated states and continuation information.
  `null` plus reason means unknown/unavailable; zero means measured zero.
- Sanitize rendered text/JSON, bound payload/graph sizes, authorize all raw
  downloads, and redact credentials and sensitive configuration in previews
  and exports. Hash original evidence without changing it; authorized source
  access is distinct from a redacted report.
- Accept only enumerated jobs/options; do not accept user code, general
  expressions, arbitrary regex with unbounded cost, or uploaded executable
  content. R1 sources are operator-configured, not arbitrary archive uploads.
- **Typed filter grammar.** The filter bar accepts a small, documented grammar
  such as `gateway:GW3 symbol:ABC end:cancel.owner lifetime<500ms phase:continuous`.
  The server parses it into enumerated fields, operators and typed values and
  compiles them to parameterised queries. Unknown fields are a 422 with
  suggestions, not ignored. The parsed form is returned so the UI can show
  chips. This is not a general expression language.
- Every response carries a `reproduce` block: the equivalent API request and,
  where one exists, the `pm-audit-cli`/`pm-audit-replay` command line for the
  same snapshot and filters. The UI's "Copy as API/CLI" uses it.

R2 adds narrowly scoped review-note/disposition routes and their change audit.
These mutate application review state only and need their own contract and tests.

## 9. Screens and information design

### 9.1 Main navigation and shared context

Use seven main workspaces in a persistent left navigation, grouped by the
reviewer's workflow (triage, investigate, trust, conclude) rather than by
data type, instead of exposing every chart as a top-level tab:

| Group | Workspace | Main question | Main content |
|---|---|---|---|
| Triage | **Overview** | Where should I look first? | Evidence banner, findings triage, activity/phase timeline, active symbols/gateways, explainable insights, simulator news strip. |
| Triage | **Findings** | What is inconsistent or deserves review? | Separate evidence, consistency (including `pm-sim-forensics`), operations, and R2 behavioural lanes; R2 threshold workbench. |
| Investigate | **Market** | What formed this symbol's market, and what happened just before and after this moment? | One symbol × time canvas (depth heatmap, trades, order lifelines, phases, news) with **Analyse** mode (quality, participants, levels, patterns, events & checks) and **Replay** mode (transport controls, book at cursor, re-run/queue, illustrations). |
| Investigate | **Participants** | How did this gateway behave? | Comparable activity metrics, per-symbol profile, outcomes, inventory path and counterparties. |
| Investigate | **Explorer** | Which records match, and what is their story? | Business episodes and raw events, typed filter bar, bounded pivot, causal story and graph. |
| Trust | **Integrity & Coverage** | What can I trust or reproduce? | Sources, manifest verification, gaps, index horizon, clock/config coverage, eligibility. |
| Conclude | **Investigations** | How do I resume, share or present this review? | Evidence basket, bookmarks, compare sets, exports and debrief reports; R2 notes, assignments and dispositions. |

Version 1.0 had separate Symbols and Replay workspaces. Both drew a symbol ×
time chart with different controls, which meant two places to learn and to
keep in sync. They are now one Market workspace: Analyse and Replay are the
same canvas at different zoom levels, and the time cursor is shared.

R1 Investigations uses URL bookmarks, the evidence basket and authorized
job/export history, not a full case-management subsystem. R2 comparison and
graph-heavy analytics live inside Market/Participants/Findings, not another
dozen main tabs.

The persistent top bar contains collection/snapshot and run selector, selected
time interval/timezone, gateway/symbol filter chips, universal entity search,
Explain switch, and evidence status. Always label **historical snapshot**;
show indexed-through and snapshot time, not an ambiguous green "connected".
A "labelled scenario" or "simulator context available" chip appears when it
applies.

**Evidence basket.** Any order, trade, episode, finding, gateway, interval or
chart selection can be pinned (shortcut `b`) to a basket in a collapsible right
rail. The basket keeps the snapshot and generation of each item, survives
navigation between workspaces, and is the input to compare mode, export and
debrief. In R1 it lives in the bookmark URL and browser storage; in R2 it
becomes part of a case. Items from a different snapshot are allowed but
visibly flagged.

**Compare mode.** Two to four basket items of the same kind (episodes,
gateways, sessions, symbols) open side by side, aligned on their anchor
event or phase start, with identical axes and scales. Differences in coverage
are shown before differences in metrics.

**Saved views.** A filter, workspace and layout can be saved by name per
user (browser storage in R1). Built-in starter views cover the reviewer
journeys in section 10.

The global interval is an explicit event-clock interval, defaulting to recorder
receipt time for raw exploration. A brush selects canonical event anchors in
the chosen run and states its clock. Gateway/symbol filters narrow results,
not the history needed to reconstruct them.

Backend reconstruction loads required preceding/context events and dependencies
before applying presentation filters. The UI shows **visible window** versus
**reconstruction context** and offers "expand context". Do not reclassify a
perfectly ordinary open order as broken simply because the user zoomed in.

### 9.2 Overview

Above the fold:

1. Evidence banner: retained/selected extent, integrity state, gaps, current
   capability restrictions; a failed check cannot be hidden below charts.
2. Tiles: unique executions and traded shares **by selected symbol**, admitted
   orders, active gateways/symbols, invariant findings, behavioural candidates
   only after a completed eligible scan. Each says scope and counting basis.
3. One synchronized activity/phase strip with order/trade/cancel/reject layers,
   gap shading and simulator news markers (N) when available. A brush opens
   the same interval in Market (Analyse or Replay).
4. **Needs review:** grouped findings ranked within their lane, first occurrence,
   gateway/symbol, explanation, evidence strength and next action.
5. **What changed?** Largest eligible departures from a named earlier baseline;
   unavailable until comparison analytics exist.

Do not fill the page with raw event totals, process error counts, a "clean market"
score, or rankings without denominators. A burst of book snapshots is not a
burst of trades.

```text
+-----------------------------------------------------------------------+
| Audit Review | Session / snapshot | time + zone | Search | Explain     |
| COVERAGE: 09:00-17:30 | gap at 10:14 | manifest checked, unanchored      |
+---------------+-------------------------------------------------------+
| Overview      | Orders | Executions | Gateways | Consistency findings  |
| Findings      | [activity + phase timeline ..(N)... gap .........]     |
| Market        | Needs review                | Evidence limitations    |
| Participants  | [finding -> story]          | [gap -> affected scope] |
| Explorer      | Symbol activity / gateway contribution                |
| Integrity     | [row -> Market]             | [row -> participant]    |
| Investigations| Eligible insights, each with "Why?" and source count   |
|  [basket: 3]  |                                                       |
+---------------+-------------------------------------------------------+
```

### 9.3 Explorer: episode first, raw data always reachable

Default to **Episodes**: order lifecycle, trade, quote, administrative action,
phase/halt, or gateway lifecycle, using existing replay episode kinds. A toggle
opens **Raw events** without losing scope. Filter by topic/type, outcome,
gateway, symbol, order/trade/command/chain ID, finding code and confidence.

Selecting a row opens a URL-addressable wide drawer with:

- Plain-language summary and the exact claim/coverage qualifiers.
- **Story**: submission -> decision -> effects, related episodes, and quantities.
- **Causality**: bounded graph; solid recorded links, distinctly labelled
  inferred links; expand parents/effects and "recorded links only".
- **Market context**: contemporaneous eligible book/phase and nearby trades.
- **Checks**: findings and exact field/value disagreements.
- **Raw evidence**: topic, envelope, original payload, source file/line and
  source hash reference, alongside normalized values and their units.

Default prose comes from the existing deterministic narration, not an LLM.
Highlight unknown topics/enums rather than dropping them. Provide "Open in
Market", "Follow counterparty", "Show cause", "Pin to basket", "Copy as
API/CLI" and "Export selection".

The **Pivot** tab (`POST /analyze`) answers ad-hoc questions the fixed
screens do not, for example "owner-cancel rate by gateway × phase" or
"median lifetime by order type × symbol", using only enumerated measures and
dimensions with the same metric definitions as everywhere else. Every cell
drills into its contributing rows.

### 9.4 Market: one symbol × time canvas

The Market workspace is built around one canvas for the selected symbol and
interval. Every layer can be toggled and every mark is clickable:

```text
+-----------------------------------------------------------------------+
| ABC | 10:02-10:20 Europe/Stockholm | [Analyse | Replay] | layers v     |
| news: (R) rumour 10:05      (C) confirmed 10:11                        |
|  price                                                                 |
|  101.2 |░░▒▒▓▓▓▓▓▓▓▒▒░░░░      ████ GW7 ask lifeline (cancelled) x     |
|  101.0 |▓▓▓▓▓▓█████▓▓▓▒▒▒░░░░  ██████████ GW2 ask (partially filled) o  |
|  100.8 |      • • ●  ●●•  •   trades (size = area, colour = aggressor)  |
|  100.6 |▓▓▓▓▓▓▓▓▓▓▓▓█████▓▓▓▓  bid depth heatmap (darker = more shares) |
|        |----true value (simulator only, dashed)----------------------- |
|        |  HALT ////        gap \\\\                                    |
|  flow  | ▁▂▅▇▅▂▁▁▃▆▃  signed aggressive volume                         |
+-----------------------------------------------------------------------+
| Analyse: quality | participants | levels | patterns | events & checks |
| Replay : |< < [>] > >| step: event/trade/phase/finding | 1x | book@t  |
+-----------------------------------------------------------------------+
```

- **Depth heatmap:** displayed quantity per price level over time, bids and
  asks in two hues, from recorded `book.*`/`depth.*` observations only. Each
  column is valid until the next observation; gaps, halts and stale
  observations are hatched, never interpolated. The observation cadence is
  shown in the legend.
- **Order lifelines:** each order as a horizontal bar at its limit price from
  admission to its end, thickness by displayed quantity. Amendments break the
  bar; the end marker encodes the end reason (filled ●, owner cancel ×, system
  cancel ⊗, expired ◌). Filter by gateway, or highlight one gateway's orders
  over everyone else's in grey. This one view shows layering, quote
  replacement, queue jumping by amendment and liquidity withdrawal.
- **Trades:** markers at price, area by size, colour by aggressor side;
  auction prints drawn distinctly.
- **Context bands:** phases, halts, breaker and collar events, gaps, recorder
  restarts, `news.event` markers and the dashed simulator true value when the
  simulator context source is available.
- **Flow strip:** signed aggressive volume per bin, optionally for one gateway.

Brushing the canvas sets the interval for every pane; clicking any mark opens
its story drawer; `b` pins it to the evidence basket. Above the server's
lifeline cap (section 8) lifelines are aggregated per level and the legend
says so; zooming in restores individual orders.

#### 9.4.1 Analyse mode

The symbol list shows activity, active gateways, time-weighted spread/depth
coverage, volatility definition, phases/halts, and findings. The local tabs
under the canvas are:

- **Quality:** time-weighted quoted spread, depth within N ticks, two-sided
  presence, effective and realized spread and price impact at declared
  horizons, per phase, with covered and excluded time.
- **Participants:** maker/taker/auction contributions, activity concentration,
  eligible liquidity dependence, and metric-selected top contributors.
- **Levels:** price-level lifetimes/withdrawals, exact queue entry
  points where supported, and distinction between displayed and reserve size.
- **Patterns:** R2 rule-by-rule candidate timeline and baseline comparisons;
  no single symbol "manipulation probability".
- **Events & checks:** filtered episodes/raw evidence, circuit-breaker and
  config context, integrity limitations affecting this symbol.

A "Why did this price move?" selection produces the observed sequence of
aggressive prints, liquidity changes, news and participants, with recorded
causal links distinguished from temporal associations. "What if gateway A
were removed?" is not an R1/R2 answer: other participants might have acted
differently.

#### 9.4.2 Replay mode: reviewer-controlled, synchronized, and honest

The default is **recorded-event playback**, not engine re-execution. The
canvas stays in place; the panes below it change:

```text
+-----------------------------------------------------------------------+
| (shared canvas above, with a vertical cursor line)                     |
+-----------------------------------+-----------------------------------+
| Book at cursor (ladder)           | Selected order / trade story      |
| bids | price | asks               | request, decision, cause, effects |
| source and age; no implied queue  | checks, confidence, source        |
+-----------------------------------+-----------------------------------+
| Canonical event timeline; linked selections across every pane         |
| Optional exact queue/re-run result, eligibility and divergence banner  |
+-----------------------------------------------------------------------+
```

Controls: step event, business episode, trade, phase, or finding; seek by ID or
canonical position; interval loop; speed; bookmark. Selecting any chart point
selects its underlying event(s), and the row selection moves the shared cursor.
Keyboard stepping must work without a mouse. Large idle periods may be skipped,
but the elapsed jump is labelled; no events are omitted from evidence.

Three modes have persistent labels:

1. **Recorded:** recorded events and observed snapshots only. Seeking shows the
   last known observation and age; gaps remain shaded and unresolved.
2. **Reproduced:** on-demand existing re-run with recorded inputs/configuration,
   output comparison, first divergence, version information and eligibility.
3. **Queue explanation:** on-demand order/level observer over that re-run;
   displayed quantity ahead, priority changes, trades/cancels ahead, reserve
   visibility warning, and the engine's queue explanation.

The current re-run requires history back to an empty-book engine start, recorded
configuration for every run, and no proven hole. A later checkpoint does not
automatically make an arbitrary mid-day fragment reproducible. If dependencies
are absent, disable the action with the exact unavailable reason.

Do not present a reproduced queue as recorded truth after the first relevant
divergence. The adapter must track command/symbol validity; if that boundary
cannot be established, conservatively invalidate subsequent queue results.
Re-run equality proves agreement with that engine build and recorded inputs,
not the absence of all exchange bugs.

Reverse seeking restores a cached derivative checkpoint or replays from a valid
earlier point; it never "undoes" matching actions heuristically. R1 may use
precomputed bounded result pages instead of maintaining an interactive engine.
Progress and cancellation are preferable to pretending an expensive seek is
instantaneous.

### 9.5 Participants

The list ranks by a selected metric, with gateway ID, covered activity,
admitted/rejected orders, executed shares per symbol, maker/taker/auction mix,
owner-cancel rate, eligible lifetime distribution, and finding counts by lane.

Click a gateway to open a deep-linkable profile with local tabs:

- **Activity:** rate/phase heatmap, order types/TIF, size/lifetime distributions,
  reject reasons, changes against its earlier eligible baseline.
- **Symbols:** per-symbol contribution and outcomes; no meaningless summed
  cross-symbol share count.
- **Execution:** fills/VWAP, effective-limit improvement, benchmark-qualified
  markouts, queue examples and sample/exclusion counts.
- **Counterparties:** R1 pair table, directed buyer × seller matrix, flow
  ring and time-windowed Sankey (`/flows`), with pair share of each side's
  activity, not just raw volume or edge thickness. R2 adds
  baseline-conditioned concentration, detected cycles and a bounded graph.
- **Inventory & outcomes:** net-traded-in-window path per symbol (section 3.2)
  and an order outcome funnel: submitted -> rejected / admitted -> filled,
  partially filled, owner-cancelled, system-cancelled (by reason), expired,
  still open. The funnel shows what happened to the gateway's orders at a glance.
- **Findings & stories:** exact contributing episodes and R2 recurring patterns.

Compare two gateways only within displayed common symbols, phases, roles and
eligible windows; show mismatched coverage. A behaviour label such as "mostly
passive" must show its formula and evidence, not infer a named trading strategy.
Where the deployment records a declared ai_trader preset, show it as a
label beside the observed features, never as their source.
Link to clearing for durable positions/P&L, retaining gateway/symbol/date context.

### 9.6 Findings

Use the four lanes in section 4, with filters and counts scoped to a completed
analysis. A row includes code/rule, severity or review priority, symbol/gateway,
interval, recurrence, evidence/coverage qualifiers, and scan/rules version.

Clicking a finding opens a consistent **evidence card**:

1. Claim in plain language and what it does **not** establish.
2. Rule, measured values, thresholds, denominators, baseline, exclusions.
3. Ordered before/during/after events with pinned chart and counterparties.
4. Strongest counter-explanations, especially system-driven cancellations,
   auctions, thin liquidity, clock problems and window edges.
5. Raw sources and causal link confidence.
6. Actions: open in Market (Replay), expand context, compare cohort, pin to
   basket, export; R2 disposition/notes.

### 9.7 Integrity & Coverage

This is a first-class workspace, not a settings page:

- Day/file/run inventory: retained, retired, missing, active/unsealed;
  original and indexed extents, malformed/torn/unsupported records.
- Manifest-chain/content verification, checked time, head hash and external
  anchoring state. Unanchored is not the same as failed.
- Sequence-gap map, restart boundaries, affected symbols/topics when known.
  An engine-wide gap whose missing topics are unknown affects all potentially
  dependent conclusions; do not pretend its symbol scope is known.
- Envelope/link-confidence distributions, unknown-topic/scale counts and
  engine/client/receipt clock warnings.
- Startup/config/engine-build coverage; re-run/queue eligibility with exact
  reasons and the earliest missing prerequisite.
- Index/rules/detection metadata, rebuild status, and explicit stale-generation
  action. Building a new generation does not change an open investigation.

### 9.8 Investigations, exports and debrief reports

R1: copy a deep link containing snapshot/generation, run, scope, selected entity,
cursor, basket and view options; list authorized exports/jobs. No credentials
in URLs. The link is a bookmark, not preservation of deleted evidence.

An export is an evidence bundle with structured JSON/NDJSON, selected raw
extracts where authorized, and a human-readable Markdown/HTML summary:

- Investigation question, selected/context scopes, source snapshot descriptor.
- Findings, formulas, numeric settings, versions, baselines and caveats.
- Raw-to-normalized references, source hashes and manifest/anchoring result.
- Re-run/queue eligibility, versions, compared extent and differences.
- Export hash inventory, creation time, redactions and omitted/truncated data.

Default exports contain only selected evidence plus required context, not an
entire unrestricted audit archive. CSV is optional for tables and must contain
explicit units, exact IDs, precision and safe spreadsheet escaping. Charts
have a table equivalent; a screenshot alone is not reproducible evidence.

**Notebook export.** The normalized events, order lifecycles, trades and
metric tables for the selected scope can be exported as Parquet with a
`descriptor.json` (snapshot descriptor, metric definitions, units, tick
scales). This lets researchers and students continue in pandas or Jupyter
without re-parsing audit files. A notebook export is a bounded derivative,
not a raw evidence extract, and follows the same redaction rules.

**Session debrief report.** A `debrief` job produces a per-session HTML/Markdown
report for teaching: session timeline with phases, halts and news; per-symbol
market quality; a per-gateway page (outcome funnel, maker/taker mix,
inventory path, VWAP versus the session VWAP, findings by lane); notable
episodes picked by documented rules (largest move, longest halt, deepest
stop cascade), each linking back into the GUI. Gateway pages can be
generated individually, so an instructor can hand each student only their
own page. That is a reviewed extract under section 2.1, not self-service
access. A per-gateway page pseudonymises every other gateway (stable
per-report aliases such as "Counterparty 3"), omits iceberg reserve and
refill data and raw records of other gateways, and includes the simulator
true value only when the instructor enables it for a finished session.

R2 adds durable cases with title/question, owner, notes, linked snapshots,
findings, basket contents and disposition history. Preserving source evidence
for a case needs an explicit authorized retention policy; do not label a
case a legal hold.

### 9.9 Shared UX and "one click away" contract

| Visible item | Direct next view |
|---|---|
| Any gateway/symbol ID | Profile drawer with current investigation scope. |
| Any order/trade/command ID | Its story, recorded fields, relationships and checks. |
| Any quantity/ratio/score | Formula, included/excluded count, units and contributing rows. |
| Any causal edge | Recorded IDs or inference rule and confidence. |
| Any chart bucket | Underlying events; if aggregated, list the contributors. |
| Any gap or warning badge | Affected extent, source evidence and disabled conclusions. |
| Any finding | Evidence card, preloaded around the relevant episode. |
| Any queue position | Order/level explanation and reproduced-versus-recorded status. |
| Any integrity badge | Exact check, checked source/hash and anchoring limitations. |

Use the clearing GUI's Explain switch, on by default, for formulas, worked
examples and teaching diagrams. Where a concept has a chapter in the
[Training Guide](../docs/books/training-guide/) or the
[AI-traders book](../docs/books/ai-traders/), the Explain text links to it.
Essential caveats, units, confidence and gap
warnings are never hidden by switching Explain off. Every table/chart has
help, accessible keyboard navigation, loading/empty/error states, bounded
pagination, and a visible scope. No red/green-only encoding.

Drawers preserve list position and browser Back/Forward. Dark/light themes,
monospace identifiers, aligned numeric columns and readable timestamp precision
support dense investigation without overwhelming the default view.

### 9.10 Visual vocabulary

Use a small, consistent set of chart types, each for the question it answers
best. Every chart has a table equivalent and drills to rows.

| Question | Chart | Where |
|---|---|---|
| Where was liquidity, and when did it move? | Price × time depth heatmap | Market canvas |
| Which orders formed that liquidity, and how did each end? | Order lifelines | Market canvas, evidence cards |
| Who traded aggressively, and in which direction? | Signed flow strip | Market canvas, Participants |
| What happened to a gateway's orders? | Outcome funnel (left-to-right bars, not a pie) | Participants, debrief |
| How did a gateway's exposure in the window evolve? | Inventory path step chart | Participants, compare mode |
| Who trades with whom? | Directed buyer × seller matrix (sorted, with row/column shares); graph only for a bounded neighbourhood | Participants, Findings |
| How do gateways differ in style? | Small multiples of the same distribution (lifetime, size, inter-arrival) on shared axes; no radar charts | Participants compare |
| How did market quality vary through the session? | Time-weighted spread/depth lines with excluded-time hatching | Market Analyse |
| What is the recorded sequence? | Canonical event table with a shared cursor | Explorer, Market Replay |

Avoid gauges, single "health" scores, 3-D charts, and dual y-axes that
imply a relation between unrelated units.

### 9.11 Dynamic illustrations

Some scenarios are much easier to understand when they are seen to unfold:
a ring of trades that returns shares to where they started, a cascade of
stop orders, an order working its way to the front of a queue. Version 1.0
had only static charts. Version 1.1 adds a small set of **animated
illustrations**, each attached to the evidence it explains.

#### 9.11.1 Rules for every animation

1. **Playback, not simulation.** Every frame is one canonical event or one
   recorded/re-run observation. The animation is driven by the same cursor
   as Replay mode, so play, pause, step forward/back, speed and "jump to
   next trade/finding" all work, and pausing shows exactly the event under
   the cursor.
2. **No invented intermediate states.** Visual easing between two frames
   lasts at most 150 ms and only moves marks between recorded positions. A
   gap, halt or missing observation freezes the frame with a hatched
   "no data" overlay; it is never tweened across.
3. **Source badge on every animation:** **Recorded**, **Reproduced** (re-run,
   with divergence banner), or **Illustrative** (a synthetic textbook example
   in Explain mode, built from no snapshot). Illustrative frames never appear
   in an evidence export. A labelled scenario session (section 4.4) is still
   **Recorded** evidence of what the scenario bot did, and also carries the
   "labelled scenario" chip.
4. **Time compression is shown.** A running clock and a "×N speed, idle
   periods skipped (4 min 12 s)" label; skipped spans are listed.
5. **Static equivalent.** Every animation has a final-state chart and an
   event table with the same frames; `prefers-reduced-motion` and the
   keyboard-only path use them by default. Animation is an aid to
   understanding, never the only way to see a result.
6. **Bounded.** The server returns at most the frame budget per request
   (section 8); denser intervals are aggregated per bucket and say so.

#### 9.11.2 Illustration catalogue

| Scenario | Illustration | What becomes visible | Source and limits |
|---|---|---|---|
| **Circular trading** (A→B→C→A) and paired round trips | **Animated flow ring.** Gateways as nodes on a circle; each trade is a particle travelling from seller to buyer along a directed edge (ECharts `lines` effect); each node has a bar showing net traded in window. Completed cycles in the same symbol light up with their path and elapsed time. | Shares that leave a gateway and come back to it within a short time while each node's net stays near zero. That is the pattern of circular or wash-like trading, and it is almost invisible in a trade list. | Recorded trades only (`/flows`). Shows observed flow, not ownership or intent (section 4.2). R1 animates flows and net bars only; cycle highlighting is the R2 detector's, with its window and quantity tolerance shown. |
| **Price-time priority and the queue** | **Animated queue ladder.** Each price level is a row of blocks, one per resting order in priority order, width by displayed quantity. New orders join at the back, amendments that lose priority jump to the back, trades consume blocks from the front, and iceberg refills reveal a new block at the back. | Why an order did not fill, and what "orders ahead of you" means. This answers journey 10.1 visually. | Exact block order only from an eligible re-run (Reproduced badge). Without one, the ladder shows aggregate level bars and the label "queue order not determinable". |
| **Layering / spoofing-like episode** | **Ladder + lifelines in step.** Large orders appear on one side, the opposite side trades, the large orders disappear; the suspect gateway's blocks are highlighted and everyone else's are grey. | Where the displayed size was, how long it lived, and what traded while it was there. | Recorded book observations and order lifecycles. Per-order blocks follow the queue-ladder rule above; without an eligible re-run the ladder shows level bars and the lifelines carry the per-order story. Shown with the same counter-explanations as the evidence card (MM repricing, halt cancels). |
| **Stop cascade / stop-trigger hunting** | **Domino chain.** On the price axis, each trade that crosses a stop trigger lights the stop, which turns into an order, hits the book, prints, and lights the next trigger. A causal-graph strip below shows the same chain. | That a burst of trades was one recorded causal chain rather than many independent decisions, and who placed the first push. | Recorded trigger links (`CERTAIN`/`RECORDED`). Heuristic links are drawn dashed and labelled. |
| **Auction call and uncross** | **Moving supply/demand curves.** Cumulative buy and sell curves during the call phase, with the indicative price at their intersection; entries and cancels animate the curves; at uncross the matched volume is filled in. | How late orders and cancels moved the indicative price: auction indicative steering, and how an uncross price is formed. | Curves from recorded order commands or book observations during the call phase. Where those are missing, only the recorded `auction.indicative` price and imbalance are animated. |
| **Momentum ignition / price run and reversal** | **Price path with flow arrows.** Aggressive orders as arrows pushing the price; the initiator's resting orders pinned on the far side; the reversal drawn after. | The order in which the setup, the push and the profit-taking happened. | Recorded sweep, fills and lifecycles; causal order from canonical sequence. |
| **Circuit breaker / collar** | **Price corridor.** The configured band drawn around the reference price; the price approaches the edge, the halt band appears, then the auction and resumption. | Why trading stopped and how close the price came to the limit beforehand. | Thresholds from recorded configuration only. |
| **Message flow for one order** | **Animated swimlane sequence diagram.** Lanes for gateway, engine, book, counterparty, drop copy and recorder; messages slide between lanes in canonical order, with each clock's timestamp. Missing messages show as a gap with their finding code. | The difference between a request, the engine's decision and its effects, and where a recorder gap or clock skew sits. | Recorded envelopes and links. Never derives network latency from different clocks (section 3.2). |
| **News absorption** (simulator) | **Converging lines.** True value steps at the news event; trade price and mid catch up; the flow strip shows who traded during the adjustment. | How fast the market priced in news, and the difference between a rumour, a confirmation and a retraction. | Simulator context only (section 6); clock offset shown. |
| **Who trades with whom over time** | **Time-windowed flow Sankey or matrix.** Sellers on the left, buyers on the right; a sliding window animates through the session. | A shift in counterparty relationships, such as an MM taking over one side. | Recorded trades. Shares of each side's activity are shown next to raw volume. |
| **Self-match prevention** | **Two-block collision.** Two orders from the same gateway approach on the ladder, and the SMP policy cancels one or both. The configured policy is shown. | What SMP does, and the difference between a prevented self-trade and an executed one. | Recorded SMP cancel reasons and configuration. |

#### 9.11.3 Placement

- **Market, Replay mode:** an "Illustrate" layer toggle offers the queue
  ladder, layering view, domino chain, momentum path, corridor, auction
  curves and SMP collision for the current cursor.
- **Evidence cards (Findings):** each detector in section 4.2 names its
  default illustration (for example, the flow ring for circular trading), so
  a reviewer can play the episode from the card.
- **Explorer story drawer:** the swimlane sequence diagram for the selected
  order or trade.
- **Participants → Counterparties:** the flow ring and the time-windowed
  Sankey.
- **Explain mode and debrief reports:** illustrative textbook versions, and
  recorded playbacks of labelled scenario sessions (section 4.4), plus short
  exported clips (WebM or an animated SVG frame strip) for teaching. A clip is
  teaching material, not evidence, carries its snapshot ID and source badge,
  and follows the debrief redaction rules (section 9.8).

## 10. Worked reviewer journeys

All examples below are illustrative scenarios, not findings about actual users
or captured EduMatcher sessions.

### 10.1 "My order should have filled"

Search exact order ID -> select run if ambiguous -> inspect accepted instructions
and amendments -> compare eligible executions -> open Queue explanation.
The result shows what quantity stood ahead, which trades consumed it, and
whether an amend/refill changed priority. Export the recorded story plus the
re-run's qualified queue evidence. If history has a hole, give the supported
partial answer and "queue not determinable", not a fabricated verdict.

### 10.2 "This symbol has a strange price spike"

Market -> brush the move -> read the depth heatmap and lifelines for withdrawn
liquidity and aggressive flow -> identify gateway contributions -> open
candidate episode -> examine order lifetimes and opposite-side executions ->
check phase/system cancellations and news markers -> switch to Replay mode
with before/after context. A layering-like candidate may become
"explained: halt-driven cancellation"; the same shape is not the same cause.

### 10.3 "Two gateways keep trading with each other"

Counterparty matrix -> pair direction/reversals -> compare each gateway's pair
share against symbol activity -> play the flow ring to see whether shares
return through a third gateway -> inspect exact orders and repeated episodes ->
check other counterparties and eligible price/queue context.
Export "repeated paired round trips observed" (or, with R2, "circular
trading ring candidate"), never "common-owner wash trading proved" when
ownership and intent are not recorded.

### 10.4 "Did the exchange or the recorder fail?"

Findings -> trade-leg disagreement -> open three-way print/fill comparison ->
check sequence gaps, window edges and drop copies -> expand context -> verify
source integrity -> request re-run if eligible.
An absent message in a proven gap does not establish an engine allocation bug.
If re-run differs, inspect the first difference and engine versions before
interpreting downstream cascades.

### 10.5 "Debrief today's class session"

Instructor opens the session snapshot -> Overview shows phases, halts and the
news strip -> runs the `debrief` job -> walks the class through the largest
move in Market (heatmap, lifelines, news marker, true-value line) -> compares
two student gateways in compare mode (outcome funnels, inventory paths,
lifetime small multiples) -> exports each student's own gateway page.

### 10.6 "Who reacted to the rumour, and was anyone early?"

Overview news strip -> click a rumour -> Market opens on the symbol with the
rumour, confirmation or retraction marked -> signed flow by gateway before
and after publication -> Pivot "net traded by gateway × (before/after
publication)". Flow before publication is checked first against clock
alignment between the simulator and the engine, then treated as a candidate
for a timing defect or chance, never as evidence that a participant had
inside knowledge.

## 11. Implementation order and acceptance gates

These are design packages, not claims of completed work. The
[workplan](./EduMatcher-Audit-GUI-Workplan.md) splits them into ordered,
test-first work packages AG0–AG33. Follow the
[business-contract testing guidelines](./EduMatcher-Testing-Guidelines.md);
expectations come from message/exchange contracts and explicit metric definitions,
not snapshots of today's renderer alone.

| Package | Scope / dependencies | Acceptance evidence |
|---|---|---|
| AU-0 | R0 thin slice: one configured collection, snapshot descriptor, ADMIN read routes for heatmap, lifelines, stories and findings, `pm-sim-forensics` import, SPA shell with Market canvas (Analyse, no Replay transport yet), story drawer and evidence banner. Built as the first, narrow cut of AU-1..AU-3, not a throwaway prototype. | One recorded session with a known layering-like sequence and a halt: heatmap columns match recorded observations with gaps hatched; each lifeline's start, end and end reason match the order's recorded lifecycle; clicking a lifeline opens the right story and raw lines; forensics SKIPPED/ERROR never render as PASS. |
| AU-1 | Typed audit service adapters, source catalog, snapshot descriptor and capability model; generalises AU-0. | Fixtures cover modern/legacy logs, rotations/zstd, retired/missing/torn input, run resets, source mutation and exact unavailable reasons. Reads do not modify sources. |
| AU-2 | ADMIN read/job API, isolated worker, derivative store, atomic generation publication, typed filter grammar and `reproduce` blocks; depends on AU-1. | API denial on every route/download for non-ADMIN; path/option validation; filter grammar rejects unknown fields and never reaches SQL unparameterised; stable pagination; unavailable/locked DB distinction; cancel, timeout, worker-death/restart and scratch cleanup tests. |
| AU-3 | SPA shell, Integrity, Explorer with Pivot, stories, existing findings and evidence basket; depends on AU-2. | Browser journey source -> finding -> story -> raw source, with correct generation, confidence, clock/unit display and Back behaviour. Basket items keep their snapshot across workspaces. No missing/error state becomes zero. |
| AU-4 | Descriptive and market-quality aggregates, Overview, Participants, Market Analyse, compare mode, simulator context adapter, `/flows`, the `/frames` frame service and its first illustrations (flow ring, time-windowed Sankey, news absorption); depends on AU-2 and AU-3. | Multi-gateway/multi-symbol fixtures prove trade deduplication, separate cancellation origins, amendment policy, cohort censoring, pre-event quotes, time-weighted (not event-weighted) spreads, phase filtering and scope-preserving drill-downs. Without a simulator database, the news/value layers show "no simulator context", not empty charts. The flow ring's per-pair totals equal the counterparty matrix for the same scope. |
| AU-5 | Re-run/queue adapters, Market Replay mode and the replay-attached illustration kinds over `/frames` (queue ladder, domino chain, corridor, auction curves, momentum, SMP, swimlane); depends on AU-2, AU-3 and AU-4. | Eligible known queue and restart fixtures match explicit priority rules; missing initial/config/gap inputs refuse analysis; divergence invalidates dependent queue; production state/sockets untouched. Each illustration's frame list equals its static event table; a gap freezes the frame instead of tweening; a non-eligible queue shows aggregate bars with "not determinable"; reduced-motion users get the static view. |
| AU-6 | Bookmarks, saved views, bounded evidence and Parquet export, debrief reports, deployment/help/API docs and R1 acceptance; depends on AU-4 and AU-5. | Bundle links/hashes/settings reproduce the selected result; a Parquet export reloads in pandas with the documented schema and units; a per-gateway debrief page or clip contains no other gateway's identifiers, raw records or reserve data, and no true value unless enabled; redaction/download authorization and snapshot expiry are explicit; all reviewer journeys in section 10 work with keyboard and accessible tables. |
| AU-7 | R2 detectors, numeric profiles, baselines, review state, scenario bots, labelled corpus and threshold workbench; depends on AU-6. | Positive and benign look-alike scenarios per detector with recorded precision/recall at the shipped profile; system-cancel/auction/thin-market controls; minimum samples, multiple comparisons, no-future-data baseline, gap exclusion, deterministic grouping and disposition history. Scenario bots refuse to start outside a simulation deployment. A labelled three-gateway ring is found by the circular-trading detector and its flow ring replays the cycle, while an MM-dominated benign session does not escalate. |

### 11.1 Performance targets to measure, not existing guarantees

Before R1 acceptance, record a repeatable reference benchmark: one retained
session of at least **10 million events**, including dense book topics,
at least 20 gateways and 50 symbols; reference machine 8 logical cores,
16 GiB RAM and local SSD. Publish actual fixture distribution and measured
worker/API/browser resource use with the implementation results.

Initial targets after preparation:

- p95 API first page/story-neighbourhood, heatmap, lifeline and flows response
  <= 2 seconds, excluding
  separately reported job preparation and network transfer;
- browser event stepping through prefetched pages <= 100 ms p95;
- job acknowledgement <= 1 second, with progress/heartbeat refreshed within
  2 seconds while work runs;
- maximum 1,000 event rows, 200 graph nodes, 5,000 lifeline segments or
  2,000 animation frames per response as specified in section 8.1;
  no whole-day raw payload in the browser;
- worker memory <= 4 GiB on the reference session, with bounded output/disk
  quotas and a visible failure rather than host exhaustion.

Measure cold and warm queries. Report index/re-run/export throughput and total
preparation time separately; do not hide an hour-long rebuild behind a fast
cached query. If targets fail, fix the read model or narrow the documented
supported scope before release; do not silently sample evidence.

### 11.2 Critical correctness scenarios

1. A trade plus two fills and two drop copies yields **one** venue execution;
   each gateway gets its own correct side. Duplicate/replayed records are
   reported, not double counted.
2. A two-decimal and a four-decimal symbol retain correct separate prices,
   quantities and values; missing precision cannot produce a plausible number.
3. A narrow window cutting an order's beginning/end shows context/censoring,
   not a confident false lifecycle violation.
4. A run reset with reused IDs/counters does not join unrelated stories.
5. A healthy local manifest without an external anchor is **checked,
   unanchored**; tamper failure, retired evidence and no manifest are distinct.
6. One owner cancel burst, one MM quote replacement, and one halt/heartbeat
   cancellation burst remain distinguishable in counts and candidate results.
7. Unsupported/insufficient/not-run/failed scans never render "no suspicious
   activity". A completed scan names the tested rules, scope and exclusions.
8. A rebuild during pagination or export leaves the investigation pinned to
   its old generation or explicitly unavailable; it never changes the facts.
9. A queue job that diverges or fails cannot leave a success-shaped queue pane.
10. Cancelling or crashing a derivative job preserves sources and the last
    complete generation; retry does not duplicate results or review actions.
11. A heatmap over an interval with a sequence gap and a halt shows both as
    hatched, unmeasured time; the time-weighted spread excludes them and
    reports the excluded duration.
12. A simulator news event whose clock is offset from the engine clock is
    shown with the offset and its uncertainty; pre-publication flow is not
    computed when the offset exceeds the analysis window.
13. A labelled scenario session shows the "labelled scenario" chip on every
    view, frame and export; a synthetic Explain-mode illustration never
    appears in an evidence export.
14. A trade between two gateways counts once in `/flows`, the counterparty
    matrix and the flow ring, with the same direction (seller → buyer) in
    all three.

## 12. Explicit non-goals and operational limitations

- No trading, exchange-control, source-editing, or automatic enforcement action.
- No assertion of criminality, manipulation, identity, common ownership, or
  private information from behavioural similarity alone.
- No full-market view beyond retained recorded venues/sources and their coverage.
- No recovery of events that were never captured or have been retired.
- No claim that matching a manifest proves input completeness or external
  anchoring, or that a successful re-run proves an engine is bug-free.
- No exact historical queue from aggregate snapshots, approximate reverse
  matching, or silent reconstruction over a proven gap.
- No P&L/account/settlement system competing with clearing.
- No live alerting or production-engine counterfactual "what-if" in R1.
  Near-live review during a running class session is a later goal and needs
  an incremental episode index first.
- No presentation of simulator context (news history, true value, bot
  presets) as audit evidence; it is a separate, labelled source.
- No LLM-generated facts, unsupported causal narration, or opaque accusation
  score. Optional future language assistance must cite the same evidence and
  cannot replace deterministic facts or reviewer judgment.

The guiding UI rule is: **a missing answer is useful evidence when the
application explains exactly why it is missing. A plausible invented answer
is worse than no answer.**

## 13. Source references and related designs

### 13.1 Design and UI precedents

- [Clearing GUI design](./EduMatcher-Clearing-GUI.md) and
  [implemented clearing GUI](../web-apps/clearing-gui/README.md): read-only
  architecture, overview/entity navigation, units, Explain mode and deployment.
- [Audit Replay](./EduMatcher-Audit-Replay.md): causal model, episodes and
  narration; implementation alignment notes supersede early sketches.
- [Audit Completeness workplan](./EduMatcher-Audit-Completeness-Workplan.md):
  manifest, gateway rejects, re-run, durability, engine clocks and queue work.
- [Audit CLI](./EduMatcher-audit-cli.md): filtering and raw-event index.
- [Log GUI design](./EduMatcher-log-GUI.md) and
  [log dashboard](../web-apps/log-gui/apps/web/src/views/Dashboard.tsx):
  operational triage precedent, not a trading-surveillance data source.

### 13.2 Implementation evidence reviewed

- [Audit reader/query](../src/edumatcher/audit/query.py),
  [writer](../src/edumatcher/audit/writer.py),
  [manifest](../src/edumatcher/audit/manifest.py), and
  [raw-event index](../src/edumatcher/audit/indexer.py).
- [Replay pipeline](../src/edumatcher/audit/replay/pipeline.py),
  [canonical ordering](../src/edumatcher/audit/replay/ordering.py),
  [link confidence](../src/edumatcher/audit/replay/links.py), and
  [anomaly definitions](../src/edumatcher/audit/replay/anomalies.py).
- [Episode index](../src/edumatcher/audit/replay/index.py),
  [JSON model](../src/edumatcher/audit/replay/render_json.py),
  [derived metric definitions](../src/edumatcher/audit/replay/derived.py),
  [confidence statistics](../src/edumatcher/audit/replay/stats.py), and
  [CLI composition](../src/edumatcher/audit/replay/cli.py).
- [Engine re-run](../src/edumatcher/audit/replay/rerun.py) and
  [queue observers](../src/edumatcher/audit/replay/queue.py).
- [Simulation forensics checks](../src/edumatcher/sim_forensics/__init__.py)
  and [workplan](./EduMatcher-Sim-Forensics-Workplan.md).
- [Market simulator news](../src/edumatcher/market_sim/news.py) and
  [news/true-value history](../src/edumatcher/market_sim/news_history.py);
  [ai_trader presets](../src/edumatcher/ai_trader/preset.py).
- [Bus sequencing note: pm-audit takes every topic](../src/edumatcher/messaging/bus.py).
- [API application/router registration](../src/edumatcher/api_gateway/main.py)
  and [existing admin audit route](../src/edumatcher/api_gateway/routers/admin.py).

### 13.3 Decisions before implementation

The proposed defaults are ADMIN-only, historical snapshots, existing API
gateway plus process worker, deterministic narration, and transparent rules.
Before implementing the corresponding package, confirm:

1. Deployment ownership and paths for configured evidence collections and the
   derivative job/result store; storage/retention budgets and anchor handling.
2. The reference capture/machine for the measured limits in section 11.
3. R2 detector profiles, numeric thresholds, eligible baseline history and
   reviewer escalation policy.
4. Whether a future reviewer role or participant-safe extract workflow is
   required. Neither is silently included in R1.
5. Whether simulator deployments record a gateway → ai_trader preset mapping
   the audit GUI can read, and how simulator and engine clocks are aligned.
6. The publication cadence of `book.*`/`depth.*` in classroom configurations,
   which sets the finest honest heatmap and markout resolution.
7. Scope and ownership of the scenario bots and their labelled corpus (R2),
   including where they live so they cannot be enabled on a non-simulation
   deployment.
8. Whether to accept `pyarrow` (not a dependency today) as an optional
   dependency for the Parquet notebook export.

The workplan's gate table (D1–D8) maps each decision to the work package it
blocks and the default used until it is made.
