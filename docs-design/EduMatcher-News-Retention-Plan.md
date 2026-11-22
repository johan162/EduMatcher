# News retention and News-view paging — plan

Status: WP-NR01 done 2026-11-22 (uncommitted); next WP-NR02.

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
  WAL), as it already does for `stats.db`/EOD. `--news-db` defaults to
  `DATA_DIR/market_sim_news.db`, and a missing file gives an empty list. The
  sim writes the row before publishing, so the database is never staler than
  the feed. The deque goes. WebSocket push is unchanged.
- **Query parameters.** `since`/`until` (ISO-8601), `filter` (symbol or sector:
  MARKET news always matches, a symbol also matches its sector's news, a
  sector its symbols' news), `status` (RUMOUR/CONFIRMED/RETRACTED),
  `sentiment` (`positive` > 0, `negative` < 0), `limit` (1–500, default 50)
  and `offset`. The reply gains `total` (the number of matches) and, per row,
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
| WP-NR02 | pm-api-gwy `GET /news` from the DB with the parameters, `total` and `resolution`, newest first; `--news-db`; drop the deque; trader-gui drops its `.reverse()`; REST spec + OpenAPI docs | open |
| WP-NR03 | terminal-gui News view: window/status/sentiment selectors, server-side filter, paging with fixed `until`, prefs; bridge passes query through; help text + participant-guide terminal chapter | open |

## 5. Open

- `value_jumps` in the same file is never pruned. It grows by one row per
  jump (a few per symbol per day). This is left alone until forensics needs
  are decided.

## 6. Notes for later WPs

- Every new WARNING+ log call needs a `log_ledger/entries/*.yaml` entry
  (`test_log_ledger.py` fails otherwise). WP-NR01 added one for the
  prune error.
- WP-NR02 changes the OpenAPI contract, so regenerate `spec/rest/openapi.json`
  (`make openapi-check` is part of `make _check`).
