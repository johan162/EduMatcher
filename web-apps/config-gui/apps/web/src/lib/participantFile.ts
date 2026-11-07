import {
  DISCONNECT_BEHAVIOURS,
  PARTICIPANT_ROLES,
  SMP_ACTIONS,
  createGateway,
  type EngineConfigDraft,
  type GatewayConfig,
} from "@edumatcher/schema";
import { uppercaseId } from "./format";
import { readTable, writeTable, type TableFileFormat } from "./tableFile";

/**
 * Bulk participant import/export as CSV or JSON. A row carries exactly the
 * Participants table's fields and creates the gateway "+ Add gateway" would:
 * a blank role is TRADER and a blank disconnect_behaviour is the role's
 * default. A blank smp_action inherits the participant default.
 */

export const PARTICIPANT_FILE_COLUMNS = [
  "id",
  "role",
  "disconnect_behaviour",
  "smp_action",
  "description",
] as const;

/** The engine's own disconnect behaviour when neither gateway nor default sets one. */
const ENGINE_DISCONNECT_DEFAULT = "CANCEL_QUOTES_ONLY";

/** An uppercased member of `allowed`, undefined when blank; pushes an error if not allowed. */
function enumValue<T extends string>(
  value: unknown,
  allowed: readonly T[],
  key: string,
  rowErrors: string[],
): T | undefined {
  if (value === undefined) return undefined;
  const v = typeof value === "string" ? uppercaseId(value) : "";
  if ((allowed as readonly string[]).includes(v)) return v as T;
  rowErrors.push(`${key} "${String(value)}" must be one of ${allowed.join(", ")}.`);
  return undefined;
}

/**
 * Parse and validate a whole file against the draft. Any error rejects the
 * file: `items` is only meaningful when `errors` is empty.
 */
export function readParticipantFile(
  text: string,
  format: TableFileFormat,
  draft: EngineConfigDraft,
): { items: GatewayConfig[]; errors: string[] } {
  const errors: string[] = [];
  const rows = readTable(text, format, PARTICIPANT_FILE_COLUMNS, ["id"], "participant", errors);

  const existing = new Set(draft.gateways.map((g) => g.id));
  const seen = new Set<string>();
  const items: GatewayConfig[] = [];

  for (const [label, row] of rows) {
    const rowErrors: string[] = [];
    const id = typeof row.id === "string" ? uppercaseId(row.id) : "";
    if (id === "") rowErrors.push("id is required.");
    else if (existing.has(id)) rowErrors.push(`id ${id} already exists.`);
    else if (seen.has(id)) rowErrors.push(`id ${id} appears more than once.`);

    const role = enumValue(row.role, PARTICIPANT_ROLES, "role", rowErrors);
    const disconnect = enumValue(row.disconnect_behaviour, DISCONNECT_BEHAVIOURS, "disconnect_behaviour", rowErrors);
    const smp = enumValue(row.smp_action, SMP_ACTIONS, "smp_action", rowErrors);
    if (row.description !== undefined && typeof row.description !== "string")
      rowErrors.push("description must be text.");

    if (rowErrors.length > 0) {
      errors.push(...rowErrors.map((e) => `${label}: ${e}`));
      continue;
    }
    const gateway = createGateway(id, role);
    if (disconnect) gateway.disconnectBehaviour = disconnect;
    if (smp) gateway.smpAction = smp;
    if (row.description) gateway.description = row.description as string;
    seen.add(id);
    items.push(gateway);
  }
  return { items: errors.length === 0 ? items : [], errors };
}

/** Append imported participants in file order. */
export function addImportedParticipants(d: EngineConfigDraft, gateways: GatewayConfig[]): void {
  d.gateways.push(...gateways);
}

/**
 * Write every participant's table fields. A gateway that inherits its
 * disconnect behaviour is written with the value it inherits now, so the
 * engine behaves the same, and named in `warnings`, as it no longer follows
 * the participant default after a re-import.
 */
export function writeParticipantFile(
  draft: EngineConfigDraft,
  format: TableFileFormat,
): { text: string; warnings: string[] } {
  const warnings: string[] = [];
  const rows = draft.gateways.map((g) => {
    const disconnect =
      g.disconnectBehaviour ?? draft.gatewayDefault.disconnectBehaviour ?? ENGINE_DISCONNECT_DEFAULT;
    if (g.id === "") warnings.push("A participant has no id.");
    else if (g.disconnectBehaviour === undefined)
      warnings.push(`${g.id}: inherits its disconnect behaviour; written as ${disconnect}.`);
    return {
      id: g.id,
      role: g.role,
      disconnect_behaviour: disconnect,
      smp_action: g.smpAction,
      description: g.description,
    };
  });
  return { text: writeTable(rows, PARTICIPANT_FILE_COLUMNS, format), warnings };
}
