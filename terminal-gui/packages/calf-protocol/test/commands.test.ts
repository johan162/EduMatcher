import { describe, expect, it } from "vitest";
import { acceptsWildcard, isChannel } from "../src/channels.js";
import { buildExit, buildHello, buildPing, buildResume, buildSub, buildUnsub } from "../src/commands.js";
import { parseLine } from "../src/line.js";

describe("channel capability", () => {
  it("accepts SYM=* for exactly the four channels the gateway allows", () => {
    expect(["TOP", "TRADE", "STATE", "AUCTION"].every((ch) => acceptsWildcard(ch as never))).toBe(true);
  });

  it("refuses SYM=* for the per-symbol channels", () => {
    // The gateway answers SUB|CH=DEPTH|SYM=* with ERR|CODE=INVALID_SYMBOL.
    expect(["DEPTH", "CB", "INDEX"].some((ch) => acceptsWildcard(ch as never))).toBe(false);
  });

  it("recognises only real channel names", () => {
    expect(isChannel("TOP")).toBe(true);
    expect(isChannel("BOOK")).toBe(false);
  });
});

describe("command builders", () => {
  it("builds a handshake the gateway will authenticate", () => {
    const frame = parseLine(buildHello("pm-terminal-bridge"));
    expect(frame.msgType).toBe("HELLO");
    expect(frame.fields).toEqual({ CLIENT: "pm-terminal-bridge", PROTO: "CALF1" });
  });

  it("keeps replay off the handshake, since HELLO is processed only once", () => {
    expect(buildHello("x")).not.toContain("RESUME");
  });

  it("builds a standalone resume for one stream", () => {
    const frame = parseLine(buildResume("TOP", "AAPL", 1042));
    expect(frame.msgType).toBe("RESUME");
    expect(frame.fields).toEqual({ CH: "TOP", SYM: "AAPL", LASTSEQ: "1042" });
  });

  it("builds one resume per stream, so a multi-stream client can recover all of them", () => {
    const lines = [buildResume("TOP", "AAPL", 1042), buildResume("TRADE", "AAPL", 88)];
    expect(lines.map((line) => parseLine(line).fields["LASTSEQ"])).toEqual(["1042", "88"]);
  });

  it("builds the bridge's always-on wildcard subscription as a single line", () => {
    const frame = parseLine(buildSub(["STATE", "TOP", "TRADE", "AUCTION"], ["*"]));
    expect(frame.msgType).toBe("SUB");
    expect(frame.fields).toEqual({ CH: "STATE,TOP,TRADE,AUCTION", SYM: "*" });
  });

  it("builds a per-symbol subscription", () => {
    expect(parseLine(buildSub(["DEPTH"], ["AAPL"])).fields).toEqual({ CH: "DEPTH", SYM: "AAPL" });
  });

  it("builds a matching unsubscribe", () => {
    expect(parseLine(buildUnsub(["CB"], ["TSLA"])).fields).toEqual({ CH: "CB", SYM: "TSLA" });
  });

  it("builds a field-less keepalive and exit", () => {
    expect(parseLine(buildPing())).toEqual({ msgType: "PING", fields: {} });
    expect(parseLine(buildExit())).toEqual({ msgType: "EXIT", fields: {} });
  });
});
