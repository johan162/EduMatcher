# EduMatcher — Line-Gateway Alignment: Review and Workplan

Scope: `pm-dc-gwy` (DC1), `pm-md-gwy` (CALF1), `pm-ralf-gwy` (RALF1). The three
gateways speak the same `MSGTYPE|KEY=VALUE` line format and should behave the
same in the same situation, the connect sequence above all. A review on
2026-11-05 found that DC and RALF agree with each other (they share most of
their session code), CALF has drifted, and all three share a few bugs.

One WP at a time. Every WP ends with new tests green, `make _check` plus the
full suite green, a holistic review, and a proposed commit message. The
maintainer commits. No backwards compatibility: wire changes are made outright.

Started: 2026-11-05

---

## 1. Decisions

| # | Question | Decision |
|---|----------|----------|
| D1 | Key for the human-readable text on `ERR` | `DETAIL` everywhere (DC/RALF). CALF drops `MSG`. |
| D2 | Reply to a `HELLO` with missing/invalid fields | `ERR\|CODE=AUTH_REQUIRED` everywhere (DC/RALF). CALF drops `PROTO_MISMATCH`. |
| D3 | Model for gateway-initiated close | DC/RALF: every close the gateway starts sends a final line (`ERR` or `EXIT\|REASON=…`), then the session drains for at most `CLOSE_GRACE_SEC` (5 s). |
| D4 | Connection over `max_connections` | Accept, close at once, log a warning — as CALF does today. No line is sent: the session never existed. |
| D5 | Heartbeat cadence | Unchanged per gateway; docs corrected to describe what the code does. |

## 2. Findings

| # | Finding | Gateways | Sev | WP |
|---|---------|----------|-----|----|
| F1 | `select.select` raises `ValueError` once an fd reaches 1024; only `OSError` is caught, so the run loop dies. No connection cap. | DC, RALF | High | W3 |
| F2 | Slow client: queue silently cleared, no `ERR\|SLOW_CLIENT`, disconnect counted as `close_after_flush`; flush's `> max` check is dead; a partly sent line is torn | CALF | High | W2 |
| F3 | Replay gap reported as success: buffer aged out completely, or `LASTSEQ` ahead of the stream (gateway restart) → empty replay, no `REPLAY_MISS` | CALF, RALF | Med | W5 |
| F4 | No inbound line-length cap (RALF); DC checks only the unterminated tail, so lines up to ~8 KB pass | RALF, DC | Med | W4 |
| F5 | Lines after the one that closed the session are still dispatched: CALF answers `PING\nHELLO…` with `AUTH_REQUIRED` *and* `WELCOME`; DC/RALF change state silently | all | Med | W3 |
| F6 | `recv` `OSError` (e.g. `ECONNRESET`) treated like `EAGAIN`: dead session lingers until idle timeout and is counted as `idle_timeout` | all | Low | W4 |
| F7 | `ERR` text key `MSG` vs `DETAIL` | CALF | — | W1 |
| F8 | Bad `HELLO` → `PROTO_MISMATCH` vs `AUTH_REQUIRED` | CALF | — | W1 |
| F9 | `PONG` has no `TS` | CALF | — | W1 |
| F10 | Idle timeout closes silently (no `EXIT\|REASON=idle_timeout`); no close grace; still sends `ERR`/`PONG`/`HB` to a closing session | CALF | — | W2 |
| F11 | No-`HELLO` deadline: CALF 5 s silent close; RALF 5 s / DC 30 s via idle `EXIT\|REASON=idle_timeout` | all | — | W3 |
| F12 | `TCP_NODELAY` set only by DC; RALF has no engine-poll budget; RALF logs no login line; RALF `UNSUB` without `CH` silently ignored (CALF: `BAD_MESSAGE`) | mixed | Low | W6 |
| F13 | Docs: DC/RALF say idle = inbound silence, code also counts outbound sends; DC/RALF say `HB` only when quiet, code sends on a timer; DC error table lists an `IDLE_TIMEOUT` code that is never sent | DC, RALF | Low | W6 |
| F14 | Found in W5: a repeated `TRADE_ID` took a `TRADE` sequence number before the replay buffer dropped it, so every subscriber saw a gap that never happened | CALF | Med | W5 |

## 3. Work packages

### W1 — CALF wire alignment (D1, D2, F7–F9)

- Every CALF `ERR` carries its text under `DETAIL`, not `MSG`.
- `HELLO` with missing `CLIENT`, `CLIENT` over 32 chars, or `PROTO != CALF1`
  → `ERR|CODE=AUTH_REQUIRED|DETAIL=…`, then close.
- `PONG|TS=…`.
- `calf_client`: read `DETAIL`; any `ERR` in reply to `HELLO` is fatal
  (`CalfProtocolMismatch`), since retrying the same `HELLO` cannot succeed.
- Spec, operator page, spy-tool page, training chapter, design docs and
  `docs/examples/calf/` updated.

### W2 — CALF close semantics (D3, F2, F10)

Port the DC/RALF model: `_close_after_flush(reason)`, `CLOSE_GRACE_SEC`,
`_drop_backlog`; slow client → `ERR|CODE=SLOW_CLIENT` and reason
`slow_client`; idle → `EXIT|REASON=idle_timeout`; `_queue_raw` drops every
line once closing; `slow_clients` / `closing_clients` metrics.

### W3 — Connect phase, all three (D4, F1, F5, F11)

- 5 s `HELLO` deadline in all three → `EXIT|REASON=auth_timeout`, reason
  `auth_timeout`.
- `max_connections` for DC and RALF; `ValueError` from `select` caught.
- `_drain_lines` stops once the session is closing.

### W4 — Inbound robustness, all three (F4, F6)

- 4096-byte line cap checked on both the unterminated tail and framed lines.
- `recv` errors other than `EAGAIN` disconnect with reason `peer_reset`.

### W5 — Replay gaps (F3)

CALF `ReplayBuffer` and RALF journal report `REPLAY_MISS` (plus `SNAP` where a
baseline exists) when the requested range is no longer held or `LASTSEQ` is
ahead of the stream.

### W6 — Small alignments and docs (D5, F12, F13)

`TCP_NODELAY` everywhere; RALF engine-poll budget; RALF login log line; RALF
`UNSUB` validation; DC/RALF doc corrections.

## 4. Status

| WP | Status |
|----|--------|
| W1 | done 2026-11-05 (uncommitted). Design docs under `docs-design/` still show `PROTO_MISMATCH`/`MSG` as history and were left alone. ALF, BALF and LALF also use `MSG`/`PROTO_MISMATCH`; out of scope here. |
| W2 | done 2026-11-05 (uncommitted). `md.slow_clients` / `md.closing_clients` added; the monitor keeps reading `md.disconnects{slow_client}`, which now moves. `_queue_raw` no longer caps the queue itself: as in RALF/DC, the flush pass checks it, so between two passes a queue can briefly exceed `max_client_queue` by one engine-poll budget. The pre-auth `auth_timeout` can still cut a refused `HELLO`'s grace short; W3 reworks that path. |
| W3 | done 2026-11-05 (uncommitted). `HELLO_TIMEOUT_SEC` (5 s) in all three → `EXIT\|REASON=auth_timeout` via the grace path (the W2 note on a refused `HELLO`'s grace is resolved: closing sessions are skipped by the deadline). `max_connections` (default 64) for `post_trade_gateway` and `dc_gateway`, mirrored wherever `market_data_gateway.max_connections` lives: loaders, `main`, cverifier field lists (DC S093), config-gen commented defaults, config-gui model/codec/form, reference docs; like MD it has no config-gen flag. `gwy.clients_max` emitted and read by the monitor. `select` `ValueError` caught. DC behaviour change: a connection silent before `HELLO` is now closed after 5 s, not 30 s. Follow-up option (not done): `select.poll` would remove the 1024-fd ceiling outright; today an fd ≥ 1024 makes the read pass log a warning and skip. |
| W4 | done 2026-11-05 (uncommitted). One `_drain_lines` shape in all three: an unterminated buffer of ≥ 4096 bytes or a complete line over 4096 bytes including the newline → `ERR\|CODE=BAD_MESSAGE\|DETAIL=line exceeds 4096 bytes`, then close (`_reject_oversized_line`). CALF's tail check was `> 4096`, one byte late. `recv` `OSError` other than `BlockingIOError` → disconnect `peer_reset`. Send-side `OSError` is still treated as "try later": a dead peer surfaces on the next read. The DC doc's "non-UTF-8 → BAD_MESSAGE" was wrong (input is decoded with `errors="replace"`) and was removed. |
| W5 | done 2026-11-05 (uncommitted). `ReplayBuffer.replay_since` takes the stream's current sequence; RALF `_replay_from` compares against each entitled channel's latest. Both answer `REPLAY_MISS` (+ `SNAP` where a baseline exists) when `LASTSEQ` is ahead of the stream or what follows it has aged out entirely; zero lines with no error now means only "already up to date". F14 fixed: the duplicate check moved ahead of sequence allocation (`ReplayBuffer.has_trade`); `append`'s own duplicate guard and `bool` return are now unused by the gateway but kept. The CALF spec and operator guide had documented the silent empty replay as intended; rewritten. `calf_client` needed no change (it resets on `SNAP` and already adopts a restarted gateway's renumbering). |
| W6 | done 2026-11-05 (uncommitted). `TCP_NODELAY` in MD and RALF; RALF engine poll bounded at 1000 per pass; RALF logs `session authenticated`; RALF `UNSUB` without `CH` → `BAD_MESSAGE\|DETAIL=CH required` (MD's `UNSUB` error gained a `DETAIL`). Docs: DC/RALF heartbeat = fixed timer, idle = no traffic either way (a reading client never idles); DC's phantom `IDLE_TIMEOUT` code removed; RALF `EXIT` is now documented as client→gateway too, matching the code and the other two gateways. config-gen comments and config-gui help corrected for MD/RALF/DC. |

**Plan complete 2026-11-05.** Still open: `make test-e2e` (skipped while the simulation held the exchange ports). Not done, noted as options: `select.poll` instead of `select.select` (no fd ceiling); one shared session module for the three gateways, now that their session code is line-for-line alike.
