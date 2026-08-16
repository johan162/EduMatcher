import { beforeEach, describe, expect, it, vi } from "vitest";
import { SymbolRefCount } from "../src/calf/symbol-refcount.js";

describe("SymbolRefCount", () => {
  const onFirst = vi.fn();
  const onLast = vi.fn();
  let refs: SymbolRefCount;

  beforeEach(() => {
    onFirst.mockClear();
    onLast.mockClear();
    refs = new SymbolRefCount({ onFirst, onLast });
  });

  it("subscribes when the first party shows interest", () => {
    refs.acquire("DEPTH", "AAPL");
    expect(onFirst).toHaveBeenCalledExactlyOnceWith("DEPTH", "AAPL");
  });

  it("does not re-subscribe for a second interested party", () => {
    refs.acquire("DEPTH", "AAPL");
    refs.acquire("DEPTH", "AAPL");
    expect(onFirst).toHaveBeenCalledTimes(1);
  });

  it("keeps the subscription while any party remains", () => {
    refs.acquire("DEPTH", "AAPL");
    refs.acquire("DEPTH", "AAPL");
    refs.release("DEPTH", "AAPL");

    expect(onLast).not.toHaveBeenCalled();
    expect(refs.count("DEPTH", "AAPL")).toBe(1);
  });

  it("unsubscribes only when the last party leaves", () => {
    refs.acquire("DEPTH", "AAPL");
    refs.acquire("DEPTH", "AAPL");
    refs.release("DEPTH", "AAPL");
    refs.release("DEPTH", "AAPL");

    expect(onLast).toHaveBeenCalledExactlyOnceWith("DEPTH", "AAPL");
    expect(refs.count("DEPTH", "AAPL")).toBe(0);
  });

  it("tracks the two CB triggers independently of each other", () => {
    // A Symbol Detail view and the Session board both wanting TSLA's CB.
    refs.acquire("CB", "TSLA");
    refs.acquire("CB", "TSLA");
    refs.release("CB", "TSLA"); // detail view closes; board still open

    expect(onLast).not.toHaveBeenCalled();
    expect(refs.count("CB", "TSLA")).toBe(1);
  });

  it("keeps channels apart for the same symbol", () => {
    refs.acquire("DEPTH", "AAPL");
    refs.acquire("CB", "AAPL");
    refs.release("DEPTH", "AAPL");

    expect(onLast).toHaveBeenCalledExactlyOnceWith("DEPTH", "AAPL");
    expect(refs.count("CB", "AAPL")).toBe(1);
  });

  it("keeps symbols apart on the same channel", () => {
    refs.acquire("DEPTH", "AAPL");
    refs.acquire("DEPTH", "MSFT");
    refs.release("DEPTH", "AAPL");

    expect(refs.count("DEPTH", "MSFT")).toBe(1);
  });

  it("ignores a release for something never acquired", () => {
    refs.release("CB", "NOPE");
    expect(onLast).not.toHaveBeenCalled();
  });

  it("re-subscribes cleanly after going to zero and back", () => {
    refs.acquire("DEPTH", "AAPL");
    refs.release("DEPTH", "AAPL");
    refs.acquire("DEPTH", "AAPL");

    expect(onFirst).toHaveBeenCalledTimes(2);
  });

  it("lists what must be re-issued after a reconnect", () => {
    refs.acquire("DEPTH", "AAPL");
    refs.acquire("CB", "TSLA");
    refs.acquire("CB", "TSLA");
    refs.acquire("DEPTH", "MSFT");
    refs.release("DEPTH", "MSFT");

    expect(refs.active()).toEqual(
      expect.arrayContaining([
        { ch: "DEPTH", sym: "AAPL" },
        { ch: "CB", sym: "TSLA" },
      ]),
    );
    expect(refs.active()).toHaveLength(2);
  });
});
