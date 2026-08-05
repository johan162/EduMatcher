# EduMatcher Terminal GUI Final Production Review

**Date:** 2026-08-03  
**Scope:** `terminal-gui/` bridge, browser store, views, calculation helpers, tests, and the CALF top-of-book normalisation path that feeds it.  
**Validation run:** `cd terminal-gui && npm test` — 36 test files passed, 675 tests passed.

## Sign-off decision

I cannot give an unconditional production sign-off yet.

The implementation is much stronger than the previous review snapshot: the most dangerous stale-data failures have been addressed. The app hides all main views when the browser socket is offline, replays current bridge-held TOP/STATE/CB state on browser reconnect, tracks live data age separately from socket health, detects and repairs TRADE sequence gaps, surfaces unrepaired tape holes, uses per-symbol tick precision, computes change against previous close, distinguishes open-baseline fallback, dims non-executable quotes, and replaces quote columns with auction indicative fields during call phases.

There are no Critical code findings in this pass. The remaining High findings are sign-off blockers because they concern production evidence and event-record correctness rather than cosmetic polish. I would sign off for a controlled read-only pilot or classroom deployment. I would sign off for production after the High items below are closed and one live-stack soak run passes.

## Critical

No Critical findings.

The current code does not show an obvious path where connected browser views continue displaying known-stale prices with full confidence after a socket outage. The main stale-data posture is now correct: when the browser socket is offline, the view is replaced by a disconnected state; when the socket is open but market data is silent, the status strip reports live tick age and rows with old prints are faded instead of being recoloured as current.

## High

### H1. Production sign-off still lacks a live-stack failure-mode soak

The unit and component coverage is unusually good, and the focused test run passed. But the remaining production risks sit across process boundaries: `pm-md-gwy`, `pm-api-gwy`, the bridge, browser reconnect, replay buffers, history outages, gateway restart, and container networking.

The code has targeted tests for many of these pieces in isolation, especially bridge gap detection and browser rendering. What is missing before production is a repeatable live-stack smoke or soak that proves the assembled system behaves the same way when real processes fail in sequence.

Minimum sign-off scenario:

1. Start `pm-md-gwy`, `pm-api-gwy`, `pm-log-srv`, and `pm-terminal` from the production container/Compose path.
2. Confirm Overview, Symbol Detail, Movers, Trade Tape, Index, and Session views populate from a live engine config.
3. Drop and restore the browser WebSocket; verify the app hides values while offline and replays current book/session/halt state on reconnect.
4. Drop and restore the bridge-to-CALF connection; verify fresh snapshots repair state-backed streams and Trade Tape gaps are either backfilled or explicitly marked.
5. Force a `TRADE` replay miss; verify the tape shows a gap marker at the gateway timestamp.
6. Force an `AUCTION` gap; verify the Session board does not present the auction list as complete.
7. Stop `pm-api-gwy`; verify history-backed views report service unavailability rather than “no history”.
8. Restart `pm-md-gwy`; verify sequence re-baselining does not black out streams or duplicate prints.

Until that exists, production sign-off depends on manual operator discipline rather than a reproducible gate.

### H2. AUCTION gaps are broadcast but not displayed anywhere

The bridge emits unrepaired gaps for channels it cannot repair. The browser store keeps `TRADE` gaps and deliberately drops non-TRADE gaps, because the Trade Tape should only say “prints were missed” for `TRADE`. That filtering is locally correct, but there is no equivalent consumer for `AUCTION` gaps.

Result: if the bridge misses an auction result and cannot repair it, the Session view’s “Recent auction results” list can be incomplete without any visible marker. This is the same class of issue that was fixed for the Trade Tape: an event record with an unmarked hole invites users to quote from an incomplete record.

This is not as severe as stale quote display, but auctions are high-significance market events. Showing no auction result with a visible gap marker is better than showing an apparently complete auction list.

Recommended fix: add an `auctionGaps` buffer to the live store, keep non-TRADE `gap` frames for `AUCTION`, and render an explicit gap row or panel notice in the Session board’s auction section.

### H3. History failures in Symbol Detail can be rendered as “no history”

**FIXED**

Overview and Movers correctly distinguish live prices from history-service outages. Symbol Detail does not apply the same rule consistently. Its chart query tracks loading but not error state. If `/api/history/trades` or `/api/history/daily` fails, the chart can fall through to the empty-history message: “No history recorded for {sym} in this window.”

That is not stale data, but it is incorrect information. A trader reading “no history recorded” will reasonably infer the symbol had no prints or bars, not that the history service failed.

Recommended fix: capture `isError` for the chart query, daily-today query, and snapshots query where relevant. Render “history service unavailable” when the query failed, and keep “no history recorded” only for a successful empty response.

## Medium

### M1. Index View lacks the same explicit history-outage handling

Index View uses live `INDEX` frames for the headline level, which is the right source. The historical chart and Open/High/Low panel are REST-backed, but query errors are not surfaced. A failed index-history call can leave an empty or live-tail-only chart and absent O/H/L values without telling the user the history service is unavailable.

Recommended fix: mirror the Overview/Movers pattern: show a small warning when index snapshots, index daily rows, or index events fail. Keep live level visible, but qualify which historical fields are unavailable.

### M2. Default Index View hides Open/High/Low on intraday timeframes

The Index View defaults to `1D`, where `dailyRows` is disabled because intraday charts use snapshot history. The values panel reads Open/High/Low only from `dailyRows`, so on the default screen those fields are absent even though traders normally expect them beside the headline index level.

This is a UX and expectation issue rather than a stale-data issue. The code comment explicitly avoids mixing intraday and daily sources, but the resulting first impression is weaker than expected for a trading terminal.

Recommended fix: either fetch today’s index daily row independently for the values panel, or carry day open/high/low on the live `INDEX` frame if that is the preferred market-data contract.

### M3. Live-feed silence is visible but not forceful

The app distinguishes socket health from market-data age, which is good. However, if the browser socket and CALF connection remain open while no market-data frames arrive for a long period, the main views keep rendering and only the footer’s “last tick … ago” turns into the warning channel.

For thin classroom markets this may be exactly right; for production it may be too quiet. A connected-but-silent feed is one of the situations where stale display can look deceptively normal.

Recommended fix: make the live-feed late threshold operator-configurable and consider a board-level warning once the age exceeds the configured threshold. Do not hide data unconditionally; a quiet market is real. But make abnormal silence harder to miss.

### M4. Previous-close age is defined but not surfaced

`data-age.ts` models `prevClose` as its own source with a five-minute cadence, but the UI only visibly reports live tick age and daily/session-total age. Previous closes are slow-moving and cached failures after one success are intentionally quiet, which is reasonable. Still, the display says “change vs previous close” without exposing when that baseline was last refreshed.

Recommended fix: expose previous-close age in the Overview/Movers footer or status details, especially after session rollover. This is lower risk than the old previous-close outage bug because the fallback is now labelled, but it would complete the three-clock story already documented in the code.

## Low

### L1. Top-bar version is hardcoded

`TopBar` displays `v0.1.0` from a constant. In production this will drift unless releases remember to update the source file.

Recommended fix: inject the package version at build time or expose it from the bridge status endpoint.

### L2. Staleness threshold is a user preference, not an operator policy

The Overview row-fade threshold is configurable in the browser and persisted to local storage. That is useful for traders, but a production display may need an operator-set default so every kiosk or browser starts with the venue’s intended policy.

Recommended fix: keep the user override, but allow an environment/config default from the bridge or generated frontend config.

### L3. Session and auction records are session-local in the browser

Auction results and halt-ended context are in-memory buffers. That matches the read-only display design, but it means a refreshed browser loses the recent auction list until new events arrive.

Recommended fix: acceptable for production if documented as a viewer limitation. If operators need a post-event display that survives refresh, add a REST-backed recent-events source rather than stretching the live store into persistence.

## Review answers to the requested questions

1. **Is correct information displayed, or do we risk stale data?** Mostly correct. The main stale-data controls are now in place. Remaining risks are history-failure mislabelling and undisplayed AUCTION gaps.
2. **Is no data preferred over stale data?** Yes in the main socket-offline path and for missing prices/baselines. Some history failures still need to say “unavailable” instead of “none recorded”.
3. **Are calculations what most traders expect?** Mostly yes: price precision is per symbol, change is previous-close based, Movers active ranks by value traded, turnover is notional, quote execution state is qualified, and VWAP is limited to same-day charts.
4. **Is the display logically arranged?** Yes overall. Overview and Symbol Detail are much better organized than the earlier review state. Index O/H/L on the default timeframe is the main UX gap.
5. **Remaining race conditions?** No obvious unresolved browser/bridge race was found in this pass. Reconnect subscription replay, bridge cache replay, top-of-book withdrawal handling, and trade gap repair are covered by tests. Cross-process race confidence still needs the live-stack soak in H1.
6. **Plain logical errors?** No Critical logical errors found. The significant logical issues are event-gap visibility for auctions and history-failure wording.
7. **Can I sign it off for production?** Not unconditionally. I can sign off for controlled read-only pilot use now. Production sign-off should wait for H1-H3 to close, followed by a clean `npm test`, `npm run typecheck`, `npm run build`, and the live-stack soak described in H1.
