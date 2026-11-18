/** A gap marker in the live tail (For-Later L038, WP-FL13). */

import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it } from "vitest";
import type { LogRow } from "@edumatcher/log-types";
import { GapMarkerRow } from "../src/components/GapMarkerRow.js";
import { isGap, useLiveStore } from "../src/store/useLiveStore.js";

function row(seq: number): LogRow {
  return {
    seq,
    client_ts: "2026-11-17T09:00:00.000Z",
    server_ts: "2026-11-17T09:00:00.000Z",
    process: "pm-engine",
    instance: null,
    pid: 1,
    host: "h",
    session: "s",
    level: "INFO",
    logger: "edumatcher.engine",
    module: null,
    line: null,
    has_exception: false,
    truncated: false,
    message: `row ${seq}`,
    tpl: null,
  };
}

describe("the live store", () => {
  beforeEach(() => useLiveStore.setState({ tail: [], tailPaused: false }));

  it("puts a gap marker between the rows before and after it", () => {
    const s = useLiveStore.getState();
    s.pushRow(row(1));
    s.pushGap({ reason: "dropped", lost: 3 });
    s.pushRow(row(5));
    const tail = useLiveStore.getState().tail;
    expect(tail.map((e) => (isGap(e) ? "gap" : e.seq))).toEqual([5, "gap", 1]);
  });

  it("keeps the marker while the tail is paused", () => {
    useLiveStore.setState({ tailPaused: true });
    useLiveStore.getState().pushGap({ reason: "restart", lost: null });
    expect(useLiveStore.getState().tail.filter(isGap)).toHaveLength(1);
  });
});

describe("GapMarkerRow", () => {
  it("says how many rows were lost when that is known", () => {
    const html = renderToStaticMarkup(
      createElement(GapMarkerRow, { gap: { kind: "gap", id: 1, reason: "dropped", lost: 3 } }),
    );
    expect(html).toContain("3 rows not received");
  });

  it("says rows may be missing after a log-server restart", () => {
    const html = renderToStaticMarkup(
      createElement(GapMarkerRow, { gap: { kind: "gap", id: 2, reason: "restart", lost: null } }),
    );
    expect(html).toContain("log server restarted");
    expect(html).toContain("history");
  });
});
