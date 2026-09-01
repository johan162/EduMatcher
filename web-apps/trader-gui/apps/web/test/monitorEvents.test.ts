import { describe, it, expect } from "vitest";
import { classifyMonitorEnvelope, isTerminalStatus, monitorEventsToCsv } from "@/lib/monitorEvents";
import type { MonitorEvent, WsEnvelope } from "@/types/index";

function env(patch: Partial<WsEnvelope<unknown>> & { type: string }): WsEnvelope<unknown> {
  return {
    type: patch.type,
    topic: patch.topic ?? "",
    ts: patch.ts ?? "2026-08-14T10:00:00.000Z",
    data: patch.data ?? {},
    ...(patch.seq !== undefined ? { seq: patch.seq } : {}),
    ...(patch.gateway_id !== undefined ? { gateway_id: patch.gateway_id } : {}),
  } as WsEnvelope<unknown>;
}

describe("isTerminalStatus", () => {
  it("recognises terminal statuses case-insensitively", () => {
    expect(isTerminalStatus("FILLED")).toBe(true);
    expect(isTerminalStatus("cancelled")).toBe(true);
    expect(isTerminalStatus("NEW")).toBe(false);
    expect(isTerminalStatus(null)).toBe(false);
  });
});

describe("classifyMonitorEnvelope (§6.9 — uniform envelopes, no monitor.event)", () => {
  it("maps an accepted order.ack to ACK + NEW status", () => {
    const c = classifyMonitorEnvelope(
      env({
        type: "order.ack",
        topic: "order.ack.GW01",
        gateway_id: "GW01",
        data: { order_id: "o1", accepted: true, symbol: "AAPL", side: "BUY", qty: 100, price: 150 },
      }),
    );
    expect(c).toMatchObject({ kind: "ACK", order_id: "o1", gateway_id: "GW01", symbol: "AAPL", orderStatus: "NEW" });
    expect(c!.detail).toContain("BUY");
    expect(c!.detail).toContain("@ 150");
  });

  it("maps a rejected order.ack to REJECT + REJECTED status with the reject code and reason", () => {
    const c = classifyMonitorEnvelope(
      env({ type: "order.ack", data: { order_id: "o2", accepted: false, reason: "collar breach", reject_code: "COLLAR_BREACH" } }),
    );
    expect(c).toMatchObject({ kind: "REJECT", orderStatus: "REJECTED" });
    expect(c!.detail).toContain("COLLAR_BREACH");
    expect(c!.detail).toContain("collar breach");
  });

  it("maps order.fill to FILL with qty @ price and status", () => {
    const c = classifyMonitorEnvelope(
      env({
        type: "order.fill",
        gateway_id: "GW02",
        data: { order_id: "o3", fill_qty: 40, fill_price: 150.5, remaining_qty: 60, status: "PARTIAL", symbol: "MSFT" },
      }),
    );
    expect(c).toMatchObject({ kind: "FILL", order_id: "o3", symbol: "MSFT", orderStatus: "PARTIAL" });
    expect(c!.detail).toBe("40 @ 150.5 · 60 left");
  });

  it("splits circuit_breaker into halt vs resume by topic", () => {
    const halt = classifyMonitorEnvelope(
      env({ type: "circuit_breaker", topic: "circuit_breaker.halt.AAPL", data: { symbol: "AAPL", level: "2" } }),
    );
    expect(halt).toMatchObject({ kind: "CB", symbol: "AAPL" });
    expect(halt!.detail).toContain("Halt");
    const resume = classifyMonitorEnvelope(
      env({ type: "circuit_breaker", topic: "circuit_breaker.resume.AAPL", data: { symbol: "AAPL" } }),
    );
    expect(resume!.detail).toContain("Resume");
  });

  it("maps session and admin.action, and ignores market-data frames", () => {
    expect(classifyMonitorEnvelope(env({ type: "session", data: { state: "CONTINUOUS", prev_state: "PRE_OPEN" } }))).toMatchObject({
      kind: "SESSION",
      detail: "→ CONTINUOUS (was PRE_OPEN)",
    });
    const admin = classifyMonitorEnvelope(
      env({
        type: "admin.action",
        data: { action: "kill_switch.symbol", initiator_gateway_id: "GW09", accepted: true, scope: { symbol: "AAPL" } },
      }),
    );
    expect(admin).toMatchObject({ kind: "ADMIN", gateway_id: "GW09", symbol: "AAPL" });
    expect(classifyMonitorEnvelope(env({ type: "book", data: { symbol: "AAPL" } }))).toBeNull();
    expect(classifyMonitorEnvelope(env({ type: "trade", data: {} }))).toBeNull();
  });
});

describe("monitorEventsToCsv (§15.9 export)", () => {
  const rows: MonitorEvent[] = [
    {
      id: "1",
      seq: 42,
      ts: "2026-08-14T10:00:00.000Z",
      kind: "FILL",
      topic: "order.fill.GW01",
      gateway_id: "GW01",
      symbol: "AAPL",
      order_id: "o1",
      detail: "40 @ 150.5",
    },
  ];
  it("emits a header and one row per event", () => {
    const csv = monitorEventsToCsv(rows);
    const lines = csv.split("\n");
    expect(lines[0]).toBe("Time,Seq,Kind,Gateway,Symbol,Order ID,Details");
    expect(lines[1]).toBe("2026-08-14T10:00:00.000Z,42,FILL,GW01,AAPL,o1,40 @ 150.5");
  });
  it("quotes cells containing commas", () => {
    const csv = monitorEventsToCsv([{ ...rows[0]!, detail: "a, b, c" }]);
    expect(csv.split("\n")[1]).toContain('"a, b, c"');
  });
});
