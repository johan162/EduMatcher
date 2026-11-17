/**
 * The uplink notices a restarted pm-log-srv and lost rows (For-Later L038, WP-FL13).
 *
 * After a crash and a restart inside the heartbeat budget the uplink stayed
 * ACTIVE and only re-subscribed on the next renew's UNKNOWN_SUB (up to 15 s);
 * `dropped` and the `msg_no` counter were ignored, so the live view showed no
 * gap. `log.server_state` now carries an `instance_id` that is new at every
 * server start.
 */

import { describe, expect, it } from "vitest";
import { LalfPsUplink, type UplinkGap } from "../src/lalf-ps-uplink.js";

interface Harness {
  uplink: LalfPsUplink;
  sent: string[];
  gaps: UplinkGap[];
  deliver: (topic: string, payload: Record<string, unknown>) => void;
}

function harness(): Harness {
  const uplink = new LalfPsUplink({
    host: "127.0.0.1",
    pubPort: 1,
    pullPort: 2,
    subIdPrefix: "test",
    leaseSec: 30,
  });
  const sent: string[] = [];
  const gaps: UplinkGap[] = [];
  const internals = uplink as unknown as {
    push: { send: (frames: Buffer[]) => Promise<void> };
    handleMessage: (topic: string, payload: Record<string, unknown>) => void;
  };
  internals.push = {
    send: async (frames) => {
      sent.push(frames[0]!.toString("utf8"));
    },
  };
  uplink.on("gap", (gap) => gaps.push(gap));
  const deliver = (topic: string, payload: Record<string, unknown>) =>
    internals.handleMessage(topic, payload);
  // ACTIVE, as after a normal subscribe.
  deliver(`log.subscribe_ack.${uplink.subId}`, { renew_before_sec: 15, last_seq: 0 });
  return { uplink, sent, gaps, deliver };
}

function event(h: Harness, seq: number, extra: Record<string, unknown>): void {
  h.deliver(`log.event.${h.uplink.subId}`, {
    rows: [{ seq, client_ts: "t", server_ts: "t", process: "p", pid: 1, host: "h", session: "s", level: "INFO", logger: "l", message: "m" }],
    ...extra,
  });
}

describe("a restarted log server (instance_id)", () => {
  it("re-subscribes at once when an ACTIVE uplink sees a new instance_id", () => {
    const h = harness();
    h.deliver("log.server_state", { state: "UP", instance_id: "A" });
    expect(h.sent).toEqual([]);
    h.deliver("log.server_state", { state: "UP", instance_id: "B" });
    expect(h.sent).toEqual(["log.subscribe"]);
    expect(h.uplink.currentState).toBe("RECONNECTING");
    expect(h.gaps).toEqual([{ reason: "restart", lost: null }]);
  });

  it("sends nothing while the instance_id stays the same", () => {
    const h = harness();
    for (let i = 0; i < 3; i++) h.deliver("log.server_state", { state: "UP", instance_id: "A" });
    expect(h.sent).toEqual([]);
    expect(h.gaps).toEqual([]);
  });
});

describe("rows lost on the way (dropped, msg_no)", () => {
  it("reports the rows the server shed since the last event", () => {
    const h = harness();
    event(h, 1, { dropped: 0, msg_no: 1 });
    event(h, 5, { dropped: 3, msg_no: 2 });
    expect(h.gaps).toEqual([{ reason: "dropped", lost: 3 }]);
  });

  it("reports a gap in the message counter", () => {
    const h = harness();
    event(h, 1, { dropped: 0, msg_no: 1 });
    event(h, 2, { dropped: 0, msg_no: 2 });
    event(h, 9, { dropped: 0, msg_no: 4 });
    expect(h.gaps).toEqual([{ reason: "msg_no", lost: null }]);
  });

  it("starts counting afresh on a new subscription", () => {
    const h = harness();
    event(h, 1, { dropped: 2, msg_no: 7 });
    h.deliver(`log.subscribe_ack.${h.uplink.subId}`, { renew_before_sec: 15, last_seq: 1 });
    event(h, 2, { dropped: 0, msg_no: 1 });
    expect(h.gaps).toEqual([]);
  });
});
