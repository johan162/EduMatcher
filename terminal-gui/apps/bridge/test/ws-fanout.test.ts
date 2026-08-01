import { beforeEach, describe, expect, it } from "vitest";
import type { WebSocket } from "ws";
import type { ClientFrame, ServerFrame } from "@edumatcher/terminal-types";
import { WsHub, type SubscriptionSink } from "../src/ws-fanout.js";

/** A WebSocket stand-in that records what it was sent and can be closed. */
class FakeSocket {
  readonly OPEN = 1;
  readonly sent: ServerFrame[] = [];
  readyState = 1;
  private handlers: Record<string, Array<(arg: Buffer) => void>> = {};

  on(event: string, handler: (arg: Buffer) => void): this {
    (this.handlers[event] ??= []).push(handler);
    return this;
  }

  send(encoded: string): void {
    this.sent.push(JSON.parse(encoded) as ServerFrame);
  }

  /** Simulate the tab sending a control frame. */
  receive(frame: ClientFrame): void {
    for (const handler of this.handlers["message"] ?? []) handler(Buffer.from(JSON.stringify(frame), "utf8"));
  }

  /** Simulate the tab going away. */
  close(): void {
    this.readyState = 3;
    for (const handler of this.handlers["close"] ?? []) handler(Buffer.alloc(0));
  }

  framesOfType(type: ServerFrame["type"]): ServerFrame[] {
    return this.sent.filter((frame) => frame.type === type);
  }

  asWebSocket(): WebSocket {
    return this as unknown as WebSocket;
  }
}

class RecordingSink implements SubscriptionSink {
  readonly calls: string[] = [];
  watch(ch: string, sym: string): void {
    this.calls.push(`watch ${ch} ${sym}`);
  }
  unwatch(ch: string, sym: string): void {
    this.calls.push(`unwatch ${ch} ${sym}`);
  }
}

const topFrame = (sym: string): ServerFrame => ({ type: "top", sym, seq: 1, ts: "t", bid: 1, ask: 2 });
const depthFrame = (sym: string): ServerFrame => ({
  type: "depth",
  sym,
  seq: 1,
  ts: "t",
  levels: 10,
  bids: [],
  asks: [],
});
const haltFrame = (sym: string): ServerFrame => ({
  type: "halt_context",
  sym,
  seq: 1,
  ts: "t",
  status: "HALTED",
});
const stateFrame = (sym: string, session: string): ServerFrame => ({
  type: "state",
  sym,
  seq: 1,
  ts: "t",
  session,
});

describe("WsHub", () => {
  let sink: RecordingSink;
  let hub: WsHub;

  beforeEach(() => {
    sink = new RecordingSink();
    hub = new WsHub(sink, 3);
  });

  function connect(): FakeSocket {
    const socket = new FakeSocket();
    hub.register(socket.asWebSocket());
    return socket;
  }

  describe("capacity", () => {
    it("accepts tabs up to the configured cap", () => {
      expect([connect(), connect(), connect()].every(Boolean)).toBe(true);
      expect(hub.clientCount).toBe(3);
    });

    it("refuses the tab that would exceed the cap", () => {
      connect();
      connect();
      connect();
      expect(hub.register(new FakeSocket().asWebSocket())).toBe(false);
      expect(hub.clientCount).toBe(3);
    });

    it("frees a slot when a tab closes", () => {
      const first = connect();
      connect();
      connect();
      first.close();
      expect(hub.register(new FakeSocket().asWebSocket())).toBe(true);
    });
  });

  describe("broadcast routing", () => {
    it("sends wildcard-channel frames to every tab regardless of interest", () => {
      const a = connect();
      const b = connect();
      hub.broadcast(topFrame("AAPL"));

      expect(a.framesOfType("top")).toHaveLength(1);
      expect(b.framesOfType("top")).toHaveLength(1);
    });

    it("sends a gap marker to every tab, the same as any other stream frame (T-H4/T-H5)", () => {
      const a = connect();
      const b = connect();
      hub.broadcast({ type: "gap", ch: "TRADE", sym: "AAPL", ts: "t" });

      expect(a.framesOfType("gap")).toHaveLength(1);
      expect(b.framesOfType("gap")).toHaveLength(1);
    });

    it("withholds depth from a tab that never asked for it", () => {
      const tab = connect();
      hub.broadcast(depthFrame("AAPL"));
      expect(tab.framesOfType("depth")).toHaveLength(0);
    });

    it("sends depth only to the tab that subscribed, and only for its symbol", () => {
      const watching = connect();
      const other = connect();
      watching.receive({ t: "subscribe", ch: "DEPTH", sym: "AAPL" });

      hub.broadcast(depthFrame("AAPL"));
      hub.broadcast(depthFrame("MSFT"));

      expect(watching.framesOfType("depth")).toHaveLength(1);
      expect(other.framesOfType("depth")).toHaveLength(0);
    });

    it("stops sending depth after the tab unsubscribes", () => {
      const tab = connect();
      tab.receive({ t: "subscribe", ch: "DEPTH", sym: "AAPL" });
      tab.receive({ t: "unsubscribe", ch: "DEPTH", sym: "AAPL" });

      hub.broadcast(depthFrame("AAPL"));
      expect(tab.framesOfType("depth")).toHaveLength(0);
    });

    it("sends halt context to a tab with that symbol's detail view open", () => {
      const tab = connect();
      tab.receive({ t: "subscribe", ch: "CB", sym: "TSLA" });

      hub.broadcast(haltFrame("TSLA"));
      expect(tab.framesOfType("halt_context")).toHaveLength(1);
    });

    it("ignores a malformed control frame instead of dropping the tab", () => {
      const tab = connect();
      for (const handler of (tab as unknown as { handlers: Record<string, Array<(b: Buffer) => void>> })
        .handlers["message"] ?? []) {
        handler(Buffer.from("not json", "utf8"));
      }

      hub.broadcast(topFrame("AAPL"));
      expect(tab.framesOfType("top")).toHaveLength(1);
    });

    it("skips a socket that is no longer open", () => {
      const tab = connect();
      tab.readyState = 3;
      hub.broadcast(topFrame("AAPL"));
      expect(tab.sent).toHaveLength(0);
    });
  });

  describe("upstream subscriptions", () => {
    it("asks the uplink to watch what a tab subscribed to", () => {
      connect().receive({ t: "subscribe", ch: "DEPTH", sym: "AAPL" });
      expect(sink.calls).toEqual(["watch DEPTH AAPL"]);
    });

    it("does not double-acquire when a tab subscribes twice", () => {
      const tab = connect();
      tab.receive({ t: "subscribe", ch: "DEPTH", sym: "AAPL" });
      tab.receive({ t: "subscribe", ch: "DEPTH", sym: "AAPL" });
      expect(sink.calls).toEqual(["watch DEPTH AAPL"]);
    });

    it("ignores an unsubscribe for something the tab never held", () => {
      connect().receive({ t: "unsubscribe", ch: "DEPTH", sym: "AAPL" });
      expect(sink.calls).toEqual([]);
    });

    it("releases everything a tab held when it disconnects", () => {
      const tab = connect();
      tab.receive({ t: "subscribe", ch: "DEPTH", sym: "AAPL" });
      tab.receive({ t: "subscribe", ch: "CB", sym: "TSLA" });
      tab.close();

      expect(sink.calls).toEqual(expect.arrayContaining(["unwatch DEPTH AAPL", "unwatch CB TSLA"]));
    });

    it("releases a disconnected tab's holds exactly once", () => {
      const tab = connect();
      tab.receive({ t: "subscribe", ch: "DEPTH", sym: "AAPL" });
      tab.close();
      tab.close();

      expect(sink.calls.filter((call) => call === "unwatch DEPTH AAPL")).toHaveLength(1);
    });
  });

  describe("session board CB triggering", () => {
    it("acquires CB for a symbol that halts while the board is open", () => {
      const tab = connect();
      tab.receive({ t: "halt_board", open: true });
      hub.broadcast(stateFrame("TSLA", "HALTED"));

      expect(sink.calls).toEqual(["watch CB TSLA"]);
    });

    it("delivers that symbol's halt context to the board", () => {
      const tab = connect();
      tab.receive({ t: "halt_board", open: true });
      hub.broadcast(stateFrame("TSLA", "HALTED"));
      hub.broadcast(haltFrame("TSLA"));

      expect(tab.framesOfType("halt_context")).toHaveLength(1);
    });

    it("picks up symbols already halted when the board opens", () => {
      const tab = connect();
      hub.broadcast(stateFrame("TSLA", "HALTED"));
      tab.receive({ t: "halt_board", open: true });

      expect(sink.calls).toEqual(["watch CB TSLA"]);
    });

    it("releases CB when the symbol resumes", () => {
      const tab = connect();
      tab.receive({ t: "halt_board", open: true });
      hub.broadcast(stateFrame("TSLA", "HALTED"));
      hub.broadcast(stateFrame("TSLA", "CONTINUOUS"));

      expect(sink.calls).toEqual(["watch CB TSLA", "unwatch CB TSLA"]);
    });

    it("does not treat an exchange-wide session change as a symbol halt", () => {
      const tab = connect();
      tab.receive({ t: "halt_board", open: true });
      hub.broadcast(stateFrame("*", "HALTED"));

      expect(sink.calls).toEqual([]);
    });

    it("ignores a repeated halt for a symbol already halted", () => {
      const tab = connect();
      tab.receive({ t: "halt_board", open: true });
      hub.broadcast(stateFrame("TSLA", "HALTED"));
      hub.broadcast(stateFrame("TSLA", "HALTED"));

      expect(sink.calls).toEqual(["watch CB TSLA"]);
    });

    it("releases every board hold when the board closes", () => {
      const tab = connect();
      tab.receive({ t: "halt_board", open: true });
      hub.broadcast(stateFrame("TSLA", "HALTED"));
      hub.broadcast(stateFrame("AAPL", "HALTED"));
      tab.receive({ t: "halt_board", open: false });

      expect(sink.calls).toEqual(["watch CB TSLA", "watch CB AAPL", "unwatch CB TSLA", "unwatch CB AAPL"]);
    });

    it("releases board holds when the tab disconnects with the board still open", () => {
      const tab = connect();
      tab.receive({ t: "halt_board", open: true });
      hub.broadcast(stateFrame("TSLA", "HALTED"));
      tab.close();

      expect(sink.calls).toEqual(["watch CB TSLA", "unwatch CB TSLA"]);
    });

    it("counts a detail view and a board as two independent holders", () => {
      const detail = connect();
      const board = connect();
      detail.receive({ t: "subscribe", ch: "CB", sym: "TSLA" });
      board.receive({ t: "halt_board", open: true });
      hub.broadcast(stateFrame("TSLA", "HALTED"));

      // Two acquires — the refcount downstream is what collapses them into
      // one CALF subscription.
      expect(sink.calls).toEqual(["watch CB TSLA", "watch CB TSLA"]);

      detail.close();
      expect(sink.calls.filter((c) => c === "unwatch CB TSLA")).toHaveLength(1);
    });

    it("ignores a redundant board-open", () => {
      const tab = connect();
      hub.broadcast(stateFrame("TSLA", "HALTED"));
      tab.receive({ t: "halt_board", open: true });
      tab.receive({ t: "halt_board", open: true });

      expect(sink.calls).toEqual(["watch CB TSLA"]);
    });
  });
});
