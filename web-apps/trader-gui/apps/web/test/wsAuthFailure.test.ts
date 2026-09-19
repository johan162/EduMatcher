// @vitest-environment jsdom
import { describe, it, expect, beforeEach, vi } from "vitest";

// H5: WebSocketManager resyncs session + halts via REST on every market-data
// "authenticated" -- stub the REST layer the same way wsRouting.test.ts does,
// even though these tests never actually authenticate a fake socket.
vi.mock("@/api/endpoints", () => ({
  getSession: vi.fn(),
  getHalts: vi.fn(),
}));

interface FakeOpts {
  onAuthFailure?: (code: number, reason: string) => void;
  [key: string]: unknown;
}

/**
 * Stand-in for ManagedSocket that records the options WebSocketManager
 * constructs it with, so the test can reach in and fire `onAuthFailure`
 * exactly as the real class would on a POLICY_VIOLATION/ADMIN_REQUIRED
 * close -- without opening a real WebSocket. Declared via vi.hoisted since
 * the vi.mock factory below is itself hoisted above normal top-level code.
 */
const { FakeManagedSocket } = vi.hoisted(() => {
  class FakeManagedSocket {
    static instances: FakeManagedSocket[] = [];
    opts: FakeOpts;
    constructor(_url: string, opts: FakeOpts) {
      this.opts = opts;
      FakeManagedSocket.instances.push(this);
    }
    on(): () => void {
      return () => {};
    }
    onStatus(): () => void {
      return () => {};
    }
    connect(): void {}
    close(): void {}
  }
  return { FakeManagedSocket };
});

vi.mock("@/ws/ManagedSocket", () => ({
  ManagedSocket: FakeManagedSocket,
}));

import { connectAll, disconnectAll } from "@/ws/WebSocketManager";
import { useAuthStore } from "@/store/useAuthStore";

beforeEach(() => {
  FakeManagedSocket.instances = [];
  useAuthStore.setState({
    apiKey: "key-1",
    gatewayId: "gw-1",
    role: "TRADER",
    gatewayCount: null,
  });
});

describe("L4: WebSocket auth-failure logs the user out", () => {
  it("wires onAuthFailure on both the events and market-data sockets for TRADER", () => {
    connectAll("TRADER");
    expect(FakeManagedSocket.instances).toHaveLength(2);
    for (const inst of FakeManagedSocket.instances) {
      expect(typeof inst.opts.onAuthFailure).toBe("function");
    }
    disconnectAll();
  });

  it("a POLICY_VIOLATION close on the events socket logs the user out", () => {
    connectAll("TRADER");
    const eventsSocket = FakeManagedSocket.instances[0]!;
    eventsSocket.opts.onAuthFailure!(1008, "policy violation");
    expect(useAuthStore.getState().apiKey).toBeNull();
    expect(useAuthStore.getState().role).toBeNull();
    disconnectAll();
  });

  it("wires onAuthFailure on the admin monitor socket for ADMIN", () => {
    connectAll("ADMIN");
    // ADMIN has no /events socket: market-data + admin monitor only.
    expect(FakeManagedSocket.instances).toHaveLength(2);
    const adminSocket = FakeManagedSocket.instances[1]!;
    adminSocket.opts.onAuthFailure!(4003, "ADMIN role required");
    expect(useAuthStore.getState().apiKey).toBeNull();
    disconnectAll();
  });

  it("an auth failure on the market-data socket also logs out", () => {
    connectAll("TRADER");
    const marketDataSocket = FakeManagedSocket.instances[1]!;
    marketDataSocket.opts.onAuthFailure!(1008, "policy violation");
    expect(useAuthStore.getState().apiKey).toBeNull();
    disconnectAll();
  });
});
