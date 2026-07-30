/**
 * `pm-api-gwy` `/api/v1/history/*` row shapes, passed through unmodified by
 * the bridge's proxy (design §17.2).
 *
 * Field names are snake_case because these come straight off pm-stats' SQLite
 * rows — the proxy deliberately does not rename anything, so the frontend's
 * history code stays interchangeable with `pm-trading-ui`'s.
 */

export interface DailyBar {
  date: string;
  symbol: string;
  open_price: number | null;
  high_price: number | null;
  low_price: number | null;
  close_price: number | null;
  vwap: number | null;
  volume: number | null;
  trade_count: number | null;
}

/**
 * One executed trade from `trade_log`.
 *
 * The timestamp column is `ts`, not `timestamp` — these rows come straight off
 * pm-stats' SQLite and the proxy renames nothing.
 */
export interface TradeRow {
  ts: string;
  trade_id: string;
  symbol: string;
  price: number;
  quantity: number;
  buy_gateway_id: string | null;
  sell_gateway_id: string | null;
}

export interface PriceSnapshotRow {
  ts: string;
  symbol: string;
  mid_price: number | null;
  best_bid: number | null;
  best_ask: number | null;
  /** Change versus the *previous snapshot*, not the day's open; null on the first. */
  pct_change: number | null;
}

export interface IndexDailyRow {
  date: string;
  index_id: string;
  open_level: number | null;
  high_level: number | null;
  low_level: number | null;
  close_level: number | null;
  close_session_state: string | null;
}

export interface IndexSnapshotRow {
  index_id: string;
  timestamp: string;
  level: number | null;
}

/**
 * Every SQLite-backed history endpoint returns this envelope
 * (`_paginated_envelope` in `api_gateway/routers/history.py`). The row key
 * differs per endpoint: `daily`, `trades`, `snapshots`.
 */
export interface PaginatedEnvelope<T> {
  count: number;
  has_more: boolean;
  next_cursor?: string;
  [rowKey: string]: T[] | number | boolean | string | undefined;
}
