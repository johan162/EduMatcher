# Engine latency Review — 2026-11 (pre-1.0.0)

**Question:** in the simulation the engine's order-entry latency
(`engine.handle_us_*`) reads p50 ≈ 260 µs but p99 ≈ 2.3 ms. Why is p99 an
order of magnitude above p50, and what can be done?

**Scope:** the engine's order path as timed by `engine.handle_us_*`
(`engine/main.py` receive loop, `engine/metrics.py`), the publish path under
it (`messaging/bus.py`, `engine/drop_copy.py`), and the host the simulation
runs on. The data is the 2026-11-16 simulation run in `~/.edumatcher-sim/data`
(`metrics.db`, `audit/`).

**Previous work:** the 2026-10-25 metrics rework (order entry split from
other topics, 60 s rolling horizon, `handle_us_p99_ex_gc`) and the 2026-11-08
GC policy (`engine/gc_policy.py`: freeze after entering CONTINUOUS, idle-tick
collection). The publish-stack fixes of the Messaging review 2026-11
(WP-MSG01/02: ULID encoding, one trailer frame). They are in place and are
not repeated here.

**Method:** the day's 1-minute aggregates of the `pm-engine` series were read
from `metrics.db`. Fan-out per command was counted from one busy audit file
(`audit-2026-11-16.10.log`, 81 904 order-entry commands): every published
message whose envelope `cause=` names the command. *(measured)* means timed on
this host (Intel Xeon W-2295, 36 threads, Python 3.14, pyzmq 27.3.0, libzmq
4.3.5) with a real `Engine` from `tests/engine_harness.make_engine`, the real
`make_publisher` stack on TCP loopback and a real `DropCopyPublisher`,
calling `_dispatch_pull_message` directly, pinned with `taskset` to one core,
medians over 300–4800 messages. Scratch scripts, not in the repo.

Status: **WP-LAT01 done 2026-11-17, uncommitted.** Test-first; full suite
15 081 passed, 1 skipped (coverage 91.76 %); black, flake8, mypy, pyright and
`make _check` clean; `make test-e2e` 39 passed. **WP-LAT02 done 2026-11-27,
uncommitted** (see its section). **WP-LAT03 done 2026-11-27, uncommitted;
its live check is pending.** WP-LAT04 open.

---

## 1. Overall assessment

There are two independent effects, and they multiply:

1. **p99 and p50 measure different work** (F1). The median order-entry
   command publishes 2 messages; the p99 command publishes 18 (a combo, a
   quote, or an order that sweeps several levels). Every fill costs about
   30–60 µs of engine time, so the 9× spread in fan-out is a 9× spread in
   latency. This is inherent and stays after every fix below.
2. **Every message runs 5–7× slower in the simulation than on a warm core**
   (E1). The host's CPU power management (`intel_pstate` `powersave`, EPP
   `balance_performance`, deep C-states) lets the engine's core clock down or
   sleep in the ~6 ms between messages. Each message then runs on a cold,
   slow core. This explains why the absolute numbers are high; it is not the
   engine code.

GC is **not** a factor: `handle_us_p99_ex_gc` equals `handle_us_p99` all
day, and `engine.gc_collections` stays flat after the freeze. Load is not a
factor either: 150–330 msg/s, `engine.busy_pct` 11–23 %, no queueing.

On the code side, two per-message costs on the publish path were worth
removing: pyzmq's flag arithmetic (P1, fixed in WP-LAT01) and the drop-copy
publication per fill (P2).

## 2. Summary of findings

| ID | Finding | Severity | WP |
|----|---------|----------|----|
| F1 | p99/p50 ≈ fan-out ratio of order-entry commands | Info | WP-LAT04 (presentation) |
| E1 | Host CPU power management makes every message 5–7× slower | High | WP-LAT03 (ops docs) ✅ |
| P1 | pyzmq `send_multipart` ORs an `IntFlag` per frame | Med | WP-LAT01 ✅ |
| P2 | Drop copy adds ~23 µs per fill on the order path | Med | WP-LAT02 ✅ |

## 3. The sim data

Hourly means of the 1-minute aggregates, 2026-11-16 (UTC), market open
08–15:

| Hour | p50 µs | p99 µs | p99 ex GC µs | max µs | busy % | msgs/min | samples/min |
|------|-------:|-------:|-------------:|-------:|-------:|---------:|------------:|
| 08 | 251 | 1287 | 1287 | 4421 | 18.6 | 19 675 | 516 |
| 09 | 237 | 2234 | 2234 | 8902 | 18.2 | 14 466 | 841 |
| 10 | 258 | 2307 | 2307 | 8180 | 14.4 | 9 633 | 527 |
| 11 | 268 | 2218 | 2218 | 5862 | 11.4 | 7 614 | 391 |
| 12 | 274 | 2396 | 2396 | 8079 | 12.6 | 8 280 | 434 |
| 13 | 269 | 2431 | 2431 | 11 614 | 17.3 | 11 702 | 659 |
| 14 | 243 | 2435 | 2435 | 10 177 | 23.3 | 18 113 | 979 |

With 400–1000 sampled order messages per 60 s window, p99 rests on 4–10
samples per window: noisy minute to minute, but the hourly level is real.
Book sizes are small (300 symbols, ~23 resting orders per book, 103
participants connected).

`proc.cpu_pct` for the engine was 18–38 % at ~160 msg/s: about 1.4 ms of
real CPU per inbound message including maintenance. The time is spent on the
CPU, not lost to preemption.

## 4. Findings

### F1. p99/p50 is the fan-out ratio *(measured)* — Info

`handle_us` is the time to handle one order-entry message to completion,
including everything it publishes (`engine/main.py`, receive loop,
`record_dispatch`). Book snapshots are not in it: `_flush_snapshots` runs in
maintenance.

Messages published per command (audit, `cause=` the command):

| Command | share | p50 | p90 | p99 | max |
|---------|------:|----:|----:|----:|----:|
| `order.new` | 66 % | 2 | 6 | 12 | 33 |
| `order.cancel` | 20 % | 1 | 1 | 1 | 1 |
| `quote.new` | 3.5 % | 10 | 18 | 25 | 30 |
| `order.amend` | 2.9 % | 2 | 2 | 6 | 10 |
| `order.oco` | 2.6 % | 5 | 5 | 5 | 10 |
| `order.oco_cancel` | 2.4 % | 3 | 3 | 3 | 3 |
| `order.combo` | 2.3 % | 13 | 25 | 33 | 40 |
| **all** | | **2** | **6** | **18** | |

The top 1 % by bytes average 8.4 `order.fill`, 5.9 `trade.executed`, 3.3
`engine.trace`, 2.5 `order.ack` and 1.2 `combo.status` each. The bottom
half average under 2 messages: an ack, a trace, a cancel.

Cost by outcome, warm core, real publish stack and drop copy, before WP-LAT01:

| Command | median µs |
|---------|----------:|
| cancel | 27 |
| resting order | 42 |
| sweep 1 level | 118 |
| sweep 2 levels | 177 |
| sweep 4 levels | 290 |
| sweep 8 levels | 498 |

About 60 µs per fill: `order.fill` ×2, `trade.executed`, a trace, position
updates and two drop-copy events (P2). 300 symbols and 100 gateways cost the
same as 1 symbol and 3 gateways (47 vs 44 µs resting, 191 vs 183 µs sweep 4).

**Consequence.** A p99 of ~9× p50 is what this mix produces on any machine.
p50 tracks "a cancel or a resting order", p99 tracks "a combo, a quote or a
multi-level sweep". The ratio only says whether the mix changed, not whether
the engine got slower.

**Fix.** None to the engine. WP-LAT04 (optional) makes the dashboard figure
say what it measures.

### E1. A cold CPU makes every message 5–7× slower *(measured)* — High

Host settings: `scaling_driver` `intel_pstate`, `scaling_governor`
`powersave`, `energy_performance_preference` `balance_performance`, deep
C-states enabled (`intel_idle`). Range 1.2–4.8 GHz.

At ~160 msg/s the engine blocks in `poller.poll()` for ~6 ms between
messages. Its core drops to a lower P-state or a deep C-state (C6 also flushes
L1/L2), and the next message runs on a cold, slow core.

Reproduced with the same engine, 300 symbols, 100 gateways, varying only the
gap between messages:

| Gap between messages | resting | cancel | sweep 4 |
|----------------------|--------:|-------:|--------:|
| none (back to back) | 47 µs | 24 µs | 192 µs |
| 1 ms `sleep` | 254 µs | 233 µs | 1008 µs |
| 6 ms `sleep` | 372 µs | 234 µs | 1032 µs |
| 20 ms `sleep` | 373 µs | 240 µs | 1038 µs |
| 1 ms busy-spin | 60 µs | 33 µs | 209 µs |

With a sleep the figures match the sim's (p50 ≈ 260 µs, sweeps and combos at
1–2.5 ms). Spinning through the same gap keeps the core awake and restores
the warm figures, so the multiplier is the core's power state, not the engine
code or the gap itself. The effect saturates by ~6 ms: a quieter market does
not make it worse.

Running pytest `-n logical` on the same host (see the 2026-11-08 sim CPU
note) adds cache pollution and migrations on top, but is not needed to
reproduce the effect.

**Fix.** Host configuration, no code (WP-LAT03):

- `sudo tuned-adm profile latency-performance`: `performance` governor and
  EPP, and holds `/dev/cpu_dma_latency` low so cores stay out of deep
  C-states. Expected: p50 ≈ 40–60 µs, p99 ≈ 300–500 µs. Costs idle power.
- Give pm-engine a core of its own and keep test runs off it (`taskset`).
  There is no engine container: the whole exchange is one container, so
  pin the process (`taskset -a -cp`), not the container. See WP-LAT03.
- If the host cannot be tuned: busy-poll in the engine loop (Q2).

### P1. pyzmq `send_multipart` ORs an `IntFlag` per frame *(measured)* — Med

pyzmq 27.3 `Socket.send_multipart` (`zmq/sugar/socket.py:715`) sends every
frame but the last with `zmq.SNDMORE | flags`. `zmq.SNDMORE` is an `IntFlag`;
on Python 3.14 the OR goes through `enum.Flag.__or__`, which costs more than
the send. It also type-checks every frame in Python before sending. In the
engine profile (resting orders plus 8-level sweeps), `enum.Flag.__or__` and
its helpers were 15 % of all time.

| Per message, pinned | µs |
|---------------------|---:|
| raw PUB `send_multipart`, 3 frames | 3.8 |
| raw PUB per-frame `send(frame, int_flag)`, 3 frames | 1.3 |
| `make_publisher` stack, before | 6.9 |
| `make_publisher` stack, after WP-LAT01 | 4.0 |
| `DropCopyPublisher.publish_fill`, before | 7.3 |
| `DropCopyPublisher.publish_fill`, after WP-LAT01 | 5.8 |

Every message the engine publishes pays this: the main PUB (`make_publisher`)
and the drop-copy PUB (`DropCopyPublisher`, a raw `zmq.Socket`). Gateways pay
it once per request on PUSH (`make_pusher`).

**Fix.** WP-LAT01.

### P2. Drop copy adds ~23 µs per fill on the order path *(measured)* — Med

`engine/main.py` `_publish_trade` → `DropCopyPublisher.publish_fill`, twice
per trade (one per counterparty).

Engine with the real publish stack, without and with a `DropCopyPublisher`,
before WP-LAT01:

| Command | no drop copy | drop copy | per fill |
|---------|------------:|----------:|---------:|
| sweep 4 | 196 µs | 290 µs | +23 µs |
| sweep 8 | 320 µs | 498 µs | +22 µs |

Measured in isolation, one `publish_fill` was 7.3 µs. The parts:

- `make_drop_copy_event`, the **validating** builder: 3.1 µs. It builds the
  generated dataclass from a dict and runs `validate()`. Its sibling
  `make_drop_copy_event_unchecked` produces identical frames in about a
  third of the time (3.34 vs 1.16 µs, pinned). The engine's other per-fill builders already use the `_unchecked`
  variants (`make_order_fill_unchecked`, `make_trade_executed_unchecked`).
- `send_multipart`: 3.6 µs, of which WP-LAT01 removes about 1.5.
- A `DropCopyMessage` dataclass for the replay deque, and `now_ns()`.

The in-engine cost (~11 µs per message) is above the isolated cost, as for
every other publish on the order path: cache and branch-predictor pressure
from the surrounding fill handling.

**Fix.** WP-LAT02.

## 5. Verified as correct

- **The latency metric times what it says.** `record_dispatch` wraps
  `_dispatch_pull_message` only; the receive, decode, command echo and
  maintenance are outside it. Order-entry topics are separated from other
  topics (`_ORDER_ENTRY_TOPICS`). Sampling is 1 in 16 plus one forced order
  sample per beacon window.
- **The GC policy works.** `gc_collections` rose by ~15 000 per hour before
  the open and by 2–27 per hour during continuous trading. Pauses up to
  25 ms still occur (`gc_pause_us_max`), but none landed in a sampled
  order dispatch: `handle_us_p99_ex_gc` equals `handle_us_p99` in every hour.
- **Book size and symbol count do not drive per-message cost** (F1 table).

## 6. Decisions

- **Q1. Change pyzmq's behaviour by subclassing `zmq.Socket`, or inside
  `SequencedPublisher`?** Subclass (`BusSocket`), created through
  `socket_class=`. The wrappers, the `SendsMultipart` protocol and every test
  recorder stay as they are; the drop-copy socket and PUSH get the fix too.
  *Taken.*
- **Q2. Busy-poll in the engine loop?** Spin on a non-blocking `poll(0)` for
  a configurable time (e.g. 200 µs–2 ms) before falling back to the blocking
  poll. It keeps the core warm regardless of host settings, at the price of
  one core at 100 %. Not recommended while the host can be tuned (E1).
  *Open; not planned.*
- **Q3. Present latency differently?** See WP-LAT04. *Open.*

## 7. Work packages

### WP-LAT01 — Bus sockets send multipart without enum arithmetic (P1) ✅

**Tests first** (`tests/test_messaging_bus.py::TestSendDoesNoFlagArithmetic`):
count calls to pyzmq's `Flag.__or__` (patched on `type(zmq.SNDMORE)`, since
`enum` copies `__or__` into each Flag subclass) while publishing through
`make_publisher` over `inproc`, pushing through `make_pusher` with
`zmq.NOBLOCK`, and calling `DropCopyPublisher.publish_fill`. Assert zero
calls, and that frames and envelope arrive intact. Failed before the change
with 2, 2 and 1 calls.

**Change.** `messaging/bus.py`: `BusSocket(zmq.Socket[bytes])` overrides
`send_multipart` to send frame by frame with `int(flags) | int(zmq.SNDMORE)`.
`make_publisher` and `make_pusher` create their sockets with
`socket_class=BusSocket`; so does `DropCopyPublisher`. The wire is unchanged.

**Result (measured, pinned):** `make_publisher` stack 6.9 → 4.0 µs per
publish; `publish_fill` 7.3 → 5.8 µs. Engine, warm core, real publish stack
and drop copy:

| Command | before | after |
|---------|-------:|------:|
| cancel | 27 µs | 24 µs |
| resting order | 42 µs | 36 µs |
| sweep 4 | 290 µs | 243 µs |
| sweep 8 | 498 µs | 411 µs |

12–18 % off the order path. On a cold core (E1) the saving scales with the
multiplier.

Three existing tests pinned the old `context.socket(kind)` call: the fake
contexts in `tests/test_drop_copy.py` and `tests/test_alf_gwy_gateway_unit.py`
now accept keyword arguments, and `tests/test_engine_final_gaps.py` asserts
`socket_class=BusSocket`.

Status: done 2026-11-17, uncommitted. Verified as in the status line at the
top.

### WP-LAT02 — Drop copy uses the unchecked builder (P2) ✅

**Tests first:** a cost test in the style of WP-LAT01 asserting that
`publish_fill` does not call the validating `make_drop_copy_event` (or
`validate()`); a wire test that the published frames are byte-identical to
`make_drop_copy_event`'s for the same arguments, including `trade_ids` and a
float price.

**Change.** `publish_fill` calls `make_drop_copy_event_unchecked`. Leave
`replay` on the validating builder (off the order path). Consider building
the frames once and keeping them, rather than a `DropCopyMessage`, if replay
can be served from them; measure first.

**Target:** `publish_fill` ≤ 4 µs pinned (5.8 after WP-LAT01).

**Done.** Tests in `tests/test_drop_copy.py::TestPublish`:
`test_fill_publication_does_not_validate` patches the validating builder and
`DropCopyEvent.validate` to fail (failed before the change);
`test_fill_frames_match_the_validating_builder_after_coercion` checks
byte-identical frames for an int price (goes out as `150.0`) and two
`trade_ids`. The existing deep-copy test already covered a float price.

`publish_fill` now calls `make_drop_copy_event_unchecked`; `replay` keeps
`make_drop_copy_replay`. The `DropCopyMessage` buffer stays: replay frames
carry a different topic (`drop_copy.replay.{recipient_id}`) and an extra
`recipient_id` field, so stored event frames could not serve replay without
re-encoding. Not worth measuring further.

**Result (measured, pinned, 3 runs × 15 × 2000 calls, medians):**
`publish_fill` 6.6–7.2 → 4.0–4.1 µs. Today's "before" is above the 5.8 µs
recorded after WP-LAT01 (the sim was running on the host), so the saving,
≈2.7 µs per fill and ≈5.4 µs per trade, is the figure to trust. The target
is met within noise. What remains is the send (~2.3 µs), `now_ns()` and the
`DropCopyMessage`.

Verified: full suite 15 619 passed, 1 skipped (coverage 91.89 %); black,
flake8, mypy, pyright and `make _check` clean. `make test-e2e`: 6 passed,
32 skipped (the sim held the exchange ports), 1 failed:
`tests/test_clearing_gui_e2e.py::test_admin_journey` fails identically with
this change stashed (timeout waiting for the 'Participants' table, page shows
only "MarketSim"; `FakeEngine` lacks `request_session`). Not caused by this
WP; rerun e2e with the sim stopped.

### WP-LAT03 — Operator guide: host tuning for latency (E1) ✅

Add a section to the operator guide (run part, near the health monitor
chapter) that explains why `engine.handle_us_*` reads 5–7× higher on a host
in `powersave`, how to check (`scaling_governor`,
`energy_performance_preference`), and the two fixes: `tuned-adm profile
latency-performance` (or `cpupower frequency-set -g performance` plus a
C-state limit) and a dedicated core for pm-engine (`--cpuset-cpus`). State the
power cost. No code.

**Check:** next sim run with the profile set; record p50/p99 here.

**Done.** New section *Engine latency and the host's CPU* in
`operator-guide/part-6-observe-and-recover/070-operator-dashboard.md`,
directly after *Reading engine latency* (the dashboard chapter is where an
operator reads these figures), plus a troubleshooting row linking to it. It
explains the fan-out ratio (F1) in one paragraph, because an operator who
sees p99 ≈ 10× p50 asks that first. Then come the cold-core effect, the
check, `tuned-adm` with undo, `cpupower` with undo, the power cost, and
pinning.

Corrected against the plan: `--cpuset-cpus` on "the engine container" does
not exist, because the whole exchange is one container. A cpuset there would
confine every `pm-*` process. The guide pins the engine process with
`taskset -a -cp` (all threads) and says the pinning is lost whenever
`pm-engine` starts again.

Verified on this host (Fedora 44, tuned 2.28.0) without changing its
settings: the sysfs files and their values (`intel_pstate`, `powersave`,
`balance_performance`, `intel_idle`); `tuned-adm active` and the
`latency-performance` profile (it sets `governor=performance`,
`energy_perf_bias=performance` and `force_latency=cstate.id_no_zero:1`,
which allows C1 only); `cpupower idle-set -D`/`-E` syntax, and that `-D 10`
leaves POLL and C1 (latencies 0 and 2 µs) and disables C1E (10) and C6
(133); `pm-opctl-cli list` shows the engine PID inside the container; and
`podman exec … taskset -a -cp 3 <pid>` works in the running container
(tried on a throwaway `sleep`). `mkdocs build --strict` is clean with the
three anchors present, and `make pdf-operator-guide` builds with no new
missing glyphs.

Not done: the live check. It needs `sudo tuned-adm profile
latency-performance` on the sim host, then a sim day; record p50/p99 here.


### WP-LAT04 — Optional: a latency figure that tracks the engine, not the mix (F1)

Options, to be decided (Q3):

- (a) Publish `engine.handle_us_p99` per command class (`new`, `cancel`,
  `quote`, `combo`), labelled like the per-symbol series.
- (b) Publish dispatch time per published message (µs per output message),
  which is flat across the mix and moves only if the engine gets slower.

Either way, pm-dash's "Engine latency" row would show it beside today's p50/p99.

## 8. Out of scope, noted

- pyzmq `recv_multipart` calls `getsockopt(zmq.RCVMORE)` per frame; on the
  engine's PULL that is ~1 µs per command. Not measured further.
- `engine.trace` messages: 0.6–3.3 per command. Each is a full publish.
  Whether every trace needs to go out on the order path is a design question,
  not a latency bug.
