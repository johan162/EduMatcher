import { describe, expect, it } from "vitest";
import type { ServerState } from "@edumatcher/log-types";
import { downFrom } from "../src/server-state.js";

const UP: ServerState = {
  server: "log-srv-1",
  state: "UP",
  proto: "1",
  subscribers: 2,
  activeBackfills: 1,
  lastSeq: 42,
  inboxDropped: 3,
  defaultLeaseSec: 30,
  timestamp: 1,
};

describe("downFrom", () => {
  it("keeps the identity of the last state but zeroes the live counts", () => {
    expect(downFrom(UP, 99)).toEqual({
      ...UP,
      state: "DOWN",
      subscribers: 0,
      activeBackfills: 0,
      timestamp: 99,
    });
  });

  it("works before any state was ever seen", () => {
    expect(downFrom(null, 5)).toMatchObject({ state: "DOWN", server: "", lastSeq: 0, timestamp: 5 });
  });
});
