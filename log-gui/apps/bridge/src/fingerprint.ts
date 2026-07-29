/**
 * Fingerprinting: from events to issues (design §11.1).
 *
 * fingerprint = sha1(process ‖ logger ‖ level ‖ normalise(message))[:16]
 *
 * `normalise()` strips the variable parts that would otherwise make every
 * occurrence of the same underlying problem unique. This is a heuristic and
 * will occasionally over- or under-group — that is accepted (§11.1) and is
 * why the issue detail view always lists distinct raw messages.
 */

import { createHash } from "node:crypto";
import type { LogRow } from "@edumatcher/log-types";

// Order matters: hex runs before integers (a long hex string like
// "1a2b3c4d5e6f" would otherwise be partially eaten by the integer rule
// first, since it contains 3+ digit runs).
const HEX_RUN = /\b[0-9a-fA-F]{6,}\b/g;
const ISO_TIMESTAMP =
  /\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:?\d{2})?\b/g;
const QUOTED_STRING = /'[^']*'|"[^"]*"/g;
const FLOAT_LITERAL = /\b\d+\.\d+\b/g;
const INTEGER_3PLUS = /\b\d{3,}\b/g;

/**
 * For a row with a traceback, only the exception type + final frame is
 * fingerprinted (design §11.1 table, last row) — two occurrences of the same
 * bug differ in every intermediate frame's local values but agree on where
 * they were raised. We approximate "final frame" as the last non-blank line
 * of the message when `has_exception` is set, since that is where Python's
 * traceback format places the raising frame and the exception line.
 */
function extractFingerprintText(row: Pick<LogRow, "message" | "has_exception">): string {
  if (!row.has_exception) return row.message;
  const lines = row.message.split("\n").map((l) => l.trim()).filter(Boolean);
  if (lines.length === 0) return row.message;
  // Last two non-blank lines: typically "File "...", line N, in ..." followed
  // by the exception type/message line.
  return lines.slice(-2).join("\n");
}

export function normaliseMessage(message: string): string {
  return message
    .replace(HEX_RUN, "<HEX>")
    .replace(ISO_TIMESTAMP, "<TS>")
    .replace(QUOTED_STRING, "<STR>")
    .replace(FLOAT_LITERAL, "<F>")
    .replace(INTEGER_3PLUS, "<N>");
}

export function computeFingerprint(row: Pick<LogRow, "process" | "logger" | "level" | "message" | "has_exception">): string {
  const text = extractFingerprintText(row);
  const normalised = normaliseMessage(text);
  const key = `${row.process}␟${row.logger}␟${row.level}␟${normalised}`;
  return createHash("sha1").update(key, "utf8").digest("hex").slice(0, 16);
}
