import { beforeEach, describe, expect, it } from "vitest";
import type { TapeTrade } from "@edumatcher/book-types";
import { TAPE_MAX, useBookStore } from "../src/store/useBookStore.js";

const t = (n: number): TapeTrade => ({ id: String(n).padStart(4, "0"), tsMs: n, px: n, qty: 1, side: "" });
const STATS = { volume: 1, tradeCount: 1, partial: false, timezone: "UTC" };

beforeEach(() => {
  useBookStore.setState({
    socketOpen: true,
    upstream: "ACTIVE",
    watched: null,
    book: null,
    stats: null,
    tape: [],
  });
});

describe("book store", () => {
  it("derives the connection state from the socket and the upstream", () => {
    expect(useBookStore.getState().connection()).toBe("LIVE");
    useBookStore.getState().apply({ type: "bridge_status", upstream: "DOWN", since: "", wsClients: 1 });
    expect(useBookStore.getState().connection()).toBe("RECONNECTING");
    useBookStore.getState().setSocketOpen(false);
    expect(useBookStore.getState().connection()).toBe("OFFLINE");
  });

  it("ignores frames for any symbol but the watched one", () => {
    const s = useBookStore.getState();
    s.watch("AAPL");
    s.apply({ type: "book", sym: "MSFT", seq: 1, tickDecimals: 2, bids: [], asks: [] });
    s.apply({ type: "session", sym: "MSFT", stats: STATS, tape: [t(1)] });
    expect(useBookStore.getState().book).toBeNull();
    expect(useBookStore.getState().tape).toEqual([]);
  });

  it("clears the previous symbol's state on a switch", () => {
    const s = useBookStore.getState();
    s.watch("AAPL");
    s.apply({ type: "session", sym: "AAPL", stats: STATS, tape: [t(1)] });
    s.watch("MSFT");
    expect(useBookStore.getState()).toMatchObject({ watched: "MSFT", stats: null, tape: [], book: null });
  });

  it("places a late older print by id and keeps the tape bounded", () => {
    const s = useBookStore.getState();
    s.watch("AAPL");
    s.apply({ type: "session", sym: "AAPL", stats: STATS, tape: [t(1), t(3)] });
    s.apply({ type: "trade", sym: "AAPL", trade: t(2), stats: STATS });
    expect(useBookStore.getState().tape.map((x) => x.px)).toEqual([1, 2, 3]);

    for (let n = 4; n < TAPE_MAX + 10; n++)
      s.apply({ type: "trade", sym: "AAPL", trade: t(n), stats: STATS });
    expect(useBookStore.getState().tape).toHaveLength(TAPE_MAX);
  });
});
