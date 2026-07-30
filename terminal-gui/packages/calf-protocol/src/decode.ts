/**
 * CALF payload decoding — wire text to numbers, one function per channel.
 *
 * Still grammar-level, not gateway semantics: these functions know that
 * `BIDS` is `price:qty:count,...` and that `EQPX` may be absent, but nothing
 * about subscriptions, sequencing, or reconnects.
 *
 * Absent-vs-zero is load-bearing throughout. The gateway omits a field it has
 * no value for (`normaliser.py` builds its field maps conditionally), and an
 * omitted `EQPX` means "no cross" while `EQPX=0` would mean "crossed at zero".
 * So every optional field decodes to `undefined`, never to `0`.
 */

import type { AuctionResultFrame, DepthLevel, HaltContextFrame, TopOfBook } from "@edumatcher/terminal-types";
import { CalfProtocolError } from "./line.js";

/** Fields present on every sequenced CALF stream message. */
export interface StreamEnvelope {
  ch: string;
  sym: string;
  seq: number;
  ts: string;
}

/**
 * Parse a number, treating both absence and unparseable text as absence.
 *
 * Degrading a malformed field to `undefined` rather than `NaN` keeps one bad
 * value on the wire from propagating into every downstream computation — a
 * missing price renders as a dash, a `NaN` price renders as "NaN" and poisons
 * any average it feeds.
 */
function num(raw: string | undefined): number | undefined {
  if (raw === undefined || raw === "") return undefined;
  const parsed = Number(raw);
  return Number.isFinite(parsed) ? parsed : undefined;
}

/** Like `num`, but for fields the gateway always emits (`QTY`, `EQQTY`, ...). */
function numOr(raw: string | undefined, fallback: number): number {
  return num(raw) ?? fallback;
}

/** Extract `CH`/`SYM`/`SEQ`/`TS`, which every stream message carries. */
export function readEnvelope(fields: Record<string, string>): StreamEnvelope {
  const ch = fields["CH"];
  const sym = fields["SYM"];
  if (!ch || !sym) throw new CalfProtocolError("stream message missing CH or SYM");
  return {
    ch,
    sym,
    seq: numOr(fields["SEQ"], 0),
    ts: fields["TS"] ?? "",
  };
}

export interface WelcomeInfo {
  proto: string;
  gateway: string;
  /** Server-assigned heartbeat interval, seconds. */
  hbint: number;
  /** Replay window the gateway retains, seconds. */
  replaySec: number;
  /** From `CH_SUPPORTED=`; empty for a pre-1.0.0 gateway that lacks the field. */
  chSupported: Set<string>;
  /** From `SYMBOLS=`; empty when the gateway was started without an engine config. */
  symbols: string[];
}

export function parseWelcome(fields: Record<string, string>): WelcomeInfo {
  const proto = fields["PROTO"] ?? "";
  if (proto !== "CALF1") throw new CalfProtocolError(`WELCOME PROTO mismatch: ${JSON.stringify(proto)}`);
  return {
    proto,
    gateway: fields["GW"] ?? "",
    hbint: numOr(fields["HBINT"], 1),
    replaySec: numOr(fields["REPLAY"], 0),
    chSupported: new Set(splitCsv(fields["CH_SUPPORTED"])),
    symbols: splitCsv(fields["SYMBOLS"]),
  };
}

function splitCsv(raw: string | undefined): string[] {
  if (!raw) return [];
  return raw
    .split(",")
    .map((token) => token.trim().toUpperCase())
    .filter((token) => token.length > 0);
}

/**
 * Decode `BIDS`/`ASKS` — `price:qty:count` triples, best price first.
 *
 * Levels with an unparseable price or qty are skipped rather than throwing,
 * matching the gateway's own `_extract_levels`: one malformed level should not
 * discard an otherwise-good ladder.
 */
export function parseLevels(raw: string | undefined): DepthLevel[] {
  if (!raw) return [];
  const levels: DepthLevel[] = [];
  for (const token of raw.split(",")) {
    const parts = token.split(":");
    const price = num(parts[0]);
    const qty = num(parts[1]);
    if (price === undefined || qty === undefined) continue;
    levels.push([price, qty, numOr(parts[2], 0)]);
  }
  return levels;
}

/** Inverse of `parseLevels` — used only by the fake gateway in tests. */
export function encodeLevels(levels: DepthLevel[]): string {
  return levels.map(([px, qty, count]) => `${px}:${qty}:${count}`).join(",");
}

/**
 * A `TOP` delta. Three distinct states per field, and all three matter:
 *
 *   - a number — this field's new value
 *   - `null`   — this side has been *withdrawn*; the book has no bid/ask at all
 *   - absent   — unchanged since the last message; keep what you had
 *
 * Collapsing withdrawal into "absent" is what made a lifted bid leave its last
 * price on screen forever, so the distinction is load-bearing rather than
 * decorative.
 */
export type TopDelta = { [K in keyof TopOfBook]?: number | null };

/**
 * Decode a `TOP` payload from either a `SNAP` or an `MD`.
 *
 * The result is a *partial* view in both cases. `MD` carries only the fields
 * that changed (`normalise_book` diffs against its own cache before emitting),
 * and even a `SNAP` omits fields the gateway has never seen a value for. Merge
 * it onto prior state; do not treat it as a replacement.
 *
 * An explicitly empty `BID=`/`ASK=` decodes to `null`, meaning that side is
 * now empty. Only those two fields can be withdrawn: `LAST` persists once a
 * symbol has traded, and the gateway never blanks it.
 */
export function decodeTop(fields: Record<string, string>): TopDelta {
  const top: TopDelta = {};

  if (fields["BID"] !== undefined) top.bid = fields["BID"] === "" ? null : (num(fields["BID"]) ?? null);
  if (fields["ASK"] !== undefined) top.ask = fields["ASK"] === "" ? null : (num(fields["ASK"]) ?? null);

  const bidSz = num(fields["BIDSZ"]);
  const askSz = num(fields["ASKSZ"]);
  const last = num(fields["LAST"]);
  const lastSz = num(fields["LASTSZ"]);
  if (bidSz !== undefined) top.bidSz = bidSz;
  if (askSz !== undefined) top.askSz = askSz;
  if (last !== undefined) top.last = last;
  if (lastSz !== undefined) top.lastSz = lastSz;
  return top;
}

export interface TradePayload {
  px: number;
  qty: number;
  side: string;
}

export function decodeTrade(fields: Record<string, string>): TradePayload {
  return {
    px: numOr(fields["PX"], 0),
    qty: numOr(fields["QTY"], 0),
    side: fields["SIDE"] ?? "",
  };
}

export interface StatePayload {
  session: string;
  prev?: string;
}

export function decodeState(fields: Record<string, string>): StatePayload {
  const payload: StatePayload = { session: fields["SESSION"] ?? "" };
  if (fields["PREV"]) payload.prev = fields["PREV"];
  return payload;
}

export interface IndexPayload {
  level?: number;
  chg?: number;
  pctChg?: number;
  open?: number;
  high?: number;
  low?: number;
  session?: string;
  aggCap?: number;
}

/**
 * Decode an `IDX` or `SNAP(CH=INDEX)` payload.
 *
 * Every field is optional: `index_snapshot_fields` returns an empty map until
 * pm-index has published its first `index.update`, so the very first frame a
 * subscriber sees can legitimately be metadata-only.
 */
export function decodeIndex(fields: Record<string, string>): IndexPayload {
  const payload: IndexPayload = {};
  const level = num(fields["LEVEL"]);
  const chg = num(fields["CHG"]);
  const pctChg = num(fields["PCTCHG"]);
  const open = num(fields["OPEN"]);
  const high = num(fields["HIGH"]);
  const low = num(fields["LOW"]);
  const aggCap = num(fields["AGGCAP"]);
  if (level !== undefined) payload.level = level;
  if (chg !== undefined) payload.chg = chg;
  if (pctChg !== undefined) payload.pctChg = pctChg;
  if (open !== undefined) payload.open = open;
  if (high !== undefined) payload.high = high;
  if (low !== undefined) payload.low = low;
  if (aggCap !== undefined) payload.aggCap = aggCap;
  if (fields["SESSION"]) payload.session = fields["SESSION"];
  return payload;
}

export interface DepthPayload {
  levels: number;
  bids: DepthLevel[];
  asks: DepthLevel[];
}

export function decodeDepth(fields: Record<string, string>): DepthPayload {
  return {
    levels: numOr(fields["LEVELS"], 0),
    bids: parseLevels(fields["BIDS"]),
    asks: parseLevels(fields["ASKS"]),
  };
}

export type AuctionPayload = Omit<AuctionResultFrame, "type" | "sym" | "seq" | "ts">;

export function decodeAuction(fields: Record<string, string>): AuctionPayload {
  const payload: AuctionPayload = {
    eqQty: numOr(fields["EQQTY"], 0),
    tradesCount: numOr(fields["TRADES"], 0),
    imbalanceQty: numOr(fields["IMBQTY"], 0),
  };
  const eqPrice = num(fields["EQPX"]);
  if (eqPrice !== undefined) payload.eqPrice = eqPrice;
  if (fields["IMBSIDE"]) payload.imbalanceSide = fields["IMBSIDE"];
  return payload;
}

export type HaltContextPayload = Omit<HaltContextFrame, "type" | "sym" | "seq" | "ts">;

/**
 * Decode a `CB` payload.
 *
 * `RESUMEAT` is ISO-8601 text, not epoch nanoseconds — the gateway's
 * `_ns_to_iso()` converts the engine's `resume_at_ns` before it reaches the
 * wire, so it is carried through as a string (correcting design §17.3's
 * `resumeAtNs`).
 */
export function decodeCb(fields: Record<string, string>): HaltContextPayload {
  const payload: HaltContextPayload = {
    status: fields["STATUS"] === "HALTED" ? "HALTED" : "ACTIVE",
  };
  const triggerPrice = num(fields["TRIGGERPX"]);
  const referencePrice = num(fields["REFPX"]);
  if (fields["LEVEL"]) payload.level = fields["LEVEL"];
  if (triggerPrice !== undefined) payload.triggerPrice = triggerPrice;
  if (referencePrice !== undefined) payload.referencePrice = referencePrice;
  if (fields["RESUMEAT"]) payload.resumeAt = fields["RESUMEAT"];
  if (fields["MODE"]) payload.resumptionMode = fields["MODE"];
  return payload;
}
