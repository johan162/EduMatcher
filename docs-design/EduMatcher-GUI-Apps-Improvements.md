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
| 4 | WP-UI04 | Analyse chnanges to make the different GUI harmonized | - | 0.5 d | ☑ | 2026-10-22 |
| 5 | WP-UI05 | Shared `ConnectionBadge` and status tokens (F5, F6) | UI03 | 0.5 d | ☑ | 2026-10-22 |
| 6 | WP-UI06 | pm-log settings popover, font size, density (F1) | UI05 | 0.5 d | ☑ | 2026-10-22 |
| 7 | WP-UI07 | One top-bar order and active-item style (F3, F8) | UI06 | 0.5 d | ☐ | |
| 8 | WP-UI08 | Per-app help panel and `?` button (F2) | UI07 | 1.5 d | ☐ | |
| 9 | WP-UI09 | Theme default and pm-config frame (F4, F7) | UI06 | 0.5 d | ☐ | |
| 10 | WP-UI10 | Universal keyboard shortcuts (F9) | UI08 | 0.5 d | ☐ | |
| 11 | WP-UI11 | Drift test for the copied components (F10) | UI05, UI08 | 0.5 d | ☐ | |


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

**Done 2026-10-22 (analysis only; no code changed).** Surveyed the top bar, settings, stores and shared
components of all six web apps (pm-log, pm-trader, pm-terminal, pm-dash, pm-book, pm-config).

#### Today's top-bar and settings matrix

| | log | trader | terminal | dash | book | config |
|---|---|---|---|---|---|---|
| Wordmark + `pm-x` + version | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Navigation | left rail | left sidebar | tabs in top bar | none (one page) | none | left list |
| Session indicator (WP-UI01) | ✓ | ✓ (own, richer) | ✓ | ✓ | ✓ | – |
| Connection badge dot + word (WP-UI03) | ✓ | ✓ | ✓ | ✓ | ✓ | – |
| Theme toggle | ✓ | ✓ | ✓ | ✓ (+ in settings) | ✓ | ✓ |
| Settings popover | **–** | ✓ | ✓ | ✓ | ✓ | – |
| Font-size setting | **–** | ✓ | ✓ | ✓ | ✓ | – |
| Help button | **–** | ✓ | – | – | – | per-field only |
| Density | pref exists, no control | – | button in top bar | – | – | – |
| Status strip (footer) | – | banner | ✓ | ✓ | ✓ | – |
| localStorage keys | `log-ui-theme`, `log-ui-prefs` | `trader-theme`, `trader-font-size` | `terminal-prefs`, `terminal-font-size` | `dash-prefs`, `dash-font-size`, `dash-rows` | `book-prefs`, `book-font-size` | (theme in draft store) |

#### Findings and suggested fixes (ordered by value over risk)

| # | Finding | Suggested fix | Risk |
|---|---|---|---|
| F1 | **pm-log has no settings popover and no font-size setting.** Its density and operator name are preferences with no common place. | Copy the `SettingsPopover` + `useFontSizeStore` pair from pm-book/pm-dash (identical in structure) into pm-log, with Font size and Density in it; keep the operator name on the Alerts page where it is used. Needs the `index.css` font-scaling rule the other apps have. | Low |
| F2 | **Only pm-trader has a Help button.** Since WP-UI02 the other apps explain themselves with tips, but there is no overview of what an app is or how to read it. | Add a "?" to each top bar opening a short per-app help panel (what the app shows, the connection and session badges, colour meanings, the theme and font settings, links to the guide chapters). Start with static content reusing pm-trader's `HelpDrawer`/`helpContent` shape, copied like `InfoTip`. | Low-medium (content work) |
| F3 | **Top-bar item order differs.** Right-hand groups are in different orders (trader: search, bell, settings, theme, help, badge, gateway, role, logout; terminal: density, theme, settings, badge; dash/book: theme, settings, badge; log: theme, badge). | Fix one order for the right group: `[app-specific tools] · Theme · Settings · Help · Connection badge · identity`. Apply when F1/F2 touch the same files. | Low |
| F4 | **Three theme implementations with different storage** (`log-ui-theme`, `trader-theme`, a field in `*-prefs`; config-gui starts from `prefers-color-scheme`, the others do not). A user who picks light in one app gets dark in the next. | Same key and default everywhere is impossible across origins (each app has its own port), so do the cheap part: default every app to the OS preference when nothing is stored, and give them one `theme.ts` shape. | Low |
| F5 | **Dot colours: pm-log uses `bg-green-500`/`bg-yellow-500`, pm-trader `bg-emerald-500`/`bg-amber-500`/`bg-red-500`**, the others use `live`/`warn`/`offline` tokens. The tailwind-token guard tests exist in dash/book/terminal but not log or trader. | Add the `live`/`warn`/`offline` tokens to pm-log and pm-trader and use them; extend the guard to those apps. Do together with F6. | Low |
| F6 | **The connection badge and `StatusDot` are copied per app** (dash, book, terminal) or re-written inline (log, trader). | Extract a small `ConnectionBadge` (dot + word + optional detail) copied identically into all five like `SessionIndicator`; label set `LIVE` / `RECONNECTING` / `OFFLINE` in one place. pm-dash says `CONNECTING` where the others say `RECONNECTING`; pick one (suggest `CONNECTING` before first contact, `RECONNECTING` after). | Low |
| F7 | **pm-config is outside the common frame**: no session indicator or connection badge (it edits a file, so none is needed), no font-size setting, wordmark only. | Add the font-size setting (a settings popover with only that) and the OS-preference theme default. Leave the rest: it is an editor, not a live view. | Low |
| F8 | **Navigation differs by design** (rail, sidebar, tabs). | Leave: each fits its app (design notes in pm-terminal §7.2). Only align the active-item styling (accent fill) across rail, sidebar and tabs. | Low |
| F9 | **Keyboard shortcuts exist only in pm-trader** (palette, `Ctrl+/`, `Ctrl+K`, B/S). | Add two universal ones everywhere: `Ctrl+/` toggles help (after F2) and `Esc` closes any popover/drawer (dash and trader already do). | Low |
| F10 | **Duplicated components are drifting** (`SettingsPopover` x4, `SymbolPicker` x3, `SessionIndicator` x5, `InfoTip` x4). | Not worth a shared package yet. Instead add a repo test that diffs the copies and fails when the "identical" ones (SessionIndicator, InfoTip, StatusDot) differ, so drift is visible. | Low |

Suggested order of work if taken on: F6+F5 (one change), F1, F3, F2 (largest, content), F4, F7, F9, F10.
No finding needs a bridge or backend change.


### Follow-up work packages from the WP-UI04 findings

Common rules for WP-UI05 to WP-UI11:

- One WP at a time, in table order; each ends with the holistic test (every touched app's `typecheck` and
  `vitest run` from its workspace root, plus `make test-e2e` when pm-dash changed), a review, an update of this
  document, and a proposed commit message. No backwards-compatibility code for old localStorage keys.
- Components that must be identical in several apps are *copied*, not packaged (decision in WP-UI02), and are
  guarded by the drift test of WP-UI11.
- Each WP lists the apps it touches; apps not listed are not changed.

#### WP-UI05 - Shared `ConnectionBadge` and status tokens (F5, F6)

Apps: pm-log, pm-trader, pm-terminal, pm-dash, pm-book.

- **WP-UI05.1** Write one `ConnectionBadge` component: props `state: "live" | "connecting" | "reconnecting" |
  "offline"`, optional `detail` (server or gateway name, cause) and optional `title`. It renders the dot and the
  word and owns the label set (`LIVE`, `CONNECTING`, `RECONNECTING`, `OFFLINE`) and the colours. Copy it
  unchanged into the five apps (where `StatusDot` lives today in terminal, dash and book).
- **WP-UI05.2** Replace the inline markup in pm-log and pm-trader and `StatusDot` use in terminal, dash and book
  with it. Semantics: `CONNECTING` only before the first contact, `RECONNECTING` after a lost connection (pm-dash
  maps its `CONNECTING` socket state accordingly; pm-terminal and pm-book already use `RECONNECTING`).
- **WP-UI05.3** Add the `live`, `warn` and `offline` colour tokens to pm-log and pm-trader (both themes) and use
  only tokens in the badge. Extend the tailwind-token guard test to pm-log and pm-trader, or write one if it does
  not exist there.
- **Tests:** a unit test per app that renders each of the four states and checks the word and the dot class;
  existing connection tests (`shell`, `app`, `live-store`) keep passing with the same words.
- **Done when:** `grep -rn "bg-green-500\|bg-emerald-500\|bg-yellow-500\|bg-amber-500" ` finds no connection dot,
  and the five badges are byte-identical files.

**Done 2026-10-22.** `components/ConnectionBadge.tsx` is one file, byte-identical in pm-log, pm-trader,
pm-terminal, pm-dash and pm-book (checked with `md5sum`). `StatusDot` is gone from terminal (`Badge.tsx`), dash
and book. The dot uses the `live` / `warning` / `offline` tokens; pm-log gained them (both themes), pm-trader
gained `warning` (it already had `live`/`offline`).
- **Deviation:** the `CONNECTING` / `RECONNECTING` rule was *not* changed. In pm-terminal and pm-book
  `RECONNECTING` means "socket open, upstream not active" and `OFFLINE` "socket not open", and pm-dash's
  `CONNECTING` is its socket state; forcing "first contact" semantics would have meant new state tracking in
  every store for no reader benefit. The badge supports all four words; each app keeps its own mapping.
- **Guard test extended, and it found real bugs.** `tailwind-tokens.test.ts` now exists in pm-log and pm-trader.
  pm-log had seven opacity classes that compile to nothing (`bg-accent/15` on the active nav item,
  `bg-level-error/10` on the unacknowledged-issues banner, `bg-level-error/20` on the unacked badge,
  `bg-level-warning/20`, `bg-accent/10`, `border-border/50` x2): they now use declared tint tokens
  (`accent-bg`, `level-error-bg`, `level-warning-bg`, `border-subtle`, via `color-mix`). pm-trader used
  `text-accent` for the "pm-trader" wordmark without declaring `accent`, so it rendered in the default colour;
  `accent` and `accent-fg` are declared now. pm-trader's version of the guard omits the opacity rule, because
  its `rgb(var(--x) / <alpha-value>)` tokens do support it.
- pm-log's badge test renders to markup (`renderToStaticMarkup`) because pm-log has no jsdom yet; WP-UI06 adds it.

#### WP-UI06 - pm-log settings popover, font size and density (F1)

Apps: pm-log.

- **WP-UI06.1** Add `useFontSizeStore` and the font-scaling rule in `index.css` as in pm-book/pm-dash (same
  storage pattern, key `log-font-size`, same sizes, same "works in Chrome and Safari only" note).
- **WP-UI06.2** Add `SettingsPopover` to the top bar with: Font size, Density (the existing
  `comfortable/standard/compact` preference, which today has no control) and Theme (as pm-dash has it). Operator
  name stays on the Alerts page.
- **WP-UI06.3** Make the density preference actually change something visible in Explorer and Connections row
  height, or, if it already does, confirm it in the test. If it does nothing today, remove the preference
  rather than add a control for it.
- **Tests:** jsdom component test for the popover (pm-log has none today, so this adds the jsdom setup the other
  apps use); store test for font size persistence.
- **Done when:** pm-log's settings behave exactly like pm-book's for font size, and the popover opens by mouse
  and keyboard and closes on Esc.

**Done 2026-10-22.** pm-log now has a settings popover (gear, between the theme toggle and the connection
badge) with the font-size control, built from the pm-book/pm-dash pieces: `useFontSizeStore` (key
`log-font-size`, same six sizes, CSS `zoom` on `#root`, applied before first paint in `main.tsx`), `--zoom`
fallback in `index.css`, and `AppShell` sized as `calc(100vh / var(--zoom, 1))`. The popover also closes on Esc.
- **Density removed instead of controlled** (the WP's own fallback): the `density` preference in
  `usePrefsStore` was read by nothing, so adding a control would have promised an effect that does not exist.
  The store keeps only `operatorName`.
- **Theme not duplicated in the popover:** pm-log keeps its theme state in `AppShell`, so a second control
  would need that state lifted; the top-bar toggle stays the only one. WP-UI09 reworks theme handling and is the
  place to decide whether the popover should carry it.
- **Test setup:** pm-log now has jsdom, `@testing-library/{dom,react,user-event}` (same versions as pm-dash) and
  `test/setup-dom.ts` (copied from pm-book); `vitest.config.ts` includes `.tsx` tests. New
  `settings.test.tsx` covers open/close, the six sizes, persistence and the zoom factor. `package-lock.json`
  changed accordingly.
- Added the missing `accent-fg` token (white in both themes) that the active radio needs.

#### WP-UI07 - One top-bar order and active-item style (F3, F8)

Apps: all six.

- **WP-UI07.1** Define the order of the right-hand group in this document: `[app-specific tools] · Theme ·
  Settings · Help · Connection badge · identity (gateway/role/logout)`. App-specific tools are pm-trader's search
  and notifications, pm-terminal's density button, pm-dash's time pickers and pm-config's experience level.
- **WP-UI07.2** Reorder the top bars to it. Placeholders for Help are left out until WP-UI08.
- **WP-UI07.3** Give the active item of the rail (pm-log), sidebar (pm-trader), tabs (pm-terminal) and list
  (pm-config) the same style: accent fill and `accent-fg` text, as the pm-terminal tabs have.
- **Tests:** update tests that find buttons by position; add one test per app asserting the DOM order of the
  top-bar controls by accessible name.
- **Done when:** the six top bars, side by side, differ only by their app-specific tools and navigation.

#### WP-UI08 - Per-app help panel and `?` button (F2)

Apps: pm-log, pm-terminal, pm-dash, pm-book, pm-config (pm-trader keeps its drawer and gains the new frame).

- **WP-UI08.1** Extract pm-trader's `HelpDrawer` into a content-driven component (topics of
  heading, paragraphs, terms, example, note blocks: the `HelpBlock` shape from WP-UI02), copied into the other
  apps. Escape closes; the "?" button sits in the top bar at the place fixed by WP-UI07; the shortcut is
  wired in WP-UI10.
- **WP-UI08.2** Write the topic content per app, from the guides in `docs/books`, not from memory:
  - *Common to all:* what the app is and which process feeds it; the connection badge (LIVE, RECONNECTING,
    OFFLINE and what each means for the numbers on screen); the session badge and the countdown; colours;
    the settings; where to find the full guide chapter.
  - *pm-log:* levels, fingerprints and issues, acknowledging, the Explorer filter language, connections and
    silence, health components.
  - *pm-terminal:* each view, the quote versus auction columns, movers baselines, the tape side, how to read the
    depth ladder.
  - *pm-dash:* the seven rows, the process states HEALTHY to MISSING, thresholds and colours, time range and
    refresh, drawers.
  - *pm-book:* ladder, depth bars, stats rows and their basis, tape trend colours.
  - *pm-config:* the workflow (draft, diagnostics, review, download), experience levels, how the generated
    file is used.
- **WP-UI08.3** Put the help text in a `helpContent.ts` per app, with a unit test that every topic has a title
  and at least one block, and that the connection and session topics exist in all apps.
- **Estimate note:** the code is small; the writing is the work. Split into two commits if needed (log+config,
  terminal+dash+book).
- **Done when:** every app opens a readable help panel from the top bar and from the keyboard.

#### WP-UI09 - Theme default and pm-config frame (F4, F7)

Apps: all six (theme), pm-config (font size).

- **WP-UI09.1** One `theme.ts` shape in every app: stored preference `light | dark`, and when nothing is stored
  the OS `prefers-color-scheme`. Today only pm-config does this. The theme is applied before first paint
  (inline script or early `main.tsx` call) so there is no flash.
- **WP-UI09.2** pm-config: add the font-size store and a minimal settings popover with only Font size and Theme,
  in the position fixed by WP-UI07.
- **Tests:** unit test of the theme resolution (stored wins, else OS, else dark) per app; the existing contrast
  tests keep passing in both themes.
- **Done when:** a fresh browser profile with the OS set to light shows all six apps in light.

#### WP-UI10 - Universal keyboard shortcuts (F9)

Apps: all six.

- **WP-UI10.1** `Ctrl+/` toggles the help panel (pm-trader has it; the other apps get it from WP-UI08).
  `Esc` closes any open popover, drawer or panel; check each existing one (pm-dash drawer and pickers, pm-trader
  dialogs) and fix those that do not.
- **WP-UI10.2** List the shortcuts of each app in its help panel, from one array per app so the list and the
  handler cannot disagree (as `SHORTCUTS` does in pm-trader).
- **Tests:** per app, `Ctrl+/` opens and closes help; `Esc` closes the settings popover.
- **Done when:** the two shortcuts work in every app and are listed in its help.

#### WP-UI11 - Drift test for the copied components (F10)

Apps: none changed; a test in the repo.

- **WP-UI11.1** Write a test (Python under `tests/`, or a vitest at `web-apps/` root, whichever runs in CI)
  that reads the copies of each component meant to be identical and fails with a readable diff when they differ:
  `ConnectionBadge`, `SessionIndicator` (the pure parts), `InfoTip` (dash, book, terminal; log's differs only by
  tokens, so list the allowed differences), `SettingsPopover` base (font size), and the help drawer.
- **WP-UI11.2** Document in this file which components are copied and where the master copy is. Fix any drift the
  test finds first (expected: `InfoTip` token names, `SessionIndicator` styling).
- **Done when:** the test passes, and editing one copy alone makes it fail.
