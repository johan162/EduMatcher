/**
 * Reading and writing a flat table (one object per row, fixed columns) as
 * CSV or JSON, for bulk import/export of draft lists. Blank CSV cells, and
 * missing or null JSON values, are left out of the row.
 */

export type TableFileFormat = "csv" | "json";

export type TableRow<C extends string> = Partial<Record<C, unknown>>;

/** Rows paired with the label errors use ("line 3", "entry 2"). */
export type LabelledRows<C extends string> = Array<[string, TableRow<C>]>;

/** Split one CSV line, honouring double quotes and "" escapes; null if a quote is left open. */
function splitCsvLine(line: string): string[] | null {
  const cells: string[] = [];
  let cell = "";
  let quoted = false;
  for (let i = 0; i < line.length; i++) {
    const ch = line[i]!;
    if (quoted) {
      if (ch !== '"') cell += ch;
      else if (line[i + 1] === '"') {
        cell += '"';
        i++;
      } else quoted = false;
    } else if (ch === '"') quoted = true;
    else if (ch === ",") {
      cells.push(cell.trim());
      cell = "";
    } else cell += ch;
  }
  if (quoted) return null;
  cells.push(cell.trim());
  return cells;
}

function parseCsv<C extends string>(
  text: string,
  columns: readonly C[],
  required: readonly C[],
  errors: string[],
): LabelledRows<C> {
  const lines = text.replace(/^﻿/, "").split(/\r?\n/);
  const header = splitCsvLine(lines[0] ?? "");
  if (header === null || (header.length === 1 && header[0] === "")) {
    errors.push(header === null ? "line 1: unterminated quote." : "The file is empty.");
    return [];
  }
  for (const [i, key] of header.entries()) {
    if (!(columns as readonly string[]).includes(key)) errors.push(`Unknown column "${key}".`);
    else if (header.indexOf(key) !== i) errors.push(`Column "${key}" appears twice.`);
  }
  for (const key of required) {
    if (!header.includes(key)) errors.push(`Missing required column "${key}".`);
  }
  if (errors.length > 0) return [];

  const rows: LabelledRows<C> = [];
  lines.slice(1).forEach((line, i) => {
    if (line.trim() === "") return;
    const label = `line ${i + 2}`;
    const cells = splitCsvLine(line);
    if (cells === null) {
      errors.push(`${label}: unterminated quote.`);
      return;
    }
    if (cells.length !== header.length) {
      errors.push(`${label}: expected ${header.length} fields, found ${cells.length}.`);
      return;
    }
    const row: TableRow<C> = {};
    header.forEach((key, j) => {
      if (cells[j] !== "") row[key as C] = cells[j];
    });
    rows.push([label, row]);
  });
  return rows;
}

function parseJson<C extends string>(
  text: string,
  columns: readonly C[],
  noun: string,
  errors: string[],
): LabelledRows<C> {
  let data: unknown;
  try {
    data = JSON.parse(text);
  } catch (err) {
    errors.push(`Not valid JSON: ${err instanceof Error ? err.message : String(err)}`);
    return [];
  }
  if (!Array.isArray(data)) {
    errors.push(`The JSON file must hold an array of ${noun} objects.`);
    return [];
  }
  const rows: LabelledRows<C> = [];
  data.forEach((item: unknown, i) => {
    const label = `entry ${i + 1}`;
    if (typeof item !== "object" || item === null || Array.isArray(item)) {
      errors.push(`${label}: not an object.`);
      return;
    }
    const row: TableRow<C> = {};
    for (const [key, value] of Object.entries(item)) {
      if (!(columns as readonly string[]).includes(key)) errors.push(`${label}: unknown key "${key}".`);
      else if (value !== null) row[key as C] = value;
    }
    rows.push([label, row]);
  });
  return rows;
}

/**
 * Parse a file into labelled rows. Structural problems go to `errors`; the
 * caller validates the values. `noun` names a row's object in messages.
 */
export function readTable<C extends string>(
  text: string,
  format: TableFileFormat,
  columns: readonly C[],
  required: readonly C[],
  noun: string,
  errors: string[],
): LabelledRows<C> {
  const rows =
    format === "json" ? parseJson(text, columns, noun, errors) : parseCsv(text, columns, required, errors);
  if (errors.length === 0 && rows.length === 0) errors.push("The file holds no rows.");
  return rows;
}

const csvCell = (value: string | number | undefined): string => {
  const s = value === undefined ? "" : String(value);
  return /[",\r\n]|^\s|\s$/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
};

/** Write rows in column order; an undefined value is a blank cell (CSV) or an absent key (JSON). */
export function writeTable<C extends string>(
  rows: Array<Partial<Record<C, string | number>>>,
  columns: readonly C[],
  format: TableFileFormat,
): string {
  if (format === "json") return JSON.stringify(rows, null, 2) + "\n";
  const lines = [columns.join(","), ...rows.map((r) => columns.map((c) => csvCell(r[c])).join(","))];
  return lines.join("\n") + "\n";
}

/** A number, or a string holding one; anything else is invalid. */
export function toNumber(value: unknown): number | undefined | "invalid" {
  if (value === undefined) return undefined;
  const n = typeof value === "string" ? Number(value) : value;
  return typeof n === "number" && Number.isFinite(n) ? n : "invalid";
}
