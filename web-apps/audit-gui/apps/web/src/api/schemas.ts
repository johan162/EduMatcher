/**
 * Zod schemas for every response the audit GUI reads.
 *
 * Mirrors the released contract, `spec/rest/openapi.json` (the "Audit
 * (ADMIN)" chapter of the REST reference), field for field;
 * `test/contract.test.ts` parses the contract's examples with these schemas
 * and fails when a field is added, dropped or changes required-ness.
 *
 * Conventions (as clearing-gui's):
 * - a field the server always sends is required; `| null` is `.nullable()`;
 *   a field with a server default may be left out and is `.optional()`;
 * - nanosecond values are decimal strings on the wire (design §3.2) and stay
 *   strings here;
 * - objects are not `.strict()`: the contract test catches drift instead.
 */
import { z } from "zod";

const int = z.number().int();

// ── Session ────────────────────────────────────────────────────────────────

export const Status = z.object({
  gateway_id: z.string(),
  gateway_role: z.string(),
  gateway_count: int.nullable().optional(),
});

// ── Collections and snapshots ──────────────────────────────────────────────

export const Collections = z.object({
  collections: z.array(
    z.object({
      id: z.string(),
      available: z.boolean(),
      reason: z.string().nullable(),
      files: int,
    }),
  ),
  count: int,
});

const Capability = z.object({
  available: z.boolean(),
  reason: z.string().nullable(),
  detail: z.string(),
});

export const Snapshot = z.object({
  snapshot_id: z.string(),
  collection_id: z.string(),
  created_at: z.string(),
  entries: int,
  first_ts: z.string().nullable(),
  last_ts: z.string().nullable(),
  files: z.array(
    z.object({
      name: z.string(),
      kind: z.enum(["active", "part", "archive"]),
      size: int,
      cutoff: int,
      torn_bytes: int,
      sha256: z.string(),
    }),
  ),
  runs: z.array(
    z.object({
      run_seq: int.nullable(),
      started_ts: z.string(),
      config_sha256: z.string().nullable(),
    }),
  ),
  capabilities: z.record(z.string(), Capability),
  symbols: z.array(z.object({ symbol: z.string(), tick_decimals: int.nullable() })),
  manifest: z.object({
    state: z.enum(["absent", "verified", "failed"]),
    entries: int,
    head_sha256: z.string().nullable(),
    anchored: z.boolean(),
    problems: z.array(z.object({ day: z.string().nullable(), message: z.string() })),
  }),
  forensics: z
    .object({
      sha256: z.string(),
      size: int,
      tool_version: z.string().nullable(),
      cut_trade_id: z.string().nullable(),
      statuses: z.record(z.string(), int),
      inputs: z.array(
        z.object({ name: z.string(), kind: z.enum(["audit", "store"]), size: int, sha256: z.string() }),
      ),
      inputs_match: z.boolean(),
      differing: z.array(z.string()),
    })
    .nullable(),
});

// ── Findings ───────────────────────────────────────────────────────────────

const Severity = z.enum(["info", "warn", "error"]);
const Lane = z.enum(["evidence", "consistency", "operations", "behaviour"]);

export const Finding = z.object({
  origin: z.enum(["replay", "forensics"]).optional(),
  code: z.string(),
  severity: Severity,
  lane: Lane,
  episode: int.nullable(),
  receipt_ts: z.string().nullable(),
  detail: z.string(),
  source: z.object({ file: z.string().nullable(), line: int }).nullable(),
  episode_kind: z.string().nullable().optional(),
  anchor: z.string().nullable().optional(),
  check: z
    .object({
      id: z.string(),
      oracle: z.string().nullable(),
      title: z.string().nullable(),
      status: z.enum(["FAIL", "ERROR", "SKIPPED"]),
      violations: int.nullable(),
      note: z.string(),
      samples: z.array(z.unknown()),
      scope: z.object({ stores: z.array(z.string()), cut_trade_id: z.string().nullable() }),
    })
    .nullable()
    .optional(),
});

export const FindingPage = z.object({
  snapshot_id: z.string(),
  lanes: z.record(
    z.string(),
    z.object({ available: z.boolean(), reason: z.string().nullable().optional(), count: int.nullable() }),
  ),
  forensics: z.object({
    available: z.boolean(),
    reason: z.string().nullable(),
    detail: z.string(),
    statuses: z.record(z.string(), int).nullable(),
  }),
  findings: z.array(Finding),
  count: int,
  has_more: z.boolean(),
  next_cursor: z.string().nullable(),
});

// ── Market (design §9.4) ──────────────────────────────────────────────────

/** Epoch nanoseconds as a decimal string (design §3.2). */
const ns = z.string();
const MaskKind = z.enum(["gap", "halt"]);
const Cell = z.tuple([int, z.number()]);

export const Heatmap = z.object({
  snapshot_id: z.string(),
  symbol: z.string(),
  clock: z.literal("receipt"),
  tick_decimals: int.nullable(),
  from_ns: ns,
  to_ns: ns,
  bin_ns: ns,
  bins: int,
  requested_bins: int,
  cadence: z.object({
    observations: int,
    median_interval_ns: ns.nullable(),
    min_interval_ns: ns.nullable(),
    max_interval_ns: ns.nullable(),
  }),
  levels: z.array(z.object({ price_ticks: int, price: z.string().nullable() })),
  columns: z.array(
    z.object({
      start_ns: ns,
      end_ns: ns,
      covered_ns: ns,
      observations: int,
      age_ns: ns.nullable(),
      masks: z.array(MaskKind),
      bids: z.array(Cell),
      asks: z.array(Cell),
    }),
  ),
  masks: z.array(z.object({ kind: MaskKind, from_ns: ns, to_ns: ns, detail: z.string() })),
  phases: z.array(z.object({ phase: z.string().nullable(), from_ns: ns, to_ns: ns })),
});

const SegmentState = z.enum(["book", "stop", "market"]);
const End = z.enum(["filled", "cancel.owner", "cancel.system", "expired", "open", "censored"]);

export const Lifelines = z.object({
  snapshot_id: z.string(),
  symbol: z.string(),
  clock: z.literal("receipt"),
  tick_decimals: int.nullable(),
  from_ns: ns,
  to_ns: ns,
  gateway: z.string().nullable(),
  aggregated: z.boolean(),
  segment_cap: int,
  segments: int,
  without_admission: int,
  lifelines: z.array(
    z.object({
      order_id: z.string(),
      run: int,
      gateway: z.string().nullable(),
      side: z.string().nullable(),
      order_type: z.string().nullable(),
      quote_id: z.string().nullable(),
      start_ns: ns,
      start_censored: z.boolean(),
      end: End,
      end_ns: ns.nullable(),
      end_reason: z.string().nullable(),
      filled_qty: int,
      segments: z.array(
        z.object({
          start_ns: ns,
          end_ns: ns,
          price_ticks: int.nullable(),
          displayed_qty: int,
          state: SegmentState,
          cause: z.enum(["admission", "fill", "refill", "amend", "trigger"]),
        }),
      ),
    }),
  ),
  levels: z.array(
    z.object({
      side: z.string().nullable(),
      state: SegmentState,
      price_ticks: int.nullable(),
      orders: int,
      segments: int,
      max_displayed_qty: int,
      from_ns: ns,
      to_ns: ns,
      ends: z.record(z.string(), int),
    }),
  ),
});

const Source = z.object({ file: z.string().nullable(), line: int });

export const EventPage = z.object({
  snapshot_id: z.string(),
  events: z.array(
    z.object({
      key: z.string(),
      run: int,
      eseq: int.nullable(),
      topic_seq: int.nullable(),
      receipt_ts: z.string(),
      receipt_ns: ns,
      topic: z.string(),
      kind: z.string(),
      symbol: z.string().nullable(),
      actor: z.string().nullable(),
      msg_id: z.string().nullable(),
      causation_id: z.string().nullable(),
      correlation_id: z.string().nullable(),
      late: z.boolean(),
      fields: z.record(z.string(), z.unknown()),
      prices: z.array(
        z.object({ name: z.string(), raw: z.number(), display: z.number().nullable(), tick_decimals: int.nullable() }),
      ),
      source: Source,
    }),
  ),
  count: int,
  has_more: z.boolean(),
  next_cursor: z.string().nullable(),
});

export const Story = z.object({
  snapshot_id: z.string(),
  entity_kind: z.string(),
  entity_id: z.string(),
  run_id: int.nullable(),
  depth: int,
  episodes: z.array(
    z.object({
      id: int,
      kind: z.string(),
      anchor: z.string(),
      actor: z.string().nullable(),
      correlation_id: z.string().nullable(),
      root_msg_id: z.string().nullable(),
      symbol: z.string().nullable(),
      run: int,
      run_seq: int.nullable(),
      opened: z.string(),
      closed: z.string().nullable(),
      outcome: z.string(),
      summary: z.string(),
      derived: z.record(z.string(), z.unknown()),
    }),
  ),
  beats: z.array(
    z.object({
      episode: int,
      seq: int,
      sort_key: z.string(),
      msg_id: z.string().nullable(),
      causation_id: z.string().nullable(),
      correlation_id: z.string().nullable(),
      topic_seq: int.nullable(),
      eseq: int.nullable(),
      publisher_run: int,
      receipt_ts: z.string(),
      topic: z.string(),
      kind: z.string(),
      role: z.string().nullable(),
      late: z.boolean(),
      text: z.string(),
      source: Source,
      fields: z.record(z.string(), z.unknown()),
      prices: z.record(z.string(), z.number()),
    }),
  ),
  links: z.array(
    z.object({
      from: int,
      to: int,
      relation: z.string(),
      confidence: z.enum(["RECORDED", "CERTAIN", "STRONG", "HEURISTIC", "NONE"]),
      evidence: z.string(),
    }),
  ),
  anomalies: z.array(Finding),
});

/** Route -> the schema of its success body (the contract test's table). */
export const ROUTE_SCHEMAS: Record<string, z.ZodType> = {
  "/api/v1/status": Status,
  "/api/v1/audit/collections": Collections,
  "/api/v1/audit/snapshots/{snapshot_id}": Snapshot,
  "/api/v1/audit/findings": FindingPage,
  "/api/v1/audit/events": EventPage,
  "/api/v1/audit/stories/{entity_kind}/{entity_id}": Story,
  "/api/v1/audit/market/{symbol}/heatmap": Heatmap,
  "/api/v1/audit/market/{symbol}/lifelines": Lifelines,
};

export type SnapshotT = z.infer<typeof Snapshot>;
export type HeatmapT = z.infer<typeof Heatmap>;
export type LifelinesT = z.infer<typeof Lifelines>;
export type LifelineT = LifelinesT["lifelines"][number];
export type EventT = z.infer<typeof EventPage>["events"][number];
export type StoryT = z.infer<typeof Story>;
export type CollectionsT = z.infer<typeof Collections>;
