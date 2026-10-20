import { describe, expect, it } from "vitest";
import {
  LalfProtocolError,
  buildHb,
  buildHello,
  buildHeaderLine,
  buildLogFrame,
  isoUtc,
  parseHeaderLine,
  parseWelcome,
  truncateUtf8,
} from "../src/protocol.js";

/** Split a built frame the way a server would: header line, then LEN bytes. */
function splitFrame(frame: Buffer) {
  const idx = frame.indexOf(0x0a);
  const { msgType, fields } = parseHeaderLine(frame.subarray(0, idx).toString("utf8"));
  return { msgType, fields, payload: frame.subarray(idx + 1) };
}

describe("header grammar", () => {
  it("round-trips a header line", () => {
    const built = buildHeaderLine("HB", { TS: "2026-07-30T09:00:00.000Z" });
    expect(parseHeaderLine(built.toString("utf8")).fields["TS"]).toBe("2026-07-30T09:00:00.000Z");
  });

  it("refuses a header value that would break framing", () => {
    expect(() => buildHeaderLine("LOG", { LOGGER: "a|b" })).toThrow(LalfProtocolError);
    expect(() => buildHeaderLine("LOG", { LOGGER: "a\nb" })).toThrow(LalfProtocolError);
  });

  it("builds a HELLO carrying the identity the server indexes by", () => {
    const { fields } = parseHeaderLine(buildHello("pm-terminal-bridge", 42, "trader-lt").toString("utf8"));
    expect(fields).toMatchObject({
      CLIENT: "pm-terminal-bridge",
      PID: "42",
      HOST: "trader-lt",
      PROTO: "LALF1",
    });
    expect("INSTANCE" in fields).toBe(false);
  });

  it("includes INSTANCE only when one was configured", () => {
    const { fields } = parseHeaderLine(buildHello("pm-x", 1, "h", "b").toString("utf8"));
    expect(fields["INSTANCE"]).toBe("b");
  });

  it("builds a heartbeat", () => {
    expect(parseHeaderLine(buildHb("t").toString("utf8")).msgType).toBe("HB");
  });
});

describe("parseWelcome", () => {
  const welcome = { PROTO: "LALF1", SRV: "log-srv01", HBINT: "5", SESSION: "s1" };

  it("reads the server-assigned heartbeat interval", () => {
    expect(parseWelcome(welcome)).toEqual({ srv: "log-srv01", hbint: 5, session: "s1" });
  });

  it("rejects a WELCOME missing a required field", () => {
    expect(() => parseWelcome({ PROTO: "LALF1", SRV: "x" })).toThrow(LalfProtocolError);
  });

  it("rejects a protocol version it cannot speak", () => {
    expect(() => parseWelcome({ ...welcome, PROTO: "LALF2" })).toThrow(LalfProtocolError);
  });
});

describe("buildLogFrame", () => {
  const base = { seq: 1, ts: "2026-07-30T09:00:00.000Z", level: "INFO" as const, logger: "terminal-bridge" };

  it("declares LEN as the payload's byte length, not its character count", () => {
    // 'café' is 5 bytes but 4 characters — declaring 4 would desynchronise
    // the server's frame reader for the rest of the connection.
    const { fields, payload } = splitFrame(buildLogFrame({ ...base, message: "café" }));
    expect(fields["LEN"]).toBe("5");
    expect(payload.length).toBe(5);
    expect(payload.toString("utf8")).toBe("café");
  });

  it("carries a message containing pipes and newlines verbatim", () => {
    const message = "SUB|CH=TOP|SYM=*\nsecond line";
    const { fields, payload } = splitFrame(buildLogFrame({ ...base, message }));
    expect(payload.toString("utf8")).toBe(message);
    expect(Number(fields["LEN"])).toBe(Buffer.byteLength(message, "utf8"));
  });

  it("emits an empty payload with LEN=0 for an empty message", () => {
    const { fields, payload } = splitFrame(buildLogFrame({ ...base, message: "" }));
    expect(fields["LEN"]).toBe("0");
    expect(payload.length).toBe(0);
  });

  it("includes MODULE, LINE and EXC only when supplied", () => {
    const plain = splitFrame(buildLogFrame({ ...base, message: "x" })).fields;
    expect("MODULE" in plain).toBe(false);
    expect("EXC" in plain).toBe(false);

    const rich = splitFrame(
      buildLogFrame({ ...base, message: "x", module: "uplink", line: 88, hasException: true }),
    ).fields;
    expect(rich).toMatchObject({ MODULE: "uplink", LINE: "88", EXC: "1" });
  });

  it("puts LEN last so a reader has every other field before the payload", () => {
    const header =
      buildLogFrame({ ...base, message: "x" })
        .toString("utf8")
        .split("\n")[0] ?? "";
    expect(header.endsWith("|LEN=1")).toBe(true);
  });

  it("rejects a level the server would answer INVALID_LEVEL to", () => {
    expect(() => buildLogFrame({ ...base, level: "TRACE" as never, message: "x" })).toThrow(
      LalfProtocolError,
    );
  });

  it("truncates an over-long message rather than refusing it", () => {
    const { fields, payload } = splitFrame(buildLogFrame({ ...base, message: "x".repeat(100) }, 16));
    expect(fields["LEN"]).toBe("16");
    expect(payload.length).toBe(16);
  });

  it("keeps a truncated payload valid UTF-8 by not splitting a codepoint", () => {
    // Each 'é' is 2 bytes, so a naive cut at 5 would land mid-character.
    const truncated = truncateUtf8("ééé", 5);
    expect(truncated.length).toBe(4);
    expect(truncated.toString("utf8")).toBe("éé");
  });
});

describe("isoUtc", () => {
  it("formats with exactly millisecond precision", () => {
    expect(isoUtc(Date.UTC(2026, 6, 30, 9, 0, 0, 123))).toBe("2026-07-30T09:00:00.123Z");
  });
});
