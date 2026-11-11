/**
 * Zod schemas for every response the clearing GUI reads.
 *
 * Mirrors the released contract, `spec/rest/openapi.json` (the "Clearing"
 * chapter of the REST reference), field for field; `test/contract.test.ts`
 * parses the contract's examples with these schemas and fails when a field
 * is added, dropped or changes required-ness on either side.
 *
 * Conventions:
 * - a field the server always sends is required; `| null` is `.nullable()`;
 *   a field it may leave out (exclude_unset) is `.optional()`;
 * - every `*_ticks` field is branded `Ticks` and every `*_minor` field
 *   `Minor` (lib/money.ts), so the formatters cannot mix the two units;
 * - objects are not `.strict()`: v1 may add fields, and a newer gateway must
 *   not break an older GUI. The contract test catches the drift instead.
 */
import { z } from "zod";
import type { Minor, Ticks } from "@/lib/money";

const int = z.number().int();
/**
 * Epoch nanoseconds (`*_ns`). About 1.8e18, beyond the 2**53 a JavaScript
 * number holds exactly, so JSON.parse rounds them by a few hundred ns and
 * `.int()` (safe integers only) would reject every real value. Display-only:
 * never compared for equality (lib/time.ts).
 */
const nanos = z.number();
/** A stored tick value (integers, or weighted averages for costs and P&L). */
const ticks = z.number() as unknown as z.ZodType<Ticks>;
const minor = int as unknown as z.ZodType<Minor>;
const runStatus = z.enum(["ok", "failed", "report-failed"]);

/** The bounded-list fields every list envelope carries besides its rows. */
const listFields = { count: int, has_more: z.boolean() };

// ── Session ────────────────────────────────────────────────────────────────

export const Status = z.object({
  gateway_id: z.string(),
  gateway_role: z.string(),
  gateway_count: int.nullable().optional(),
});

// ── Current state ──────────────────────────────────────────────────────────

export const PositionRow = z.object({
  gateway_id: z.string(),
  symbol: z.string(),
  net_qty: int,
  tick_decimals: int,
  avg_cost: z.number(),
  avg_cost_ticks: ticks,
  mark_price: z.number().nullable(),
  mark_price_ticks: ticks.nullable(),
  realized_pnl: z.number(),
  realized_pnl_ticks: ticks,
  unrealized_pnl: z.number(),
  unrealized_pnl_ticks: ticks,
  buy_qty: int,
  sell_qty: int,
  buy_notional: z.number(),
  buy_notional_ticks: ticks,
  sell_notional: z.number(),
  sell_notional_ticks: ticks,
  last_trade_ts_ns: nanos.nullable(),
  updated_ts_ns: nanos,
});
export const Positions = z.object({ positions: z.array(PositionRow), ...listFields });

export const ExposureRow = z.object({
  gateway_id: z.string(),
  symbol: z.string(),
  net_qty: int,
  tick_decimals: int,
  mark_price: z.number().nullable(),
  mark_price_ticks: ticks.nullable(),
  net_notional: z.number().nullable(),
  net_notional_ticks: ticks.nullable(),
  gross_notional: z.number().nullable(),
  gross_notional_ticks: ticks.nullable(),
  realized_pnl: z.number(),
  realized_pnl_ticks: ticks,
  unrealized_pnl: z.number(),
  unrealized_pnl_ticks: ticks,
  total_pnl: z.number(),
  total_pnl_ticks: ticks,
});
export const Exposure = z.object({ exposure: z.array(ExposureRow), ...listFields });

export const TradeRow = z.object({
  trade_id: z.string(),
  ts_ns: nanos,
  ingest_ts_ns: nanos,
  trade_date: z.string(),
  symbol: z.string(),
  quantity: int,
  tick_decimals: int,
  price: z.number(),
  price_ticks: ticks,
  buy_gateway_id: z.string().nullable(),
  sell_gateway_id: z.string().nullable(),
  buy_order_id: z.string().nullable(),
  sell_order_id: z.string().nullable(),
  aggressor_side: z.string().nullable(),
  match_type: z.string().nullable(),
  msg_id: z.string().nullable(),
});
export const TradePage = z.object({
  trades: z.array(TradeRow),
  count: int,
  has_more: z.boolean(),
  next_cursor: z.string().nullable(),
  retained_from: z.string().nullable(),
});

export const DailyRow = z.object({
  trade_date: z.string(),
  gateway_id: z.string(),
  symbol: z.string(),
  tick_decimals: int,
  traded_qty: int,
  traded_notional: z.number(),
  traded_notional_ticks: ticks,
  buy_qty: int,
  sell_qty: int,
  buy_notional: z.number(),
  buy_notional_ticks: ticks,
  sell_notional: z.number(),
  sell_notional_ticks: ticks,
  net_amount: z.number(),
  net_amount_ticks: ticks,
  realized_pnl: z.number(),
  realized_pnl_ticks: ticks,
  end_net_qty: int,
  end_avg_cost: z.number(),
  end_avg_cost_ticks: ticks,
  end_unrealized_pnl: z.number(),
  end_unrealized_pnl_ticks: ticks,
  last_trade_ts_ns: nanos.nullable(),
  updated_ts_ns: nanos,
});
export const Daily = z.object({ daily: z.array(DailyRow), ...listFields });

export const CloseSnapshotRow = z.object({
  trade_date: z.string(),
  gateway_id: z.string(),
  symbol: z.string(),
  net_qty: int,
  tick_decimals: int,
  realized_pnl: z.number(),
  realized_pnl_ticks: ticks,
  unrealized_pnl: z.number(),
  unrealized_pnl_ticks: ticks,
  mark_price: z.number().nullable(),
  mark_price_ticks: ticks.nullable(),
});
export const CloseSnapshots = z.object({ snapshots: z.array(CloseSnapshotRow), ...listFields });

export const ClearingSymbolRow = z.object({
  symbol: z.string(),
  tick_decimals: int,
  traded_qty: int,
  traded_notional: z.number(),
  traded_notional_ticks: ticks,
  realized_pnl: z.number(),
  realized_pnl_ticks: ticks,
  open_net_qty: int,
  open_unrealized_pnl: z.number(),
  open_unrealized_pnl_ticks: ticks,
});
export const ClearingSymbols = z.object({ symbols: z.array(ClearingSymbolRow), ...listFields });

/** Cross-symbol totals: display currency, already converted row by row. */
const participantTotals = {
  gateway_id: z.string(),
  realized_pnl: z.number(),
  unrealized_pnl: z.number(),
  total_pnl: z.number(),
  position_count: int,
  open_position_count: int,
  last_update_ts_ns: nanos.nullable(),
};
export const ParticipantRow = z.object(participantTotals);
export const Participants = z.object({ participants: z.array(ParticipantRow), ...listFields });

export const ParticipantDetail = z.object({
  ...participantTotals,
  positions: z.array(PositionRow),
  latest_close_date: z.string().nullable(),
  links: z.object({
    positions: z.string(),
    exposure: z.string(),
    trades: z.string(),
    daily: z.string(),
    close_snapshots: z.string(),
    gateway_sessions: z.string(),
    settlements: z.string(),
    balances: z.string(),
  }),
});

// ── Operational evidence ───────────────────────────────────────────────────

const gapFields = {
  run_seq: int.nullable(),
  last_seq: int.nullable(),
  next_seq: int.nullable(),
  missing_trades: int.nullable(),
};
export const FeedGap = z.object({ ...gapFields, trade_date: z.string(), ts_ns: nanos });

export const EodRun = z.object({
  trade_date: z.string(),
  status: runStatus,
  started_at: z.string(),
  finished_at: z.string(),
  /** ADMIN only: omitted for a participant. */
  steps: z
    .array(z.object({ step: z.string(), status: z.string(), message: z.string() }))
    .nullable()
    .optional(),
});

export const Summary = z.object({
  participant_count: int,
  open_position_count: int,
  realized_pnl: z.number(),
  unrealized_pnl: z.number(),
  last_trade_ts_ns: nanos.nullable(),
  last_flush_ts_ns: nanos.nullable(),
  session_date: z.string().nullable(),
  gap_count: int,
  latest_gap: FeedGap.nullable(),
  eod_db_available: z.boolean(),
  last_eod_run: EodRun.nullable(),
});

export const SessionEventRow = z.object({
  id: int,
  event_type: z.enum(["EOD", "PHASE", "GAP"]),
  ts_ns: nanos,
  trade_date: z.string(),
  phase: z.object({ state: z.string(), prev_state: z.string().nullable() }).nullable().optional(),
  gap: z.object(gapFields).nullable().optional(),
  eod: z
    .object({ symbols_count: int, marked_symbols: z.array(z.string()) })
    .nullable()
    .optional(),
});
export const SessionEvents = z.object({ events: z.array(SessionEventRow), ...listFields });

export const GatewaySessionRow = z.object({
  gateway_id: z.string(),
  connected_at_ns: nanos,
  disconnected_at_ns: nanos.nullable(),
  disconnect_reason: z.string().nullable(),
});
export const GatewaySessions = z.object({ sessions: z.array(GatewaySessionRow), ...listFields });

export const ReconciliationRow = z.object({
  side: z.enum(["BUY", "SELL"]),
  trade_date: z.string(),
  gateway_id: z.string(),
  symbol: z.string(),
  raw_qty: int,
  summary_qty: int,
  qty_diff: int,
  tick_decimals: int,
  raw_notional: z.number(),
  raw_notional_ticks: ticks,
  summary_notional: z.number(),
  summary_notional_ticks: ticks,
  notional_diff: z.number(),
  notional_diff_ticks: ticks,
});
export const Reconciliation = z.object({
  discrepancies: z.array(ReconciliationRow),
  count: int,
  has_more: z.boolean(),
  retained_from: z.string().nullable(),
  compared_from: z.string().nullable(),
  compared_to: z.string().nullable(),
});

export const Health = z.object({
  database: z.object({
    available: z.boolean(),
    detail: z.string(),
    wal_mode: z.string().nullable(),
    trade_events_rows: int.nullable(),
    gateway_symbol_positions_rows: int.nullable(),
    gateway_daily_summary_rows: int.nullable(),
    last_trade_ts_ns: nanos.nullable(),
    last_flush_ts_ns: nanos.nullable(),
  }),
  process: z.object({ alive: z.boolean(), detail: z.string() }),
});

// ── EOD settlement (minor units) ───────────────────────────────────────────

export const SettlementRow = z.object({
  trade_date: z.string(),
  account: z.string(),
  amount_minor: minor,
  amount: z.string(),
  /** Per symbol, the unrounded day P&L as a decimal string. */
  detail: z.record(z.string(), z.string()),
  run_status: runStatus.nullable(),
});
export const Settlements = z.object({
  settlements: z.array(SettlementRow),
  count: int,
  has_more: z.boolean(),
  runs: z.array(EodRun),
});

export const BalanceRow = z.object({
  account: z.string(),
  opening_balance_minor: minor,
  opening_balance: z.string(),
  settlement_total_minor: minor,
  settlement_total: z.string(),
  balance_minor: minor,
  balance: z.string(),
});
export const Balances = z.object({
  balances: z.array(BalanceRow),
  count: int,
  as_of: z.string().nullable(),
  last_settled_date: z.string().nullable(),
});

// ── Market-maker settings (GET /api/v1/symbols, requester-scoped) ──────────

export const SymbolInfo = z.object({
  symbol: z.string(),
  tick_decimals: int,
  enforce_mm_obligation: z.boolean().nullable().optional(),
  mm_max_spread_ticks: ticks.nullable().optional(),
  mm_min_qty: int.nullable().optional(),
  prev_close: z.number().nullable().optional(),
});
export const SymbolList = z.object({ symbols: z.array(SymbolInfo), count: int });

/** Each route the GUI calls, with the schema of its 200 body. */
export const ROUTE_SCHEMAS: Record<string, z.ZodType> = {
  "/api/v1/status": Status,
  "/api/v1/symbols": SymbolList,
  "/api/v1/clearing/summary": Summary,
  "/api/v1/clearing/participants": Participants,
  "/api/v1/clearing/participants/{gateway_id}": ParticipantDetail,
  "/api/v1/clearing/positions": Positions,
  "/api/v1/clearing/exposure": Exposure,
  "/api/v1/clearing/trades": TradePage,
  "/api/v1/clearing/daily": Daily,
  "/api/v1/clearing/close-snapshots": CloseSnapshots,
  "/api/v1/clearing/symbols": ClearingSymbols,
  "/api/v1/clearing/session-events": SessionEvents,
  "/api/v1/clearing/gateway-sessions": GatewaySessions,
  "/api/v1/clearing/reconciliation": Reconciliation,
  "/api/v1/clearing/health": Health,
  "/api/v1/clearing/settlements": Settlements,
  "/api/v1/clearing/balances": Balances,
};

export type PositionRowT = z.infer<typeof PositionRow>;
export type ExposureRowT = z.infer<typeof ExposureRow>;
export type TradeRowT = z.infer<typeof TradeRow>;
export type DailyRowT = z.infer<typeof DailyRow>;
export type CloseSnapshotRowT = z.infer<typeof CloseSnapshotRow>;
export type ClearingSymbolRowT = z.infer<typeof ClearingSymbolRow>;
export type ParticipantRowT = z.infer<typeof ParticipantRow>;
export type SessionEventRowT = z.infer<typeof SessionEventRow>;
export type GatewaySessionRowT = z.infer<typeof GatewaySessionRow>;
export type ReconciliationRowT = z.infer<typeof ReconciliationRow>;
export type SettlementRowT = z.infer<typeof SettlementRow>;
export type BalanceRowT = z.infer<typeof BalanceRow>;
export type EodRunT = z.infer<typeof EodRun>;
export type SummaryT = z.infer<typeof Summary>;
export type SymbolInfoT = z.infer<typeof SymbolInfo>;
