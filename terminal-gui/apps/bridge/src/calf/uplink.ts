/**
 * `CalfUplink` — the bridge's single upstream live-data connection (design
 * §6.4, §17.1).
 *
 * One TCP session to `pm-md-gwy` serves every browser tab. Inbound CALF lines
 * are decoded once here and handed out as ready-to-send JSON frames; no tab
 * ever sees the wire format.
 *
 * Four places this departs from design §17.1, each verified against the
 * shipped gateway rather than inferred:
 *
 *   1. **Reconnect does not use `HELLO|RESUME=1`.** §17.1 step 3 has the
 *      bridge issue "a separate HELLO...RESUME=1 per stream" after a drop.
 *      That cannot work: `_handle_client_line` only dispatches `HELLO` while a
 *      session is unauthenticated, so the second one on a connection is
 *      answered with `ERR|CODE=BAD_MESSAGE` — a connection can resume at most
 *      one `(CH, SYM)` stream, ever. Instead the bridge reconnects with a
 *      plain `HELLO` and re-subscribes; the gateway's automatic `SNAP` on
 *      `SUB` restores correct state for `TOP`/`STATE`/`INDEX`/`DEPTH`/`CB`.
 *   2. **There is no `ERR|CODE=SLOW_CLIENT` to react to.** The gateway drops
 *      an over-queued client silently (`_queue_raw` clears the queue and marks
 *      the session closing; `_flush_client_writes` then disconnects). It looks
 *      like any other close, and is handled as one.
 *   3. **A keepalive `PING` is required.** See `config.calf.pingIntervalSec`.
 *   4. **`TRADE` gaps are resumed via the standalone `RESUME` command,
 *      per-symbol, on detection rather than never.** §17.1 accepted a lost
 *      print on `TRADE`/`AUCTION` reconnect as the right trade-off for a
 *      display-only viewer; that held until it became clear the Trade Tape is
 *      read as a time-and-sales record, and an unmarked hole in one is worse
 *      than an absent one (T-H4/T-H5). `AUCTION` still has no baseline and is
 *      not resumed — see `checkForGap` and `RESUMABLE_CHANNELS` below for the
 *      reasoning and the one channel it currently covers. Both channels'
 *      unrepaired gaps are still reported so a viewer knows, rather than the
 *      silence §17.1 originally assumed.
 *   5. **A `SNAP` on a channel that has none is discarded.** The gateway
 *      answers `REPLAY_MISS` with a fresh `SNAP` for the stream, which the
 *      protocol describes for the snapshot-backed channels and which
 *      `_send_snapshot_for_stream` can only fill for those. On `TRADE` or
 *      `AUCTION` it produces an envelope with no payload. Newer gateways skip
 *      it; this bridge drops it regardless, since a decoder keyed on `CH`
 *      would otherwise render it as a print of zero shares at zero price.
 */

import { EventEmitter } from "node:events";
import { Socket } from "node:net";
import {
  CalfProtocolError,
  LineBuffer,
  buildExit,
  buildHello,
  buildPing,
  buildResume,
  buildSub,
  buildSymbolsRequest,
  buildUnsub,
  decodeAuction,
  decodeCb,
  decodeDepth,
  decodeIndex,
  decodeState,
  decodeTop,
  decodeTrade,
  isChannel,
  parseLine,
  parseSymbolsReply,
  parseWelcome,
  readEnvelope,
  SNAPSHOT_ELIGIBLE,
  type Channel,
  type WelcomeInfo,
} from "@edumatcher/calf-protocol";
import type { CalfState, ServerFrame, TradeSide, WatchChannel } from "@edumatcher/terminal-types";
import { SymbolRefCount } from "./symbol-refcount.js";
import { TopCache } from "./top-cache.js";

/**
 * Channels resumed on a detected gap, rather than left to self-heal.
 *
 * `TOP`/`STATE`/`DEPTH`/`CB` all baseline on `SNAP` — the reconnect that
 * caused the gap also triggers the fresh `SUB` that repairs it, so resuming
 * them too would just replay data a `SNAP` is about to supersede. `TRADE` has
 * no such baseline: a missed print is gone for good unless replayed, and it
 * is also the one stream people read as a record rather than as current state
 * (design §11, T-H5). `AUCTION` shares that gap-shaped hole but is out of
 * scope here — lower volume, and resuming it would double this change's
 * surface for a channel the review did not flag.
 */
const RESUMABLE_CHANNELS = new Set<Channel>(["TRADE"]);

const streamKey = (ch: string, sym: string): string => `${ch}|${sym}`;

/** Where one `(ch, sym)` stream has got to, and what it is still owed. */
interface StreamPosition {
  /** Highest `SEQ` seen. */
  seq: number;
  /**
   * Which connection `seq` was observed on.
   *
   * A sequence can only move backward two ways: a `RESUME` replaying history,
   * or a gateway process restarting and beginning its counters again at 1
   * (`SequenceAllocator` holds them in memory, not on the connection). The
   * first is only possible within the connection that asked; so a backward
   * step on a *later* connection is the second, and must be adopted rather
   * than mistaken for a duplicate — which would black the stream out for as
   * long as the new gateway lives.
   */
  gen: number;
  /**
   * Sequence ranges a `RESUME` was sent for and which have not arrived yet.
   *
   * `replay_since` answers with everything past `LASTSEQ`, so a reply mixes
   * the genuinely missing messages with ones already delivered above them.
   * These ranges are what distinguishes the two: inside one is a message this
   * bridge never saw, outside is a print already on the tape.
   */
  holes: Array<{ from: number; to: number }>;
}

/**
 * Whether `seq` is one of the messages a `RESUME` was sent to recover, marking
 * it taken if so.
 *
 * Replay arrives in sequence order on one ordered connection, so everything
 * below `seq` within the same hole has already been handed over and the range
 * can simply advance past it.
 */
function takeFromHole(position: StreamPosition, seq: number): boolean {
  const hole = position.holes.find((h) => seq >= h.from && seq <= h.to);
  if (hole === undefined) return false;
  hole.from = seq + 1;
  if (hole.from > hole.to) position.holes = position.holes.filter((h) => h !== hole);
  return true;
}

/** Held for the bridge's whole lifetime, regardless of tab count (§6.4). */
const WILDCARD_CHANNELS: Channel[] = ["STATE", "TOP", "TRADE", "AUCTION"];

const RECONNECT_MIN_MS = 500;
const RECONNECT_MAX_MS = 10_000;

export interface CalfUplinkOptions {
  host: string;
  port: number;
  clientId: string;
  indexIds: string[];
  pingIntervalSec: number;
}

export interface CalfUplinkEvents {
  frame: [ServerFrame];
  status: [CalfState];
  welcome: [WelcomeInfo];
  /** A symbol seen on the wire that was not in `WELCOME|SYMBOLS=`. */
  symbol: [string];
  /** `ERR` from the gateway — a real problem worth an operator's attention. */
  gatewayError: [{ code: string; detail: Record<string, string> }];
  /**
   * A per-symbol subscription was opened or closed (design §17.5).
   *
   * Only the 0↔1 edges, not every browser tab's interest — what an operator
   * needs is how many streams this bridge is actually holding upstream.
   */
  subscription: [{ action: "SUB" | "UNSUB"; ch: WatchChannel; sym: string; held: number }];
  /**
   * A hole in one `(ch, sym)` stream that could not be closed (T-H4/T-H5) —
   * either the channel is not resumed at all, or a `RESUME` came back
   * `REPLAY_MISS` because the gap outlasted the gateway's replay window.
   */
  gap: [{ ch: string; sym: string; ts: string }];
}

export class CalfUplink extends EventEmitter<CalfUplinkEvents> {
  private socket: Socket | null = null;
  private readonly lines = new LineBuffer();
  private readonly topCache = new TopCache();
  private readonly refCount: SymbolRefCount;
  private readonly knownSymbols = new Set<string>();
  private readonly knownTickDecimals: Record<string, number> = {};
  /**
   * Where each `(ch, sym)` stream stands, across reconnects (T-H4).
   *
   * Deliberately never cleared on reconnect: the gateway's own sequence
   * counters live in its process, not the connection, so the value from
   * before a drop is exactly what is needed to notice the drop cost anything.
   * Clearing it here would make every reconnect look gap-free by definition.
   */
  private readonly streams = new Map<string, StreamPosition>();
  /**
   * Bumped on every connection, so `StreamPosition.gen` can tell a replay
   * within one session apart from a gateway that restarted between two.
   */
  private generation = 0;
  /**
   * `TS` of the message that revealed each gap a `RESUME` was sent for.
   *
   * `ERR|CODE=REPLAY_MISS` carries no `TS` of its own, and this process's wall
   * clock is not the gateway's — a marker stamped here would be sorted among
   * prints stamped there, which is how a hole ends up drawn at the wrong point
   * on the tape. The message that exposed the hole is the one whose gateway
   * `TS` bounds it, so that is what is held until the `RESUME` is answered.
   * An entry is overwritten by the next `RESUME` for the same stream and is
   * otherwise harmless; the map is bounded by stream count, like `streams`.
   */
  private readonly pendingResumeTs = new Map<string, string>();

  private reconnectDelayMs = RECONNECT_MIN_MS;
  private reconnectTimer: NodeJS.Timeout | null = null;
  private pingTimer: NodeJS.Timeout | null = null;
  private stopped = false;
  private handshaken = false;
  private supportedChannels = new Set<string>();

  state: CalfState = "DOWN";
  stateSince = new Date().toISOString();
  gateway: string | null = null;

  constructor(private readonly opts: CalfUplinkOptions) {
    super();
    this.refCount = new SymbolRefCount({
      onFirst: (ch, sym) => {
        this.sendSub(ch, sym);
        this.emit("subscription", { action: "SUB", ch, sym, held: this.refCount.active().length });
      },
      onLast: (ch, sym) => {
        this.send(buildUnsub([ch], [sym]));
        this.emit("subscription", { action: "UNSUB", ch, sym, held: this.refCount.active().length });
      },
    });
  }

  /** Symbols this bridge knows about — `WELCOME|SYMBOLS=` plus any seen live. */
  symbols(): string[] {
    return [...this.knownSymbols].sort();
  }

  /**
   * Per-symbol display precision from `REF=`.
   *
   * Empty against a gateway that predates the field, which is what tells a
   * browser tab to fall back to `DEFAULT_TICK_DECIMALS` rather than silently
   * assuming it.
   */
  tickDecimals(): Record<string, number> {
    return { ...this.knownTickDecimals };
  }

  start(): void {
    this.stopped = false;
    this.open();
  }

  async stop(): Promise<void> {
    this.stopped = true;
    this.clearTimers();
    if (this.socket) {
      try {
        this.socket.write(buildExit());
      } catch {
        // Best effort — the peer may already be gone.
      }
      this.socket.removeAllListeners();
      this.socket.destroy();
      this.socket = null;
    }
    this.setState("DOWN");
  }

  /**
   * Register interest in a per-symbol channel on behalf of one browser tab.
   * The `SUB` only reaches the gateway if this is the first interested party.
   */
  watch(ch: WatchChannel, sym: string): void {
    this.refCount.acquire(ch, sym);
  }

  unwatch(ch: WatchChannel, sym: string): void {
    this.refCount.release(ch, sym);
  }

  // -- connection ------------------------------------------------------------

  private open(): void {
    if (this.stopped) return;

    this.handshaken = false;
    this.lines.reset();
    // A new connection may be a new gateway process, and so a new numbering
    // for every stream. Sequence positions are kept (that is what makes a gap
    // across a drop visible at all); this is what lets them be re-anchored if
    // the counters behind them started over.
    this.generation += 1;

    const socket = new Socket();
    this.socket = socket;

    socket.on("connect", () => socket.write(buildHello(this.opts.clientId)));
    socket.on("data", (chunk: Buffer) => this.onData(chunk));
    socket.on("error", () => this.onClosed());
    socket.on("close", () => this.onClosed());

    socket.connect(this.opts.port, this.opts.host);
  }

  private onClosed(): void {
    if (this.stopped) return;
    if (this.socket) {
      this.socket.removeAllListeners();
      this.socket.destroy();
      this.socket = null;
    }
    this.clearTimers();
    this.setState("RECONNECTING");

    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.open();
    }, this.reconnectDelayMs);
    this.reconnectTimer.unref?.();
    this.reconnectDelayMs = Math.min(this.reconnectDelayMs * 2, RECONNECT_MAX_MS);
  }

  private onData(chunk: Buffer): void {
    let lines: string[];
    try {
      lines = this.lines.push(chunk);
    } catch (err) {
      // An oversized unterminated line means the stream is no longer framed
      // the way CALF promises. Reconnecting is the only clean recovery.
      this.emit("gatewayError", { code: "BAD_FRAMING", detail: { message: String(err) } });
      this.socket?.destroy();
      return;
    }

    for (const line of lines) {
      try {
        this.handleLine(line);
      } catch (err) {
        if (err instanceof CalfProtocolError) {
          this.emit("gatewayError", { code: "PARSE_ERROR", detail: { line, message: err.message } });
          continue;
        }
        throw err;
      }
    }
  }

  private handleLine(line: string): void {
    const { msgType, fields } = parseLine(line);

    switch (msgType) {
      case "WELCOME":
        return this.onWelcome(fields);
      case "HB":
      case "PONG":
        return;
      case "SYMBOLS": {
        // The authoritative instrument universe, which WELCOME may not have
        // carried at all. Merged rather than replacing, so symbols already
        // learned from live data are not dropped if the gateway's own set is
        // somehow narrower.
        const reply = parseSymbolsReply(fields);
        for (const sym of reply.symbols) this.learnSymbol(sym);
        this.learnTickDecimals(reply.tickDecimals);
        return;
      }
      case "ERR": {
        const code = fields["CODE"] ?? "UNKNOWN";
        this.emit("gatewayError", { code, detail: fields });
        // The one RESUME failure mode that means the gap is now permanent: the
        // buffer that would have closed it aged out before this bridge asked.
        // CH/SYM identify which stream, the same way they do on RESUME itself.
        //
        // Reported only for a stream this bridge actually asked to repair —
        // `pendingResumeTs` both proves that and supplies the gateway-clock
        // timestamp the ERR line lacks. A REPLAY_MISS for anything else is not
        // this bridge's hole to describe, and inventing a local timestamp for
        // it would place the marker somewhere it does not belong.
        if (code === "REPLAY_MISS" && fields["CH"] && fields["SYM"]) {
          const key = streamKey(fields["CH"], fields["SYM"]);
          const ts = this.pendingResumeTs.get(key);
          // Nothing is coming to fill the hole this ERR refuses, so the range
          // held open for it would only mislabel a later redelivery as
          // backfill.
          const position = this.streams.get(key);
          if (position !== undefined) position.holes = [];
          if (ts !== undefined) {
            this.pendingResumeTs.delete(key);
            this.emit("gap", { ch: fields["CH"], sym: fields["SYM"], ts });
          }
        }
        return;
      }
      default:
        return this.onStreamMessage(msgType, fields);
    }
  }

  private onWelcome(fields: Record<string, string>): void {
    const welcome = parseWelcome(fields);
    this.handshaken = true;
    this.gateway = welcome.gateway;
    this.supportedChannels = welcome.chSupported;
    this.reconnectDelayMs = RECONNECT_MIN_MS;

    for (const sym of welcome.symbols) this.learnSymbol(sym);
    this.learnTickDecimals(welcome.tickDecimals);

    this.emit("welcome", welcome);
    // Ask rather than rely on WELCOME|SYMBOLS=, which is optional and absent
    // whenever the gateway could not read an engine config.
    this.send(buildSymbolsRequest());
    this.subscribeAll();
    this.armPing();
    this.setState("ACTIVE");
  }

  /**
   * Issue every subscription this bridge should hold, from scratch.
   *
   * Called on first connect and again after every reconnect — the gateway
   * keeps no subscription state across connections, and the automatic `SNAP`
   * each `SUB` triggers is what makes a plain re-subscribe an adequate
   * substitute for the per-stream `RESUME` the design assumed.
   */
  private subscribeAll(): void {
    const wildcards = WILDCARD_CHANNELS.filter((ch) => this.supports(ch));
    if (wildcards.length > 0) this.send(buildSub(wildcards, ["*"]));

    if (this.opts.indexIds.length > 0 && this.supports("INDEX")) {
      this.send(buildSub(["INDEX"], this.opts.indexIds));
    }

    for (const { ch, sym } of this.refCount.active()) this.sendSub(ch, sym);
  }

  /**
   * Whether the gateway advertised this channel.
   *
   * A gateway predating `CH_SUPPORTED` sends no such field at all; treating an
   * empty set as "supports everything" keeps the bridge working against one
   * rather than refusing to subscribe to anything.
   */
  private supports(ch: Channel): boolean {
    return this.supportedChannels.size === 0 || this.supportedChannels.has(ch);
  }

  private sendSub(ch: WatchChannel, sym: string): void {
    if (!this.supports(ch)) return;
    this.send(buildSub([ch], [sym]));
  }

  // -- stream dispatch --------------------------------------------------------

  private onStreamMessage(msgType: string, fields: Record<string, string>): void {
    const { ch, sym, seq, ts } = readEnvelope(fields);
    if (sym !== "*") this.learnSymbol(sym);

    // SYM=* (today, only STATE's exchange-wide session stream) is deliberately
    // not gap-checked here. It does have its own real, independently
    // sequenced SEQ, so a gap purely on that stream — distinct from any
    // concrete symbol's own STATE delivery — would go undetected. Accepted
    // rather than closed: RESUME itself rejects SYM=* on every channel (the
    // gateway has no per-symbol snapshot path to serve one from), STATE is
    // SNAPSHOT_ELIGIBLE so the reconnect that would cause a real gap also
    // triggers a fresh SNAP, and every exchange-wide transition this stream
    // carries is also re-emitted per concrete symbol, which does get checked.
    //
    // A SEQ of 0 is `readEnvelope`'s default for a missing or unparseable
    // field, not a position. Sequencing against it would baseline the stream
    // at 0, make the next real SEQ look like a gap, and send a RESUME the
    // gateway rejects with BAD_MESSAGE rather than REPLAY_MISS — leaving a
    // hole nobody is told about. Pass such a message through unsequenced.
    const sequenced = sym !== "*" && seq > 0;

    if (msgType === "SNAP") {
      // A SNAP is a baseline, never a continuation: it re-anchors the stream
      // wherever the gateway currently is, so it can never be a gap and must
      // not be compared as one. Skipping this is not cosmetic — the gateway
      // answers REPLAY_MISS with a SNAP, so a SNAP that left the baseline
      // behind would make the next live message look like a fresh gap and
      // RESUME again, against a window already proved too old. That loops.
      // Outstanding holes go with it: a snapshot supersedes them, and nothing
      // is coming to fill them.
      if (sequenced) {
        this.streams.set(streamKey(ch, sym), { seq, gen: this.generation, holes: [] });
      }

      // ...and `_send_snapshot_for_stream` only knows how to fill
      // TOP/STATE/INDEX/DEPTH/CB. On TRADE or AUCTION it emits an envelope
      // with no payload at all, which `decodeTrade` reads as a print of zero
      // shares at zero price. There is no snapshot of a print; the ERR that
      // preceded this one already said the prints are gone.
      if (!isChannel(ch) || !SNAPSHOT_ELIGIBLE.has(ch)) return;
    } else if (sequenced && !this.checkForGap(ch, sym, seq, ts)) {
      return;
    }

    switch (ch) {
      case "TOP":
        // Both SNAP and MD are partial; only the merged view is meaningful.
        this.emit("frame", { type: "top", sym, seq, ts, ...this.topCache.merge(sym, decodeTop(fields)) });
        return;

      case "TRADE": {
        const trade = decodeTrade(fields);
        this.emit("frame", { type: "trade", sym, seq, ts, ...trade, side: trade.side as TradeSide });
        return;
      }

      case "STATE":
        this.emit("frame", { type: "state", sym, seq, ts, ...decodeState(fields) });
        return;

      case "INDEX":
        this.emit("frame", { type: "index", sym, seq, ts, ...decodeIndex(fields) });
        return;

      case "DEPTH":
        this.emit("frame", { type: "depth", sym, seq, ts, ...decodeDepth(fields) });
        return;

      case "AUCTION":
        this.emit("frame", { type: "auction_result", sym, seq, ts, ...decodeAuction(fields) });
        return;

      case "CB":
        this.emit("frame", { type: "halt_context", sym, seq, ts, ...decodeCb(fields) });
        return;

      default:
        this.emit("gatewayError", { code: "UNKNOWN_CHANNEL", detail: { ch, msgType } });
    }
  }

  private learnSymbol(sym: string): void {
    if (this.knownSymbols.has(sym)) return;
    this.knownSymbols.add(sym);
    this.emit("symbol", sym);
  }

  /**
   * Notice a hole in one `(ch, sym)` stream and, where possible, close it
   * (T-H4/T-H5).
   *
   * `SEQ` is strictly increasing per stream on the gateway side (never reset
   * by a client reconnecting — the counter lives in the gateway process), so
   * anything past the recorded position + 1 means at least one message never
   * reached this bridge. The first message ever seen for a stream has nothing
   * to compare against and is never a gap by definition — it is establishing
   * the baseline, not continuing one.
   *
   * Returns whether the caller should pass the message on.
   *
   * A `seq` at or below what is on record is not automatically a duplicate.
   * `RESUME|LASTSEQ=n` asks `replay_since` for *everything* past `n`, and `n`
   * is the baseline from before the jump — so one reply carries both the
   * messages that were genuinely missing and the ones already delivered above
   * them. `StreamPosition.holes` is what separates the two. Getting this wrong
   * in either direction is a data defect: emitting a duplicate prints the same
   * trade on the tape twice, and dropping a backfill loses the print the
   * `RESUME` was sent to recover.
   */
  private checkForGap(ch: string, sym: string, seq: number, ts: string): boolean {
    const key = streamKey(ch, sym);
    const position = this.streams.get(key);

    if (position === undefined) {
      // The first message on a stream establishes the baseline; it is never a
      // gap, because there is nothing yet for it to be a gap in.
      this.streams.set(key, { seq, gen: this.generation, holes: [] });
      return true;
    }

    if (seq <= position.seq) {
      // A gateway that restarted numbers this stream from 1 again. Adopting
      // its numbering is the only alternative to discarding the stream for
      // good — see `StreamPosition.gen`.
      if (position.gen !== this.generation) {
        this.streams.set(key, { seq, gen: this.generation, holes: [] });
        return true;
      }
      // Backfill inside a hole is wanted; anything else is a redelivery of a
      // message already emitted. Either way the baseline stays put: moving it
      // backward would turn the next ordinary message into a phantom gap (or,
      // just as easily, paper over a real one).
      return takeFromHole(position, seq);
    }

    const previous = position.seq;
    position.seq = seq;
    position.gen = this.generation;

    if (seq === previous + 1) return true;

    if (isChannel(ch) && RESUMABLE_CHANNELS.has(ch)) {
      position.holes.push({ from: previous + 1, to: seq - 1 });
      // Held so the REPLAY_MISS that may answer this can be placed in time by
      // the gateway's clock rather than ours — see `pendingResumeTs`.
      this.pendingResumeTs.set(key, ts);
      this.send(buildResume(ch, sym, previous));
      return true;
    }

    // A gap on a snapshot-baselined channel is not worth telling a viewer
    // about: the SUB that follows every reconnect triggers a fresh SNAP for
    // exactly these channels, so whatever was missed is already superseded by
    // the time anyone could act on knowing about it. Only a channel with no
    // baseline — AUCTION, here; TRADE took the RESUME branch above — leaves a
    // hole nothing else will ever close.
    if (isChannel(ch) && SNAPSHOT_ELIGIBLE.has(ch)) return true;

    this.emit("gap", { ch, sym, ts });
    return true;
  }

  /**
   * Merge a `REF=` map, newest wins.
   *
   * Merged rather than replaced for the same reason the symbol set is: the
   * `SYMBOLS` reply and `WELCOME` are two views of the same reference data
   * arriving at different moments, and a reconnect should never narrow what
   * the bridge already knows.
   */
  private learnTickDecimals(decimals: Record<string, number>): void {
    Object.assign(this.knownTickDecimals, decimals);
  }

  // -- plumbing ----------------------------------------------------------------

  private send(line: string): void {
    if (!this.handshaken || !this.socket) return;
    this.socket.write(line);
  }

  private armPing(): void {
    if (this.pingTimer) clearInterval(this.pingTimer);
    this.pingTimer = setInterval(() => this.send(buildPing()), this.opts.pingIntervalSec * 1000);
    this.pingTimer.unref?.();
  }

  private clearTimers(): void {
    if (this.pingTimer) {
      clearInterval(this.pingTimer);
      this.pingTimer = null;
    }
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
  }

  private setState(state: CalfState): void {
    if (this.state === state) return;
    this.state = state;
    this.stateSince = new Date().toISOString();
    this.emit("status", state);
  }
}
