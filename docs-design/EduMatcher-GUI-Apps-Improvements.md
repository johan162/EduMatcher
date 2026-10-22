# EduMatcher — Improving existing GUI Application for coherence and usability


This design document will record ideas hoe to align the fve different GUI applications
1. **pm-log** - The log server
2. **pm-trader** - The trading plaform 
3. **pm-terminal** - The "Tapedeck" info terminal
4. **pm-dash** - Operator dashbaóard
5. **pm-book** - The order book viewer

Started: 2026-10-21

## Status

Legend: ☐ not started · ◐ in progress · ☑ done (awaiting/after commit)

| # | WP | Content | Depends on | Est. | Status | Done on |
|---|---|---|---|---|---|---|
| 1 | WP-UI01 | Add Session state and time to next states | - | 0.5 d | ☑ | 2026-10-21 |
| 2 | WP-UI02 | Add tooltip and better help text  | - | 0.5 d | ☑ | 2026-10-21 |
| 3 | WP-UI03 | Harmonize all ONLINE/OFFLINE top row badges  | - | 0.5 d | ☑ | 2026-10-22 |
| 4 | WP-UI04 | Analyse chnanges to make the different GUI harmonized | - | 0.5 d | ☐ |  |


## Workpackages

### WP-UI01 - Add Session state and time to next states


In `pm-trader` top-row there is a highlighted current sessions state with the next state indicated as well as the
time left until state-changes, 
The format used is

```
<CURRENT STATE>  ->  <NEXT STATE> in <TIME TO STATE CHANGE>  <CURRENT TIME>
```

For example

```
CONTINUES -> Closing Auction in 03:08.23  12:51:37
```

The same indication, using identical color schema and fonts should be added to the oter relevant GUI apps listed below. All should follow identical design and have it in the top row excep "pm-terminal" who needs it at the bottom status row due to navigation in the top row.

   | GUI App   | Position  | WP Step | 
|-----------|-----------|---------|
| pm-dash   | Top row   |  WP-UI01.1       |
| pm-terminal | Bottom status row | WP-UI01.2 |
| pm-book  | Top row | WP-UI01.3 |
| pm-log  | Top row | WP-UI01.4 |  

If the exchange is started outside traing hours and before the proper states has been determined the state should be shown as "UNKNOWN" usually just takes a second or two to resolve. See `pm-trader` logic for fetching current and next state. It cold also be gotten from `md-gwy` . Whatever is easiest.

**Open Questions:**

Q1: How can pm-log web/bridge get hold of SESSION state? We want to avoid API since that requires a login and API-token

*Answered:* from `pm-md-gwy` over CALF. CALF needs no credentials (`HELLO|CLIENT=..|PROTO=CALF1`), and
`SUB|CH=STATE|SYM=*` answers at once with a `SNAP` carrying `SESSION` plus, when known, `NEXTPHASE`/`NEXTAT`.
md-gwy starts at `SESSION=UNKNOWN` and resolves it by querying the engine, which is exactly the "UNKNOWN"
behaviour asked for above.

**Decisions (2026-10-21):**

- D1: pm-dash, pm-book and pm-log bridges each open one CALF connection to md-gwy (same source as pm-terminal)
  and forward a small `session` frame `{state, nextState, nextAt}` to the browser. One code path, one behaviour.
- D2: pm-trader also shows `UNKNOWN` until its first session state arrives (it showed `Closed` before).
- D3: The trailing clock is in the exchange session timezone in pm-dash, pm-terminal, pm-book and pm-log.
  pm-trader keeps browser local time: it has no timezone source (see follow-up F1).
- D4: Existing session read-outs are replaced by the new indicator: pm-terminal's status-row phase text,
  badge, countdown and right-hand clock; pm-dash's `STATE · trading-date` text (trading date moves to the tooltip).
- D5: Countdown format is pm-trader's `formatCountdown` (`MM:SS`, `HH:MM:SS` from one hour). When no next
  transition is known the indicator shows the badge and clock only — never a countdown to zero.

**Follow-ups:**

- F1: Carry `session_timezone` in the reference bundle / `/reference/schedule` so pm-trader's clock and its
  schedule-fallback countdown can use the exchange timezone instead of browser local time.
- F2: md-gwy only learns the next transition from a scheduler-driven `session.state`; if it restarts
  mid-phase, CALF clients get no countdown until the next transition (pm-trader is unaffected thanks to its
  schedule fallback).

**Implementation notes (done 2026-10-21):**

- Bridges: `apps/bridge/src/calf-session.ts` (`CalfSessionUplink`) in dash-, book- and log-gui — one CALF
  connection, `SUB|CH=STATE|SYM=*`, reconnect with backoff, `UNKNOWN` while md-gwy is down or silent for
  10 s (it sends `HB` every second). Browser frame `market_session` (`{state, nextState, nextAt}`); not
  `session`, which book-gui already uses for a symbol's tape. Config `CALF_HOST`/`CALF_PORT`/`CALF_CLIENT_ID`,
  wired in the app compose files, `deployment/*/compose*.yaml` and `web-apps/Makefile` (`VM_BACKEND_IP`).
- Web: `components/SessionIndicator.tsx`, one copy per app (dash, book, log, terminal). The copies differ
  only in the clock formatter each app already has (`lib/time.ts`, `lib/format.ts`, `lib/formatTs.ts`) and
  in text tokens (log-gui has no `fg-faint`). Change them together.
- pm-trader: `useSessionClock().known` (`phaseSince !== null`) drives the `Unknown` badge; the store's
  `CLOSED` default stays, so order-entry logic is untouched.
- pm-terminal: `lib/session-countdown.ts` (overdue/imminent styling) removed with its test; the strip shows
  `Unknown` whenever the CALF feed is not LIVE.
- book-gui's clock uses the watched symbol's session timezone, so it reads UTC until a book is open.
- The tailwind-token guard tests (dash, book, terminal) read `bg-slate-500` as the token `slate-`, so no
  built-in palette shade could pass; fixed to strip the shade.

### WP-UI02 - Add tooltip and better help text 

As an educational tool we need to have explanation readily available to columns and data fields 
across the GUI applications.

1. **WP-UI02.1**: pm-log On the dashboard page the fields "total events", "error rate", "warnings", "processes", "log server"
should be tooltipped. 
2. **WP-UI02.2**: pm-log. BUG 1: When the log-srv is shut dow the "log server" still shows "UP" 
3. **WP-UI02.3**: pm-dash. The columns header in the second dashboard row that shows a table of processes needs explanation vy a tooltip (perhaps a separate circled "i" to be clicked)
4. **WP-UI02.4**: pm-trader. The current help text (top right corner "?") is too compact. Each order type needs a much more extensive and formatted description.

**Done 2026-10-21.** Scope was widened the four items to *every* table header and
field across the web GUIs. What exists now:

- **Convention:** a small "i" (`InfoTip`, or `FieldInfo` in pm-trader) beside the heading or label; it opens on hover
  *and* keyboard focus, is `role="tooltip"`, and is `position: fixed` from the trigger's rectangle so a scrolling
  table or truncated tile cannot clip it. The wording lives in one module per app (`lib/help.ts`; pm-trader:
  `lib/columnHelp.ts` + `lib/fieldHelp.ts`) and widgets look it up by the name already on screen, so a widget
  needs no extra prop. pm-dash: every `HealthTable` column, `StatTile`, `Gauge` and chart title. pm-book: the
  statistics fields, the BIDS/ASKS/TRADES titles and ladder columns. pm-terminal: Overview, Movers, Trade Tape,
  News, depth ladder, symbol detail and index rows. pm-log: dashboard tiles, Health rows, Connections columns.
  pm-trader: blotter, market table, positions, trade history, all admin tables, and the OCO / Combo / quote /
  amend / replace / kill-switch / halt forms. pm-config already had help on nearly every field; the table headers
  and the few fields without it were filled in.
- **WP-UI02.2 (bug):** a killed or crashed pm-log-srv never publishes its own `DOWN` (only a clean `stop()` does);
  the bridge's uplink noticed the missing heartbeats and went `SERVER_DOWN` internally but never told the
  browsers, so "log server" stayed `UP`. The bridge now broadcasts a synthesised `DOWN` (`server-state.ts`) and the
  web store forgets the server state whenever the socket to the bridge is not open.
- **WP-UI02.4:** the pm-trader help drawer is wider (680 px) and larger type, and has a topic per order family
  (Market & Limit, Stop / Stop-Limit / Trailing, FOK & IOC, Iceberg, OCO & Combo) with a glossary, a worked
  example and a callout each, plus new Order Status and Reading the Tables topics.

Insights:

- An `InfoTip` is a button, so any test or screen-reader query `getByRole("button", { name: /RSS/ })` now also
  matches "RSS help"; the two tests that did that were made exact. A `<label>` must not wrap an `InfoTip`
  (the label would bind to the button), so labelled forms became `<div>` + `aria-label` on the input, as
  `OrderTicket` already did.
- Help wording was checked against the code and the operator/participant guides rather than written from memory
  (for example the depth ladder's `%` is distance from the touch, the tape's Side is the aggressor, pm-trader's
  Chg % is against the open while pm-book's Chg is against the previous close). Where two apps show a
  similarly named figure on a different basis the text says so.
- The `InfoTip` component is copied per app (dash, book, terminal, log), like `SessionIndicator`; a shared package
  was not worth the build wiring for 40 lines.


### WP-UI03 - Harmonize all ONLINE/OFFLINE top row badges

All Web-apps that display a ONLINE/OFFLINE badge except one do it in an identical manner - a RED/GREEN Marker and the TEXT ONLINE/OFFLINE. The one not following this standard is pm-trader which uses a signal-strength icon + ONLINE/OFFLINE Text in the more middle of the top row.

- **WP-UI03.1** Change the pm-trader connection badge to be the same as for example pm-terminal ; a RED/GREEN Dot + the text ONLINE/OFFLINE further to the right in the top row, just to the left of the participant name.

- **WP-UI03.2** Add the same badge indicator to the log-gui in the top row and remove it as separate value in the dashbboard top row saying UP/DOWN to be consistent with the othre GUI


**Done 2026-10-22.** The existing standard in pm-dash, pm-book and pm-terminal is a dot plus **LIVE** /
RECONNECTING (CONNECTING in pm-dash) / **OFFLINE**, not the word ONLINE, so that wording was kept.
- pm-trader: the signal-strength icon is gone; the top bar's right group now ends with the same dot + word
  (green LIVE, amber RECONNECTING, red OFFLINE) immediately left of the gateway ID. The per-socket detail
  (events / market-data / monitor) stays as the hover title.
- pm-log: the same dot + word is in the right group of the top bar, followed by the server name and, when not
  LIVE, the cause ("log server down", "log.db unavailable"). The "Log server" tile is removed from the dashboard
  (grid 5 -> 4 tiles); its explanation moved into the badge's hover title.
- Not harmonised (left for WP-UI04): pm-log's dot colours use `bg-green-500`/`bg-yellow-500` Tailwind shades
  while the others use the `live`/`warn`/`offline` tokens, and pm-log and pm-trader still carry their own
  markup instead of a shared `StatusDot`.


### WP-UI04 - Analyse chnanges to make the different GUI harmonized

The different GUI was made at different times and while they are reasonable alike they still differ in some operational way, for example the log-GUI does not have a font scaling setting. It is only trader-fui that have a help button in the top row to the right. Since they below to the same system the app-framework , settings etc. should ideally be identical so the user can find things easier.

- **WP-UI04.1** Compare and analyse what minor and low-risk top level app-changes can or should be done to harmonize the different GUI apps. Create a list in this document as findings and suggest a way to fix each of the findings. 