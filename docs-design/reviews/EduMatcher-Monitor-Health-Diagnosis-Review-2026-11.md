# pm-monitor Health Diagnosis Review — 2026-11 (pre-1.0.0)

**Scope:** why `pm-monitor` turns a process DEGRADED and how it tells the
operator, at `dac95e8f` (v0.80.0). In `src/edumatcher/monitor/`: `state.py`
(509 lines, the per-process health rules and the RSS-growth rule),
`thresholds.py` (264, breach levels with hysteresis and the event wording)
and `collector.py` (925; `readings`, `processes`, `snapshot` and
`_publish_transitions`). The texts that describe them: the log-ledger
entries `src/edumatcher/log_ledger/entries/monitor.yaml`, the operator
guide's "Health Monitoring" chapter
(`docs/books/operator-guide/part-6-observe-and-recover/060-health-monitor.md`)
and the dash-gui help texts (`web-apps/dash-gui/apps/web/src/lib/help.ts`,
`components/help/helpContent.ts`). The engine's latency figures
(`engine/metrics.py`, `percentile` and the 60 s horizon) and the dash-gui
bridge's mirror of the fixed rules (`apps/bridge/src/thresholds.ts`) were
read where they decide what pm-monitor judges. They were not reviewed as
code of their own.

**Focus:** whether a DEGRADED state is (a) deserved and (b) explained:
calibration of the rules that raise it, and whether the event, the log line
and the dashboard say which rule did it.

**Trigger:** the AI-trader simulation of 2026-11-16 reported eight
`HEALTHY -> DEGRADED` transitions (five processes) with no reason in the
event or its log line; the log-ledger explanation for the line is generic.

**Previous work:** the design `docs-design/EduMatcher-Operator-Dashboard.md`
(§9.6 thresholds, §10 health model) and its workplan insights (I36 loop lag
line, I63 DEGRADED after HUNG, I93 scheduler round-trips, I108 credited
silence, I118 loop-age colouring); review item R4 (RSS warm-up and ramp
rules); `EduMatcher-Monitor-Review-2026-11.md` (WP-MON01–07: counters,
`metrics.db`, CLI). Their fixes are in place and are not repeated here.

**Method:** the transitions were read from the simulation's own
`~/.edumatcher-sim/data/metrics.db` (`events`, `samples_1m`). Findings marked
*(repro)* were reproduced with scratch scripts against the tree at
`dac95e8f`, driving the real `ProcessState` (beacons every 2 s, evaluated
every second), `ThresholdBook`, `band_reading` and the engine's
`percentile`, fed with the simulation's minute RSS figures where stated.
*(measured)* means read from that `metrics.db`. The other findings are by
inspection, with line numbers given.

Status: **Open.** Decisions Q1–Q5 are needed before WP-MHD01–05.

---

## Delivery rule: test first

Every WP follows true TDD:

1. Add one or more tests that express the externally observable behaviour
   the WP must deliver (the `health.event` detail, the log line, the
   process state in the snapshot, the breach list, the bridge's fixed
   rules).
2. Run the focused test command and record the expected failure. The test
   must fail because the behaviour is absent, not because of an import,
   fixture or assertion mistake.
3. Implement the smallest production change that makes those tests pass.
4. Add the boundary and regression cases discovered on the way.
5. Run the WP's focused tests, then `tests/test_monitor_*.py`,
   `tests/test_dash_thresholds_mirror.py` and
   `tests/test_sim_forensics_ops.py` with `-n logical`, then
   black/flake8/mypy/pyright. Do not start the next WP with a known failing
   test.

Tests are not backfilled after an implementation. A defect found while
working a WP becomes a failing regression test before its fix is written.
One WP at a time; stop after each for review and commit.

Rule-level tests use `ProcessState`/`ThresholdBook` directly with the
`beacon()` helper of `tests/test_monitor_state.py`. Event and log tests use
the `mon`/`clocks` fixtures of `tests/test_monitor_snapshot.py` (real
`Monitor`, fake clocks) and assert on the published `health.event` frames and
`caplog`. The open-market RSS shape is pinned as a fixture of minute values
taken from the 2026-11-16 run (ralf-gwy 49 → 626 MB between 08:28 and 08:43,
flat after).

## Status

Legend: ☐ not started · ◐ in progress · ☑ done (awaiting/after commit) · ⚠ blocked

| # | WP | Content | Findings | Depends on | Est. | Status | Done on |
|---|---|---|---|---|---|---|---|
| 1 | WP-MHD01 | Every DEGRADED names the rule that caused it | C1, C4 | Q1 | 1 d | ☐ | |
| 2 | WP-MHD02 | Memory filled at the market open is not a leak | C2, C7 | Q5 | 0.75 d | ☐ | |
| 3 | WP-MHD03 | One burst of slow messages does not degrade the engine | C3 | Q2 | 0.5 d | ☐ | |
| 4 | WP-MHD04 | One late loop iteration does not degrade a process | C5 | Q4, WP-MHD01 | 0.25 d | ☐ | |
| 5 | WP-MHD05 | Clears and transitions say what they are based on | C6, C8 | Q3, WP-MHD01 | 0.5 d | ☐ | |
| 6 | WP-MHD06 | Ledger, guide and dashboard texts describe the final rules | D1–D6 | WP-MHD01–05 | 0.5 d | ☐ | |

Suggested order: **WP-MHD01 → 02 → 03 → 04 → 05 → 06.** WP-MHD01 first,
because it makes every later calibration change visible in the events
themselves; it also turns the loop-lag check into a rule, which WP-MHD04
debounces and WP-MHD05 words. WP-MHD02 removes the largest source of false
alarms (five CRIT breaches at every open). The text-only WP comes last so the
texts describe the final rules.

Estimated sequential effort: about 3.5 days, excluding review time and
findings discovered on the way.

---

## 1. Overall assessment

The health model itself is sound. Every one of the eight DEGRADED
transitions of 2026-11-16 had a cause that pm-monitor knew: each was
preceded, about 10 ms earlier, by a `THRESHOLD` event on the same subject,
and each cleared within a second of that breach clearing *(measured)*.
Silence credit (I108), the start-up grace and the HUNG / SILENT / DEAD rules
behaved as designed; none of them fired.

The defects are in two places:

- **The diagnosis is not carried to where the operator looks (C1, C4).**
  The `PROCESS_STATUS` event and its log line say only `HEALTHY -> DEGRADED`;
  the reason is in a separate `THRESHOLD` line the operator must find and
  match by subject. One path to DEGRADED (`loop_lag_ms` over 1 s) has no
  event of its own at all.
- **Three rules raise on events that are not degradation (C2, C3, C5).**
  The RSS-growth rule reads the memory filled at the market open as a leak
  (five CRIT breaches, all false). The engine p99 rule raises on four slow
  messages, because its sample makes p99 the fourth-worst message and the
  five-second debounce cannot filter a figure held for 60 s. The loop-age
  rule raises on one reading. Together they caused six of today's eight
  transitions; the other two were real host CPU contention.

Severity key: **High**: a process or the exchange reported healthy while it
is not, or the reverse with operator action likely. **Med**: a misleading or
unexplained state the operator sees every trading day. **Low**: clarity,
wording, rare cases.

### What happened on 2026-11-16 *(measured)*

| Time (UTC) | Process | Threshold event before the transition | Verdict |
|---|---|---|---|
| 08:48:07 | `pm-engine` | `rss_growth_pct_1h CRIT 140.547 > 100` | false: open fill (C2) |
| 08:48:11–13 | `pm-api-gwy` dashboards / monitor / desk | `rss_growth_pct_1h CRIT 650.563` / `710.919` / `710.933 > 100` | false: open fill (C2) |
| 08:52:12 | `pm-ralf-gwy` | `rss_growth_pct_1h CRIT 1179.782 > 100` | false: open fill (C2) |
| 12:08:50 | `pm-engine` | `engine_handle_p99_us WARN 5764.427 > 5000` | noise: four slow messages, host CPU 5 % (C3) |
| 14:09:21 | `pm-stats` | `loop_age_ms WARN 1336.589 > 1000` | one reading, host CPU CRIT 97.1 % (C5, C8) |
| 14:09:54 | `pm-engine` | `engine_handle_p99_us WARN 5528.068 > 5000` | host CPU CRIT 97–100 % at 14:07–14:12 (C8) |

---

## 2. Summary of findings

| ID | Sev | Area | Finding | WP |
|----|-----|------|---------|----|
| C1 | Med | Events | `PROCESS_STATUS` detail and log line carry no reason; the cause is a separate `THRESHOLD` line *(measured)* | MHD01 |
| C2 | Med | RSS rule | The market-open fill reads as a leak: 5 CRIT breaches 08:47–08:52, cleared 8–9 min later *(repro)* | MHD02 |
| C3 | Med | Engine p99 | p99 of ~390 samples is the 4th-worst message; a 60 s-held gauge passes the 5 s debounce, so one burst degrades the engine for ~64 s *(repro)* | MHD03 |
| C4 | Med | Health rule | `loop_lag_ms > 1000` makes a process DEGRADED with no threshold, no breach row and no event *(repro)* | MHD01 |
| C5 | Low | Loop age | `loop_age_ms` is raised on one reading and holds DEGRADED for 30 s *(repro)* | MHD04 |
| C6 | Low | Wording | A breach whose reading stops arriving "clears" printing its last, still-breaching value (`cleared (1179.791)`) *(repro)* | MHD05 |
| C7 | Low | RSS rule | A steady leak's percentage falls as RSS grows: a 150 MB/h leak clears at 02:50 while still leaking *(repro)* | MHD02 |
| C8 | Low | Context | Nothing ties a process's latency or loop breach to a concurrent host CPU breach | MHD05 |
| D1–D6 | — | Texts | See §5 | MHD06 |

---

## 3. Correctness findings

### C1. A DEGRADED transition does not say why *(measured)* — Med

`collector.py:662-692` `_publish_transitions`; `collector.py:623`.

`snapshot()` hands `processes()` the set of breached subjects
(`thresholds.breached_subjects()`, `collector.py:623`), and
`ProcessState.evaluate` receives only `breached: bool` (`state.py:305-332`).
The rule that is in breach is known to the `ThresholdBook` but not to the
transition code, which writes:

```python
detail = (
    f"first seen {state}" if previous is None else f"{previous} -> {state}"
)
```

So the event, the `metrics.db` row and the log line
(`process pm-ralf-gwy@edumatcher: HEALTHY -> DEGRADED`) carry no cause. In
the 2026-11-16 run the cause was always the `THRESHOLD` event on the same
subject logged 5–30 ms before (table in §1). An operator reading the log
console, `pm-monitor-cli events --kind PROCESS_STATUS` or the dashboard's
event list sees only the transition. The log-ledger entry for the line
(`monitor.yaml:66`) points elsewhere ("Look at the process's own rows around
this time", D1).

The live views do show breaches: `pm-monitor-cli status` lists them
(`cli.py:495-515`), and the dash-gui Processes row colours loop age by its
breach. Neither helps after the fact, and the dash-gui process drawer lists
no breaches at all.

The same applies to HUNG, SILENT and DEAD: the figures that decided them
(loop age, beacon silence, whether the PID exists) are in the snapshot but
not in the event.

**Fix.** Build the transition detail from the subject's active breaches,
e.g. `HEALTHY -> DEGRADED: rss_growth_pct_1h CRIT 1179.8 > 100`, and add the
deciding figure for HUNG / SILENT / DEAD (`loop_age 6.2 s > 5 s`,
`no beacon for 7.1 s, PID gone`). See Q1 for the loop-lag path.

### C2. The memory filled at the market open reads as a leak *(repro)* — Med

`state.py:85-103` (constants), `state.py:394-418` `rss_growth_pct`.

The rule takes the RSS of one hour ago as the base and declines a step with
three checks: at least 100 MB added, still rising ≥ 1 % over the last 15
min, and less than half the hour's growth within those 15 min
(`RSS_RISING_WINDOW_SEC = 900`, `RSS_RAMP_MAX_SHARE = 0.5`). The checks
assume the step is over in less than 15 min. At the 2026-11-16 open it took
about 13 min *(measured)*:

| Minute (v_last) | 08:28 | 08:31 | 08:34 | 08:37 | 08:40 | 08:43 | 08:46 → 09:04 |
|---|---|---|---|---|---|---|---|
| `pm-ralf-gwy` MB | 49 | 135 | 265 | 387 | 514 | 615 | 626 |
| `pm-engine` MB | 84 | 120 | 153 | 167 | 175 | 180 | 180 |
| `pm-api-gwy/monitor` MB | 100 | 386 | 691 | 776 | 784 | 787 | 787 |

Some 15–18 min after the open the 15-minute window starts inside the ramp:
RSS has still risen ≥ 1 % within it, and less than half the hour's growth
lies in it, while the base is the pre-open figure. Fed these minute values,
the real `ProcessState` and `ThresholdBook` give *(repro)*:

```
08:47:00 pm-engine@edumatcher:            rss_growth_pct_1h CRIT 140.547 > 100
08:47:00 pm-api-gwy/monitor@edumatcher:   rss_growth_pct_1h CRIT 710.919 > 100
08:47:00 pm-api-gwy/desk@edumatcher:      rss_growth_pct_1h CRIT 710.933 > 100
08:47:00 pm-api-gwy/dashboards@edumatcher: rss_growth_pct_1h CRIT 650.563 > 100
08:51:00 pm-ralf-gwy@edumatcher:          rss_growth_pct_1h CRIT 1179.782 > 100
08:55:29 … 08:59:29                        … cleared
```

That is the simulation's event log within a minute (minute resolution). A
CRIT is raised at once (no debounce), so each process and the exchange were
DEGRADED for 8–10 min at every open, on a rule meant for leaks. The guide's
claim that a ramp "is not a leak, neither while it happens nor after it has
levelled off" (D3) does not hold for a ramp longer than 15 min's worth of
checks.

A leak grows across the whole hour; a step grows in one part of it. Tested
on the same data and two synthetic leaks *(repro)*, a rule that requires
**each 15-minute quarter of the hour to add at least 10 % of the hour's
growth** (the other conditions unchanged) raises nothing on any of the five
processes above and still catches both leaks:

| Case | Current rule | Quarter rule |
|---|---|---|
| Open fill, 5 processes | 5 × CRIT | none |
| 100 MB + 150 MB/h linear | CRIT at 01:10 | CRIT at 01:10 |
| 300 MB flat 30 min, then +400 MB/h | WARN 01:10, CRIT 01:16 | CRIT 01:21 |

**Fix.** Replace the 15-minute rising and ramp-share checks with the
quarter rule (Q5).

### C3. Four slow messages degrade the engine for a minute *(repro)* — Med

`engine/metrics.py:60-69, 79, 355-389`; `thresholds.py:31-33, 203-210`;
`collector.py:587-595`.

The engine times one message in 16 and reports p99 over the sampled
messages of the last 60 s. At the simulation's rate that is about 390
samples (`engine.handle_samples` 379–410 between 12:05 and 12:10
*(measured)*). Nearest-rank p99 of 390 values is rank 387, i.e. the
**fourth-worst** sample *(repro)*:

```
4 slow of 390 -> p99 = 5800 us
3 slow of 390 -> p99 = 280 us
```

One extra slow message moves the figure twenty-fold. At 12:08 the p50 was
279 µs, GC accounted for none of it (`handle_us_p99_ex_gc` equal to
`handle_us_p99`), host CPU averaged 5.5 % *(measured)*.

The threshold debounce (`RAISE_AFTER = 5` consecutive one-second
evaluations) was written for figures that change every second. A p99 over
60 s holds a burst for up to 60 evaluations, so any burst passes it. Through
the real `ThresholdBook`, a value held for 60 s *(repro)*:

```
t=  4s engine_handle_p99_us WARN 5764.4 > 5000
t= 89s engine_handle_p99_us cleared (1970)
```

The simulation shows the same, 12:08:50 → 12:09:54. The engine was DEGRADED
for a minute because of four messages.

**Fix.** Raise a windowed rule only when its breach outlasts the window
(Q2).

### C4. A late loop makes a process DEGRADED with no trace *(repro)* — Med

`state.py:113-115, 330`.

```python
if breached or self.loop_lag_ms > LOOP_LAG_DEGRADED_MS:
    return "DEGRADED"
```

`loop_lag_ms` is not a threshold rule: `readings()` builds none for it
(`collector.py:551-602`), so it has no breach row, no `THRESHOLD` event,
no log line and no entry in `pm-monitor-cli status`'s breach list. A
`ProcessState` whose beacon carries `loop_lag_ms = 1500` with nothing in
breach evaluates to `DEGRADED` *(repro)*. The transition event (C1) is then
the only trace, and it says nothing. No transition on 2026-11-16 took this
path alone, but the scheduler and the market maker both carry comments about
staying under this line (`scheduler/main.py:195-197`, `mm_bot/bot.py:101`)
because it has fired before (I36, I93).

It is also the one DEGRADED cause the dash-gui bridge's fixed-rule list
(`apps/bridge/src/thresholds.ts:43-44`) does not know, so the Lag chart has
no threshold line.

**Fix.** Make it a fixed rule `loop_lag_ms` (warn 1 000 ms), like
`loop_age_ms`, so DEGRADED means exactly "a rule on this process is in
breach" (Q1).

### C5. One late reading holds a process DEGRADED for 30 s *(repro)* — Low

`collector.py:572-579` (`debounce=False`), `thresholds.py:42-46`.

`loop_age_ms` is raised on the first reading over 1 s and needs 30 lower
readings to clear. One reading of 1 336.6 ms followed by 36 ms *(repro)*:

```
t=  0s loop_age_ms WARN 1336.6 > 1000
t= 30s loop_age_ms cleared (36)
```

That is the pm-stats transition at 14:09:21 → 14:09:52, during a host CPU
breach. A loop that is really stuck is HUNG at 5 s (`hung_after_sec`) on
its own; the warning adds value only for a loop that is late *repeatedly*.
The design accepted the 30 s tail after HUNG (I63); the instant raise was
never argued.

**Fix.** Debounce `loop_age_ms` (and the new `loop_lag_ms`) like the
configurable rules (Q4).

### C6. A breach that stops being judged "clears" with a breaching value *(repro)* — Low

`thresholds.py:130-133, 185-187`.

When a reading stops arriving (a rule declined to judge, a process went
away), `evaluate` steps the track to OK with its last value, and the detail
prints it:

```
t=  0s rss_growth_pct_1h CRIT 1179.791 > 100
t= 34s rss_growth_pct_1h cleared (1179.791)
```

All five RSS clears of 2026-11-16 read like this. "Cleared" next to a value
eleven times the limit looks like a bug to an operator.

**Fix.** Word the no-reading case differently, e.g.
`rss_growth_pct_1h cleared (no longer judged; last 1179.791)`.

### C7. A steady leak clears itself *(repro)* — Low

`state.py:394-418`.

Growth is a percentage of the RSS an hour ago, and that base grows with the
leak. 100 MB + 150 MB/h linear *(repro)*: CRIT at 01:10 (120 %), WARN at
01:35 (80 %), cleared at 02:50 (40 %), while the process still leaks
150 MB every hour. An operator who did not act in the first two hours sees
the alarm go away. This is inherent in a relative rule and not fixed by the
quarter rule.

**Fix.** See Q5: document now; an absolute MB/h band is a separate change.

### C8. A process breach does not show the host contention behind it — Low

`collector.py:609-625`.

At 14:09 `pm-stats` (loop age) and `pm-engine` (p99) breached while
`host_cpu_pct` was CRIT at 97–100 % *(measured)*. The process events do not
mention it, so the reader cannot tell "this process is slow" from "the
machine is saturated". On this host the cause was outside the exchange
(memory `sim-vs-pytest-cpu`: pytest on the same machine).

**Fix.** When a host breach is active, append it to a process's DEGRADED
reason; do not suppress the process breach (Q3).

---

## 4. Performance findings

None. The changes add one dictionary lookup per process per snapshot and a
few `_rss_at` scans of a 62-entry deque per process per second; nothing that
grows with history.

---

## 5. Comments and docstrings

| ID | Where | Problem |
|----|-------|---------|
| D1 | `log_ledger/entries/monitor.yaml:66-77` | "Look at the process's own rows around this time for the cause": the cause is the `threshold … on <same key>` line just before, or (today) nowhere for loop lag (C4). |
| D2 | `web-apps/dash-gui/apps/web/src/lib/help.ts:11` | "DEGRADED: running but a loop is late (see Loop age and Lag)": a threshold breach (RSS growth, engine p99, any "increase" rule) is the more common cause. |
| D3 | `060-health-monitor.md:183` | The `rss_growth_pct_1h` row says a ramp "is not a leak, neither while it happens nor after it has levelled off": false for a ramp of more than about 15 min (C2). |
| D4 | `state.py:97-103` comments; `rss_growth_pct` docstring (`state.py:394-404`) | Describe the 15-minute rising / ramp-share checks as telling a step from a leak; same claim as D3. |
| D5 | `060-health-monitor.md:153, 222` | The DEGRADED row ("or its loop ran more than 1 s late") and the `PROCESS_STATUS` row of the events table (`HEALTHY -> HUNG`) change with WP-MHD01. |
| D6 | `060-health-monitor.md:207-212` | "A breach is raised after five consecutive seconds over a warn level": not true for windowed rules after WP-MHD03, nor for `loop_age_ms` today. |

---

## 6. Verified as correct

- **Ordering of thresholds and judgement.** `snapshot()` evaluates the
  thresholds before judging the processes (`collector.py:618-625`), so a
  transition and its breach land in the same second; today's pairs are 5–30
  ms apart.
- **Clear and transition move together.** Each DEGRADED → HEALTHY of
  2026-11-16 followed its breach's clear by under 20 ms; no process stayed
  DEGRADED without a breach.
- **Silence credit (I108) and start-up grace.** Not involved in any of
  today's transitions; re-read, unchanged.
- **Event detail is not parsed.** The `PROCESS_STATUS` detail is shown, not
  parsed: `sim_forensics` (H1) lists ops events near a failed check verbatim
  (`tests/test_sim_forensics_ops.py:82`), the dash-gui shows the text, and
  `audit/replay/lexicon.py:247` only names the kind. A longer detail (512
  characters max, `collector.py:718`) breaks no reader.
- **Exchange status.** Correctly DEGRADED for every process breach and for
  the host CPU breaches; the snapshot's `thresholds` list already names the
  rule for both.

---

## 7. Decisions

| # | Question | Recommendation |
|---|---|---|
| Q1 | How should the loop-lag path explain itself? (a) make `loop_lag_ms` a fixed threshold rule (warn 1 000 ms), so DEGRADED is exactly "a rule on this process is in breach" and every reason is a breach row; (b) keep the separate check in `evaluate` and add a `reasons` list to `ProcessHealth` (schema change, regenerated models, dash-gui type). | **(a).** One mechanism: the event, the log line, `status` and the dashboard's breach list all cover it with no schema change, and WP-MHD04's debounce applies to it for free. (b) keeps two paths that must be explained separately. The bridge's `FIXED_RULES` and `tests/test_dash_thresholds_mirror.py` gain the rule. |
| Q2 | How should a rule over a 60 s window be debounced? (a) a per-rule raise count longer than the window (90 one-second evaluations for `engine_handle_p99_us`; CRIT still at once); (b) judge p99 only from a minimum sample (≥ 1 000 sampled messages); (c) time more messages in the engine (1 in 4). | **(a).** It filters one burst and still raises on latency that lasts. (b) would never judge p99 at the simulation's ~390 samples per minute, the very rate where the rule matters. (c) costs engine throughput (I28 measured ~1 % for timing every message) and still leaves p99 = the 10th-worst message. |
| Q3 | Concurrent host CPU breach: (a) append `host_cpu_pct CRIT 97.1` to the process's DEGRADED reason; (b) do not judge process latency and loop rules while the host is in breach. | **(a).** Contention is context, not an excuse: a process that is slow because the host is saturated is still slow for its clients. (b) would hide a real fault that happens to coincide with load. |
| Q4 | Debounce `loop_age_ms` / `loop_lag_ms`? (a) yes, `RAISE_AFTER` (5 consecutive seconds, about three late beacons); (b) keep the instant raise. | **(a).** A stuck loop is HUNG at 5 s anyway; the warning's job is repeated lateness. I63 (30 s DEGRADED after HUNG) is unchanged: the warning is already up while the process is HUNG. |
| Q5 | RSS leak rule: (a) quarter rule (each 15 min of the hour adds ≥ 10 % of its growth) replacing the rising / ramp-share checks, and document that a percentage alarm fades on a long-running leak (C7); (b) also add an absolute `rss_growth_mb_1h` band now. | **(a).** It removes every false alarm seen and catches the synthetic leaks (§3 C2). (b) is a new configuration key with no measured default; record it for later if leaks are seen in practice. |

---

## 8. Work packages

### WP-MHD01 — Every DEGRADED names the rule that caused it (C1, C4; after Q1)

**Tests first:**

1. `tests/test_monitor_snapshot.py`: an engine beacon stream whose
   `engine.handle_us_p99` breaches → the `PROCESS_STATUS` event's detail is
   `HEALTHY -> DEGRADED: engine_handle_p99_us WARN <v> > 5000`, and the log
   line carries the same text. (Fails today.)
2. Same file: two rules in breach on one process → both named, in rule
   order, separated by `; `. (Fails today.)
3. `tests/test_monitor_state.py` / `test_monitor_snapshot.py`: a beacon with
   `loop_lag_ms = 1500` → a `THRESHOLD` event `loop_lag_ms WARN 1500 > 1000`
   on the process, a breach row in the snapshot, and the process DEGRADED
   with that reason. (Fails today: no event, no breach.)
4. `loop_lag_ms` credited by a silence (I108) is not judged as late:
   unchanged.
5. HUNG names its figure (`loop_age 6.2 s > 5 s`), SILENT and DEAD name the
   beacon silence (and DEAD "PID gone" on the local host). (Fails today.)
6. DEGRADED → HEALTHY and a first-seen HEALTHY keep their current detail;
   `tests/test_monitor_health.py:380` (`HUNG -> DEGRADED`) is updated to the
   new form deliberately.
7. `tests/test_dash_thresholds_mirror.py`: the bridge's `FIXED_RULES`
   contains `loop_lag_ms` (warn 1000). (Fails today.)

**Change.** `collector.readings()` adds a `loop_lag_ms` reading per live
process (fixed, warn `LOOP_LAG_DEGRADED_MS`, moved to `thresholds.py` next to
`LOOP_AGE_WARN_MS`); `ProcessState.evaluate` drops its own lag check.
`_publish_transitions` appends the subject's active breaches (from
`thresholds.active()`, worded as `Change.detail`) to a DEGRADED transition,
and the deciding figure to HUNG / SILENT / DEAD. Bridge `FIXED_RULES` and its
docstring gain `loop_lag_ms`; the dash-gui Lag chart picks up its threshold
line through `fromRule()`.

**Exit criteria.** Tests 1–7 pass; `tests/test_monitor_*.py`,
`tests/test_dash_thresholds_mirror.py`, `tests/test_sim_forensics_ops.py`
and the dash-gui web/bridge tests green; full suite green.

### WP-MHD02 — Memory filled at the market open is not a leak (C2, C7; after Q5)

**Tests first** (`tests/test_monitor_state.py`):

1. The 2026-11-16 open, as minute RSS fixtures for `pm-ralf-gwy`,
   `pm-engine` and `pm-api-gwy/monitor`, fed every 2 s from 07:00 to 09:30 →
   `rss_growth_pct` is `None` at every second. (Fails today: 140–1180 % from
   08:47.)
2. 100 MB + 150 MB/h linear → growth reported from the first full hour of
   history (≥ 100 % at 01:10). Unchanged.
3. 300 MB flat 30 min, then +400 MB/h → growth reported by 01:21 at the
   latest. (Passes today, earlier; must still pass.)
4. Existing warm-up, 100 MB minimum and restart tests: unchanged.
5. A process whose RSS falls in one quarter (a GC release) and rises in
   the others → `None`.

**Change.** In `rss_growth_pct`, replace the `RSS_RISING_*` and
`RSS_RAMP_MAX_SHARE` checks with: each of the four 15-minute quarters of the
hour adds at least `RSS_QUARTER_MIN_SHARE` (0.1) of the hour's growth. Remove
the constants the change orphans. Comments and docstring (D4) describe the
new rule and C7.

**Exit criteria.** Tests 1–5 pass; `tests/test_monitor_*.py` green. Replaying
the 2026-11-16 minute series of all exchange processes through the rule
(scratch script) raises nothing.

### WP-MHD03 — One burst of slow messages does not degrade the engine (C3; after Q2)

**Tests first** (`tests/test_monitor_thresholds.py`):

1. A reading with a raise count of 90 held over warn for 60 evaluations,
   then under → no change at all. (Fails today: WARN at the 5th.)
2. The same held for 90 evaluations → WARN at the 90th. (Fails today: at
   the 5th.)
3. CRIT on the same rule is raised at once. Unchanged.
4. `tests/test_monitor_snapshot.py`: an engine stream with p99 at 5 764 µs
   for 60 s → no `THRESHOLD` event and the engine stays HEALTHY. (Fails
   today.)

**Change.** `Reading.debounce: bool` becomes `raise_after: int` (default
`RAISE_AFTER`, 1 for the "any increase" rules); `ThresholdBook._step` uses
the reading's count. `readings()` passes `WINDOWED_RAISE_AFTER = 90` for
`engine_handle_p99_us`, with a comment tying it to the engine's
`LATENCY_HORIZON_NS`.

**Exit criteria.** Tests 1–4 pass; `tests/test_monitor_*.py` green.

### WP-MHD04 — One late loop iteration does not degrade a process (C5; after Q4, WP-MHD01)

**Tests first** (`tests/test_monitor_thresholds.py`,
`tests/test_monitor_snapshot.py`):

1. One beacon with `loop_age_ms` 1 336 then normal ones → no event, process
   HEALTHY. (Fails today.)
2. The same for `loop_lag_ms`. (Fails after WP-MHD01 until this WP.)
3. `loop_age_ms` over 1 s for five consecutive seconds → WARN. Unchanged in
   effect.
4. HUNG → recovered passes through DEGRADED while the warning clears (I63).
   Unchanged.

**Change.** The two loop readings use the default raise count.

**Exit criteria.** Tests 1–4 pass; `tests/test_monitor_*.py` green.

### WP-MHD05 — Clears and transitions say what they are based on (C6, C8; after Q3, WP-MHD01)

**Tests first:**

1. `tests/test_monitor_thresholds.py`: a breach whose reading stops →
   detail `rss_growth_pct_1h cleared (no longer judged; last 1179.791)`.
   (Fails today.)
2. A breach whose value falls back → `host_cpu_pct cleared (50)`.
   Unchanged (`test_monitor_thresholds.py:181-185, 238`).
3. `tests/test_monitor_snapshot.py`: a process breach while
   `host_cpu_pct` is CRIT → the DEGRADED detail ends with
   `; host: host_cpu_pct CRIT <v> > 95`. (Fails today.)
4. A process breach with no host breach → no host part. Unchanged.

**Change.** `Change` gets a flag for "no reading" (set in the
`evaluate` loop at `thresholds.py:185-187`) used by `detail`. The
WP-MHD01 reason builder appends active `host` breaches.

**Exit criteria.** Tests 1–4 pass; `tests/test_monitor_*.py` green.

### WP-MHD06 — Ledger, guide and dashboard texts describe the final rules (D1–D6)

**Tests first:** `tests/test_log_ledger.py` and
`tests/test_docs_monitor_config.py` stay green; add a ledger test that the `process %s: %s` explanation mentions the reason
after the colon. (Fails today.)

**Change.**

- D1: ledger `process %s: %s`: the detail names the rule(s); act on the
  rule; `threshold … on <key>` lines give the history.
- D2: dash-gui `help.ts` state text: DEGRADED = a rule on the process is in
  breach (loop age or lag, RSS growth, engine latency, an "increase" rule);
  the event says which.
- D3, D4: the `rss_growth_pct_1h` row and comments describe the quarter rule
  and C7 (a long leak's percentage falls; watch the RSS chart).
- D5: health-model table and events table with the new detail and the
  `loop_lag_ms` row in the threshold table.
- D6: raise counts per rule (5 s, 90 s for `engine_handle_p99_us`, once for
  "any increase").

**Exit criteria.** Texts match the code of WP-MHD01–05; `make _check` and
the full suite green; `mkdocs build` clean.

---

## 9. Out of scope, noted

- **Engine latency sample size.** `engine/metrics.py` times 1 message in 16
  (`SAMPLE_EVERY`), so p99 at classroom and simulation rates rests on a few
  outliers. WP-MHD03 handles it on the monitor side; changing the sampling
  is an engine decision (I28/I31) and is not proposed.
- **Why the engine had four 6–20 ms messages at 12:08** with no GC and an
  idle host was not investigated. If WP-MHD03 is in place, only sustained
  slowness will surface; a recurring pattern belongs to the engine latency
  work (memory `engine-latency-gc`).
- **Exchange status changes have no event.** OPERATIONAL ↔ DEGRADED of the
  exchange is visible only through the process and threshold events that
  cause it. Not a defect today; noted for the dashboard work.
