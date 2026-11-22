# News retention and News-view paging — plan

Status: all WPs done 2026-11-22 (WP-NR03 uncommitted).

## 1. Problem

Restarting the stack empties the terminal's News tab. pm-market-sim already
writes every headline to `market_sim_news.db` (`news_events`,
`market_sim/news_history.py`), but `GET /api/v1/news` serves
`SimClient.news`, an in-memory `deque(maxlen=200)` in pm-api-gwy that only
the live PUB feed fills. A restarted pm-api-gwy starts empty. Nothing prunes
the database either, so it would grow without bound.

## 2. Decisions (Johan, 2026-11-22)

| # | Question | Decision |
|---|----------|----------|
| D1 | Default time window | rolling last 24 h (not "since midnight") |
| D2 | Order of `GET /news` | newest first; the v1 contract changes, no `order=` switch |
| D3 | Filters | time window, symbol/sector, status, sentiment (positive/negative) |
| D4 | Retention | configurable: `news.retention_days` in `market_sim.yaml`, default 90 |

No migration of anything (standing rule): the database schema is unchanged.

## 3. Design

- **Retention (pm-market-sim).** `news.retention_days` (1–3650, default 90).
  On every session-phase change, including the first one seen at startup,
  the sim deletes `news_events` rows older than `now - retention_days`.
  Phase changes happen a few times a day, so the window holds to within
  hours, even with all news rates at 0. `value_jumps` (forensics) is not
  pruned. That is a separate question, see §5.
- **Source of `GET /news` (pm-api-gwy).** The endpoint reads `news_events` directly (read-only,
  WAL) at `DATA_DIR/market_sim_news.db`, the module constant
  `news_history.NEWS_HISTORY_DB`, the same way as `companies.db` (no
  `--news-db` option). A missing file gives an empty list; an unreadable one
  gives 503 `NEWS_DB_UNAVAILABLE`. The
  sim writes the row before publishing, so the database is never staler than
  the feed. The deque goes. WebSocket push is unchanged.
- **Query parameters.** `from`/`to` (ISO-8601, inclusive, naive = UTC;
  named like the history endpoints' `from`/`to`), `filter` (symbol or sector:
  MARKET news always matches, a symbol also matches its sector's news, a
  sector its symbols' news), `status` (RUMOUR/CONFIRMED/RETRACTED),
  `sentiment` (`positive` > 0, `negative` < 0), `limit` (1–500, default 50)
  and `offset`. The reply gains `total` (the number of matches), `has_more` and, per row,
  `resolution` (CONFIRMED/RETRACTED/null: what became of a rumour, found
  across the whole table, so paging can't hide it).
- **Terminal News view.** It has a window selector (1 h / 24 h / 7 d / 30 d /
  All) defaulting to 24 h, status and sentiment selectors, the existing
  symbol/sector filter (now applied server-side) and 50 rows a page with
  "Page n of m · N headlines". Page 1 polls every 20 s. Leaving page 1 fixes
  `until`, so rows don't shift under the reader, and a "N new" chip returns
  to page 1. The selections persist in `usePrefsStore`.

## 4. Work packages

| WP | Scope | Status |
|----|-------|--------|
| WP-NR01 | `news.retention_days` config + `prune_news_events()` + call on phase change; tests; operator-guide market-model chapter + example yaml | done 2026-11-22 |
| WP-NR02 | pm-api-gwy `GET /news` from the DB with the parameters, `total`, `has_more` and `resolution`, newest first; drop the deque; trader-gui and terminal-gui drop their `.reverse()`; REST spec + OpenAPI docs | done 2026-11-22 |
| WP-NR03 | terminal-gui News view: window/status/sentiment selectors, server-side filter, paging with fixed `to`, prefs; bridge passes query through; help text + participant-guide terminal chapter | done 2026-11-22 |

## 5. Open

- trader-gui's News screen still shows the newest 200 (one `GET /news` page
  plus the live WebSocket adds), unpaged and filtered client-side. Not in
  scope; give it the terminal's paging if wanted.

- `value_jumps` in the same file is never pruned. It grows by one row per
  jump (a few per symbol per day). This is left alone until forensics needs
  are decided.

## 6. Notes for later WPs

- Every new WARNING+ log call (WP-NR02 added `news: cannot read %s: %s`) needs a `log_ledger/entries/*.yaml` entry
  (`test_log_ledger.py` fails otherwise). WP-NR01 added one for the
  prune error.
- WP-NR02 changes the OpenAPI contract, so regenerate `spec/rest/openapi.json`
  (`make openapi-check` is part of `make _check`).
- WP-NR02 pages with `offset` + `total` + `has_more`, not the D6
  `after`/`next_cursor` cursor of the history endpoints. The News view needs
  "page n of m" and jumps between pages, and the table is small (thousands of
  rows). WP-NR03 fixes `to` while off page 1, so rows do not shift between
  pages.
- `resolution` is tied to its rumour by `related_id` *and* `event_seq` order,
  because news ids can repeat across a sim restart.
- `filter` is expanded in pm-api-gwy from `SimClient.sectors` (the deployed
  `market_sim.yaml`) into a target set, so the SQL needs no sector knowledge.
- WP-NR03: the bridge needed no change (it passes the query string through).
  `newsMatches()`/`resolutions()` were removed, because filtering and
  resolution moved server-side. Window, status and sentiment persist in
  `terminal-prefs`; the symbol/sector text does not. Off page 1 the view pins
  `from`/`to` to page 1's last request and counts newer rows with a
  `limit=1` query from `to + 1 ms`. The Time column puts the date in front
  when it isn't today's (session timezone).
