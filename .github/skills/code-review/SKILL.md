# Code Review Skill

## Purpose

Perform a structured, multi-pass code review of one or more Python source files.
Covers correctness, concurrency, style, structure, and static-tool cleanliness.

---

## When to Use

- When asked to "review" a file, a module, or a PR diff
- Before merging a feature branch
- When a file has grown large and may need splitting
- After a refactor, to check for latent issues introduced by the change
- When tests are failing and the cause is unclear

---

## Procedure

### Step 1 — Scope

Ask (or infer from context) which files to review. If no files are specified,
review all files touched in the most recent commit:

```bash
git diff --name-only HEAD~1 HEAD
```

### Step 2 — Static tools (must all be clean before the review proceeds)

Run the full tool chain on the target files and fix or clearly report every
failure before moving to the manual review passes:

```bash
poetry run black --check <file(s)>
poetry run flake8 <file(s)>
poetry run mypy <file(s)>
poetry run pyright <file(s)>
poetry run pytest -x -q
```

If any tool fails, report the failures and offer to fix them first.

### Step 3 — Logic and correctness

- Off-by-one errors, inverted conditions, wrong operator precedence
- Silent failures — bare `except`, swallowed exceptions, unchecked return values
- State corruption — mutable shared structures mutated without copy/deepcopy
- Incorrect defaults — mutable default arguments (`def f(x=[])`)
- Type mismatches — runtime types that diverge from annotations at call sites
- Missing edge-case handling — empty collections, `None` inputs, zero quantities

### Step 4 — Concurrency and resource safety

- Race conditions — shared state accessed from threads or ZMQ callbacks without
  locks or ownership discipline
- TOCTOU gaps — check-then-act patterns (`if exists: open`) that can fail between
  the check and the action
- Resource leaks — sockets, files, or DB connections not closed on every exit path
  (including exceptions)
- Signal-handler safety — complex logic (I/O, lock acquisition) called directly
  from a signal handler instead of setting a flag

### Step 5 — Code quality and structure

- **File size**: flag any file over ~500 lines as a split candidate; flag any file
  over ~800 lines as requiring a split with a concrete module proposal
- **Function length**: flag functions over ~60 lines
- **Dead code**: unreachable branches, unused imports, variables written but never
  read
- **Magic numbers/strings**: bare literals that should be named constants
- **Premature abstraction**: helpers or base classes used only once

### Step 7 — ZeroMQ messaging (project-specific)

This project uses ZMQ as its primary inter-process bus. Run these checks on any
file that creates sockets, sends messages, or subscribes to topics.

#### Documentation coverage
- Every message topic used (send or receive) must have an entry in
  `docs/user-guide/09-messages.md` — flag any topic that is absent
- Every payload field must be documented (name, type, description, optional/required)
- The pub/sub responsibility for each topic must be stated clearly: who publishes,
  who subscribes, and under what conditions

#### Topic and subscription correctness
- ZMQ topic filtering is **prefix-based**: a subscriber on `"order.fill"` silently
  receives `"order.filled"` too — verify all filter strings are as specific as
  intended
- Cross-check every `_dispatch` / `_handle_event` branch against the topics passed
  to `make_subscriber()`; a handler for a topic that was never subscribed to will
  silently never fire
- Verify topic strings are constructed consistently (e.g. always
  `f"order.fill.{gateway_id}"`, never bare `"order.fill"`)

#### Socket lifecycle and safety
- Sockets must be closed on **every** exit path: normal return, exception, and
  signal; check that `finally` or context managers cover all paths
- ZMQ sockets are **not thread-safe**; flag any socket passed between threads or
  accessed from a signal handler directly (signal handlers must only set a flag)
- PUSH sockets buffer silently when the PULL server is down; PUB drops messages
  silently when no subscriber is connected — verify the code is aware of which
  side it depends on and documents the assumption

#### Receive-loop discipline
- Every receive loop must use `poller.poll(timeout=...)` rather than a bare
  blocking `recv()`; a blocking `recv()` without a timeout prevents clean shutdown
- Check that the poll timeout is short enough for timers (heartbeat, reissue) to
  fire promptly but not so short it creates a busy loop (50 ms floor is a
  reasonable minimum)

#### Send-side correctness
- `send_multipart()` raises `zmq.ZMQError` when the socket is closed or in EAGAIN
  state; verify that callers guard against this on shutdown paths
- Frame ordering must be `[topic_bytes, payload_bytes]` everywhere —
  swapped or missing frames cause silent misrouting that is hard to debug
- All topics and payloads must be encoded with `encode()` / decoded with `decode()`
  from `edumatcher.models.message`; raw frame construction outside this helper is
  a flag

### Step 6 — Security (OWASP basics)

- Injection risks (shell, SQL, or format-string construction from user-controlled
  input)
- Hardcoded credentials or secrets
- Insecure deserialization (`pickle`, `eval`, `exec` on external data)

---

## Output Format

Group findings by severity. Lead with the static-tool results, then one section
per review pass.

| Marker | Severity | Action |
|--------|----------|--------|
| 🔴 **Critical** | Correctness bug, race condition, resource leak | Must fix before merge |
| 🟠 **Warning** | Bad practice, latent risk, oversized file | Should fix |
| 🟡 **Suggestion** | Readability or structural improvement | Consider fixing |
| ✅ **Clean** | No issues found in this category | |

After reporting, offer to apply fixes for all 🔴 Critical items immediately, then
ask whether to proceed with 🟠 Warnings.

Make sure to run a full test suite and static code checks after any fix, and report the results and offer to fix any new issues before proceeding to the next review pass.

---

## Example Invocation

```
Review src/edumatcher/engine/main.py for correctness and race conditions.
Run all static checks first.
```

```
Do a full code review of the files changed in the last commit.
```
