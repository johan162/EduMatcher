# EduMatcher Terminal GUI Final Production Review

**Date:** 2026-08-03 (original review) · **Re-verified:** 2026-09-17  
**Scope:** `web-apps/terminal-gui/` (moved from `terminal-gui/` in `6eb45bad`) — bridge, browser store, views, calculation helpers, tests, and the CALF top-of-book normalisation path that feeds it.  
**Validation run (2026-09-17):** `npm test` (what `make test` runs) — 36 test files, 675 tests passed; `npm run typecheck` clean (bridge + web); `npm run build` succeeds. Run in a clean Linux mirror of the tree, because the `node_modules` checked out on the development Mac carries macOS-native Rollup binaries.

## Revision summary (2026-09-17)

The tree has changed very little since the original review: every commit touching `web-apps/terminal-gui/` after `0b9f75ae` (the H3 fix) is a directory move, container/port harmonisation, or test-harness change. A rename-aware diff from `0b9f75ae` to `HEAD` shows only three source changes: the repo-root depth and default ports in `apps/bridge/src/config.ts`, the proxy ports in `apps/web/vite.config.ts`, and test setup. No view, store or bridge logic changed. So every open finding below still applies to the code as it stands, and a fresh pass surfaced six more.

| ID | Finding | Severity | Status on 2026-09-17 |
|----|---------|----------|----------------------|
| H1 | No live-stack failure-mode soak | High | **Open.** The container path now exists (`deployment/docker`, `make up-all`), but there is still no scripted soak |
| H2 | AUCTION gaps broadcast but not displayed | High | **Open.** Unchanged |
| H3 | Symbol Detail chart renders history failure as "no history" | High | **Fixed** (`0b9f75ae`). No regression test; residual gap split out as M6 |
| H4 | No liveness check on the browser↔bridge WebSocket | High | **New** |
| M1 | Index View has no history-outage handling | Medium | **Open.** Unchanged |
| M2 | Index View hides Open/High/Low on the default `1D` timeframe | Medium | **Open.** Fix is now cheaper: the live `INDEX` frame already carries O/H/L |
| M3 | Live-feed silence is visible but not forceful | Medium | **Open.** More important now because of H4 |
| M4 | Previous-close age defined but not surfaced | Medium | **Open.** Unchanged |
| M5 | Halt countdown and "halted for" timers freeze between frames | Medium | **New** |
| M6 | Symbol Detail session statistics ignore history failure and age | Medium | **New** (residual of H3) |
| M7 | Chart windows do not roll over at UTC midnight on an unattended display | Medium | **New** |
| M8 | "Fade off" preference comes back after a reload as a control that shows "fade 1 min" | Medium | **New** |
| L1 | Top-bar version is hardcoded | Low | **Open, partly mitigated.** `make bump-version` exists, but it copies a `package.json` version that is never bumped |
| L2 | Staleness threshold is a user preference, not an operator policy | Low | **Open.** Unchanged |
| L3 | Session and auction records are session-local in the browser | Low | **Partly addressed.** Documented in the user guide; the empty-state wording still claims more than the browser knows |
| L4 | Trade Tape row key collides after a `pm-md-gwy` restart | Low | **New** |

## Sign-off decision

**Unchanged: I still cannot give an unconditional production sign-off.**

The implementation is much stronger than the previous review snapshot, and most of the stale-data controls are in place:

- all main views are hidden while the browser socket is offline
- bridge-held TOP/STATE/CB state is replayed when the browser reconnects
- live data age is tracked separately from socket health
- TRADE sequence gaps are detected and repaired, and holes that cannot be repaired are shown on the tape
- prices use per-symbol tick precision
- change is measured against the previous close, and falling back to the open is labelled
- quotes that cannot be executed are dimmed
- during call phases, auction indicative fields replace the quote columns

There are no Critical code findings. The open High items block sign-off. H1 and H2 concern production evidence and whether the event record is complete. H4 is new: the "hide everything when offline" control only works when the TCP connection actually closes, and a half-open connection never closes.

I would sign off now for a controlled read-only pilot or classroom deployment. I would sign off for production after steps 1–4 of the implementation plan below are done (H4, H2, M6 and H3's regression test, M1/M2) and one live-stack soak run passes (H1).

## Critical

No Critical findings.

When the browser socket closes, the view is replaced by a disconnected state. When the socket is open but market data is silent, the status strip reports live tick age, and rows with old prints are faded rather than recoloured as current. H4 qualifies the first half of this: the path is correct once the browser learns the socket is gone, but nothing makes it learn that promptly.

## High

### H1. Production sign-off still lacks a live-stack failure-mode soak

**Status 2026-09-17: Open.** Since the review, the production container and Compose path exists: `deployment/docker/compose.guis.yaml` builds `terminal-gui`, and `make up-all` resolves the per-config read-only API key automatically. The remaining gap is unchanged, though. Nothing under `tests/`, `deployment/` or `web-apps/terminal-gui/` drives the assembled stack through failures.

The unit and component coverage is unusually good. But the remaining production risks sit across process boundaries: `pm-md-gwy`, `pm-api-gwy`, the bridge, browser reconnect, replay buffers, history outages, gateway restart, and container networking. What is missing is a repeatable live-stack smoke or soak that proves the assembled system behaves as it does in isolation when real processes fail in sequence.

Minimum sign-off scenario:

1. Start `pm-md-gwy`, `pm-api-gwy`, `pm-log-srv`, and `pm-terminal` from the production container/Compose path (`deployment/docker`, `make up-all`).
2. Confirm Overview, Symbol Detail, Movers, Trade Tape, Index, and Session views populate from a live engine config.
3. Drop and restore the browser WebSocket. Verify the app hides values while offline and replays current book, session and halt state on reconnect.
4. Blackhole the browser WebSocket without closing it, for example by pausing the bridge container. Verify the app goes OFFLINE within the heartbeat window (see H4).
5. Drop and restore the bridge-to-CALF connection. Verify fresh snapshots repair the state-backed streams, and Trade Tape gaps are either backfilled or explicitly marked.
6. Force a `TRADE` replay miss. Verify the tape shows a gap marker at the gateway timestamp.
7. Force an `AUCTION` gap. Verify the Session board does not present the auction list as complete.
8. Stop `pm-api-gwy`. Verify every history-backed view, Symbol Detail and Index included, reports that the service is unavailable rather than "no history" or blank fields.
9. Restart `pm-md-gwy`. Verify sequence re-baselining does not black out streams, duplicate prints, or produce React key warnings on the tape (L4).

Until that exists, production sign-off depends on operators being disciplined by hand rather than on a gate anyone can rerun.

### H2. AUCTION gaps are broadcast but not displayed anywhere

**Status 2026-09-17: Open.** `apps/web/src/store/useLiveStore.ts:326-339` still returns `{}` for any `gap` frame whose `ch` is not `TRADE`. The bridge still emits them: `apps/bridge/src/calf/uplink.ts` `checkForGap` sends `AUCTION` down the non-resumable, non-snapshot branch, and `server.ts:77-80` broadcasts it. The store's own comment says AUCTION is the *more common* of the two gap kinds today. `views/Session.tsx:92-143` has no gap input.

The bridge emits unrepaired gaps for channels it cannot repair. The browser store keeps `TRADE` gaps and deliberately drops the others, because the Trade Tape should only say "prints were missed" about `TRADE`. That filtering is right for the tape, but nothing consumes `AUCTION` gaps instead.

Result: if the bridge misses an auction result and cannot repair it, the Session view's "Recent auction results" list can be incomplete with no visible marker. This is the class of issue already fixed for the Trade Tape: a record with an unmarked hole invites users to quote from an incomplete record. Auctions are high-significance events, so a visible gap marker is better than a list that looks complete.

Recommended fix: add an `auctionGaps` buffer to the live store and keep `gap` frames for `AUCTION` in it. Render gap rows interleaved by timestamp in the Session board's auction table, reusing `mergeTapeRows`'s merge approach. Symbol Detail's auction banner should say nothing about gaps: it shows the newest result, not a record.

### H3. History failures in Symbol Detail can be rendered as "no history"

**Status 2026-09-17: Fixed** in `0b9f75ae`, and the fix is still in place. `views/SymbolDetail.tsx:145-168` captures `isError` for the series and snapshots queries into `chartError`, and `:308-313` renders "History service unavailable" before the empty-history message. Two follow-ups remain:

- **No regression test.** Nothing under `apps/web/test/` asserts "History service unavailable". The plan below adds one.
- **The daily-today query was not covered.** The original recommendation named it, but `dailyToday` (`:135-143`) still ignores `isError` and age. It is now tracked as M6.

Original finding, for context: the chart query tracked loading but not error state, so a failed `/api/history/trades` or `/api/history/daily` fell through to "No history recorded for {sym} in this window."

### H4. No liveness check on the browser↔bridge WebSocket (new)

The review's central stale-data control is `AppShell` replacing every view with "Disconnected… values are hidden" once `wsStatus !== "open"`. That status only changes when the browser's `WebSocket` fires `close` (`apps/web/src/lib/ws.ts:76`), and a browser only fires `close` when the TCP connection really ends. A **half-open** connection never fires it. Common causes are a NAT or reverse-proxy idle timeout, a Wi-Fi or VPN change, laptop sleep/resume, or a paused or partitioned container with no RST.

On a half-open connection the tab stays "LIVE" and keeps showing every price, at full confidence, indefinitely.

Nothing in the protocol can catch this today:

- The browser never sends anything periodically. The `ping` client frame exists in the types but is never sent.
- The bridge sends `bridge_status` only when CALF connection state changes (`apps/bridge/src/server.ts:57-63`). A healthy quiet feed and a dead socket therefore look identical from the browser.
- The only symptom is the footer's "last tick … ago" turning amber after 120 s (M3). A thin classroom book produces that same symptom routinely.

The same gap exists on the bridge side:

- `ws-fanout.ts` never pings its clients.
- `send` (`:189-191`) ignores `bufferedAmount`.
- A dead or stalled tab keeps its `DEPTH`/`CB` reference-count holds, accumulates outbound frames in bridge memory, and counts toward `MAX_WS_CLIENTS` (default 200) until the OS TCP timeout fires, which can take many minutes.

This is High rather than Medium because it bypasses the one control the review relies on for "no data is preferred over stale data".

Recommended fix:

1. **Bridge heartbeat.** Broadcast `bridge_status` on a fixed interval (for example every 5 s) as well as on change. It is already excluded from `MARKET_DATA_FRAMES`, so it will not reset the data-age clock.
2. **Browser watchdog.** In `TerminalStreamClient`, close the socket if no frame of any type has arrived for three heartbeat intervals. The existing close → reconnect → replay path then does the rest, including the OFFLINE blanking.
3. **Bridge-side reaping.** Send protocol-level `ping` frames to each client, `terminate()` any socket that misses a pong, and close with 1013 any tab whose `bufferedAmount` exceeds a fixed ceiling. Either way `unregister` releases its holds.

## Medium

### M1. Index View lacks the same explicit history-outage handling

**Status 2026-09-17: Open.** `views/IndexView.tsx:60-78` destructures only `data` from the snapshots, daily and events queries, and no error is rendered anywhere in the view.

Index View takes the headline level from live `INDEX` frames, which is the right source. The historical chart and the "Recent changes" strip are REST-backed, but query errors are not surfaced. A failed index-history call can leave an empty or live-tail-only chart with nothing telling the user the history service is unavailable.

Recommended fix: mirror the Overview/Movers pattern. Show a small warning when index snapshots, daily rows or events fail. Keep the live level visible.

### M2. Default Index View hides Open/High/Low on intraday timeframes

**Status 2026-09-17: Open.** `IndexView.tsx:93` reads `todayRow` from `dailyRows`, which is disabled on intraday timeframes (`:66-71`), so O/H/L render as `—` on the default `1D` screen (`:166-168`).

**Correction to the recommended fix:** the live data contract already carries these values. `pm-md-gwy`'s normaliser emits `OPEN`/`HIGH`/`LOW` on `IDX` (`src/edumatcher/md_gateway/normaliser.py:396-415`), `packages/calf-protocol/src/decode.ts:308-310` decodes them, `IndexFrame` types them (`packages/terminal-types/src/ws.ts:140-142`), and `useLiveStore` merges them into `indexLive`. The view just never reads them.

Recommended fix: take Open/High/Low from `snapshot.open/high/low`, the live frame, on every timeframe. Drop the `todayRow` path for the values panel. That also brings the view in line with its own module rule that headline figures come from the live stream (§10.2a), and removes the intraday/daily source mixing that the current comment tries to avoid.

### M3. Live-feed silence is visible but not forceful

**Status 2026-09-17: Open.** The threshold is still hardcoded (`lib/data-age.ts:35`, `live: 60`, flagged at 2×) and the warning appears only in the footer (`components/layout/StatusStrip.tsx:89-94`). Until H4 lands, this footer is also the only signal of a half-open socket.

If the browser socket and the CALF connection both stay open while no market-data frames arrive for a long time, the main views keep rendering and only the footer's "last tick … ago" warns. For thin classroom markets that may be right; for production it is too quiet.

Recommended fix: make the live-feed late threshold an operator setting, delivered in `hello` (see L2). Once the age exceeds it while CALF is `ACTIVE`, show a board-level warning. Do not hide data unconditionally, because a quiet market is real.

### M4. Previous-close age is defined but not surfaced

**Status 2026-09-17: Open.** `lib/data-age.ts` still models `prevClose` with a five-minute cadence, and nothing renders it: only `live` (StatusStrip) and `daily` (Overview footer) are shown. `lib/usePrevCloses.ts:60-67` itself documents why this matters. If the refetch fails across a session rollover, every baseline silently slips one session and `unavailable` stays false because the map is populated.

Recommended fix: return `dataUpdatedAt` from `usePrevCloses`. Render "previous close Xm old" in the Overview and Movers footers, flagged with `isLate("prevClose", …)`, next to the existing "session totals" age.

### M5. Halt countdown and "halted for" timers freeze between frames (new)

`views/Session.tsx:178` renders `resumeAt(cb.resumeAt)`, which shows `HH:MM:SS (mm:ss)` remaining, and `:183` renders `elapsed(entry.since)`. `views/SymbolDetail.tsx:520` renders "Not before …" the same way. All three read `Date.now()` at render time, and nothing makes these components re-render with time:

- The Session view selects only `sessionPhase`, `halted`, `auctions` and prefs.
- Symbol Detail re-renders on that symbol's frames, and a halted symbol usually has none.

The countdown therefore sits on whatever it showed when the last relevant frame arrived. For example, "(04:59)" can still be on screen three minutes later. That is a stale time presented as current, on the view operators watch during a halt. `StatusStrip` and `Overview` already use `useNow` for exactly this reason.

Recommended fix: call `useNow(1_000)` in `HaltRow` and `HaltDetail`, and pass `now` into `resumeAt` and `elapsed`, which already accept it.

### M6. Symbol Detail session statistics ignore history failure and age (new; H3 residual)

`views/SymbolDetail.tsx:135-143` polls `dailyToday` every 10 s but uses only `data`. It feeds Open, High, Low, VWAP, Vol, average trade size and the `buildRows` change figures. There are two failure shapes:

- **Failure before the first success:** every one of those fields shows `—` with no explanation. The Overview explains the same condition ("Open, volume and turnover unavailable — the history service is not reachable").
- **Failure after a success:** TanStack Query keeps the last `data` on a failed refetch. The panel then keeps showing the last good High/Low/VWAP/Volume as if they were current, while `last` from CALF keeps moving. That is stale data mixed with live data in one panel.

Recommended fix: capture `isError` and `dataUpdatedAt`. Render the Overview's notice on error, and a "session totals Xs old" age flagged with `isLate("daily", …)` beside the statistics.

### M7. Chart windows do not roll over at UTC midnight on an unattended display (new)

`SymbolDetail.tsx:133` computes `spec = useMemo(() => timeframeSpec(preset), [preset])`, and `IndexView.tsx:57` computes `from = useMemo(() => indexRangeStart(tf), [tf])`. Both evaluate `Date.now()` once and never again. On a lobby display left on `1D` or `Live` across midnight UTC:

- The query key still says yesterday. The chart spans two sessions.
- Symbol Detail still draws today's VWAP and the previous-close line across the whole window. That is exactly the misleading-benchmark failure the `startOfDay` comment in `lib/timeframe.ts:34-47` exists to prevent (T-H2).

`usePrevCloses` already solved this for its own query by deriving the key from the date on every render (`:68`). The chart windows did not get the same treatment.

Recommended fix: add a `useUtcDate()` hook (a `useNow(60_000)` sliced to `YYYY-MM-DD`) and include it in both `useMemo` dependency lists, so the window and query key move at the rollover.

### M8. "Fade off" preference comes back after a reload as a control that shows "fade 1 min" (new)

`STALE_AFTER_CHOICES` uses `Infinity` for "off" (`store/usePrefsStore.ts:51`), and the store persists it through zustand's JSON storage. `JSON.stringify(Infinity)` is `null`. I confirmed this against the current store: after `setStaleAfterSec(Infinity)` and a rehydrate, the persisted state is `"staleAfterSec":null`. After a reload:

- Fading happens to stay off, because `Number.isFinite(null)` is false.
- The `<select>` gets `value="null"`, which matches no option (`views/Overview.tsx:307`), so the browser displays the first option: **"fade 1 min"**.
- The footer legend "faded row = no print in …" disappears (`:451`).

A reader is told that unfaded rows printed within the last minute when nothing is being faded at all. Low effort to fix, but it misstates what the display means, which is the question this review exists to answer.

Recommended fix: represent "off" as a JSON-safe literal (`"off"`) in the type, the choices, `isStale` and `staleLabel`. Keep `null` free to mean "follow the operator default" for L2, matching the existing `pageDelaySec` convention. No migration is needed: a value already persisted as `null` becomes "follow default".

## Low

### L1. Top-bar version is hardcoded

**Status 2026-09-17: Open, partly mitigated.** `components/layout/TopBar.tsx:17` is still `const VERSION = "v0.1.0"`. Commit `04d9e98a` added `make bump-version`, which `make up` and `make cdist` run. It `sed`-rewrites that constant from `package.json`, but three problems remain:

- `package.json` is itself `0.1.0` and is not bumped by `scripts/mkghrelease.sh`, while the product is at `0.39.1`.
- The `deployment/docker` release path never runs the target.
- It rewrites a tracked source file as a side effect of a build.

The displayed version is still wrong in every build.

Recommended fix: have the bridge report the release version in `hello`, set at image build from the release tag, and render that. A dev build shows `dev`. Then delete `bump-version` from `web-apps/terminal-gui/Makefile`. `trader-gui` and `config-gui` use the same target and have the same problem, but they are outside this review's scope.

### L2. Staleness threshold is a user preference, not an operator policy

**Status 2026-09-17: Open.** All thresholds are still client-only (`usePrefsStore`, default `staleAfterSec: 300`; `data-age.ts` constants).

The Overview row-fade threshold is configurable in the browser and persisted to local storage. That is useful for traders, but a production display may need an operator-set default so every kiosk or browser starts with the venue's intended policy.

Recommended fix: add bridge config (for example `STALE_AFTER_SEC`, `LIVE_LATE_AFTER_SEC`) and send it in `hello`. The user's choice stays an override, and `null` means follow the operator default (see M8).

### L3. Session and auction records are session-local in the browser

**Status 2026-09-17: Partly addressed.** `docs/user-guide/290-trader-info-terminal.md` ("Session & Halt Status Board") now states that Recent auction results is "a session-scoped, client-side ring buffer of every auction uncross seen since the tab opened". That is the documentation half of the original recommendation. The UI still overclaims, though: after a mid-session reload, the empty state reads **"No auctions completed yet this session"** (`views/Session.tsx:94`), which is false. The browser only knows about auctions since the tab opened.

Recommended fix: change the empty state and panel subtitle to "since this page was opened". A REST-backed recent-events source remains the option if operators need a record that survives a refresh.

### L4. Trade Tape row key collides after a `pm-md-gwy` restart (new)

`views/TradeTape.tsx:188` keys print rows by `` `${t.sym}-${t.seq}` ``. `SEQ` is per stream and held in gateway memory. After a `pm-md-gwy` restart the bridge correctly adopts the restarted numbering (`uplink.ts` `StreamPosition.gen`), but the browser's 500-print buffer still holds the pre-restart prints. On a thin symbol, where old and new low sequence numbers both fall within the 200 visible rows, two rows share a key. React then warns and may reuse or omit rows. This is H1 step 9.

Recommended fix: include `ts` in the key, as `Session.tsx` already does for auctions (`${sym}-${seq}-${ts}`).

## Notes (not findings)

- `store/useLiveStore.ts:341-342`: the `// Frames no view consumes yet.` / `return {};` after the `gap` case is unreachable, because the case above returns on both branches. Once H2 lands the comment is also wrong. Leave it for whoever implements H2 to remove as part of that change.

## Implementation plan (priority order)

The order is: the stale-data controls the review depends on first, then completeness of the event record, then views that show incorrect information, then polish. Each step is sized to be one commit. Steps 1–4 are the production sign-off set; step 11 (H1) is the gate that validates them. The soak script itself can be written in parallel with steps 1–4.

After every step, from `web-apps/terminal-gui/`: `make typecheck`, `make test`, `npm run build`.

| # | Findings | Change | Main files | Tests to add | Done when |
|---|----------|--------|------------|--------------|-----------|
| 1 | **H4** | Periodic `bridge_status` heartbeat. Browser watchdog closes a silent socket after 3 intervals. Bridge pings clients, terminates on a missed pong, and closes tabs above a `bufferedAmount` ceiling | `apps/bridge/src/server.ts`, `apps/bridge/src/ws-fanout.ts`, `apps/bridge/src/config.ts`, `apps/web/src/lib/ws.ts` | `ws-resubscribe.test.ts`: a silent socket goes `reconnecting` after the window (fake timers), and the heartbeat does not move `lastTickAt`. `ws-fanout.test.ts`: an unresponsive client is terminated and its holds released | A blackholed socket shows OFFLINE within ~15 s |
| 2 | **H2** | `auctionGaps` store buffer. Interleaved gap rows in "Recent auction results". Remove the dead `return {}` | `store/useLiveStore.ts`, `views/Session.tsx` | `live-store.test.ts`: AUCTION gap kept, TRADE gap still separate. `session-view.test.tsx`: gap row renders between results by `ts` | An AUCTION gap is visible on the Session board |
| 3 | **M6**, H3 follow-up | `isError`/`dataUpdatedAt` on `dailyToday`, with the Overview-style notice and age. Add H3's missing regression test | `views/SymbolDetail.tsx` | `symbol-detail.test.tsx`: series fetch rejects → "History service unavailable". Daily fetch rejects → notice. Daily fetch fails after a success → age shown and flagged late | No Symbol Detail history failure renders as blank or as current |
| 4 | **M1**, **M2** | Take Index O/H/L from the live `INDEX` frame. Warning line for failures of the snapshots, daily or events queries | `views/IndexView.tsx` | New `index-view.test.tsx`: O/H/L shown on `1D` from a live frame, and each failing query shows its warning while the live level stays visible | Index View default screen shows O/H/L, and outages are stated |
| 5 | **M7** | `useUtcDate()` hook, added to the `spec` and `from` memo dependencies | `lib/staleness.ts` (next to `useNow`), `views/SymbolDetail.tsx`, `views/IndexView.tsx` | Fake-timer test crossing 00:00 UTC: the query key and window move to the new day | A `1D` chart left open over midnight shows only today |
| 6 | **M5** | `useNow(1_000)` in `HaltRow` and `HaltDetail`, passing `now` into `resumeAt` and `elapsed` | `views/Session.tsx`, `views/SymbolDetail.tsx` | `session-view.test.tsx`: advance fake timers → countdown and elapsed text change with no new frame | Halt timers tick |
| 7 | **M8** | Represent "off" as `"off"`, not `Infinity` | `store/usePrefsStore.ts`, `lib/staleness.ts`, `views/Overview.tsx` | `prefs.test.ts`: "off" survives persist and rehydrate. `staleness.test.ts`: update the `Infinity` case | After a reload the control shows what is in force |
| 8 | **L2**, **M3** | Bridge config `STALE_AFTER_SEC` and `LIVE_LATE_AFTER_SEC` sent in `hello`. The store holds them. `null` preference follows the operator default. Board-level "no market data for …" banner once live age exceeds the threshold while CALF is `ACTIVE` | `apps/bridge/src/config.ts`, `server.ts`, `packages/terminal-types/src/ws.ts`, `store/useLiveStore.ts`, `store/usePrefsStore.ts`, `lib/data-age.ts`, `components/layout/AppShell.tsx` | `live-store.test.ts`: hello thresholds stored. `data-age.test.ts`: `isLate` uses them. Banner render test | An operator can set venue policy, and abnormal silence is hard to miss |
| 9 | **M4** | Show previous-close age in the Overview and Movers footers | `lib/usePrevCloses.ts`, `views/Overview.tsx`, `views/Movers.tsx` | `overview-view.test.tsx`: age rendered and flagged late past 2× cadence | All three data clocks are visible |
| 10 | **L4**, **L3**, **L1** | Tape key includes `ts`. Session empty state says "since this page was opened". Bridge reports release version in `hello`, TopBar renders it, `bump-version` target removed | `views/TradeTape.tsx`, `views/Session.tsx`, `apps/bridge/src/config.ts`, `server.ts`, `packages/terminal-types/src/ws.ts`, `components/layout/TopBar.tsx`, `Dockerfile`, `Makefile` | `trade-tape.test.ts`: two prints with equal `sym`/`seq` and different `ts` both render. TopBar shows the hello version | — |
| 11 | **H1 (gate)** | Scripted live-stack soak covering the nine scenarios in H1, run against `deployment/docker` `make up-all` | new script under `deployment/docker/` (or `tests/`), plus a `make` target | The soak is the test | One clean run recorded, then production sign-off |

## Review answers to the requested questions (updated 2026-09-17)

1. **Is correct information displayed, or do we risk stale data?** Mostly correct. The remaining stale-data risks are:
   - a half-open socket that keeps showing values at full confidence (H4)
   - Symbol Detail statistics kept after a history failure (M6)
   - halt timers that freeze (M5)
   - `1D` charts that span two sessions after midnight (M7)
   - a fade control that misreports what is in force (M8)
   - AUCTION gaps that are not displayed (H2)
2. **Is no data preferred over stale data?** Yes, when the socket actually closes, and for missing prices and baselines. Not yet for a half-open socket (H4), for Index history (M1), or for Symbol Detail session statistics (M6).
3. **Are calculations what most traders expect?** Mostly yes: per-symbol price precision, change vs previous close, Movers active ranked by value traded, notional turnover, qualified quote execution state, and VWAP limited to same-day windows. The same-day limit only holds until midnight on an unattended display (M7).
4. **Is the display logically arranged?** Yes overall. The main UX gap is still Index O/H/L on the default timeframe (M2), and it is now a one-line data-source change.
5. **Remaining race conditions?** No unresolved browser/bridge ordering race was found. Reconnect subscription replay, bridge cache replay, top-of-book withdrawal handling and trade gap repair are covered by tests. The remaining cross-process weakness is liveness detection (H4), not ordering. Cross-process confidence still needs the H1 soak.
6. **Plain logical errors?** No Critical ones. The new ones are the `Infinity` persistence round trip (M8) and the tape row-key collision after a gateway restart (L4).
7. **Can I sign it off for production?** Not unconditionally. It can be signed off now for controlled read-only pilot use. For production, it needs plan steps 1–4, then a clean `make typecheck`, `make test` and `npm run build`, then one clean run of the H1 soak.
