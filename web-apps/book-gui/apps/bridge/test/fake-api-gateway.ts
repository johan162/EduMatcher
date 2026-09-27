/**
 * A scriptable stand-in for `pm-api-gwy`: the `WS /api/v1/market-data` socket
 * and the REST reads the bridge uses (`/history/session`, `/history/trades`,
 * `/history/daily`, `/reference/symbols`).
 *
 * Behaviour mirrors the real gateway as observed in WP0 (captures in
 * `fixtures/`): auth first frame, subscription ack, cached `book` + trade tail
 * on subscribe, `resume_from` / `resume` replaying prints after a `seq`, and
 * `trades.reset` when a resume is too old.
 */

import websocketPlugin from "@fastify/websocket";
import Fastify, { type FastifyInstance } from "fastify";
import type { WebSocket } from "ws";

export interface HistoryTradeRow {
  ts: string;
  trade_id: string;
  symbol: string;
  price: number;
  quantity: number;
  tick_decimals: number;
  aggressor_side: string;
}

export interface DailyRow {
  date: string;
  symbol: string;
  close_price: number | null;
}

interface Envelope {
  type: string;
  topic: string;
  ts: string;
  seq: number;
  data: Record<string, unknown>;
}

interface Client {
  socket: WebSocket;
  authed: boolean;
  syms: Set<string>;
}

export class FakeApiGateway {
  readonly app: FastifyInstance;
  port = 0;
  apiKey = "ro-key";

  /** Every control frame any client sent, after auth. */
  readonly controls: Record<string, unknown>[] = [];
  historyTrades: Record<string, HistoryTradeRow[]> = {};
  daily: Record<string, DailyRow[]> = {};
  session = { session_timezone: "Europe/Stockholm", session_date: "2026-09-27" };
  symbols = [
    { symbol: "AAPL", tick_decimals: 2 },
    { symbol: "MSFT", tick_decimals: 2 },
    { symbol: "BRK", tick_decimals: 0 },
  ];
  /** Set to e.g. 503 to make every history read fail. */
  historyStatus = 200;
  /** `/history/trades` rows per page, whatever `limit` asks for — to exercise paging. */
  pageSize = 2;
  /** Answer the next resume (explicit or `resume_from`) with `trades.reset`. */
  resetNextResume = false;

  private readonly clients = new Set<Client>();
  private readonly bookCache = new Map<string, Envelope>();
  private readonly tradeTail = new Map<string, Envelope[]>();
  private readonly bookSeq = new Map<string, number>();
  private tradeSeq = 0;

  constructor() {
    this.app = Fastify({ logger: false });
  }

  async start(): Promise<void> {
    await this.app.register(websocketPlugin);
    this.routes();
    await this.app.listen({ host: "127.0.0.1", port: this.port });
    const addr = this.app.server.address();
    if (addr && typeof addr === "object") this.port = addr.port;
  }

  get baseUrl(): string {
    return `http://127.0.0.1:${this.port}`;
  }

  async stop(): Promise<void> {
    this.dropAll();
    await this.app.close();
  }

  /** Publish a book snapshot. `seqJump` skips that many seqs, simulating dropped events. */
  pushBook(sym: string, data: Record<string, unknown>, seqJump = 0): void {
    const seq = (this.bookSeq.get(sym) ?? 0) + 1 + seqJump;
    this.bookSeq.set(sym, seq);
    const env: Envelope = {
      type: "book",
      topic: `book.${sym}`,
      ts: new Date().toISOString(),
      seq,
      data: { symbol: sym, tick_decimals: 2, ...data },
    };
    this.bookCache.set(sym, env);
    this.sendTo(sym, env);
  }

  /** Publish a print; `deliver: false` records it in the tail only, as if the socket had dropped it. */
  pushTrade(sym: string, id: string, price: number, quantity: number, deliver = true): void {
    this.tradeSeq += 1;
    const env: Envelope = {
      type: "trade",
      topic: "trade.executed",
      ts: new Date().toISOString(),
      seq: this.tradeSeq,
      data: {
        id,
        symbol: sym,
        price,
        quantity,
        aggressor_side: "BUY",
        ts_ns: Date.parse("2026-09-27T10:00:00Z") * 1e6 + this.tradeSeq * 1e9,
        tick_decimals: 2,
      },
    };
    const tail = this.tradeTail.get(sym) ?? [];
    tail.push(env);
    this.tradeTail.set(sym, tail);
    if (deliver) this.sendTo(sym, env);
  }

  /** Close every market-data socket, as a gateway restart would. */
  dropAll(): void {
    for (const c of this.clients) c.socket.terminate();
    this.clients.clear();
  }

  subscribesFor(sym: string): Record<string, unknown>[] {
    return this.controls.filter(
      (c) => c["action"] === "subscribe" && JSON.stringify(c["items"]).includes(`"${sym}"`),
    );
  }

  async until(predicate: () => boolean, timeoutMs = 3000): Promise<void> {
    const deadline = Date.now() + timeoutMs;
    while (!predicate()) {
      if (Date.now() > deadline) throw new Error("fake gateway: condition not met in time");
      await new Promise((r) => setTimeout(r, 10));
    }
  }

  private sendTo(sym: string, env: Envelope): void {
    for (const c of this.clients) if (c.authed && c.syms.has(sym)) c.socket.send(JSON.stringify(env));
  }

  private replayTrades(client: Client, sym: string, fromSeq?: number): void {
    const tail = this.tradeTail.get(sym) ?? [];
    if (fromSeq !== undefined && this.resetNextResume) {
      this.resetNextResume = false;
      client.socket.send(
        JSON.stringify({ type: "trades.reset", topic: "trade.executed", data: { symbol: sym } }),
      );
      client.socket.send(JSON.stringify({ type: "resume.rejected", data: { reason: "too_old" } }));
    } else if (fromSeq !== undefined) {
      for (const env of tail) if (env.seq > fromSeq) client.socket.send(JSON.stringify(env));
      return;
    }
    for (const env of tail) client.socket.send(JSON.stringify(env));
  }

  private routes(): void {
    this.app.get("/api/v1/market-data", { websocket: true }, (socket) => {
      const client: Client = { socket, authed: false, syms: new Set() };
      socket.on("message", (raw: Buffer) => {
        const msg = JSON.parse(raw.toString("utf8")) as Record<string, unknown>;
        if (!client.authed) {
          if (msg["api_key"] !== this.apiKey) {
            socket.close(1008);
            return;
          }
          client.authed = true;
          this.clients.add(client);
          socket.send(JSON.stringify({ type: "authenticated" }));
          return;
        }
        this.controls.push(msg);
        const items = (msg["items"] as { symbols: string[]; resume_from?: { trades?: number } }[]) ?? [];
        if (msg["action"] === "subscribe") {
          for (const item of items) {
            for (const sym of item.symbols) {
              client.syms.add(sym);
              socket.send(JSON.stringify({ type: "subscription", data: { symbols: [...client.syms] } }));
              const book = this.bookCache.get(sym);
              if (book) socket.send(JSON.stringify(book));
              this.replayTrades(client, sym, item.resume_from?.trades);
            }
          }
        } else if (msg["action"] === "unsubscribe") {
          for (const item of items) for (const sym of item.symbols) client.syms.delete(sym);
          socket.send(JSON.stringify({ type: "subscription", data: { symbols: [...client.syms] } }));
        } else if (msg["action"] === "resume") {
          const sym = (msg["symbols"] as string[])[0] ?? "";
          this.replayTrades(client, sym, msg["from_seq"] as number);
        }
      });
      socket.on("close", () => this.clients.delete(client));
    });

    const guard = (auth: string | undefined) => auth === `Bearer ${this.apiKey}`;

    this.app.get("/api/v1/history/session", (req, reply) => {
      if (!guard(req.headers.authorization)) return reply.status(401).send({});
      if (this.historyStatus !== 200) return reply.status(this.historyStatus).send({});
      return this.session;
    });

    this.app.get<{ Querystring: { symbol: string; date: string; after?: string } }>(
      "/api/v1/history/trades",
      (req, reply) => {
        if (!guard(req.headers.authorization)) return reply.status(401).send({});
        if (this.historyStatus !== 200) return reply.status(this.historyStatus).send({});
        const rows = (this.historyTrades[req.query.symbol] ?? []).filter((r) =>
          r.ts.startsWith(req.query.date),
        );
        const start = req.query.after ? Number(req.query.after) : 0;
        const page = rows.slice(start, start + this.pageSize);
        const hasMore = start + this.pageSize < rows.length;
        return {
          trades: page,
          count: page.length,
          has_more: hasMore,
          ...(hasMore ? { next_cursor: String(start + this.pageSize) } : {}),
        };
      },
    );

    this.app.get<{ Querystring: { symbol: string; from: string } }>("/api/v1/history/daily", (req, reply) => {
      if (!guard(req.headers.authorization)) return reply.status(401).send({});
      if (this.historyStatus !== 200) return reply.status(this.historyStatus).send({});
      const rows = (this.daily[req.query.symbol] ?? []).filter((r) => r.date >= req.query.from);
      return { daily: rows, count: rows.length, has_more: false };
    });

    this.app.get("/api/v1/reference/symbols", (req, reply) => {
      if (!guard(req.headers.authorization)) return reply.status(401).send({});
      return { symbols: this.symbols, config_version: "test" };
    });
  }
}

/** A `/history/trades` row for 2026-09-27, the fake's session date. */
export function historyRow(
  sym: string,
  id: string,
  price: number,
  quantity: number,
  time = "09:00:00",
): HistoryTradeRow {
  return {
    ts: `2026-09-27T${time}.000+00:00`,
    trade_id: id,
    symbol: sym,
    price,
    quantity,
    tick_decimals: 2,
    aggressor_side: "SELL",
  };
}
