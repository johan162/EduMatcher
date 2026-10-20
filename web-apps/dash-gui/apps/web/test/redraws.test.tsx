// @vitest-environment jsdom
/**
 * D3's rule, as built (I118): the 1 Hz snapshot must not redraw the history
 * charts. Recharts' chart components are wrapped to count their renders;
 * live snapshots within one bucket of every chart redraw none of them, and
 * a refetch or a new bucket is what does.
 */

import { cleanup, render, waitFor } from "@testing-library/react";
import { createElement, type ComponentType } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ServerFrame } from "@edumatcher/dash-types";

const renders = { bars: 0, lines: 0 };
vi.mock("recharts", async (importOriginal) => {
  const real = await importOriginal<typeof import("recharts")>();
  const counted = (Chart: ComponentType<object>, kind: keyof typeof renders) =>
    function Counted(props: object) {
      renders[kind] += 1;
      return createElement(Chart, props);
    };
  return {
    ...real,
    BarChart: counted(real.BarChart as ComponentType<object>, "bars"),
    LineChart: counted(real.LineChart as ComponentType<object>, "lines"),
    AreaChart: counted(real.AreaChart as ComponentType<object>, "lines"),
  };
});

const { default: App } = await import("../src/App.js");
const { useDashStore } = await import("../src/store/useDashStore.js");
const { fakeBridge } = await import("./fake-bridge.js");
const { FakeSocket } = await import("./fake-socket.js");
const { CAPTURED, fixtureSnapshot } = await import("./fixtures/snapshots.js");

/** A minute's first second: every later second up to :09 is in the same 10 s and 1 min bucket. */
const T = Math.floor(Date.parse(CAPTURED.ts) / 60_000) * 60_000 + 1000;
const at = (ms: number, seq: number): ServerFrame => ({ type: "snapshot", data: fixtureSnapshot({ seq, ts: new Date(ms).toISOString() }) });

beforeEach(() => {
  cleanup();
  localStorage.clear();
  FakeSocket.instances = [];
  vi.stubGlobal("WebSocket", FakeSocket);
  useDashStore.setState({ socket: "CONNECTING", monitor: null, snapshot: null, events: [], recent: [], thresholds: null, links: null, range: "1h", refresh: "off" });
});
afterEach(() => vi.unstubAllGlobals());

describe("live snapshots and the history charts", () => {
  it.each(["/", "/participant/TRADER01", "/book/AAPL", `/process/${encodeURIComponent("pm-engine@kappa1")}`])(
    "%s: snapshots within a bucket redraw no chart",
    async (path) => {
      const bridge = fakeBridge();
      render(
        <MemoryRouter initialEntries={[path]}>
          <App />
        </MemoryRouter>,
      );
      const socket = FakeSocket.latest();
      socket.open();
      socket.deliver({ type: "hello", version: "1", monitor: "UP", sessionTz: "Europe/Stockholm" }, at(T, 1));
      // Every panel has its history, and has drawn it.
      await waitFor(() => expect(bridge.count("/api/rate?")).toBeGreaterThanOrEqual(2));
      await new Promise((r) => setTimeout(r, 50));
      const before = { ...renders };
      expect(before.bars + before.lines).toBeGreaterThan(0);
      for (let i = 1; i <= 8; i++) socket.deliver(at(T + i * 1000, 1 + i));
      await new Promise((r) => setTimeout(r, 50));
      expect(renders).toEqual(before);
    },
  );
});
