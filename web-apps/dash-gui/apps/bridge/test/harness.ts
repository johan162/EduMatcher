/**
 * Runs the real bridge (`buildBridge`) on an ephemeral port, with browser
 * tabs as plain `ws` clients — the whole server side, end to end.
 */

import WebSocket from "ws";
import type { ServerFrame } from "@edumatcher/dash-types";
import type { BridgeConfig } from "../src/config.js";
import type { Logger } from "../src/logging/logger.js";
import { buildBridge, type Bridge } from "../src/server.js";

export const silentLogger: Logger = {
  debug: () => undefined,
  info: () => undefined,
  warn: () => undefined,
  error: () => undefined,
  critical: () => undefined,
  destination: () => "test",
  close: () => Promise.resolve(),
};

export function testConfig(overrides: Partial<BridgeConfig> = {}): BridgeConfig {
  return {
    host: "127.0.0.1",
    port: 0,
    corsOrigin: "*",
    maxWsClients: 10,
    wsPingSec: 60,
    wsPingMaxMissed: 2,
    wsMaxBufferedBytes: 5_000_000,
    monitor: { host: "127.0.0.1", pubPort: 5611, downAfterSec: 3 },
    metricsDbPath: "/nonexistent/metrics.db",
    logServer: {
      enabled: false,
      host: "127.0.0.1",
      port: 0,
      clientId: "test",
      connectTimeoutSec: 0.1,
      failoverTimeoutSec: 1,
      queueMaxSize: 10,
      failoverDir: "/tmp",
    },
    ...overrides,
  };
}

/** A browser tab: a `ws` client collecting every frame it receives. */
export class Tab {
  readonly frames: ServerFrame[] = [];
  private constructor(readonly socket: WebSocket) {
    socket.on("message", (raw: Buffer) => this.frames.push(JSON.parse(raw.toString("utf8")) as ServerFrame));
  }

  static async open(port: number): Promise<Tab> {
    const socket = new WebSocket(`ws://127.0.0.1:${port}/ws`);
    const tab = new Tab(socket);
    await new Promise<void>((resolve, reject) => {
      socket.once("open", () => resolve());
      socket.once("error", reject);
    });
    return tab;
  }

  async next<T extends ServerFrame["type"]>(type: T, timeoutMs = 3000): Promise<Extract<ServerFrame, { type: T }>> {
    const deadline = Date.now() + timeoutMs;
    for (;;) {
      const hit = this.frames.find((f): f is Extract<ServerFrame, { type: T }> => f.type === type);
      if (hit) return hit;
      if (Date.now() > deadline) throw new Error(`no ${type} frame; got ${this.frames.map((f) => f.type).join(",")}`);
      await new Promise((r) => setTimeout(r, 10));
    }
  }

  close(): void {
    this.socket.close();
  }
}

export interface Rig {
  bridge: Bridge;
  port: number;
  stop(): Promise<void>;
}

export async function startRig(overrides: Partial<BridgeConfig> = {}): Promise<Rig> {
  const bridge = await buildBridge(testConfig(overrides), silentLogger);
  await bridge.app.listen({ host: "127.0.0.1", port: 0 });
  const addr = bridge.app.server.address();
  const port = addr && typeof addr === "object" ? addr.port : 0;
  return { bridge, port, stop: () => bridge.close() };
}
