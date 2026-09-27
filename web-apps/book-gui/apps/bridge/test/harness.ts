/**
 * Runs the real bridge (`buildBridge`) against a `FakeApiGateway`, with
 * browser tabs as plain `ws` clients — the whole server side, end to end.
 */

import WebSocket from "ws";
import type { ClientFrame, ServerFrame } from "@edumatcher/book-types";
import type { BridgeConfig } from "../src/config.js";
import type { Logger } from "../src/logging/logger.js";
import { buildBridge, type Bridge } from "../src/server.js";
import { FakeApiGateway } from "./fake-api-gateway.js";

export const silentLogger: Logger = {
  debug: () => undefined,
  info: () => undefined,
  warn: () => undefined,
  error: () => undefined,
  critical: () => undefined,
  destination: () => "test",
  close: () => Promise.resolve(),
};

export function testConfig(
  baseUrl: string,
  apiKey: string,
  overrides: Partial<BridgeConfig> = {},
): BridgeConfig {
  return {
    host: "127.0.0.1",
    port: 0,
    corsOrigin: "*",
    maxWsClients: 10,
    wsHeartbeatSec: 60,
    wsPingSec: 60,
    wsPingMaxMissed: 2,
    wsMaxBufferedBytes: 5_000_000,
    apiGateway: { baseUrl, apiKey },
    upstream: { pingSec: 60, pingMaxMissed: 3, downAfterSec: 30 },
    tapeMax: 500,
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

export class Tab {
  readonly frames: ServerFrame[] = [];
  private constructor(readonly socket: WebSocket) {
    socket.on("message", (raw: Buffer) => this.frames.push(JSON.parse(raw.toString("utf8")) as ServerFrame));
  }

  static async open(port: number): Promise<Tab> {
    const socket = new WebSocket(`ws://127.0.0.1:${port}/ws/stream`);
    const tab = new Tab(socket);
    await new Promise<void>((resolve, reject) => {
      socket.once("open", () => resolve());
      socket.once("error", reject);
    });
    return tab;
  }

  send(frame: ClientFrame): void {
    this.socket.send(JSON.stringify(frame));
  }

  /** The first frame, at or after index `from`, that matches. */
  async next<T extends ServerFrame["type"]>(
    type: T,
    predicate: (f: Extract<ServerFrame, { type: T }>) => boolean = () => true,
    from = 0,
    timeoutMs = 3000,
  ): Promise<Extract<ServerFrame, { type: T }>> {
    const deadline = Date.now() + timeoutMs;
    for (;;) {
      const hit = this.frames
        .slice(from)
        .find((f): f is Extract<ServerFrame, { type: T }> => f.type === type && predicate(f as never));
      if (hit) return hit;
      if (Date.now() > deadline) {
        throw new Error(`no ${type} frame; got ${this.frames.map((f) => f.type).join(",")}`);
      }
      await new Promise((r) => setTimeout(r, 10));
    }
  }

  close(): void {
    this.socket.close();
  }
}

export interface Rig {
  gw: FakeApiGateway;
  bridge: Bridge;
  port: number;
  stop(): Promise<void>;
}

export async function startRig(
  setup: (gw: FakeApiGateway) => void = () => undefined,
  overrides: Partial<BridgeConfig> = {},
  apiKey = "ro-key",
): Promise<Rig> {
  const gw = new FakeApiGateway();
  setup(gw);
  await gw.start();
  const bridge = await buildBridge(testConfig(gw.baseUrl, apiKey, overrides), silentLogger);
  await bridge.app.listen({ host: "127.0.0.1", port: 0 });
  const addr = bridge.app.server.address();
  const port = addr && typeof addr === "object" ? addr.port : 0;
  return {
    gw,
    bridge,
    port,
    async stop() {
      await bridge.close();
      await gw.stop();
    },
  };
}

export async function until(predicate: () => boolean, timeoutMs = 3000): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  while (!predicate()) {
    if (Date.now() > deadline) throw new Error("condition not met in time");
    await new Promise((r) => setTimeout(r, 10));
  }
}
