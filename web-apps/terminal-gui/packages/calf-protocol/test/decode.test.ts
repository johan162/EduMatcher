import { describe, expect, it } from "vitest";
import { parseLine } from "../src/line.js";
import {
  decodeAuction,
  decodeCb,
  decodeDepth,
  decodeIndex,
  decodeState,
  decodeTop,
  decodeTrade,
  encodeLevels,
  parseLevels,
  parseRef,
  parseSymbolsReply,
  parseWelcome,
  readEnvelope,
} from "../src/decode.js";

const fieldsOf = (line: string) => parseLine(line).fields;

describe("readEnvelope", () => {
  it("reads the fields every stream message carries", () => {
    const env = readEnvelope(fieldsOf("MD|CH=TOP|SYM=AAPL|SEQ=42|TS=2026-07-11T14:32:00.512Z"));
    expect(env).toEqual({ ch: "TOP", sym: "AAPL", seq: 42, ts: "2026-07-11T14:32:00.512Z" });
  });

  it("throws when SYM is missing, since nothing can be routed without it", () => {
    expect(() => readEnvelope(fieldsOf("MD|CH=TOP|SEQ=1"))).toThrow();
  });
});

describe("parseWelcome", () => {
  const line =
    "WELCOME|PROTO=CALF1|GW=md-gwy01|HBINT=1|REPLAY=30" +
    "|CH_SUPPORTED=AUCTION,CB,DEPTH,INDEX,STATE,TOP,TRADE|SYMBOLS=AAPL,MSFT,TSLA";

  it("parses the handshake the shipped gateway actually sends", () => {
    const welcome = parseWelcome(fieldsOf(line));
    expect(welcome.gateway).toBe("md-gwy01");
    expect(welcome.hbint).toBe(1);
    expect(welcome.replaySec).toBe(30);
    expect(welcome.symbols).toEqual(["AAPL", "MSFT", "TSLA"]);
    expect(welcome.chSupported.has("AUCTION")).toBe(true);
    expect(welcome.chSupported.has("CB")).toBe(true);
  });

  it("rejects a protocol version it cannot speak", () => {
    expect(() => parseWelcome(fieldsOf("WELCOME|PROTO=CALF2|GW=x"))).toThrow();
  });

  it("reports no symbols when the gateway ran without an engine config", () => {
    // SYMBOLS= is only emitted when the gateway knows any symbols at all.
    expect(parseWelcome(fieldsOf("WELCOME|PROTO=CALF1|GW=x|HBINT=1")).symbols).toEqual([]);
  });

  it("reports an empty channel set for a gateway predating CH_SUPPORTED", () => {
    expect(parseWelcome(fieldsOf("WELCOME|PROTO=CALF1|GW=x")).chSupported.size).toBe(0);
  });

  it("carries per-symbol display precision from REF=", () => {
    const welcome = parseWelcome(fieldsOf(`${line}|REF=AAPL:2,MSFT:2,TSLA:4`));
    expect(welcome.tickDecimals).toEqual({ AAPL: 2, MSFT: 2, TSLA: 4 });
  });

  it("reports no precision for a gateway predating REF", () => {
    // Emptiness is the capability signal — a caller falls back to the default
    // knowingly rather than by accident.
    expect(parseWelcome(fieldsOf(line)).tickDecimals).toEqual({});
  });
});

describe("parseRef", () => {
  it("decodes SYM:DEC tuples", () => {
    expect(parseRef("AAPL:2,TSLA:4")).toEqual({ AAPL: 2, TSLA: 4 });
  });

  it("ignores trailing components it does not yet understand", () => {
    // The tuple is designed to grow to SYM:DEC:MULT:CCY without a further
    // protocol change, so an older client must not choke on a newer gateway.
    expect(parseRef("AAPL:2:1:USD")).toEqual({ AAPL: 2 });
  });

  it("skips a malformed entry rather than discarding the rest", () => {
    // Matching parseLevels: one bad token should not cost every other symbol
    // its precision.
    expect(parseRef("AAPL:2,GARBAGE,MSFT:x,TSLA:4")).toEqual({ AAPL: 2, TSLA: 4 });
  });

  it("rejects a negative or fractional precision", () => {
    expect(parseRef("AAPL:-1,MSFT:2.5")).toEqual({});
  });

  it("accepts zero decimals", () => {
    // A whole-number-priced instrument is a real configuration, and 0 must not
    // be confused with absent.
    expect(parseRef("JPY:0")).toEqual({ JPY: 0 });
  });

  it("has nothing to decode when the field is absent", () => {
    expect(parseRef(undefined)).toEqual({});
  });
});

describe("parseSymbolsReply", () => {
  it("returns the universe and its precision together", () => {
    const reply = parseSymbolsReply(fieldsOf("SYMBOLS|COUNT=2|SYMBOLS=AAPL,TSLA|REF=AAPL:2,TSLA:4"));
    expect(reply.symbols).toEqual(["AAPL", "TSLA"]);
    expect(reply.tickDecimals).toEqual({ AAPL: 2, TSLA: 4 });
  });

  it("treats an empty universe as an answer, not a parse failure", () => {
    const reply = parseSymbolsReply(fieldsOf("SYMBOLS|COUNT=0"));
    expect(reply.symbols).toEqual([]);
    expect(reply.tickDecimals).toEqual({});
  });
});

describe("parseLevels", () => {
  it("decodes price:qty:count triples in wire order", () => {
    expect(parseLevels("150.10:1400:4,150.09:800:2")).toEqual([
      [150.1, 1400, 4],
      [150.09, 800, 2],
    ]);
  });

  it("returns an empty ladder when the side is omitted rather than empty", () => {
    // The gateway omits BIDS entirely when there are no resting bids.
    expect(parseLevels(undefined)).toEqual([]);
  });

  it("defaults a missing order count to zero", () => {
    expect(parseLevels("150.10:1400")).toEqual([[150.1, 1400, 0]]);
  });

  it("skips a malformed level instead of discarding the whole ladder", () => {
    expect(parseLevels("150.10:1400:4,garbage,150.08:400:1")).toEqual([
      [150.1, 1400, 4],
      [150.08, 400, 1],
    ]);
  });

  it("round-trips through encodeLevels", () => {
    const levels = parseLevels("150.10:1400:4,150.09:800:2");
    expect(parseLevels(encodeLevels(levels))).toEqual(levels);
  });
});

describe("decodeTop", () => {
  it("returns only the fields an MD delta actually carried", () => {
    // normalise_book emits just what changed — here, the bid side only.
    expect(decodeTop(fieldsOf("MD|CH=TOP|SYM=AAPL|SEQ=2|BID=150.11|BIDSZ=900"))).toEqual({
      bid: 150.11,
      bidSz: 900,
    });
  });

  it("returns an empty view for a symbol the gateway has no state for", () => {
    expect(decodeTop(fieldsOf("SNAP|CH=TOP|SYM=NEW|SEQ=1"))).toEqual({});
  });

  it("distinguishes a zero size from an absent one", () => {
    const decoded = decodeTop(fieldsOf("MD|CH=TOP|SYM=AAPL|BIDSZ=0"));
    expect(decoded.bidSz).toBe(0);
    expect("bid" in decoded).toBe(false);
  });

  it("reports a withdrawn bid side as null, distinct from unchanged", () => {
    // An empty BID= means the book has no bid at all. Merging code must clear
    // the price, not keep the last one it saw.
    expect(decodeTop(fieldsOf("MD|CH=TOP|SYM=AAPL|SEQ=3|BID=|BIDSZ=0"))).toEqual({
      bid: null,
      bidSz: 0,
    });
  });

  it("reports a withdrawn ask side as null", () => {
    expect(decodeTop(fieldsOf("MD|CH=TOP|SYM=AAPL|SEQ=3|ASK=|ASKSZ=0")).ask).toBeNull();
  });

  it("leaves the untouched side absent when only one side is withdrawn", () => {
    const decoded = decodeTop(fieldsOf("MD|CH=TOP|SYM=AAPL|SEQ=3|BID=|BIDSZ=0"));
    expect("ask" in decoded).toBe(false);
  });

  it("treats an unparseable price as a withdrawal rather than silently keeping the old one", () => {
    // Garbage on the wire must never leave a stale price displayed as live.
    expect(decodeTop(fieldsOf("MD|CH=TOP|SYM=AAPL|BID=n/a")).bid).toBeNull();
  });
});

describe("decodeTrade", () => {
  it("decodes price, quantity and aggressor side", () => {
    expect(decodeTrade(fieldsOf("TRADE|CH=TRADE|SYM=AAPL|SEQ=9|PX=150.12|QTY=200|SIDE=BUY"))).toEqual({
      px: 150.12,
      qty: 200,
      side: "BUY",
    });
  });

  it("reports an empty side when the engine had no aggressor to name", () => {
    expect(decodeTrade(fieldsOf("TRADE|CH=TRADE|SYM=AAPL|PX=1|QTY=1|SIDE=")).side).toBe("");
  });
});

describe("decodeState", () => {
  it("decodes an exchange-wide transition, which arrives under SYM=*", () => {
    const line = "STATE|CH=STATE|SYM=*|SEQ=3|SESSION=CONTINUOUS|PREV=OPENING_AUCTION";
    expect(readEnvelope(fieldsOf(line)).sym).toBe("*");
    expect(decodeState(fieldsOf(line))).toEqual({ session: "CONTINUOUS", prev: "OPENING_AUCTION" });
  });

  it("omits prev when the gateway did not supply one", () => {
    expect(decodeState(fieldsOf("SNAP|CH=STATE|SYM=*|SESSION=CLOSED"))).toEqual({ session: "CLOSED" });
  });
});

describe("decodeIndex", () => {
  it("decodes a full live index update", () => {
    const line =
      "IDX|CH=INDEX|SYM=EDU100|SEQ=42|LEVEL=1048.73|SESSION=CONTINUOUS" +
      "|OPEN=1042.10|CHG=+6.63|PCTCHG=+0.64|HIGH=1056.30|LOW=1040.05|AGGCAP=7350000000000";
    expect(decodeIndex(fieldsOf(line))).toEqual({
      level: 1048.73,
      session: "CONTINUOUS",
      open: 1042.1,
      chg: 6.63,
      pctChg: 0.64,
      high: 1056.3,
      low: 1040.05,
      aggCap: 7350000000000,
    });
  });

  it("decodes the metadata-only SNAP sent before pm-index has published anything", () => {
    expect(decodeIndex(fieldsOf("SNAP|CH=INDEX|SYM=EDU100|SEQ=1|TS=x"))).toEqual({});
  });
});

describe("decodeDepth", () => {
  it("decodes both sides of a ladder", () => {
    const line =
      "DEPTH|CH=DEPTH|SYM=AAPL|SEQ=2|LEVELS=10" +
      "|BIDS=150.10:1400:4,150.09:800:2|ASKS=150.12:900:2,150.13:600:1";
    expect(decodeDepth(fieldsOf(line))).toEqual({
      levels: 10,
      bids: [
        [150.1, 1400, 4],
        [150.09, 800, 2],
      ],
      asks: [
        [150.12, 900, 2],
        [150.13, 600, 1],
      ],
    });
  });

  it("decodes a one-sided book, where the empty side is omitted from the wire", () => {
    const decoded = decodeDepth(fieldsOf("DEPTH|CH=DEPTH|SYM=AAPL|SEQ=3|LEVELS=10|ASKS=150.12:900:2"));
    expect(decoded.bids).toEqual([]);
    expect(decoded.asks).toHaveLength(1);
  });
});

describe("decodeAuction", () => {
  it("decodes a crossed auction", () => {
    const line =
      "AUCTION|CH=AUCTION|SYM=AAPL|SEQ=1|EQPX=149.85|EQQTY=12400|TRADES=38|IMBSIDE=BUY|IMBQTY=1400";
    expect(decodeAuction(fieldsOf(line))).toEqual({
      eqPrice: 149.85,
      eqQty: 12400,
      tradesCount: 38,
      imbalanceSide: "BUY",
      imbalanceQty: 1400,
    });
  });

  it("leaves the equilibrium price absent on a no-cross rather than reporting zero", () => {
    const decoded = decodeAuction(fieldsOf("AUCTION|CH=AUCTION|SYM=MSFT|SEQ=1|EQQTY=0|TRADES=0|IMBQTY=0"));
    expect(decoded.eqPrice).toBeUndefined();
    expect(decoded.eqQty).toBe(0);
    expect(decoded.imbalanceSide).toBeUndefined();
  });

  it("carries the reason a circuit-breaker reopening can be told from the close", () => {
    const decoded = decodeAuction(
      fieldsOf("AUCTION|CH=AUCTION|SYM=AAPL|SEQ=2|EQQTY=0|TRADES=0|IMBQTY=0|REASON=REOPEN"),
    );
    expect(decoded.reason).toBe("REOPEN");
  });

  it("reads the scheduled and startup reasons too", () => {
    const of = (reason: string) =>
      decodeAuction(fieldsOf(`AUCTION|CH=AUCTION|SYM=AAPL|SEQ=1|EQQTY=0|TRADES=0|IMBQTY=0|REASON=${reason}`))
        .reason;
    expect(of("SCHEDULED")).toBe("SCHEDULED");
    expect(of("RECOVERY")).toBe("RECOVERY");
  });

  it("omits the reason when an older gateway sends none", () => {
    const decoded = decodeAuction(fieldsOf("AUCTION|CH=AUCTION|SYM=AAPL|SEQ=1|EQQTY=0|TRADES=0|IMBQTY=0"));
    expect(decoded.reason).toBeUndefined();
  });

  it("drops a reason it does not recognise rather than passing it through", () => {
    // Absent is a state every consumer already handles; an unknown string
    // typed as a known variant is not.
    const decoded = decodeAuction(
      fieldsOf("AUCTION|CH=AUCTION|SYM=AAPL|SEQ=1|EQQTY=0|TRADES=0|IMBQTY=0|REASON=SOMETHING_NEW"),
    );
    expect(decoded.reason).toBeUndefined();
  });
});

describe("decodeCb", () => {
  it("decodes an automatic halt with full trigger context", () => {
    const line =
      "CB|CH=CB|SYM=TSLA|SEQ=4|STATUS=HALTED|LEVEL=L2|TRIGGERPX=261.40" +
      "|REFPX=248.00|RESUMEAT=2026-07-11T11:07:17.000Z|SRC=CB";
    expect(decodeCb(fieldsOf(line))).toEqual({
      status: "HALTED",
      level: "L2",
      triggerPrice: 261.4,
      referencePrice: 248,
      resumeAt: "2026-07-11T11:07:17.000Z",
      haltSource: "CB",
    });
  });

  it("keeps RESUMEAT as ISO text, not epoch nanoseconds", () => {
    // Corrects design §17.3's resumeAtNs — the gateway's _ns_to_iso() has
    // already converted by the time the value reaches the wire.
    const decoded = decodeCb(fieldsOf("CB|CH=CB|SYM=TSLA|STATUS=HALTED|RESUMEAT=2026-07-11T11:07:17.000Z"));
    expect(decoded.resumeAt).toBe("2026-07-11T11:07:17.000Z");
  });

  it("omits trigger context for an operator-initiated halt", () => {
    const decoded = decodeCb(fieldsOf("CB|CH=CB|SYM=TSLA|SEQ=5|STATUS=HALTED|LEVEL=ADMIN_SYMBOL"));
    expect(decoded.level).toBe("ADMIN_SYMBOL");
    expect(decoded.triggerPrice).toBeUndefined();
    expect(decoded.referencePrice).toBeUndefined();
    expect(decoded.resumeAt).toBeUndefined();
  });

  it("decodes a resume, which carries no halt detail at all", () => {
    expect(decodeCb(fieldsOf("CB|CH=CB|SYM=TSLA|SEQ=6|STATUS=ACTIVE|SRC=ADMIN"))).toEqual({
      status: "ACTIVE",
      haltSource: "ADMIN",
    });
  });

  it("drops a halt source it does not recognise rather than passing it through", () => {
    // A newer gateway may grow a source this client has no branch for.
    // Absent is a state every consumer already handles; an unknown string
    // typed as a known variant is not.
    const decoded = decodeCb(fieldsOf("CB|CH=CB|SYM=TSLA|STATUS=HALTED|SRC=SOMETHING_NEW"));
    expect(decoded.haltSource).toBeUndefined();
  });

  it("reads the baseline SNAP for a symbol that has never halted as ACTIVE", () => {
    expect(decodeCb(fieldsOf("SNAP|CH=CB|SYM=AAPL|SEQ=1|STATUS=ACTIVE"))).toEqual({ status: "ACTIVE" });
  });

  it("reads the ACE corridor off a halt", () => {
    const line = "CB|CH=CB|SYM=AAPL|SEQ=4|STATUS=HALTED|LEVEL=L1|CORRLO=90.00|CORRHI=110.00|EXP=0|SRC=CB";
    expect(decodeCb(fieldsOf(line))).toEqual({
      status: "HALTED",
      level: "L1",
      corridorLow: 90,
      corridorHigh: 110,
      expansion: 0,
      haltSource: "CB",
    });
  });

  it("reads an extension's widened corridor and the price that caused it", () => {
    // Without these a client keeps a RESUMEAT that has already passed and
    // reports the symbol as overdue to reopen.
    const line =
      "CB|CH=CB|SYM=AAPL|SEQ=5|STATUS=HALTED|LEVEL=L1|RESUMEAT=2026-07-20T13:37:00.000Z" +
      "|CORRLO=80.00|CORRHI=120.00|EXP=1|SRC=CB|INDICPX=122.00|INDICQTY=500|IMB=BUY";
    expect(decodeCb(fieldsOf(line))).toEqual({
      status: "HALTED",
      level: "L1",
      resumeAt: "2026-07-20T13:37:00.000Z",
      corridorLow: 80,
      corridorHigh: 120,
      expansion: 1,
      haltSource: "CB",
      indicativePrice: 122,
      indicativeQty: 500,
      imbalanceSide: "BUY",
    });
  });

  it("reads a resume the trading day forced", () => {
    const line =
      "CB|CH=CB|SYM=AAPL|SEQ=9|STATUS=ACTIVE|SRC=CB|REASON=CLOSING_BACKSTOP|CLAMPED=1|PRINTPX=120.00";
    expect(decodeCb(fieldsOf(line))).toEqual({
      status: "ACTIVE",
      haltSource: "CB",
      reason: "CLOSING_BACKSTOP",
      clamped: true,
      printPrice: 120,
    });
  });

  it("ignores an imbalance side it does not recognise", () => {
    const decoded = decodeCb(fieldsOf("CB|CH=CB|SYM=AAPL|SEQ=6|STATUS=HALTED|IMB=SIDEWAYS"));
    expect(decoded.imbalanceSide).toBeUndefined();
  });

  it("leaves an ordinary resume free of backstop fields", () => {
    const decoded = decodeCb(fieldsOf("CB|CH=CB|SYM=AAPL|SEQ=7|STATUS=ACTIVE|SRC=CB"));
    expect(decoded.reason).toBeUndefined();
    expect(decoded.clamped).toBeUndefined();
    expect(decoded.printPrice).toBeUndefined();
  });
});
