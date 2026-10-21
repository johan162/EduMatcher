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
| 1 | WP-UI02 | Add tooltip and better help text  | - | 0.5 d | ☐ | |



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
that are not obvious

1. **WP-UI02.1**: pm-log On the dashboard page the fields "total events", "error rate", "warnings", "processes", "log server"
should be tooltipped. 
2. **WP-UI02.2**: pm-log. BUG 1: When the log-srv is shut dow the "log server" still shows "UP" 
3. **WP-UI02.3**: pm-dash. The columns header in the second dashboard row that shows a table of processes needs explanation vy a tooltip (perhaps a separate circled "i" to be clicked)
4. **WP-UI02.4**: pm-trader. The current help text (top right corner "?") is too compact. Each order type needs a much more extensive and formatted description.