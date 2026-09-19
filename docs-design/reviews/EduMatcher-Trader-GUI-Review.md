# EduMatcher Trader GUI (`pm-trading-ui`) — Code Review

**Scope:** `web-apps/trader-gui/apps/web/src/` — the TRADER path in depth (order ticket, blotters, amend/replace/cancel, OCO/combo, positions/flatten, WebSocket layer, market-data stores, chart/tape/DOM). The MARKET_MAKER quote screens got a lighter pass. ADMIN screens are out of scope.
**Cross-checked against:** `src/edumatcher/api_gateway/` (`routers/orders.py`, `routers/ws.py`, `caches.py`, `market_cache.py`, `schemas.py`, `engine_client.py`) and `src/edumatcher/engine/main.py`. Where the GUI and the engine disagree, the engine is taken as the truth.
**Date:** 2026-09-16
**Review bar:** "Does it work as designed, on paper?" UI testing capacity is limited, so every finding below is either traced end-to-end through gateway and engine code, or confirmed by a probe test (see Appendix A).
**IDs:** C = critical, H = high, M = medium, L = low.

---

## 1. Verdict

**Can a trader trade shares with it? The happy path works. It is not yet correct enough to rely on.**

What works end to end:

- Login → `GET /status` → `GET /bootstrap/trader` → sockets open → `orders.snapshot` seeds the blotter.
- All 8 single-leg order types can be entered. Client validation matches the gateway's `OrderRequest` rules, and the ticket gets a synchronous verdict through `?wait=ack`.
- The blotter stays current from `order.ack/fill/amended/cancelled/expired` with no polling.
- Cancel, bulk cancel, amend (engine-mirroring `validateAmend`), cancel-replace, positions and flatten all work.
- The market-data layer is well designed: a pair-based subscription diff, per-topic `seq` tracking, and a throttled overview render.
- `tsc --noEmit` is clean and the existing suite is green (47 files, 353 tests).

What stops me calling it correct:

1. **The blotter can lie about order state after an ordinary event.** A rejected cancel or amend (collar breach, tick violation, late cancel on an order that just filled) marks a *still-resting* order `REJECTED`. The row goes terminal, its cancel button is disabled, and nothing short of a gateway restart brings it back (**C1**).
2. **Cancel-replace on a partially filled order over-trades** (**C2**).
3. **Several order types cannot be replaced or undone** because the live order rows never carry `stop_price` / `visible_qty` / `trail_offset` (**C3**).
4. **OCO groups never appear**, so "Cancel group" is unreachable for a fresh OCO (**H1**).
5. **Market data is not idempotent under replay.** After a reconnect, volume is double-counted, and the chart can throw and swallow live prints (**H2, H3**).
6. **A trader cannot see halts that began before login, and cannot re-sync session state after a disconnect** (**H4, H5**).

Suggested bar before classroom use: fix C1–C3 and H1–H5.

| Severity | Count | Theme |
|---|---|---|
| Critical | 3 | Order state wrong, unintended exposure, unusable modify/undo |
| High | 6 | OCO grouping, replay duplication, gap repair, halt/session awareness, private-stream gaps |
| Medium | 8 | Order-type gating, misleading confirmations, lost bulk feedback, flatten semantics |
| Low | 10 | Docs-vs-code drift, dead code, UX papercuts |

**The root cause behind most findings.** The same message means different things, and the client folds it as if it meant one thing:

- `order.ack accepted=false` is a new-order reject, a cancel reject, *and* an amend reject (C1).
- A replayed `trade` looks the same as a live one (H2).
- An ack is the only place order attributes arrive, but the hot-path ack carries only some of them (C3, H1).

Each fix below removes the ambiguity at the source rather than patching one symptom.

---

## 2. Critical findings

### ~~C1 — A rejected cancel or amend marks a live order `REJECTED` (GUI and gateway cache)~~

**FIXED**

**Where:** `store/useOrderStore.ts:137` (`applyAck`) · `api_gateway/caches.py:48` · engine `_handle_cancel` (main.py:5735) / `_handle_amend` (main.py:5808) → `_reject` (main.py:694)

The engine reports a failed cancel or amend by publishing `order.ack` with `accepted=false` and the **existing** `order_id` (plus the request's `request_tag`). `applyAck` does not tell this apart from a new-order reject and sets `status = "REJECTED"`. The gateway's `SessionCaches.apply` makes the same mistake, so the `orders.snapshot` sent on reconnect repeats the wrong state. `hydrate` (the Refresh button) then refuses to overwrite a terminal row with a non-terminal one (`useOrderStore.ts:131`), so a `GET /orders` that still lists the order as resting cannot repair it either.

Triggers are routine, not exotic:

- Amend to a price outside the collar (`COLLAR_BREACH`), off-tick (`TICK_VIOLATION`), or during `CLOSED` (`MARKET_CLOSED`).
- Amend with qty ≤ filled when fills landed while the dialog was open (see M6).
- Cancel racing a fill (`ORDER_NOT_FOUND`). A `FILLED` order is relabelled `REJECTED`.
- `NOT_OWNER`, and gateway-status rejects.

What the trader experiences:

- The order vanishes from the Workspace compact blotter, which filters out terminal rows.
- In Active Orders its Amend/Replace/Cancel buttons are disabled and it cannot be selected for bulk cancel, **while it is still resting in the engine and can still fill.**
- The only feedback the trader got was "Amend submitted" or "Cancel submitted". The reject reason is never shown.

Confirmed by probes P1a and P1b.

**Fix (long-term, breaking allowed):** stop overloading `order.ack`.

- Give cancel and amend rejects their own message type, e.g. `order.cancel_reject` / `order.amend_reject` carrying `order_id`, `request_tag`, `reject_code` and `reason`.
- The gateway cache must not change order status on them.
- The GUI shows them as a toast and an Event Center `REJECT` entry, correlated by the `request_tag` it already generates (`queries/index.ts` `newOrderRequestTag`) but never reads.
- Related: `DELETE /orders/{id}?wait=ack` only waits on `order.cancelled`, so a rejected cancel always times out as a 503. It should wait on the reject topic as well.

---

### ~~C2 — Cancel-replace defaults to the original total quantity → over-trading on partial fills~~

**FIXED**

**Where:** `components/orders/ReplaceDialog.tsx:30`

`const [qty, setQty] = useState(String(order.quantity))` pre-fills the replacement with the order's **original total**. Replace creates a brand-new order, so for a partially filled order the right default is `remaining_qty`.

Example: BUY 100 @ 10.00 with 60 filled. The trader opens Replace and changes only the price. A fresh BUY 100 is sent, so 160 shares are bought against an intent of 100. The dialog shows no filled or remaining figure to warn them. (Amend correctly uses total quantity, because the engine's amend qty *is* the total. The two dialogs share the label "Quantity" with different meanings.)

**Fix:** default to `remaining_qty`, label it "Replacement quantity", and show "filled so far" read-only as the Amend dialog does. Better still, read the order live from the store by id (see M6).

---

### ~~C3 — Live order rows lack `stop_price` / `visible_qty` / `trail_offset` / `smp_action`, so Replace and Undo break~~

**FIXED**

**Where:** engine new-order hot-path ack (main.py, ack payload carries only `symbol, side, order_type, tif, qty, price, client_tag`) · `store/useOrderStore.ts` `detailPatch` · `ReplaceDialog.tsx:47` · `lib/resubmit.ts`

The blotter is seeded from `orders.snapshot` (the gateway cache), which is built from acks and fills. Neither carries the stop price, visible slice, trail offset or SMP action. Every live `Order` therefore has these fields `null` unless the user presses Refresh, which goes through `GET /orders` `OrderDisplay` and does carry them. The consequences:

| Type | Replace dialog | Power-user Undo (re-submit after cancel) |
|---|---|---|
| ICEBERG | **Impossible**: no visible-qty input, and validation fails with "Visible qty required" | Body lacks `visible_qty` → gateway 422. **The order is already cancelled.** |
| TRAILING_STOP | **Impossible**: no trail-offset input, validation fails | Body lacks `trail_offset` → 422 |
| STOP / STOP_LIMIT | Stop price field is blank; the trader must remember and retype it | Body lacks `stop_price` → 422 |
| any | `smp_action` silently reverts to the gateway default | same |

The Order Detail drawer also shows no stop or iceberg attributes. Confirmed by probe P3.

**Fix:** make the ack the complete order record. The OCO, combo and quote seeding paths already publish `order_to_display_dict(...)`; the single-order hot path should publish the same fields (price, stop_price, visible_qty, trail_offset, smp_action, group ids). Adding a few pre-bound locals to the inline `dumps` keeps the perf argument intact. Until then, Replace and Undo must refuse types whose attributes are unknown rather than send a bad body.

---

## 3. High findings

### ~~H1 — OCO legs are never grouped; "Cancel group" is unreachable~~

**FIXED**

**Where:** engine `_handle_oco_order` (main.py:5563: leg ack `order={symbol, side, order_type, tif, quantity, price}`, no `oco_group_id`) · `hooks/useOrderEventNotifications.ts` (ignores accepted `oco.ack`) · `useOrderStore.applyCancelled` (patches status only)

`computeOrderGroups` keys on `oco_group_id`, but no event that creates or keeps an OCO leg in the store carries it:

- The leg acks don't have it.
- `oco.ack` has `order_id_1/2` but is only used to toast rejections.
- `order.cancelled` does carry group ids, but `applyCancelled` drops them.

A freshly placed OCO therefore shows up as two unrelated orders with no Group badge and no row in the Groups panel. The existing `orderGroups.test.tsx` passes because it builds rows with `oco_group_id` already set. Combo legs are fine, because their acks use `order_to_display_dict(child)`. Confirmed by probe P2.

**Fix:** publish `order_to_display_dict(leg)` in the OCO leg ack, the same shape the combo path uses (this lands with C3). In the GUI, `applyCancelled` / `applyExpired` should fold group ids like `detailPatch` does.

### H2 — Trade prints are not de-duplicated; replay inflates volume and can crash the chart handler

**Where:** `ws/WebSocketManager.ts:291` (`emit`) → `:306` (`recordTrade`) · `store/useBookStore.ts` `recordTrade` · `components/symbol/SymbolChart.tsx:191` · gateway `routers/ws.py:394`

Prints are re-delivered in three normal situations:

- **Every market-data reconnect.** The wildcard `trades` item is re-subscribed, and the gateway's `_emit_snapshots` ignores `resume_from` for wildcard items and sends the whole 60-second tail for every symbol.
- **Every `resume.rejected` for `trade.executed`.** This is always the outcome; see H3.
- **Every re-subscribe of a symbol's trades.**

`SeqTracker.observe` correctly reports "not a gap" for these, but the envelope is still emitted and folded. As a result:

- `liveVolume` double-counts, so the Market Overview volume is inflated until the next 30-second rollup poll.
- `recentTrades` holds duplicates. `TradesTape` de-duplicates by id when rendering, so the tape itself looks right, but the store does not.
- `SymbolChart` folds each replayed print. A print in the current bucket overwrites the bar's close with an older price and adds its volume again. A print from an earlier bucket makes `series.update` throw `Cannot update oldest data` (checked in the lightweight-charts v5 source).
- Because `emit` runs **before** the store update and does not isolate handler exceptions, that throw aborts `recordTrade` for the print and skips every listener registered after the chart. Live prints are lost from the book store (probe P7).

Confirmed by probes P6a and P7.

**Fix:**

1. De-duplicate trades by `id` (a bounded set per symbol) in `recordTrade`, and check the same id before emitting `trade` on the bus.
2. Wrap each bus handler call in `emit` in try/catch so one faulty view cannot starve the stores.
3. In `SymbolChart`, ignore ticks older than `lastBar.time`.
4. Gateway: honour `resume_from` for the wildcard item too (see H3).

### H3 — Gap repair for `trade.executed` can never succeed

**Where:** `ws/WebSocketManager.ts:210` (`repairGap`) · gateway `routers/ws.py:419` (`_emit_resume`)

`trade.executed` is one venue-wide topic, so `symbolForTopic` returns null and the resume frame goes out without `symbols`. The gateway derives no symbol from the topic, answers `resume.rejected: unknown_topic`, and the client then resets the tracker and requests a trades snapshot **for the focus symbols only**. Missed prints for every other symbol on the overview are lost, and the focus symbols get their whole tail replayed, which feeds H2. The per-symbol trade buffers do carry the venue-wide `seq`, so a venue-wide resume is implementable server-side. Confirmed by probe P6b.

**Fix (gateway + client):** support `resume` on `trade.executed` with no symbol by merging the per-symbol buffers on `seq > from_seq`, and apply the same path when replaying a wildcard `resume_from`. The client code needs no change once the server supports it.

### ~~H4 — Halts are invisible to TRADER/MARKET_MAKER unless they begin after login~~

**Where:** `lib/bootstrap.ts:32` (halts only on `BootstrapAdmin`) · `OrderTicket.tsx` (no halt check)

`useHaltStore` is hydrated only from the ADMIN bootstrap. The trader bootstrap has no `halts`, `/admin/halts` is ADMIN-only, and the market-data socket sends no circuit-breaker snapshot on subscribe. A symbol halted before login, or halted while the socket was reconnecting, shows no HALT badge anywhere. A resume missed during a disconnect leaves a stale badge for the rest of the session. The ticket also doesn't disable MARKET/FOK/IOC for a halted symbol, so they round-trip to a `CIRCUIT_BREAKER_ACTIVE` reject.

**Fix:**

- Add `halts` to `GET /bootstrap/trader`, or expose a trading-role halt-status endpoint.
- Re-fetch it on every market-data reconnect.
- Gate MARKET/FOK/IOC in the ticket on `useHaltStore`.

### ~~H5 — Session phase defaults to CLOSED and is never re-synced after a reconnect~~

**Where:** `store/useSessionStore.ts:45` · `lib/bootstrap.ts` · `WebSocketManager.ts:415` (`onReconnect`) · `useSessionQuery` (defined, never used)

- If `bootstrap.session` is `null` (listed in `incomplete` when the engine query timed out), the phase stays `CLOSED`. The ticket then blocks every submit, and Flatten is disabled, until the next `session` event. On a quiet venue that can be the whole day.
- After a market-data reconnect nothing re-reads `GET /session`. A transition missed while disconnected leaves the ticket's TIF gating, auction-disabled types and closed banner wrong.

**Fix:** fetch `/session` (the existing `useSessionQuery`) on every market-data authentication and whenever bootstrap reports `session` incomplete. Model "unknown" explicitly rather than defaulting to `CLOSED`.

### H6 — The private stream has no gap detection, and Refresh cannot reconcile

**Where:** `WebSocketManager.handlePrivateMessage` (ignores `stream_seq`) · gateway `routers/ws.py:173` (queue `maxsize=256`, `_record_drop` on overflow) · `useOrderStore.hydrate` · `types/index.ts:216`

- The gateway drops private events when a client's queue is full and numbers the stream with `stream_seq` precisely so the loss is detectable. The GUI never checks it, so a dropped fill or cancel leaves the blotter and positions wrong until the next reconnect.
- The manual Refresh (`hydrate`) only merges. `GET /orders` lists resting orders only, and a working row missing from it is kept as `NEW` forever (probe P5).
- `GET /orders` returns `OrderDisplay` with `ts_ns`, but `normalizeOrder` reads `timestamp`. Every refreshed row gets `updated_at = null`, which blanks the Updated column and breaks `pruneTerminal`'s recency ordering (probe P4). The type comment describing "`timestamp` (epoch seconds)" is stale.

**Fix:**

- Track `stream_seq` from `authenticated`/`orders.snapshot` onwards. On a gap, close and reopen the events socket; the snapshot is the repair.
- Make `hydrate` authoritative for non-terminal rows: a working row absent from `GET /orders` is gone.
- Read `ts_ns`.

---

## 4. Medium findings

**~~M1 — Order-type gating is narrower than the engine.~~** `OrderTicket.tsx:40` disables MARKET/FOK/IOC only in the two auction phases. The engine rejects them in **every** phase where `is_matching_enabled` is false (only `CONTINUOUS` matches), so in `PRE_OPEN` they round-trip to `SESSION_NOT_PERMITTED`, and during a halt see H4. `PositionPanel` already gates on `phase === "CONTINUOUS"`, so the two components disagree. Gate on "not CONTINUOUS or symbol halted", in one helper next to `ALLOWED_TIF`.

**M2 — "Accepted" is misleading for FOK, MARKET and IOC.** The ticket toasts `BUY 100 AAPL accepted` from the *first* ack (`OrderTicket.tsx:202`). For a FOK the authoritative outcome is a second `order.ack accepted=false INSUFFICIENT_LIQUIDITY`, and for MARKET/IOC with no liquidity it is `order.cancelled`. `useOrderEventNotifications` ignores `order.ack` and sends cancels to the Event Center without a toast, so the trader never learns the order died. Toast the terminal outcome of an order this session submitted: a reject ack, or a cancel with zero fills.

**M3 — Bulk cancel and Flatten All lose per-order feedback.** Both loop `mutation.mutate(...)` on a single `useMutation` (`ActiveOrdersPage.tsx:135`, `PositionPanel.tsx:99`). In TanStack Query v5 the callbacks passed to `mutate` fire only for the **latest** call (checked in `query-core` `MutationObserver`), so errors for N−1 of the cancels or flattens are silently dropped. Use `mutateAsync` with `Promise.allSettled` and report a summary.

**M4 — Flatten semantics.**
- It sizes the close from `GET /positions`, which the gateway builds from fills *this gateway process* has seen (`routers/reference.py:186`), not the engine ledger. After a gateway restart it reads flat while the engine holds a position.
- It ignores resting orders on the same symbol, so a long 100 with a working SELL 100 flattens to short 100.
- The power-user "Undo" cancels a MARKET order (`PositionPanel.tsx:70`), which never rests, so it can never undo anything.

Serve `/positions` from the engine (as `/admin/positions` does), warn when opposite-side working orders exist, and drop the Undo on flatten.

**M5 — The combo form forces `smp_action: "NONE"`** (`ComboForm.tsx:67`, `comboSchema` default). That *explicitly permits self-trades* and overrides the gateway's configured SMP default, which the single-leg ticket deliberately preserves by omitting the field. Omit it, or offer the same "Gateway default" choice.

**~~M6 — The Amend and Replace dialogs work on a snapshot of the order.~~** **FIXED** The `order` prop is captured when the dialog opens, so fills that arrive while it is open are not reflected in *Filled* or in `validateAmend`'s `filled`. The engine then rejects, which triggers C1. Pass `order_id` and read the row live from `useOrderStore`. Close the dialog with a notice if the order goes terminal.

**M7 — The ticket's session and tick rules have no single source.** `AUCTION_DISABLED` (ticket), `isContinuous` (PositionPanel) and `ALLOWED_TIF` (sessionState.ts) encode overlapping engine rules in three places. The 2026-08-14 audit found the same "rule stated twice" failure. Consolidate the order-acceptance rules in `lib/sessionState.ts` with engine citations, the way `validateAmend` does.

**M8 — Gateway `build_combo_payload` hardcodes `tick_decimals=2` per leg** (`api_gateway/translate.py`). This is outside the GUI, but the combo ticket drives it. Prices are converted with the right symbol, so the field is at best redundant and at worst wrong for non-2-decimal symbols.

---

## 5. Low findings

- **L1 — The shortcut table disagrees with the bindings** (`lib/shortcuts.ts` vs `useGlobalShortcuts.ts`). F3, F4 and Ctrl+L are documented as "toggle" but navigate. `Shift+F` (flatten selected position) is documented but not bound. Ctrl+Shift+F only navigates. Derive the table from the bindings, the same fix pattern as the `serve.ts` `ENV_OPTIONS` change.
- **L2 — B/S fire a live order on a single keystroke with no confirmation** whenever focus is not in an input, for example right after clicking an order-type tab or a DOM level. It is intentional per §12.11, but for MARKET it is a one-key market order of the last quantity typed. Consider "armed" mode or confirming MARKET.
- **L3 — `setOverviewSubscription` is never called** (`WebSocketManager.ts:176`), so the `FOCUS_FULL_CHANNELS` branch of `planPairs` is unreachable. `useSessionQuery` is unused. This is dead code, mentioned rather than removed.
- **L4 — The `apiFetch` docstring says 401 triggers automatic logout;** no `QueryClient` error handler does that. `ManagedSocket`'s `onAuthFailure` is never wired either, so a revoked key reconnects forever.
- **L5 — `SeqTracker` keeps high-water marks for focus topics after unsubscribe.** Re-focusing a symbol later logs a spurious gap and sends a needless resume for its `depth`/`auction` topics.
- **L6 — `useWsEvent` binds the handler once** (`deps: [type]`). Every current handler is safe because it reads stores via `getState`, uses stable setters, or is remounted by key. It is a latent stale-closure trap for the next author; route it through `useEventCallback`.
- **L7 — Order Detail drawer:** live entries are appended to history without de-duplication, so after the 30-second refetch the same event shows twice.
- **L8 — Order Entry:** the ticket's symbol starts empty even when an active symbol exists, so the Ref hint is blank until the trader types.
- **L9 — `client_tag` is dropped by Replace and by Undo.**
- **L10 (MM) — `NewQuoteForm` captures `initial` in `useState` once.** A Re-quote prefill while the form is already open does not update the fields.

---

## 6. Completeness — order types

Checked against gateway `OrderRequest` / `OcoLegRequest` / `ComboLegRequest` and the engine's validation.

| Type | Entry | Client ⇔ gateway ⇔ engine validation | Amend | Replace | Undo | Notes |
|---|---|---|---|---|---|---|
| MARKET | ✅ | ✅ | n/a | n/a | n/a | gating M1; outcome M2 |
| LIMIT | ✅ | ✅ | ✅ (C1 on reject) | ⚠ C2 | ✅ | |
| STOP | ✅ | ✅ | qty only | ⚠ stop blank (C3) | ❌ 422 (C3) | no client check of stop-vs-last direction; the engine triggers immediately |
| STOP_LIMIT | ✅ | ✅ | price/qty | ⚠ stop blank (C3) | ❌ 422 (C3) | |
| FOK | ✅ | ✅ | n/a | n/a | n/a | kill not surfaced (M2) |
| IOC | ✅ | ✅ matches gateway (price required); the engine would accept priceless | n/a | n/a | n/a | TIF hidden, DAY sent; harmless |
| ICEBERG | ✅ | ✅ matches gateway (`visible < qty`); the engine allows `visible == qty` | price/qty | ❌ (C3) | ❌ (C3) | |
| TRAILING_STOP | ✅ | ✅ | n/a | ❌ (C3) | ❌ (C3) | the engine rejects if no prior trade; no hint in the ticket |
| OCO | ✅ LIMIT/STOP legs | ✅ | per leg | per leg | — | grouping broken (H1). The gateway and engine also accept STOP_LIMIT / TRAILING_STOP / IOC / FOK legs, which the form does not offer. |
| Combo (AON) | ✅ LIMIT/MARKET legs | ✅ | — | — | — | SMP forced NONE (M5) |
| Quote (MM) | ✅ | ✅ | — | — | — | light pass only |

TIF: `ALLOWED_TIF` matches the engine (ATO only in OPENING_AUCTION, ATC only in CLOSING_AUCTION, nothing in CLOSED).

---

## 7. Message handling and redraw — what is right

So the fixes above are not read as "rewrite the layer":

- **Single source per concern:**
  - The order store is seeded by `orders.snapshot` and folded by `order.*`.
  - The book store is fed only by the market-data router.
  - Views subscribe with narrow Zustand selectors, so a book tick for MSFT does not re-render the AAPL ladder.
- **The gateway registers the private sink before building the snapshot**, so an event is at worst duplicated, never lost. The client folds converge under that duplication, because the replayed events arrive in order after the snapshot.
- **Pair-based subscription diffing** sends unsubscribes before subscribes, keeping heavy-channel fan-out bounded. Reconnect re-declares the full set.
- **`SeqTracker`** handles first-seen and at-or-below-high-water correctly. Its only blind spots are the replay semantics in H2/H3.
- **`useThrottledBooks`** bounds overview renders to `VITE_MARKET_THROTTLE_MS` while the DOM ladder and ticket read the live store.
- **`toOrderStatus`** folds unknown statuses from quantities, which defends against wire drift.
- **`ManagedSocket`:** backoff, auth timeout and status-before-auth are all correct and tested.

---

## 8. Suggested fix order

1. ~~**C1** — Distinct cancel/amend reject messages (engine + gateway cache + GUI toast by `request_tag`).~~
2. ~~**C3 + H1** — Full order record on every ack (engine), then fold group ids in `applyCancelled`/`applyExpired` (GUI).~~
3. ~~**C2, M6** — The Replace/Amend dialogs read the live row and default to remaining quantity.~~
4. ~~**H2, H3** — Trade de-duplication by id, exception-isolated `emit`, chart old-tick guard, and venue-wide trade resume (gateway).~~
5. **H4, H5, M1** — Halts in the trader bootstrap, re-sync session and halts on reconnect, one gating helper.
6. **H6** — `stream_seq` gap detection, authoritative `hydrate`, `ts_ns`.
7. M2–M5, then the lows.

Each step should come with a regression test that feeds the **engine's real payload shape**. Several existing tests pass only because they hand the store fields the engine never sends (e.g. `oco_group_id` on an OCO leg ack).

---

## Appendix A — Probe tests

Written in the review workspace only, not added to the repo. Each asserts the *current* behaviour, so a green run confirms the defect (9/9 green, 2026-09-16):

| Probe | Confirms |
|---|---|
| P1a | Amend `COLLAR_BREACH` reject ack → resting order `REJECTED`; `hydrate` with a `NEW` row cannot restore it |
| P1b | `FILLED` order + late cancel `ORDER_NOT_FOUND` ack → `REJECTED` |
| P2 | Two OCO leg acks in engine shape → `computeOrderGroups` returns `[]` |
| P3 | ICEBERG from an ack has `visible_qty: null`; resubmit body lacks it; `orderSchema` rejects the replace candidate |
| P4 | `normalizeOrder({ts_ns})` → `updated_at: null` |
| P5 | `hydrate([])` leaves a working row `NEW` |
| P6a | Replayed print → `liveVolume` 300 for 200 traded, duplicate `recentTrades`, `lastPrice` regressed |
| P6b | `trade.executed` gap → `resume` frame without `symbols` |
| P7 | A throwing `trade` bus listener prevents `recordTrade` |

Baseline: `tsc --noEmit -p apps/web/tsconfig.json` clean; `vitest run` 47 files / 353 tests green.
