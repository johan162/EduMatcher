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

const Finding = z.object({
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

/** Route -> the schema of its success body (the contract test's table). */
export const ROUTE_SCHEMAS: Record<string, z.ZodType> = {
  "/api/v1/status": Status,
  "/api/v1/audit/collections": Collections,
  "/api/v1/audit/snapshots/{snapshot_id}": Snapshot,
  "/api/v1/audit/findings": FindingPage,
};

export type SnapshotT = z.infer<typeof Snapshot>;
export type CollectionsT = z.infer<typeof Collections>;
