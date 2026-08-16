import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import {
  ManagedSocket,
  backoffDelay,
  type ManagedSocketOptions,
  type WebSocketLike,
} from "@/ws/ManagedSocket";

/** Minimal scriptable stand-in for the browser WebSocket. */
class FakeSocket implements WebSocketLike {
  static instances: FakeSocket[] = [];
  readyState = 0;
  sent: string[] = [];
  closed = false;
  onopen: ((ev: unknown) => void) | null = null;
  onmessage: ((ev: { data: string }) => void) | null = null;
  onerror: ((ev: unknown) => void) | null = null;
  onclose: ((ev: { code?: number; reason?: string }) => void) | null = null;

  constructor(readonly url: string) {
    FakeSocket.instances.push(this);
  }

  send(data: string): void {
    this.sent.push(data);
  }

  close(code = 1000, reason = ""): void {
    if (this.closed) return;
    this.closed = true;
    this.readyState = 3;
    this.onclose?.({ code, reason });
  }

  // — test helpers —
  open(): void {
    this.readyState = 1;
    this.onopen?.({});
  }

  deliver(obj: unknown): void {
    this.onmessage?.({ data: JSON.stringify(obj) });
  }

  get frames(): unknown[] {
    return this.sent.map((s) => JSON.parse(s) as unknown);
  }
}

function makeSocket(opts: Partial<ManagedSocketOptions> = {}): ManagedSocket {
  return new ManagedSocket("ws://test/market-data", {
    authFrame: () => ({ api_key: "key-1" }),
    factory: (url) => new FakeSocket(url),
    ...opts,
  });
}

beforeEach(() => {
  FakeSocket.instances = [];
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("backoffDelay", () => {
  it("follows the §7.4 schedule and holds at the cap", () => {
    expect(backoffDelay(1)).toBe(1_000);
    expect(backoffDelay(2)).toBe(2_000);
    expect(backoffDelay(3)).toBe(4_000);
    expect(backoffDelay(4)).toBe(8_000);
    // The regression this guards: indexing the table with min(attempt, len-1)
    // pinned every later attempt at 8s and the 30s cap was never reached.
    expect(backoffDelay(5)).toBe(30_000);
    expect(backoffDelay(50)).toBe(30_000);
  });

  it("respects a lower cap", () => {
    expect(backoffDelay(4, 5_000)).toBe(5_000);
  });
});

describe("ManagedSocket", () => {
  it("sends the auth frame on open and stays CONNECTING until confirmed", () => {
    const s = makeSocket();
    s.connect();
    const ws = FakeSocket.instances[0]!;
    ws.open();

    expect(ws.frames).toEqual([{ api_key: "key-1" }]);
    expect(s.status).toBe("CONNECTING");

    ws.deliver({ type: "authenticated" });
    expect(s.status).toBe("OPEN");
    s.close();
  });

  it("invokes onReconnect after every authentication", () => {
    const onReconnect = vi.fn();
    const s = makeSocket({ onReconnect });
    s.connect();
    const first = FakeSocket.instances[0]!;
    first.open();
    first.deliver({ type: "authenticated" });
    expect(onReconnect).toHaveBeenCalledTimes(1);

    first.close(1006);
    vi.advanceTimersByTime(1_000);
    const second = FakeSocket.instances[1]!;
    expect(second).toBeDefined();
    second.open();
    second.deliver({ type: "authenticated" });
    expect(onReconnect).toHaveBeenCalledTimes(2);
    s.close();
  });

  it("drops a socket that never confirms authentication", () => {
    const s = makeSocket({ authTimeoutMs: 5_000 });
    s.connect();
    const ws = FakeSocket.instances[0]!;
    ws.open();
    expect(ws.closed).toBe(false);

    vi.advanceTimersByTime(5_000);
    expect(ws.closed).toBe(true);
    expect(s.status).toBe("CLOSED");

    // …and the backoff took over rather than leaving a dead socket.
    vi.advanceTimersByTime(1_000);
    expect(FakeSocket.instances).toHaveLength(2);
    s.close();
  });

  it("escalates the reconnect delay across consecutive failures", () => {
    const s = makeSocket();
    s.connect();
    FakeSocket.instances[0]!.close(1006);

    vi.advanceTimersByTime(999);
    expect(FakeSocket.instances).toHaveLength(1);
    vi.advanceTimersByTime(1);
    expect(FakeSocket.instances).toHaveLength(2);

    FakeSocket.instances[1]!.close(1006);
    vi.advanceTimersByTime(1_999);
    expect(FakeSocket.instances).toHaveLength(2);
    vi.advanceTimersByTime(1);
    expect(FakeSocket.instances).toHaveLength(3);
    s.close();
  });

  it("resets the backoff after a successful authentication", () => {
    const s = makeSocket();
    s.connect();
    FakeSocket.instances[0]!.close(1006);
    vi.advanceTimersByTime(1_000);
    const second = FakeSocket.instances[1]!;
    second.open();
    second.deliver({ type: "authenticated" });
    expect(s.reconnectAttempt).toBe(0);

    second.close(1006);
    vi.advanceTimersByTime(1_000);
    expect(FakeSocket.instances).toHaveLength(3);
    s.close();
  });

  it("reports auth failures and does not reconnect after close()", () => {
    const onAuthFailure = vi.fn();
    const s = makeSocket({ onAuthFailure });
    s.connect();
    FakeSocket.instances[0]!.close(4003, "ADMIN role required");
    expect(onAuthFailure).toHaveBeenCalledWith(4003, "ADMIN role required");

    s.close();
    vi.advanceTimersByTime(60_000);
    expect(FakeSocket.instances).toHaveLength(1);
  });

  it("drops frames while not open and tracks lastMessageAt", () => {
    const s = makeSocket();
    s.connect();
    const ws = FakeSocket.instances[0]!;
    expect(s.lastMessageAt).toBeNull();

    // readyState is still CONNECTING — send must not throw or enqueue.
    s.send({ action: "subscribe" });
    expect(ws.sent).toHaveLength(0);

    ws.open();
    ws.deliver({ type: "authenticated" });
    s.send({ action: "subscribe" });
    expect(ws.frames).toContainEqual({ action: "subscribe" });
    expect(s.lastMessageAt).not.toBeNull();
    s.close();
  });
});
