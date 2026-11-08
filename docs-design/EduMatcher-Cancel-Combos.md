Version: 0.1.0

Date: 2026-11-08

Status: Implemented (WP-CC1, WP-CC2, WP-CC3), uncommitted


# EduMatcher — Cancelling combos from an ALF client

---

## Table of Contents

1. [Summary and verdict](#1-summary-and-verdict)
2. [Verification: what exists today](#2-verification-what-exists-today)
3. [Is this orthogonal?](#3-is-this-orthogonal)
4. [Gap analysis](#4-gap-analysis)
5. [Proposed change](#5-proposed-change)
6. [Wire behaviour of the cancel (unchanged)](#6-wire-behaviour-of-the-cancel-unchanged)
7. [Optional protocol extensions (not recommended now)](#7-optional-protocol-extensions-not-recommended-now)
8. [Tests](#8-tests)
9. [Documentation](#9-documentation)
10. [Open decisions](#10-open-decisions)
11. [Phased plan](#11-phased-plan)


## 1. Summary and verdict

The request was for a new `CancelCombo` action in the ALF protocol, on the
premise that a combo cannot be cancelled over ALF today.

**That premise holds for the ALF *client library* and the AI trader, not for the
ALF *protocol*.** The wire action already exists and works end to end:

```text
CANCEL|COMBO_ID=<combo-label>
```

It is specified in `010-alf.md` ("Combo cancel"), parsed by `pm-alf-gwy`,
forwarded to the engine as `order.combo_cancel`, offered by `pm-alf-console`,
and exposed as `DELETE /combos/{combo_id}` on the REST gateway. What is
missing is only the *client-side builder* (`alf_client.protocol`) and the
AI trader's `Action`/transport mapping that would use it.

So the work is a small client-side addition, orthogonal to everything else,
and **no change to the ALF1 wire format, the gateway or the engine is needed**.
A new protocol verb would duplicate `CANCEL|COMBO_ID=` and is rejected in §7.


## 2. Verification: what exists today

| Layer | Evidence | Combo cancel? |
|---|---|---|
| ALF spec | `docs/books/protocols-and-clients/part-2-specifications/010-alf.md`, "Combo cancel": `CANCEL\|COMBO_ID=<combo-label>`; semantics "cancels a combo and its still-resting child legs" | Yes |
| ALF gateway | `alf_gwy/gateway.py` `_handle_cancel`: if `COMBO_ID` present → `make_combo_cancel_msg(combo_id, gateway_id)` → engine | Yes |
| Engine | `engine/main.py` `_handle_combo_cancel` (topic `order.combo_cancel`): looks the combo up by `combo_id` **and** owning `gateway_id`, refuses `ORDER_NOT_FOUND` / `ORDER_ALREADY_TERMINAL`, else `_cascade_cancel_combo(combo, CANCELLED)` and publishes `combo.cancel_ack.{GW}` | Yes |
| Engine → ALF | `combo.cancel_ack` is rendered by the gateway as `COMBO_ACK\|ACCEPTED=FALSE` when refused and as nothing when accepted (the leg `CANCELLED` frames and `COMBO_STATUS\|STATUS=CANCELLED` say it) | Yes |
| ALF console | `alf_console/display.py`: `CANCEL\|COMBO_ID=<combo-label> — cancel a combo and all its legs`; subscribes `combo.cancel_ack.{ID}` | Yes |
| REST gateway | `api_gateway/routers/orders.py` `cancel_combo` → `engine.send_combo_cancel` | Yes |
| Tests | `test_combo_gateway_integration.py` ("Cancel via COMBO_ID cancels all children atomically"), `test_alf_examples.py`, `test_alf_console_cancel_case.py`, `test_gateway_and_scheduler.py` | Yes |
| **ALF client lib** | `alf_client/protocol.py` has `new_combo`, `cancel`, `cancel_oco` — **no `cancel_combo`** | **No** |
| **AI trader** | `ai_trader/actions.py` has `NewCombo`, `CancelOco`, `CancelOrder` — **no `CancelCombo`**; `ai_trader/transport.py` falls through to `alf.cancel_oco` for any other action | **No** |

Result: the only missing pieces are the last two rows.

Can it be done "today" without any change? Over the wire, yes — any client
that writes `CANCEL|COMBO_ID=...` to its socket succeeds. Through the
repo's own client library or the AI trader, no: there is no builder and no
action, and `Transport._encode`'s final `return alf.cancel_oco(action.tag)`
would silently turn an unknown action into an OCO cancel.


## 3. Is this orthogonal?

Yes, on every axis that matters:

* **Protocol**: no new verb, field or frame. ALF is frozen at `ALF1`; this
  stays inside it.
* **Gateway / engine**: untouched. Ownership (`combo.gateway_id`), terminal
  state handling and cascade cancel are already implemented and covered.
* **Other cancel paths**: single-order cancel (`CancelOrder`, `CANCEL|ID=`) and
  OCO cancel (`CancelOco`, `CANCEL|OCO_ID=`) use different identifiers and
  different engine handlers; adding a third sibling does not interact with them.
* **Combo placement**: `NewCombo` is unchanged. The new action only references
  the same `combo_id` label the client chose at submit (`tag` doubles as
  `COMBO_ID`, `new_combo` sets `TAG=combo_id`).
* **In-flight AI-trader work**: the uncommitted `basket` strategy /
  `combo` execution style only *creates* combos via `Executor.combo_for` and
  `Agent._basket`. It does not cancel them, so this change neither depends on
  it nor conflicts with it beyond both touching `actions.py` and
  `transport.py`.


## 4. Gap analysis

Besides the missing builder and action, reading the existing path shows three
properties a new client has to live with. None needs fixing for the client work.

1. **No `RTAG` on combo (or OCO) cancel.** The gateway raises
   `UNSUPPORTED_FIELD` ("RTAG is only supported for CANCEL|ID"). A client
   therefore cannot correlate a refused combo cancel by request tag; it has to
   correlate on `COMBO_ID`.
2. **Accepted cancel produces no dedicated frame.** Success is observed
   indirectly: the leg `CANCELLED` frames (carrying the leg `TAG`) and
   `COMBO_STATUS|COMBO_ID=..|STATUS=CANCELLED`. Refusal arrives as
   `COMBO_ACK|COMBO_ID=..|ACCEPTED=FALSE|REASON=..`, **without** the machine
   readable `REJECT_CODE` that the engine's `combo.cancel_ack` carries.
   (REST callers get the full ack, including `cancelled_order_ids`.)
3. **The AI-trader transport ignores combo frames.** `_to_event` has no branch
   for `COMBO_ACK` or `COMBO_STATUS`, so they map to `None`; the agent
   learns of a combo's legs only through their fills and cancels. This
   matches `NewCombo`'s documented fire-and-forget contract.

A further, existing limitation, documented in the participant guide: combos
seeded by `market_maker_combos` are owned by the internal gateway `MM` and can
not be cancelled by any real ALF session.


## 5. Proposed change

Client-side only. Implemented 2026-11-08.

### 5.1 `alf_client/protocol.py`

```python
def cancel_combo(combo_id: str) -> bytes:
    return build_line("CANCEL", {"COMBO_ID": combo_id})
```

Alongside `cancel_oco`; deliberately no `rtag` parameter (§4.1).

### 5.2 `ai_trader/actions.py`

```python
@dataclass(frozen=True)
class CancelCombo:
    tag: str  # the combo id given to NewCombo
    symbol: str  # routing key: the first leg's symbol, as for NewCombo
```

Added to the `Action` union. Mirrors `CancelOco` (tag + routing symbol), since
the transport selects the session by symbol.

### 5.3 `ai_trader/transport.py`

In `_encode`, before the OCO fallthrough:

```python
if isinstance(action, CancelCombo):
    return alf.cancel_combo(action.tag)
```

and make the final line explicit (an `assert isinstance(action, CancelOco)`
before the OCO encoding) so a future action type can no
longer be encoded as an OCO cancel by accident. This hardening is the only
change to existing lines; it is justified because adding a sibling action is
exactly when the implicit fallthrough would bite.

### 5.4 Who sends it

Nothing in the agent emits `CancelCombo` (decision D1: action only). The `basket` strategy's combos are
all-or-none and short-lived (legs at the touch, `TIF=DAY`), and the agent does
not track them after submit. Emitting a cancel (for example, to withdraw a
basket whose legs have not filled within a timeout) needs tracking state that
`NewCombo`'s contract says does not exist. That is a separate feature; this
document only supplies the action and its encoding. Adding an unused action is
acceptable here because the request is explicitly for the capability; if it is
not wanted without a caller, stop after §5.1 (see decision D1).


## 6. Wire behaviour of the cancel (unchanged)

```text
> CANCEL|COMBO_ID=PAIR-001
```

| Outcome | Frames received |
|---|---|
| Accepted, legs resting | one `CANCELLED\|ORDER_ID=..\|TAG=<leg tag>..` per resting leg, then `COMBO_STATUS\|COMBO_ID=PAIR-001\|STATUS=CANCELLED` |
| Unknown label, or not owned by this gateway | `COMBO_ACK\|COMBO_ID=PAIR-001\|ACCEPTED=FALSE\|REASON=Combo not found` |
| Already `MATCHED`/`FAILED`/`CANCELLED`/`REJECTED` | `COMBO_ACK\|..\|ACCEPTED=FALSE\|REASON=Combo already <STATUS>` |
| Missing `COMBO_ID` value | `ERR\|CODE=MISSING_FIELD` (gateway) |
| `RTAG` supplied | `ERR\|CODE=UNSUPPORTED_FIELD` (gateway) |

Fills that already happened are not reversed. A combo whose legs have all
filled is `MATCHED` and is refused as already terminal.


## 7. Optional protocol extensions (not recommended now)

Considered and **not** proposed, since ALF1 is frozen and nothing needs them:

* **A new `CANCELCOMBO` verb.** Duplicates `CANCEL|COMBO_ID=`; two spellings of
  one action is strictly worse.
* **`RTAG` on combo/OCO cancel.** Additive and cheap in the gateway, because the
  engine already echoes `request_tag` on `combo.cancel_ack`. It would only help
  clients that want to correlate refusals by tag, and it widens ALF1. Revisit
  together with a positive cancel-ack frame, in an ALF minor version, if a real
  client needs it.
* **A positive `COMBO_CANCEL_ACK` frame** carrying `CANCELLED_IDS` and
  `REJECT_CODE`. Same reasoning; REST already provides the full ack for clients
  that need it.


## 8. Tests

Following the existing layout:

* `tests/test_alf_client.py` — `p.cancel_combo("C1") == b"CANCEL|COMBO_ID=C1\n"`,
  next to the `cancel_oco` assertion.
* `tests/test_ai_trader_alf_transport.py` — a `CancelCombo` action reaches the
  fake exchange as `CANCEL|COMBO_ID=<tag>`, modelled on
  `test_cancel_oco_and_cancel_oco`; and an unknown action type raises instead
  of being encoded as an OCO cancel.

No gateway or engine tests are needed; those paths are already covered (§2).


## 9. Documentation

* `010-alf.md` already specifies the wire action; add one sentence to "Combo
  cancel" noting that there is no `RTAG` and that success is signalled by the
  leg `CANCELLED` frames plus `COMBO_STATUS|STATUS=CANCELLED` (currently
  implicit), and cross-reference the table in §6.
* The AI-trader docs list no actions, so nothing to add there.
* No change to the REST or console documentation.


## 10. Open decisions

| # | Question | Recommendation |
|---|---|---|
| D1 (decided: add both) | Add `CancelCombo` to the AI trader with no caller, or stop at `alf.cancel_combo`? | Add both: the action is one dataclass plus one branch, and it removes the silent OCO fallthrough. Do not add agent logic that emits it. |
| D2 | Add `RTAG` and a positive ack frame to ALF? | No, not under ALF1 (§7). |
| D3 | Make the transport raise on unknown actions (§5.3)? | Yes; done as an `assert`. |


## 11. Phased plan

1. **WP-CC1 — client builder** → verify: `alf.cancel_combo` unit test passes.
2. **WP-CC2 — AI-trader action and transport** → verify: transport test against
   the fake exchange; unknown action raises.
3. **WP-CC3 — docs** (§9) → verify: `mkdocs build` clean.

Done: WP-CC1 and WP-CC2 with the tests of §8 (`test_cancel_combo` sends a
`CancelCombo` through a real gateway), WP-CC3 as the one ALF spec sentence
(the AI-trader docs list no actions, so there was nothing to add there).

Each step passes black, flake8, mypy, pyright and pytest before the next.
