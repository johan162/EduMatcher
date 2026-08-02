import { beforeEach, describe, expect, it } from "vitest";
import type { ServerFrame } from "@edumatcher/terminal-types";
import { useLiveStore } from "../src/store/useLiveStore.js";

const apply = (...frames: ServerFrame[]) => {
  for (const frame of frames) useLiveStore.getState().applyFrame(frame);
};
const state = () => useLiveStore.getState();

const hello = (over: Partial<Extract<ServerFrame, { type: "hello" }>> = {}): ServerFrame => ({
  type: "hello",
  symbols: ["AAPL", "MSFT"],
  tickDecimals: { AAPL: 2, MSFT: 4 },
  indexes: ["EDU100"],
  calf: "ACTIVE",
  gateway: "md-gwy01",
  ...over,
});

const state_ = (sym: string, session: string, over: Record<string, unknown> = {}): ServerFrame =>
  ({ type: "state", sym, seq: 1, ts: "2026-07-30T09:30:00.000Z", session, ...over }) as ServerFrame;

const cb = (sym: string, over: Record<string, unknown> = {}): ServerFrame =>
  ({
    type: "halt_context",
    sym,
    seq: 1,
    ts: "2026-07-30T09:30:00.000Z",
    status: "HALTED",
    ...over,
  }) as ServerFrame;

const auction = (sym: string, seq: number, over: Record<string, unknown> = {}): ServerFrame =>
  ({
    type: "auction_result",
    sym,
    seq,
    ts: "2026-07-30T09:30:02.000Z",
    eqQty: 12400,
    tradesCount: 38,
    imbalanceQty: 0,
    ...over,
  }) as ServerFrame;

beforeEach(() => useLiveStore.getState().reset());

describe("hello", () => {
  it("adopts the symbol universe and gateway identity", () => {
    apply(hello());
    expect(state().symbols).toEqual(["AAPL", "MSFT"]);
    expect(state().indexes).toEqual(["EDU100"]);
    expect(state().gateway).toBe("md-gwy01");
  });
});

describe("connection state", () => {
  it("is OFFLINE before the socket opens", () => {
    expect(state().connectionState()).toBe("OFFLINE");
  });

  it("is LIVE once the socket is open and CALF is active", () => {
    state().setWsStatus("open");
    apply(hello());
    expect(state().connectionState()).toBe("LIVE");
  });

  it("is RECONNECTING while the bridge has lost CALF", () => {
    state().setWsStatus("open");
    apply(hello(), { type: "bridge_status", calf: "RECONNECTING", since: "t", wsClients: 1 });
    expect(state().connectionState()).toBe("RECONNECTING");
  });

  it("reports OFFLINE when our own socket drops, even if CALF was last seen healthy", () => {
    // Anything the bridge told us about CALF is now of unknown age.
    state().setWsStatus("open");
    apply(hello({ calf: "ACTIVE" }));
    state().setWsStatus("reconnecting");
    expect(state().connectionState()).toBe("OFFLINE");
  });
});

describe("exchange session phase", () => {
  it("tracks the wildcard STATE frame, not a per-symbol one", () => {
    apply(state_("*", "CONTINUOUS", { prev: "OPENING_AUCTION" }));
    expect(state().sessionPhase).toBe("CONTINUOUS");
    expect(state().sessionPrev).toBe("OPENING_AUCTION");
  });

  it("does not let a symbol halt overwrite the exchange phase", () => {
    apply(state_("*", "CONTINUOUS"), state_("TSLA", "HALTED"));
    expect(state().sessionPhase).toBe("CONTINUOUS");
  });

  it("does not record the wildcard as a halted symbol", () => {
    apply(state_("*", "HALTED"));
    expect(state().haltedList()).toEqual([]);
  });
});

describe("halt tracking", () => {
  it("records a symbol that halts", () => {
    apply(state_("TSLA", "HALTED", { prev: "CONTINUOUS", ts: "2026-07-30T11:02:17.000Z" }));

    expect(state().haltedList()).toEqual([
      { sym: "TSLA", prev: "CONTINUOUS", since: "2026-07-30T11:02:17.000Z" },
    ]);
  });

  it("clears the symbol when it resumes", () => {
    apply(state_("TSLA", "HALTED"), state_("TSLA", "CONTINUOUS", { prev: "HALTED" }));
    expect(state().haltedList()).toEqual([]);
  });

  it("keeps the original since across a repeated halt frame", () => {
    // Otherwise the board would keep resetting how long a halt has run.
    apply(
      state_("TSLA", "HALTED", { ts: "2026-07-30T11:02:17.000Z" }),
      state_("TSLA", "HALTED", { ts: "2026-07-30T11:05:00.000Z" }),
    );
    expect(state().haltedList()[0]?.since).toBe("2026-07-30T11:02:17.000Z");
  });

  it("ignores a resume for a symbol that was never halted", () => {
    apply(state_("AAPL", "CONTINUOUS"));
    expect(state().haltedList()).toEqual([]);
  });

  it("sorts halted symbols so the board does not reshuffle as frames arrive", () => {
    apply(state_("TSLA", "HALTED"), state_("AAPL", "HALTED"), state_("MSFT", "HALTED"));
    expect(
      state()
        .haltedList()
        .map((h) => h.sym),
    ).toEqual(["AAPL", "MSFT", "TSLA"]);
  });
});

describe("circuit-breaker detail", () => {
  it("attaches CB context to an existing halt", () => {
    apply(state_("TSLA", "HALTED"), cb("TSLA", { level: "L2", triggerPrice: 261.4 }));

    expect(state().haltedList()[0]?.context).toMatchObject({ level: "L2", triggerPrice: 261.4 });
  });

  it("does not invent a halt from CB alone", () => {
    // STATE is the authority on whether a symbol is halted; CB only says why.
    apply(cb("TSLA", { level: "L2" }));
    expect(state().haltedList()).toEqual([]);
  });

  it("ignores a resume-shaped CB, leaving STATE to clear the halt", () => {
    apply(state_("TSLA", "HALTED"), cb("TSLA", { status: "ACTIVE", haltSource: "CB" }));

    expect(state().haltedList()).toHaveLength(1);
    expect(state().haltedList()[0]?.context).toBeUndefined();
  });

  it("drops CB context when the symbol resumes", () => {
    apply(state_("TSLA", "HALTED"), cb("TSLA", { level: "L2" }), state_("TSLA", "CONTINUOUS"));
    expect(state().haltedList()).toEqual([]);
  });
});

describe("auction ring buffer", () => {
  it("shows the most recent uncross first", () => {
    apply(auction("AAPL", 1), auction("MSFT", 2));
    expect(state().auctions.map((a) => a.sym)).toEqual(["MSFT", "AAPL"]);
  });

  it("preserves a no-cross result as distinct from a zero price", () => {
    apply(auction("MSFT", 1, { eqQty: 0, tradesCount: 0 }));
    expect(state().auctions[0]?.eqPrice).toBeUndefined();
  });

  it("stays bounded so a lobby display cannot grow without limit", () => {
    for (let i = 0; i < 250; i += 1) apply(auction("AAPL", i));
    expect(state().auctions).toHaveLength(200);
  });

  it("drops the oldest entries once bounded, not the newest", () => {
    for (let i = 0; i < 250; i += 1) apply(auction("AAPL", i));
    expect(state().auctions[0]?.seq).toBe(249);
  });
});

describe("trade prints", () => {
  it("does not disturb the book, which is where the last price is read from", () => {
    // The gateway now refreshes TOP.LAST after a trade, so the Overview takes
    // last/bid/ask from one frame. Individual prints are the Trade Tape's job.
    apply(
      { type: "top", sym: "AAPL", seq: 1, ts: "t", bid: 150.1, last: 150.11 },
      { type: "trade", sym: "AAPL", seq: 1, ts: "t", px: 151.5, qty: 25, side: "BUY" },
    );

    expect(state().top["AAPL"]).toEqual({ bid: 150.1, last: 150.11 });
  });

  it("picks the new price up from the top frame that follows", () => {
    apply(
      { type: "top", sym: "AAPL", seq: 1, ts: "t", bid: 150.1, last: 150.11 },
      { type: "trade", sym: "AAPL", seq: 1, ts: "t", px: 151.5, qty: 25, side: "BUY" },
      { type: "top", sym: "AAPL", seq: 2, ts: "t2", bid: 151.4, last: 151.5 },
    );

    expect(state().top["AAPL"]?.last).toBe(151.5);
  });
});

describe("trade gaps (T-H4/T-H5)", () => {
  it("records an unrepaired gap, newest first", () => {
    apply(
      { type: "gap", ch: "TRADE", sym: "AAPL", ts: "t1" },
      { type: "gap", ch: "TRADE", sym: "MSFT", ts: "t2" },
    );

    expect(state().tradeGaps).toEqual([
      { type: "gap", ch: "TRADE", sym: "MSFT", ts: "t2" },
      { type: "gap", ch: "TRADE", sym: "AAPL", ts: "t1" },
    ]);
  });

  it("leaves the trade tape itself untouched", () => {
    apply(
      { type: "trade", sym: "AAPL", seq: 1, ts: "t", px: 150, qty: 10, side: "BUY" },
      { type: "gap", ch: "TRADE", sym: "AAPL", ts: "t2" },
    );

    expect(state().trades).toHaveLength(1);
  });

  it("keeps a non-TRADE gap off the tape, which speaks only of prints", () => {
    // The Trade Tape's marker reads "some prints were missed". That is true of
    // a TRADE gap and false of an AUCTION one — and AUCTION is in fact the
    // commoner of the two here, since a TRADE gap only survives a RESUME that
    // came back REPLAY_MISS.
    apply(
      { type: "gap", ch: "AUCTION", sym: "AAPL", ts: "t1" },
      { type: "gap", ch: "TRADE", sym: "AAPL", ts: "t2" },
    );

    expect(state().tradeGaps).toEqual([{ type: "gap", ch: "TRADE", sym: "AAPL", ts: "t2" }]);
  });
});

describe("top of book", () => {
  it("replaces rather than merges, since the bridge already merged the delta", () => {
    apply(
      { type: "top", sym: "AAPL", seq: 1, ts: "t", bid: 150.1, bidSz: 1400, ask: 150.12 },
      { type: "top", sym: "AAPL", seq: 2, ts: "t2", ask: 150.13 },
    );
    // A bridge frame is the whole book, so a missing bid means no bid.
    expect(state().top["AAPL"]).toEqual({ ask: 150.13 });
  });

  it("strips the envelope fields out of the stored book", () => {
    apply({ type: "top", sym: "AAPL", seq: 9, ts: "t", bid: 1 });
    expect(state().top["AAPL"]).toEqual({ bid: 1 });
  });
});

describe("ACE corridor", () => {
  it("replaces the halt context when the corridor is extended", () => {
    // An extension is a continuation of the same halt: the gateway resends
    // the halt's own detail alongside the widened corridor, so replacing
    // wholesale keeps the two consistent.
    apply(state_("AAPL", "HALTED"));
    apply(cb("AAPL", { level: "L1", corridorLow: 90, corridorHigh: 110, expansion: 0 }));
    apply(
      cb("AAPL", {
        level: "L1",
        corridorLow: 80,
        corridorHigh: 120,
        expansion: 1,
        indicativePrice: 122,
        imbalanceSide: "BUY",
        resumeAt: "2026-07-30T13:37:00.000Z",
      }),
    );

    const context = state().halted["AAPL"]?.context;
    expect(context?.expansion).toBe(1);
    expect(context?.corridorHigh).toBe(120);
    expect(context?.indicativePrice).toBe(122);
    expect(context?.resumeAt).toBe("2026-07-30T13:37:00.000Z");
  });

  it("retains how a halt ended so a forced close can be reported", () => {
    // The halt is gone by the time the backstop reports itself, so there is
    // nowhere in `halted` for the fact to live.
    apply(state_("AAPL", "HALTED"));
    apply(cb("AAPL", { level: "L1" }));
    apply(
      cb("AAPL", {
        status: "ACTIVE",
        reason: "CLOSING_BACKSTOP",
        clamped: true,
        printPrice: 120,
      }),
    );

    expect(state().haltEnded["AAPL"]?.reason).toBe("CLOSING_BACKSTOP");
    expect(state().haltEnded["AAPL"]?.clamped).toBe(true);
    expect(state().haltEnded["AAPL"]?.printPrice).toBe(120);
  });

  it("ignores a halt context for a symbol that is not halted", () => {
    apply(cb("AAPL", { level: "L1" }));
    expect(state().halted["AAPL"]).toBeUndefined();
  });
});

describe("data age (T-M4)", () => {
  it("stamps arrival for market data", () => {
    const before = Date.now();
    apply({ type: "top", sym: "AAPL", seq: 1, ts: "t", last: 150 });
    expect(state().lastTickAt).toBeGreaterThanOrEqual(before);
  });

  it("is not advanced by frames that only prove the bridge is alive", () => {
    // A gateway publishing nothing at all still sends these. Counting them
    // would make a silent feed read as a live one, which is the exact
    // confusion the reading exists to resolve.
    apply({ type: "top", sym: "AAPL", seq: 1, ts: "t", last: 150 });
    const stamped = state().lastTickAt;

    apply({ type: "bridge_status", calf: "ACTIVE", since: "t", wsClients: 1 });
    apply({ type: "symbols", symbols: ["AAPL"] });

    expect(state().lastTickAt).toBe(stamped);
  });

  it("has no reading before the first frame", () => {
    // Null, not zero: nothing has arrived rather than something arriving at
    // the epoch.
    expect(state().lastTickAt).toBeNull();
  });
});

describe("next session transition (T-M6)", () => {
  it("records the timetable the feed supplied", () => {
    apply(state_("*", "CONTINUOUS", { nextPhase: "CLOSING_AUCTION", nextAt: "2026-07-30T16:25:00.000Z" }));

    expect(state().sessionNextPhase).toBe("CLOSING_AUCTION");
    expect(state().sessionNextAt).toBe("2026-07-30T16:25:00.000Z");
  });

  it("clears the target when a later transition carries none", () => {
    // The clearing is the signal. A manual transition moves the engine
    // somewhere the schedule did not predict, so the old target has stopped
    // being a fact about anything — keeping it would count the screen down
    // to a transition nobody is going to perform.
    apply(state_("*", "CONTINUOUS", { nextPhase: "CLOSING_AUCTION", nextAt: "2026-07-30T16:25:00.000Z" }));
    apply(state_("*", "CLOSED"));

    expect(state().sessionNextPhase).toBeNull();
    expect(state().sessionNextAt).toBeNull();
  });

  it("has no target before any session frame", () => {
    expect(state().sessionNextPhase).toBeNull();
  });
});
