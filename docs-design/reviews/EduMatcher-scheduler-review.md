# EduMatcher Session Scheduler — Code Review

**Scope:** `src/edumatcher/scheduler/` (`main.py`; `__init__.py` is empty) plus the contracts it depends on (`models/session.py`, `models/message.py::make_session_transition_msg`, `messaging/bus.py::make_pusher`, `config.py::ENGINE_PULL_ADDR`/`ENGINE_CONFIG_FILE`) and the engine consumer (`engine/main.py::_handle_session_transition`).
**Review bar:** Educational-but-correct, matching the engine review. Correctness defects and any crash/hang on plausible input are must-fix; operational and clarity gaps are noted where they teach something.
**Reviewer note:** Findings carry IDs for tracking (C = critical, H = high, M = medium, L = low, A = architecture). Line references are to the working tree at review time.

---

## 1. Executive summary

The scheduler is a small, single-threaded, fire-and-forget process: it loads a five-entry schedule (from the `schedule:` block of the engine config YAML, or a hardcoded default), then PUSHes `session.transition` messages to the engine at wall-clock times. `--now` mode rapid-fires the full sequence for testing. The code is readable, the SIGINT/SIGTERM handling with fine-grained sleep is a nice touch, and the config-missing fallback paths are sensible.

Because it is single-threaded and does not share state, there are **no concurrency or race conditions** — the "interaction with the engine free of race conditions" criterion is satisfied trivially. The real weaknesses are elsewhere and stem from one conceptual gap: **the engine session lifecycle is a *sequential, dependent* state machine (`CLOSED → PRE_OPEN → OPENING_AUCTION → CONTINUOUS → CLOSING_AUCTION → CLOSED`), but the scheduler treats each entry as an *independent* absolute-time event.** That mismatch produces the highest-severity findings: skipping past-due transitions silently desyncs the engine (H1), and the scheduler cannot recover or report that the engine rejected anything (M3).

There are also two robustness gaps that violate the "no crashing or hanging" bar: a blocking PUSH send with infinite linger can hang the process when the engine is not consuming (H2), and a plausible unquoted `HH:MM` config value is parsed by PyYAML as a base-60 integer and crashes the scheduler with an unhandled traceback (H3).

| Severity | Count | Theme |
|---|---|---|
| Critical | 0 | — |
| High | 3 | Sequential-state desync on skip; blocking-send/linger hang; malformed-time crash |
| Medium | 3 | No schedule validation; one-shot (no day rollover); fire-and-forget with misleading success |
| Low | 7 | DST/naive-time, duplication, `print` logging, ignored `--delay`, connect heuristic, negative-sleep micro-race, unguarded send |
| Architecture | 3 | Shared run-loop helper; confirmed transitions + startup state recovery; shared schedule validation |

---

## 2. Critical findings

None. No defect corrupts state or is unconditionally destructive; the scheduler's blast radius is limited to "engine session state is wrong/absent," which the engine itself defends against by validating transitions.

---

## 3. High-severity findings

### H1 — Skipping past-due transitions silently desyncs the engine

- **Where:** `main.py:_run_scheduled` — `if target < now: print("… already past, skipping"); continue`.
- **What:** Each schedule entry is evaluated against absolute wall-clock time and skipped if already past. But engine transitions are *sequential and dependent* (`VALID_TRANSITIONS` in `models/session.py`): `CLOSED` only accepts `PRE_OPEN`, `PRE_OPEN` only accepts `OPENING_AUCTION`/`CONTINUOUS`, etc. If the scheduler starts (or restarts after a crash) mid-day — say 10:00 — it skips `PRE_OPEN`, `OPENING_AUCTION`, and `CONTINUOUS`, and the *first message it actually sends* is `CLOSING_AUCTION` at 16:00. The engine, still in `CLOSED`, sees `CLOSED → CLOSING_AUCTION`, which is not in `VALID_TRANSITIONS[CLOSED]`, logs a warning, and ignores it (`engine/main.py:2664`). The subsequent `CLOSED` (16:05) is likewise rejected.
- **Impact:** Starting the scheduler late — the exact scenario in a restart/recovery — leaves the engine **stuck in whatever state it was in, all day**, with only a silent engine-side log line. Meanwhile the scheduler prints "All transitions sent. Done." (see M3), so an operator believes the day was driven correctly. For the component whose sole job is driving the session timeline, this is the most important correctness gap.
- **Fix:** Before waiting on future entries, compute the *most recent past* transition and fast-forward the engine into the correct current state by replaying the necessary intermediate transitions in order (respecting `VALID_TRANSITIONS`). Better, recover the engine's actual current state first (see A2) and only send the transitions needed to reach the correct "now" state, then resume the timed schedule. At minimum, warn loudly that skipping intermediate states will desync the engine.

### H2 — Blocking PUSH send with infinite linger can hang the scheduler

- **Where:** `main.py:main` (`push_sock = make_pusher(ENGINE_PULL_ADDR)`), the `send_multipart` calls in `_run_scheduled`/`_run_now`, and `finally: push_sock.close()`. `make_pusher` (`bus.py`) creates a default `zmq.PUSH` socket (no `SNDTIMEO`, default `LINGER = -1`).
- **What:** A `zmq.PUSH` socket with **no connected peer** blocks on `send` until a peer appears — it does not buffer against zero pipes. So if the engine is not up when a scheduled time fires, `send_multipart` blocks indefinitely. Separately, because `LINGER` defaults to `-1` (infinite), `push_sock.close()` in the `finally` block blocks forever if any queued message was never delivered (e.g., the engine died after connecting). Signal-based interruption of a blocking ØMQ C call is not guaranteed, so the `running=False` flag may not free a send that is already blocked.
- **Impact:** The process can hang — on a scheduled send when the engine is absent, or on shutdown when messages are undelivered — violating the "without … hanging" bar. This mirrors the ALF gateway's C1 root cause (blocking engine send), though the scheduler's low message volume makes it less likely under a healthy engine.
- **Fix:** Set a bounded `SNDTIMEO` and a finite `LINGER` (e.g., a few hundred ms) on the push socket; treat a send timeout as a logged warning rather than a block. Optionally set `ZMQ_IMMEDIATE`/`CONNECT_TIMEOUT` semantics so an absent engine fails fast instead of hanging.

### H3 — Unquoted `HH:MM` config values are parsed as base-60 integers and crash the scheduler

- **Where:** `main.py:_load_schedule` (`t = sched.get(key)`, appended as `str(t)`) → `main.py:_time_today` (`h, m = hhmm.split(":")`, `int(h)`, `int(m)`, `now.replace(hour=..., minute=...)`).
- **What:** `_time_today` is unguarded and runs *inside* the `_run_scheduled` loop, outside the try/except that only wraps YAML *loading*. Several plausible inputs crash it with an unhandled traceback:
  - **PyYAML sexagesimal:** PyYAML (YAML 1.1) parses an unquoted `pre_open: 09:00` as the integer `540` (9×60). `str(540)` → `"540"`, and `"540".split(":")` → `["540"]`, which fails the two-tuple unpack → `ValueError`. The project's own sample config documents the unquoted form (`engine_config.sample.yaml:433`, `pre_open: 09:00`), so this is an easy footgun for anyone enabling `sessions_enabled` and copying that shape.
  - **Out-of-range / malformed:** `"25:00"` → `now.replace(hour=25)` raises `ValueError` ("hour must be in 0..23"); `"16:5:00"` → too many values to unpack.
- **Impact:** A valid-looking configuration crashes the scheduler on startup rather than degrading gracefully. Given H1's silent-skip behavior and this crash-on-parse behavior, the schedule-loading path is the least robust part of a component meant to run unattended.
- **Fix:** Validate and normalize each schedule time when loading (regex `^([01]?\d|2[0-3]):[0-5]\d$`, or `datetime.strptime(str(t), "%H:%M")`), reject with a clear error, and document that times must be quoted strings. Wrap `_time_today` parsing so a bad entry is skipped-with-warning, not fatal. This pairs with a shared validator (A3).

---

## 4. Medium-severity findings

**M1 — No validation that the schedule is complete, ordered, or forms a valid transition chain.** `_load_schedule` builds entries in a fixed `mapping` order and returns whatever subset is present; nothing checks that times are chronologically increasing or that the resulting sequence is a legal path through `VALID_TRANSITIONS`. A partial schedule (e.g., only `continuous_start`) sends `CONTINUOUS` first, which the engine rejects from `CLOSED`; an out-of-order schedule produces "already past, skipping" for entries that come chronologically before an earlier-listed one. All failures are silent on the scheduler side. Validate the chain and monotonic ordering at load time and refuse to start on an invalid schedule.

**M2 — One-shot process; no day rollover.** All times are computed for *today* (`_time_today` uses `datetime.now().replace(...)`). If the scheduler starts after the last entry, every entry is "already past," the loop finishes immediately, and it exits — never driving the engine. There is no logic to roll to the next trading day or to loop day-over-day, despite the module docstring framing it as the driver of "daily trading phases." Either document it as a strictly same-day, start-before-market tool, or add next-day scheduling.

**M3 — Fire-and-forget with misleading success reporting.** PUSH/PULL gives no delivery or acceptance feedback, yet the scheduler prints "→ Sending transition to X" and "All transitions sent. Done." regardless of whether the engine accepted (or even received) anything. Combined with H1/M1, an operator gets a green light while the engine sat idle. Subscribe to the engine's `session.state` broadcasts (published at `engine/main.py:2709`) to confirm each transition actually applied, and report the confirmed state — not just "sent."

---

## 5. Low-severity findings

**L1 — Naive local-time arithmetic ignores DST.** `_time_today` builds naive local `datetime`s and `(target - now).total_seconds()` computes a duration across a naive local timeline. On DST-transition days the wait can be off by an hour. Acceptable for a teaching system, but note it (or use a timezone-aware clock).

**L2 — Duplicated run-loop scaffolding.** `_run_scheduled` and `_run_now` each re-implement the same `running` flag, `_stop` handler, `signal.signal(...)` registration, and interruptible `while running and monotonic < deadline: sleep(min(1.0, …))` loop. Extract a shared helper (A1).

**L3 — `print()` for all logging.** The scheduler prints to stdout/stderr while the rest of the codebase (engine, persistence) uses the `logging` module. Standardize on `logging` for consistent formatting, levels, and capture.

**L4 — `--delay` is silently ignored outside `--now`.** `now_mode_delay = args.delay` is only used by `_run_now`; passing `--delay` in scheduled mode has no effect and no warning. Minor CLI surprise.

**L5 — `time.sleep(0.1)` "let socket connect" heuristic.** For PUSH/PULL this is unnecessary for delivery (messages queue once a peer connects) and is a heuristic, not a guarantee. Harmless, but worth a comment or removal; real connect-readiness should be handled via socket options (see H2).

**L6 — Theoretical negative-sleep race.** The loop guards with `while … time.monotonic() < deadline` before computing `min(1.0, deadline - time.monotonic())`. Time advances between the two calls, so the argument could become a tiny negative and `time.sleep()` would raise `ValueError`. Effectively impossible in practice, but clamping with `max(0.0, …)` removes the sharp edge.

**L7 — `send_multipart` exceptions are unguarded.** A ØMQ error (context terminated, `ETERM`) propagates as an unhandled traceback. Low impact given the process is exiting anyway, but a logged, clean exit would be tidier.

---

## 6. Performance review

Not applicable in any meaningful sense: the scheduler sends at most five messages per day and otherwise sleeps. The only performance-adjacent note is L5 (the fixed 0.1 s connect sleep), which is negligible. No hot path, no allocation concerns.

---

## 7. Data-structure assessment

Not applicable. The schedule is a flat `list[tuple[str, str]]`, which is the right shape. The only structural suggestion is semantic, not representational: model the schedule as an ordered sequence of *transitions between known states* (so validity against `VALID_TRANSITIONS` can be checked) rather than as independent time→state pairs (see H1/M1/A3).

---

## 8. Architecture and organization

**A1 — Extract a shared interruptible-run helper.** A single `run_transitions(push, items, wait_fn)` (or a small `_sleep_until(deadline, running_flag)` plus shared signal setup) removes the L2 duplication and makes both modes exercise one tested code path.

**A2 — Confirm transitions and recover current state on startup.** The scheduler should open a SUB on the engine `session.state` topic (or use the request/reply session-state API already present — `make_session_state_request_msg` exists in `models/message.py`) to (a) learn the engine's actual current state at startup, enabling the H1 fast-forward correctly, and (b) verify each transition applied, enabling honest reporting (M3). This turns a blind emitter into a closed-loop driver.

**A3 — Share schedule validation with the config verifier.** H3/M1 both stem from unvalidated schedule input. A single `validate_schedule(raw) -> list[(time, SessionState)]` — enforcing quoted `HH:MM`, chronological order, and a legal `VALID_TRANSITIONS` path — should live alongside the other config validators (`cverifier`/`config_gen`) and be used both there and here, so a bad schedule is caught before either process starts.

---

## 9. Domain notes (educational bar, brief)

- **Sessions must start from `CLOSED`.** The default schedule and `--now` sequence only work if the engine boots `CLOSED` (which `sessions_enabled: true` arranges). Worth stating explicitly near the schedule docs so students don't run `--now` against an already-`CONTINUOUS` engine and see silent no-ops.
- **`--now` against a non-`CLOSED` engine is a silent no-op** for every message after the first invalid transition — a good teaching example of why fire-and-forget transports need confirmation (A2).
- **Two ways in, one behavior:** `session.transition` can also be driven by the API gateway and the ops CLI (`api_gateway/engine_client.py`, `commands/client.py`). Documenting that the scheduler is just one producer on a shared topic clarifies the "who owns session state" question.

---

## 10. Testing and verification recommendations

Each High/Medium finding should land with a regression test:

1. **H1 fast-forward:** start the scheduler with a schedule whose first N entries are in the past; assert it emits the correct catch-up transitions in `VALID_TRANSITIONS` order (or, with A2, drives the engine to the correct current state) rather than skipping to a rejected transition.
2. **H3 config parsing:** feed unquoted `09:00` (→ int 540), `"25:00"`, and `"16:5:00"`; assert a clean validation error at load, no traceback, and no partial run.
3. **M1 chain validation:** partial and out-of-order schedules are rejected at load with a clear message.
4. **M3 confirmation:** with a stub engine that rejects a transition, assert the scheduler reports the rejection rather than "Done."
5. **H2 no-hang:** with no engine listening, assert `send`/`close` return within the configured timeout rather than blocking (inject `SNDTIMEO`/`LINGER`).
6. **Interrupt path:** SIGINT during a wait exits promptly and closes the socket without hanging.

The existing `tests/test_messages.py::TestSessionMessages` already covers the message shape; the gaps above are all in the scheduling/lifecycle logic, which currently has little direct coverage.

---

## 11. Suggested remediation order

| Phase | Items | Rationale |
|---|---|---|
| 1 — Stop crashes/hangs | H3 (validate/guard time parsing), H2 (`SNDTIMEO` + finite `LINGER`) | Small, surgical; each removes an unattended crash/hang |
| 2 — Fix the core semantics | H1 (catch-up/fast-forward), A2 (state recovery + confirmation), M3 | Makes the scheduler actually reliable across restarts and reports truthfully |
| 3 — Validation & robustness | M1, A3 (shared schedule validator), M2 (day-rollover decision) | Reject bad schedules early; decide same-day vs. multi-day explicitly |
| 4 — Hygiene | A1 (dedupe run loop), L1–L7 | Structure, logging, and edge polish once behavior is correct |

---

*End of review. The scheduler is small and largely correct in the happy path; the findings concentrate on (a) treating a sequential state machine as independent timed events and (b) two input/transport paths that can crash or hang unattended.*
