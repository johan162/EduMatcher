/**
 * CALF line grammar — a direct TS port of `md_gateway/protocol.py`.
 *
 * Every CALF message is one newline-delimited UTF-8 line:
 *
 *     MSGTYPE|KEY=VALUE|KEY=VALUE\n
 *
 * This module knows the grammar and nothing else: no channel semantics, no
 * gateway state, no sockets (design §5.2). Behaviour is deliberately
 * identical to the Python parser, including last-value-wins on duplicate keys
 * and the 4096-byte line ceiling.
 */

export class CalfProtocolError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "CalfProtocolError";
  }
}

export interface CalfFrame {
  msgType: string;
  fields: Record<string, string>;
}

/** `_MAX_LINE_BYTES` in `md_gateway/gateway.py`, including the newline. */
export const MAX_LINE_BYTES = 4096;

const MSGTYPE_PATTERN = /^[A-Z0-9_]+$/;

/** Parse one CALF line. Mirrors `protocol.parse_line`. */
export function parseLine(line: string): CalfFrame {
  const raw = line.replace(/[\r\n]+$/, "");
  if (!raw) throw new CalfProtocolError("empty line");

  const parts = raw.split("|");
  const msgType = parts[0] ?? "";
  if (!MSGTYPE_PATTERN.test(msgType)) {
    throw new CalfProtocolError(`invalid MSGTYPE: ${JSON.stringify(msgType)}`);
  }

  const fields: Record<string, string> = {};
  for (const token of parts.slice(1)) {
    const eq = token.indexOf("=");
    if (eq < 0) throw new CalfProtocolError(`invalid field token: ${JSON.stringify(token)}`);
    const key = token.slice(0, eq);
    if (!key) throw new CalfProtocolError("empty field key");
    fields[key] = token.slice(eq + 1);
  }

  return { msgType, fields };
}

/** Build one CALF line, newline included. Mirrors `protocol.build_line`. */
export function buildLine(msgType: string, fields?: Record<string, string>): string {
  if (!MSGTYPE_PATTERN.test(msgType)) {
    throw new CalfProtocolError(`invalid MSGTYPE: ${JSON.stringify(msgType)}`);
  }

  const tokens = [msgType];
  for (const [key, value] of Object.entries(fields ?? {})) {
    if (!key) throw new CalfProtocolError("empty field key");
    if (key.includes("|") || value.includes("|")) {
      throw new CalfProtocolError("'|' not allowed in key/value");
    }
    tokens.push(`${key}=${value}`);
  }
  return `${tokens.join("|")}\n`;
}

/**
 * Reassembles complete lines from a TCP byte stream.
 *
 * The CALF reference calls this out as non-negotiable: one `data` event is
 * not one message. A single chunk may hold a partial line, one line, several
 * lines, or a line split mid-multi-byte-codepoint — hence buffering as bytes
 * and decoding only once a full line is in hand.
 */
export class LineBuffer {
  private buf: Buffer = Buffer.alloc(0);

  constructor(private readonly maxLineBytes: number = MAX_LINE_BYTES) {}

  /**
   * Append received bytes and return every complete line they finish.
   *
   * Throws `CalfProtocolError` if the buffer grows past `maxLineBytes` with no
   * newline in it — the same defensive guard `md_gateway` applies to its own
   * inbound direction, so a wedged or non-CALF peer cannot make us buffer
   * without bound.
   */
  push(chunk: Buffer): string[] {
    this.buf = this.buf.length === 0 ? chunk : Buffer.concat([this.buf, chunk]);

    const lines: string[] = [];
    for (;;) {
      const idx = this.buf.indexOf(0x0a);
      if (idx < 0) break;
      lines.push(this.buf.subarray(0, idx).toString("utf8"));
      this.buf = this.buf.subarray(idx + 1);
    }

    if (this.buf.length > this.maxLineBytes) {
      const overflow = this.buf.length;
      this.buf = Buffer.alloc(0);
      throw new CalfProtocolError(`line exceeds ${this.maxLineBytes} bytes (buffered ${overflow})`);
    }

    return lines;
  }

  /** Bytes held back waiting for their terminating newline. */
  get pendingBytes(): number {
    return this.buf.length;
  }

  /** Drop any partial line — used when a connection is torn down and re-opened. */
  reset(): void {
    this.buf = Buffer.alloc(0);
  }
}
