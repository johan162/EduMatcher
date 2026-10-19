/** The scaffold bridge end to end: status route, /ws greeting, static serving. */

import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import type { BridgeStatus } from "@edumatcher/dash-types";
import { startRig, Tab, type Rig } from "./harness.js";

let rig: Rig | undefined;
afterEach(async () => {
  await rig?.stop();
  rig = undefined;
});

describe("bridge", () => {
  it("reports its status", async () => {
    rig = await startRig();
    const res = await fetch(`http://127.0.0.1:${rig.port}/api/bridge/status`);
    expect(res.status).toBe(200);
    const body = (await res.json()) as BridgeStatus;
    expect(body).toMatchObject({
      monitor: "DOWN",
      source: "127.0.0.1:5611",
      metricsDb: "/nonexistent/metrics.db",
      wsClients: 0,
      logging: "test",
    });
    expect(body.version).toMatch(/^\d+\.\d+\.\d+/);
  });

  it("greets every tab on /ws with hello, and counts it", async () => {
    rig = await startRig();
    const tab = await Tab.open(rig.port);
    const hello = await tab.next("hello");
    expect(hello).toMatchObject({ monitor: "DOWN", sessionTz: "UTC" });
    const status = (await (await fetch(`http://127.0.0.1:${rig.port}/api/bridge/status`)).json()) as BridgeStatus;
    expect(status.wsClients).toBe(1);
    tab.close();
  });

  it("refuses a tab beyond max_ws_clients", async () => {
    rig = await startRig({ maxWsClients: 1 });
    const first = await Tab.open(rig.port);
    const second = await Tab.open(rig.port);
    const code = await new Promise<number>((resolve) => second.socket.once("close", (c) => resolve(c)));
    expect(code).toBe(1013);
    first.close();
  });

  it("serves the web app, falling back to index.html for client routes but not for /api", async () => {
    const dir = mkdtempSync(join(tmpdir(), "dash-static-"));
    writeFileSync(join(dir, "index.html"), "<!doctype html><title>pm-dash</title>");
    rig = await startRig({ staticDir: dir });
    const page = await fetch(`http://127.0.0.1:${rig.port}/some/route`);
    expect(page.status).toBe(200);
    expect(await page.text()).toContain("pm-dash");
    expect((await fetch(`http://127.0.0.1:${rig.port}/api/nope`)).status).toBe(404);
  });
});
