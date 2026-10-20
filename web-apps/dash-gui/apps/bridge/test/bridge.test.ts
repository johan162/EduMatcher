/** The scaffold bridge end to end: status route, /ws greeting, static serving. */

import { mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import type { BridgeStatus } from "@edumatcher/dash-types";
import { frames, snapshot, startRig, Tab, type Rig } from "./harness.js";

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
      monitorConnected: false,
      snapshotsIn: 0,
      eventsIn: 0,
      invalidIn: 0,
      handlerErrors: 0,
      lastSnapshotTs: null,
      sessionTz: "UTC",
      metricsDb: { path: "/nonexistent/metrics.db", ok: false },
      wsClients: 0,
      logging: "test",
      links: { logGui: null, bookGui: null },
    });
    // The release version scripts/mkbld.sh writes, as the top bar shows it -- not the workspace package's.
    const release = JSON.parse(readFileSync(new URL("../../web/src/version.json", import.meta.url), "utf8")) as { version: string };
    expect(body.version).toBe(release.version);
  });

  it("serves the cross-app base URLs it is configured with", async () => {
    rig = await startRig({ links: { logGui: "http://logs.example:8091", bookGui: null } });
    const body = (await (await fetch(`http://127.0.0.1:${rig.port}/api/bridge/status`)).json()) as BridgeStatus;
    expect(body.links).toEqual({ logGui: "http://logs.example:8091", bookGui: null });
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

  it("hello carries the session timezone of the last snapshot, also once pm-monitor is DOWN", async () => {
    let now = 1_000_000;
    rig = await startRig({}, { connect: false, now: () => now });
    rig.bridge.uplink.handle(frames("health.snapshot", snapshot(1, "America/New_York")));
    now += 5000;
    rig.bridge.uplink.checkSilence();
    expect(rig.bridge.uplink.state).toBe("DOWN");
    const tab = await Tab.open(rig.port);
    expect(await tab.next("hello")).toMatchObject({ monitor: "DOWN", sessionTz: "America/New_York" });
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
