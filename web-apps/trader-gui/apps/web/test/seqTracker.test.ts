import { describe, it, expect } from "vitest";
import { SeqTracker } from "@/ws/seqTracker";
import { channelForTopic, symbolForTopic } from "@/ws/topics";

describe("SeqTracker", () => {
  it("does not report a gap on the first seq for a topic", () => {
    // Connecting mid-stream is normal; the first seq is a baseline, not a gap.
    expect(new SeqTracker().observe("depth.AAPL", 128_400)).toBeNull();
  });

  it("reports the size of a skip", () => {
    const t = new SeqTracker();
    t.observe("depth.AAPL", 10);
    expect(t.observe("depth.AAPL", 14)).toEqual({
      topic: "depth.AAPL",
      expected: 11,
      received: 14,
      missed: 3,
    });
  });

  it("accepts contiguous sequences", () => {
    const t = new SeqTracker();
    t.observe("book.AAPL", 1);
    expect(t.observe("book.AAPL", 2)).toBeNull();
    expect(t.observe("book.AAPL", 3)).toBeNull();
  });

  it("ignores replays without walking the counter backwards", () => {
    const t = new SeqTracker();
    t.observe("trade.executed", 100);
    expect(t.observe("trade.executed", 98)).toBeNull();
    expect(t.lastSeq("trade.executed")).toBe(100);
    // …so the next live event is still judged against the high-water mark.
    expect(t.observe("trade.executed", 101)).toBeNull();
  });

  it("counts each topic independently", () => {
    const t = new SeqTracker();
    t.observe("depth.AAPL", 5);
    t.observe("depth.MSFT", 900);
    expect(t.observe("depth.AAPL", 6)).toBeNull();
    expect(t.lastSeq("depth.MSFT")).toBe(900);
  });

  it("ignores envelopes with no seq", () => {
    const t = new SeqTracker();
    expect(t.observe("session.state", undefined)).toBeNull();
    expect(t.lastSeq("session.state")).toBeUndefined();
  });

  it("forgets one topic or all of them", () => {
    const t = new SeqTracker();
    t.observe("depth.AAPL", 5);
    t.observe("book.AAPL", 7);
    t.reset("depth.AAPL");
    expect(t.lastSeq("depth.AAPL")).toBeUndefined();
    expect(t.lastSeq("book.AAPL")).toBe(7);
    t.reset();
    expect(t.entries()).toEqual([]);
  });
});

describe("topic classification", () => {
  it("maps engine topics to channels", () => {
    expect(channelForTopic("book.AAPL")).toBe("book");
    expect(channelForTopic("depth.AAPL")).toBe("depth");
    expect(channelForTopic("trade.executed")).toBe("trades");
    expect(channelForTopic("auction.result.AAPL")).toBe("auction");
    expect(channelForTopic("auction.indicative.AAPL")).toBe("auction");
    expect(channelForTopic("session.state")).toBeNull();
  });

  it("extracts the symbol, and none for venue-wide topics", () => {
    expect(symbolForTopic("depth.AAPL")).toBe("AAPL");
    expect(symbolForTopic("auction.indicative.aapl")).toBe("AAPL");
    // trade.executed is one topic for every symbol.
    expect(symbolForTopic("trade.executed")).toBeNull();
  });
});
