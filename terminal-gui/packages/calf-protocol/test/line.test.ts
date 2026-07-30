import { describe, expect, it } from "vitest";
import { CalfProtocolError, LineBuffer, buildLine, parseLine } from "../src/line.js";

describe("parseLine", () => {
  it("parses a message type with no fields", () => {
    expect(parseLine("PONG")).toEqual({ msgType: "PONG", fields: {} });
  });

  it("parses a real gateway snapshot line", () => {
    const frame = parseLine("SNAP|CH=TOP|SYM=AAPL|SEQ=1|TS=2026-07-11T14:32:00.000Z|BID=150.10|BIDSZ=1400");
    expect(frame.msgType).toBe("SNAP");
    expect(frame.fields).toEqual({
      CH: "TOP",
      SYM: "AAPL",
      SEQ: "1",
      TS: "2026-07-11T14:32:00.000Z",
      BID: "150.10",
      BIDSZ: "1400",
    });
  });

  it("keeps '=' inside a value, splitting on the first one only", () => {
    expect(parseLine("ERR|CODE=BAD_MESSAGE|MSG=a=b").fields["MSG"]).toBe("a=b");
  });

  it("resolves duplicate keys last-value-wins, matching the Python parser", () => {
    expect(parseLine("MD|SYM=AAPL|SYM=MSFT").fields["SYM"]).toBe("MSFT");
  });

  it("tolerates a value that is empty", () => {
    expect(parseLine("STATE|PREV=").fields["PREV"]).toBe("");
  });

  it("strips a trailing CRLF as well as a bare LF", () => {
    expect(parseLine("HB|TS=x\r\n").fields["TS"]).toBe("x");
  });

  it.each([
    ["an empty line", ""],
    ["a lowercase message type", "snap|CH=TOP"],
    ["a message type with punctuation", "SN-AP|CH=TOP"],
    ["a field token with no '='", "SNAP|CHTOP"],
    ["a field token with an empty key", "SNAP|=TOP"],
  ])("rejects %s", (_label, line) => {
    expect(() => parseLine(line)).toThrow(CalfProtocolError);
  });
});

describe("buildLine", () => {
  it("round-trips through parseLine", () => {
    const fields = { CH: "DEPTH", SYM: "AAPL", SEQ: "7" };
    expect(parseLine(buildLine("SUB", fields)).fields).toEqual(fields);
  });

  it("always terminates the line with a newline", () => {
    expect(buildLine("PING").endsWith("\n")).toBe(true);
  });

  it("refuses to build a line whose value would break the grammar", () => {
    expect(() => buildLine("SUB", { SYM: "A|B" })).toThrow(CalfProtocolError);
  });

  it("refuses an invalid message type", () => {
    expect(() => buildLine("sub")).toThrow(CalfProtocolError);
  });
});

describe("LineBuffer", () => {
  const feed = (buf: LineBuffer, text: string) => buf.push(Buffer.from(text, "utf8"));

  it("returns nothing until a newline arrives", () => {
    const buf = new LineBuffer();
    expect(feed(buf, "SNAP|CH=TOP")).toEqual([]);
    expect(feed(buf, "|SYM=AAPL\n")).toEqual(["SNAP|CH=TOP|SYM=AAPL"]);
  });

  it("returns every line when several arrive in one chunk", () => {
    const buf = new LineBuffer();
    expect(feed(buf, "HB|TS=1\nHB|TS=2\nHB|TS=3\n")).toEqual(["HB|TS=1", "HB|TS=2", "HB|TS=3"]);
  });

  it("holds back a trailing partial line while releasing complete ones", () => {
    const buf = new LineBuffer();
    expect(feed(buf, "HB|TS=1\nHB|TS=")).toEqual(["HB|TS=1"]);
    expect(feed(buf, "2\n")).toEqual(["HB|TS=2"]);
  });

  it("reassembles a multi-byte character split across two chunks", () => {
    const buf = new LineBuffer();
    const encoded = Buffer.from("ERR|MSG=café\n", "utf8");
    // Split mid-way through the 2-byte 'é'.
    const cut = encoded.length - 3;
    expect(buf.push(encoded.subarray(0, cut))).toEqual([]);
    expect(buf.push(encoded.subarray(cut))).toEqual(["ERR|MSG=café"]);
  });

  it("reports how many bytes are waiting on their newline", () => {
    const buf = new LineBuffer();
    feed(buf, "HB|TS=1\nPAR");
    expect(buf.pendingBytes).toBe(3);
  });

  it("throws once a line with no newline exceeds the ceiling", () => {
    const buf = new LineBuffer(16);
    expect(() => feed(buf, "X".repeat(17))).toThrow(CalfProtocolError);
  });

  it("does not throw on a long line that is fully terminated", () => {
    const buf = new LineBuffer(16);
    expect(feed(buf, `${"X".repeat(64)}\n`)).toHaveLength(1);
  });

  it("recovers usable framing after an overflow", () => {
    const buf = new LineBuffer(16);
    expect(() => feed(buf, "X".repeat(17))).toThrow();
    expect(feed(buf, "HB|TS=1\n")).toEqual(["HB|TS=1"]);
  });

  it("drops a partial line on reset so a reconnect starts clean", () => {
    const buf = new LineBuffer();
    feed(buf, "SNAP|CH=TO");
    buf.reset();
    expect(feed(buf, "P|SYM=AAPL\n")).toEqual(["P|SYM=AAPL"]);
    expect(buf.pendingBytes).toBe(0);
  });
});
