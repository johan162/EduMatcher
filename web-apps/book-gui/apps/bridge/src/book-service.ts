/**
 * Ties the upstream connection, the history reads and the per-symbol session
 * books together (design §5.4).
 *
 * The session book for a symbol lives exactly as long as some tab watches it:
 * created and seeded on the first watch, dropped with the upstream
 * subscription on the last release.
 */

import { EventEmitter } from "node:events";
import type { ServerFrame, SymbolInfo } from "@edumatcher/book-types";
import type { Logger } from "./logging/logger.js";
import type { HistoryClient } from "./session/history-seed.js";
import { SessionBook } from "./session/session-book.js";
import type { MarketUplink } from "./upstream/market-uplink.js";
import { SymbolRefcount } from "./upstream/symbol-refcount.js";

export interface BookServiceEvents {
  /** A frame for the tabs watching one symbol. */
  symbolFrame: [string, ServerFrame];
  /** A frame for every tab. */
  frame: [ServerFrame];
}

export class BookService extends EventEmitter<BookServiceEvents> {
  symbols: SymbolInfo[] = [];

  private readonly refs = new SymbolRefcount();
  private readonly sessions = new Map<string, SessionBook>();

  constructor(
    private readonly uplink: MarketUplink,
    private readonly history: HistoryClient,
    private readonly tapeMax: number,
    private readonly log: Logger,
  ) {
    super();

    uplink.on("book", (frame) => {
      const session = this.sessions.get(frame.sym);
      if (!session) return;
      session.book = frame;
      this.emit("symbolFrame", frame.sym, frame);
    });

    uplink.on("trade", (sym, trade) => {
      const session = this.sessions.get(sym);
      const applied = session?.addLive(trade);
      if (!session || !applied) return;
      this.emit("symbolFrame", sym, { type: "trade", sym, trade: applied, stats: session.snapshot().stats });
    });

    uplink.on("reseed", (sym) => {
      const session = this.sessions.get(sym);
      if (!session) return;
      log.warn("book-bridge.session", `trades for ${sym} could not be replayed; re-seeding from history`);
      session.reset();
      void this.seed(sym, session);
    });

    uplink.on("status", (state) => {
      if (state === "ACTIVE") void this.refreshSymbols();
    });
  }

  /** Unknown until the reference data has been read; until then every symbol is accepted. */
  knows(sym: string): boolean {
    return this.symbols.length === 0 || this.symbols.some((s) => s.symbol === sym);
  }

  acquire(sym: string): void {
    if (!this.refs.acquire(sym)) return;
    const session = new SessionBook(this.tapeMax);
    this.sessions.set(sym, session);
    this.uplink.subscribe(sym);
    void this.seed(sym, session);
  }

  release(sym: string): void {
    if (!this.refs.release(sym)) return;
    this.sessions.delete(sym);
    this.uplink.unsubscribe(sym);
  }

  /** What a tab that has just started watching `sym` needs to render at once. */
  initialFrames(sym: string): ServerFrame[] {
    const session = this.sessions.get(sym);
    if (!session) return [];
    const frames: ServerFrame[] = [];
    if (session.book) frames.push(session.book);
    if (!session.seeding) frames.push({ type: "session", sym, ...session.snapshot() });
    return frames;
  }

  watched(): Record<string, number> {
    return this.refs.held();
  }

  async refreshSymbols(): Promise<void> {
    try {
      const symbols = await this.history.symbols();
      if (JSON.stringify(symbols) === JSON.stringify(this.symbols)) return;
      this.symbols = symbols;
      this.emit("frame", { type: "symbols", symbols });
    } catch (err) {
      this.log.warn("book-bridge.history", `symbol list unavailable: ${String(err)}`);
    }
  }

  private async seed(sym: string, session: SessionBook): Promise<void> {
    const generation = session.generation;
    const current = () => this.sessions.get(sym) === session && session.generation === generation;
    try {
      const { timezone, date } = await this.history.session();
      const [trades, prevClose] = await Promise.all([
        this.history.trades(sym, date),
        this.history.previousClose(sym, date),
      ]);
      if (!current()) return;
      session.seed(trades, { sessionDate: date, timezone, prevClose });
      this.log.info("book-bridge.session", `${sym} seeded from ${trades.length} trade(s) of ${date}`);
    } catch (err) {
      if (!current()) return;
      this.log.warn(
        "book-bridge.history",
        `history unavailable for ${sym}; live trades only: ${String(err)}`,
      );
      session.seedPartial(Date.now());
    }
    this.emit("symbolFrame", sym, { type: "session", sym, ...session.snapshot() });
  }
}
