/**
 * Standing interest must survive a reconnect.
 *
 * The bridge reference-counts per-symbol channels across tabs and releases a
 * tab's holds the instant its socket closes. That is right, but it means a
 * reconnected tab holds nothing while its components still believe they
 * asked — so `DEPTH` and `CB` stop arriving and nothing says so. A depth
 * ladder frozen on its last pre-outage frame is a book that is *wrong*
 * rather than absent, which is the failure this terminal cannot ship with.
 *
 * The views cannot fix this themselves: their effects are keyed on the
 * symbol, not on the connection, so they never fire again.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ClientFrame } from "@edumatcher/terminal-types";
import { TerminalStreamClient } from "../src/lib/ws.js";

/** A WebSocket stand-in that records what was sent and can be opened/closed. */
class FakeSocket {
  static instances: FakeSocket[] = [];
  static readonly OPEN = 1;
  static readonly CLOSED = 3;

  readyState = 0;
  sent: string[] = [];
  private readonly listeners = new Map<string, Array<(event?: unknown) => void>>();

  constructor(readonly url: string) {
    FakeSocket.instances.push(this);
  }

  addEventListener(type: string, handler: (event?: unknown) => void): void {
    const existing = this.listeners.get(type) ?? [];
    existing.push(handler);
    this.listeners.set(type, existing);
  }

  send(data: string): void {
    this.sent.push(data);
  }

  close(): void {
    this.readyState = FakeSocket.CLOSED;
    this.fire("close");
  }

  /** Drive the socket to open, as the browser would. */
  accept(): void {
    this.readyState = FakeSocket.OPEN;
    this.fire("open");
  }

  /** Drive an inbound server frame, as the browser would deliver a "message". */
  deliver(frame: unknown): void {
    this.fire("message", { data: JSON.stringify(frame) });
  }

  private fire(type: string, event?: unknown): void {
    for (const handler of this.listeners.get(type) ?? []) handler(event);
  }

  get frames(): ClientFrame[] {
    return this.sent.map((raw) => JSON.parse(raw) as ClientFrame);
  }
}

beforeEach(() => {
  FakeSocket.instances = [];
  vi.stubGlobal("WebSocket", FakeSocket);
  vi.stubGlobal("window", { location: { protocol: "http:", host: "localhost:8190" } });
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

function connected(): { client: TerminalStreamClient; socket: () => FakeSocket } {
  const client = new TerminalStreamClient(
    () => undefined,
    () => undefined,
  );
  client.connect();
  FakeSocket.instances[0]?.accept();
  return { client, socket: () => FakeSocket.instances.at(-1) as FakeSocket };
}

describe("subscriptions across a reconnect", () => {
  it("re-declares every standing subscription on the new socket", () => {
    const { client, socket } = connected();
    client.send({ t: "subscribe", ch: "DEPTH", sym: "AAPL" });
    client.send({ t: "subscribe", ch: "CB", sym: "AAPL" });

    socket().close();
    vi.advanceTimersByTime(1_000);
    socket().accept();

    expect(socket().frames).toEqual([
      { t: "subscribe", ch: "DEPTH", sym: "AAPL" },
      { t: "subscribe", ch: "CB", sym: "AAPL" },
    ]);
  });

  it("does not re-declare something that was unsubscribed before the drop", () => {
    const { client, socket } = connected();
    client.send({ t: "subscribe", ch: "DEPTH", sym: "AAPL" });
    client.send({ t: "unsubscribe", ch: "DEPTH", sym: "AAPL" });

    socket().close();
    vi.advanceTimersByTime(1_000);
    socket().accept();

    expect(socket().frames).toEqual([]);
  });

  it("re-opens the halt board, which is standing interest too", () => {
    const { client, socket } = connected();
    client.send({ t: "halt_board", open: true });

    socket().close();
    vi.advanceTimersByTime(1_000);
    socket().accept();

    expect(socket().frames).toEqual([{ t: "halt_board", open: true }]);
  });

  it("forgets a closed halt board", () => {
    const { client, socket } = connected();
    client.send({ t: "halt_board", open: true });
    client.send({ t: "halt_board", open: false });

    socket().close();
    vi.advanceTimersByTime(1_000);
    socket().accept();

    expect(socket().frames).toEqual([]);
  });

  it("does not replay a ping, which carries no standing state", () => {
    const { client, socket } = connected();
    client.send({ t: "ping" });

    socket().close();
    vi.advanceTimersByTime(1_000);
    socket().accept();

    expect(socket().frames).toEqual([]);
  });

  it("declares a subscription only once, however many times it was asked for", () => {
    // The bridge refuses a duplicate hold, so a replayed duplicate would
    // leave a hold nothing releases.
    const { client, socket } = connected();
    client.send({ t: "subscribe", ch: "DEPTH", sym: "AAPL" });
    client.send({ t: "subscribe", ch: "DEPTH", sym: "AAPL" });

    socket().close();
    vi.advanceTimersByTime(1_000);
    socket().accept();

    expect(socket().frames).toEqual([{ t: "subscribe", ch: "DEPTH", sym: "AAPL" }]);
  });

  it("survives more than one reconnect", () => {
    const { client, socket } = connected();
    client.send({ t: "subscribe", ch: "CB", sym: "TSLA" });

    for (let i = 0; i < 3; i += 1) {
      socket().close();
      vi.advanceTimersByTime(30_000);
      socket().accept();
      expect(socket().frames).toEqual([{ t: "subscribe", ch: "CB", sym: "TSLA" }]);
    }
  });
});

/**
 * H4: a half-open socket never fires the browser's own `close` event, so the
 * only way to notice it is a watchdog timing out on frames actually received.
 */
describe("liveness watchdog on a silent socket", () => {
  it("closes the socket and goes reconnecting after three missed heartbeat intervals", () => {
    const statuses: string[] = [];
    const client = new TerminalStreamClient(
      () => undefined,
      (status) => statuses.push(status),
    );
    client.connect();
    FakeSocket.instances[0]?.accept();

    // The socket never receives another frame and never fires "close" itself
    // — exactly what a half-open TCP path looks like from here.
    vi.advanceTimersByTime(14_999);
    expect(statuses).not.toContain("reconnecting");

    vi.advanceTimersByTime(1);
    expect(statuses).toContain("reconnecting");
  });

  it("does not fire while frames keep arriving, including bare heartbeats", () => {
    const statuses: string[] = [];
    const client = new TerminalStreamClient(
      () => undefined,
      (status) => statuses.push(status),
    );
    client.connect();
    const socket = FakeSocket.instances[0]!;
    socket.accept();

    for (let i = 0; i < 5; i += 1) {
      vi.advanceTimersByTime(4_000);
      socket.deliver({ type: "bridge_status", calf: "ACTIVE", since: "t", wsClients: 1 });
    }

    expect(statuses).not.toContain("reconnecting");
  });

  it("gives a reconnected socket a fresh window rather than the old deadline", () => {
    const statuses: string[] = [];
    const client = new TerminalStreamClient(
      () => undefined,
      (status) => statuses.push(status),
    );
    client.connect();
    FakeSocket.instances[0]?.accept();

    vi.advanceTimersByTime(10_000);
    FakeSocket.instances[0]?.close();
    vi.advanceTimersByTime(500); // the reconnect backoff
    FakeSocket.instances.at(-1)?.accept();
    statuses.length = 0;

    // Only 10s left if the old deadline carried over; it must not have.
    vi.advanceTimersByTime(10_000);
    expect(statuses).not.toContain("reconnecting");
  });
});
