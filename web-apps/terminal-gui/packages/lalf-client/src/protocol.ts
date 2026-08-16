/**
 * LALF wire protocol — a TS port of `edumatcher/logclient/protocol.py`.
 *
 * LALF shares CALF's header grammar (`MSGTYPE|KEY=VALUE|...\n`) but adds one
 * thing CALF never needed: `LOG` carries an arbitrary-text payload that cannot
 * survive a pipe-delimited field, because a log message may itself contain
 * `|`, embedded newlines, or any Unicode. The header line's final field is
 * therefore `LEN=<n>`, and exactly `n` further raw UTF-8 bytes follow the
 * header's own newline — never scanned for a delimiter.
 *
 * Getting that byte count wrong is the single most common implementation
 * mistake, so `buildLogFrame` measures the encoded payload rather than the
 * string's `.length`, which would be wrong for every non-ASCII message.
 */

export const PROTO_VERSION = "LALF1";
/** Payload ceiling before truncation, matching `DEFAULT_MAX_MESSAGE_BYTES`. */
export const DEFAULT_MAX_MESSAGE_BYTES = 65536;
export const MAX_HEADER_LINE_BYTES = 4096;

export const LOG_LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] as const;
export type LogLevel = (typeof LOG_LEVELS)[number];

export class LalfProtocolError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "LalfProtocolError";
  }
}

const MSGTYPE_PATTERN = /^[A-Z0-9_]+$/;

export function parseHeaderLine(line: string): { msgType: string; fields: Record<string, string> } {
  const raw = line.replace(/[\r\n]+$/, "");
  if (!raw) throw new LalfProtocolError("empty line");

  const parts = raw.split("|");
  const msgType = parts[0] ?? "";
  if (!MSGTYPE_PATTERN.test(msgType)) {
    throw new LalfProtocolError(`invalid MSGTYPE: ${JSON.stringify(msgType)}`);
  }

  const fields: Record<string, string> = {};
  for (const token of parts.slice(1)) {
    const eq = token.indexOf("=");
    if (eq < 0) throw new LalfProtocolError(`invalid field token: ${JSON.stringify(token)}`);
    const key = token.slice(0, eq);
    if (!key) throw new LalfProtocolError("empty field key");
    fields[key] = token.slice(eq + 1);
  }
  return { msgType, fields };
}

/**
 * Build one header line. Callers building a `LOG` frame must append the
 * payload bytes themselves, immediately after, with no separator.
 */
export function buildHeaderLine(msgType: string, fields?: Record<string, string>): Buffer {
  if (!MSGTYPE_PATTERN.test(msgType)) {
    throw new LalfProtocolError(`invalid MSGTYPE: ${JSON.stringify(msgType)}`);
  }
  const tokens = [msgType];
  for (const [key, value] of Object.entries(fields ?? {})) {
    if (!key) throw new LalfProtocolError("empty field key");
    if (/[|\n]/.test(key) || /[|\n]/.test(value)) {
      throw new LalfProtocolError("'|' and newline not allowed in header key/value");
    }
    tokens.push(`${key}=${value}`);
  }
  return Buffer.from(`${tokens.join("|")}\n`, "utf8");
}

/** UTC ISO-8601 with milliseconds — the format every LALF `TS` field uses. */
export function isoUtc(ms: number = Date.now()): string {
  return new Date(ms).toISOString().replace(/(\.\d{3})\d*Z$/, "$1Z");
}

export function buildHello(client: string, pid: number, host: string, instance?: string): Buffer {
  const fields: Record<string, string> = {
    CLIENT: client,
    PID: String(pid),
    HOST: host,
    PROTO: PROTO_VERSION,
  };
  if (instance !== undefined) fields["INSTANCE"] = instance;
  return buildHeaderLine("HELLO", fields);
}

export function buildHb(ts: string): Buffer {
  return buildHeaderLine("HB", { TS: ts });
}

export function buildExit(): Buffer {
  return buildHeaderLine("EXIT");
}

export interface WelcomeInfo {
  srv: string;
  /** Server-assigned heartbeat interval in seconds. */
  hbint: number;
  session: string;
}

export function parseWelcome(fields: Record<string, string>): WelcomeInfo {
  const missing = ["PROTO", "SRV", "HBINT", "SESSION"].filter((key) => !(key in fields));
  if (missing.length > 0) throw new LalfProtocolError(`WELCOME missing fields: ${missing.join(",")}`);
  if (fields["PROTO"] !== PROTO_VERSION) {
    throw new LalfProtocolError(`WELCOME PROTO mismatch: ${JSON.stringify(fields["PROTO"])}`);
  }
  const hbint = Number(fields["HBINT"]);
  if (!Number.isFinite(hbint))
    throw new LalfProtocolError(`invalid HBINT: ${JSON.stringify(fields["HBINT"])}`);
  return { srv: fields["SRV"] ?? "", hbint, session: fields["SESSION"] ?? "" };
}

export interface LogRecord {
  seq: number;
  ts: string;
  level: LogLevel;
  logger: string;
  message: string;
  module?: string;
  line?: number;
  hasException?: boolean;
}

/**
 * Build a complete `LOG` frame: header line followed by `LEN` payload bytes.
 *
 * Over-long messages are truncated rather than rejected, matching the server's
 * own truncate-not-reject behaviour, and truncation never splits a multi-byte
 * codepoint — a half-character would make the payload invalid UTF-8 even
 * though `LEN` still matched.
 */
export function buildLogFrame(record: LogRecord, maxMessageBytes = DEFAULT_MAX_MESSAGE_BYTES): Buffer {
  if (!(LOG_LEVELS as readonly string[]).includes(record.level)) {
    throw new LalfProtocolError(`invalid LEVEL: ${JSON.stringify(record.level)}`);
  }

  const payload = truncateUtf8(record.message, maxMessageBytes);

  const fields: Record<string, string> = {
    SEQ: String(record.seq),
    TS: record.ts,
    LEVEL: record.level,
    LOGGER: record.logger,
  };
  if (record.module !== undefined) fields["MODULE"] = record.module;
  if (record.line !== undefined) fields["LINE"] = String(record.line);
  if (record.hasException) fields["EXC"] = "1";
  fields["LEN"] = String(payload.length);

  return Buffer.concat([buildHeaderLine("LOG", fields), payload]);
}

/** Encode as UTF-8, cutting back to a codepoint boundary if over `maxBytes`. */
export function truncateUtf8(text: string, maxBytes: number): Buffer {
  const encoded = Buffer.from(text, "utf8");
  if (encoded.length <= maxBytes) return encoded;

  let cut = maxBytes;
  // Continuation bytes are 10xxxxxx; walk back off any we landed inside.
  while (cut > 0 && (encoded[cut] ?? 0) >= 0x80 && (encoded[cut] ?? 0) < 0xc0) cut -= 1;
  return encoded.subarray(0, cut);
}
