import type { EngineConfigDraft, ParticipantRole } from "@edumatcher/schema";

/** A participant that could get a generated key in one API instance. */
export interface KeyCandidate {
  id: string;
  role: ParticipantRole;
  /** The instance that already holds a key for it, if any; it cannot get another. */
  holder?: string;
}

/**
 * Every participant, with the instance already holding a key for it. A
 * participant may have keys in only one instance, and like pm-config-gen a
 * participant that already has a key is not given another.
 */
export function keyCandidates(draft: EngineConfigDraft): KeyCandidate[] {
  const holders = new Map<string, string>();
  for (const gw of draft.apiGateways) {
    for (const c of gw.credentials) {
      if (c.gatewayId !== null && !holders.has(c.gatewayId)) holders.set(c.gatewayId, gw.name);
    }
  }
  return draft.gateways
    .filter((g) => g.id !== "")
    .map((g) => ({ id: g.id, role: g.role, holder: holders.get(g.id) }));
}

const ALPHABET = "abcdefghijklmnopqrstuvwxyz0123456789";

/** pm-config-gen's token length (DEFAULT_API_GATEWAY_KEY_BYTES * 2): short enough to type in class. */
export const DEFAULT_KEY_TOKEN_LENGTH = 6;
export const MIN_KEY_TOKEN_LENGTH = 4;
export const MAX_KEY_TOKEN_LENGTH = 64;

/** A random key in pm-config-gen's `key-<id>-<token>` shape, `tokenLength` characters of [a-z0-9]. */
export function randomApiKey(participantId: string, tokenLength = DEFAULT_KEY_TOKEN_LENGTH): string {
  let token = "";
  while (token.length < tokenLength) {
    for (const b of crypto.getRandomValues(new Uint8Array(tokenLength))) {
      // Reject the top of the byte range so every character is equally likely.
      if (b < 252 && token.length < tokenLength) token += ALPHABET[b % ALPHABET.length];
    }
  }
  return `key-${participantId.toLowerCase()}-${token}`;
}

/** Add one generated key per participant to API instance `index`. */
export function addGeneratedKeys(
  d: EngineConfigDraft,
  index: number,
  participantIds: string[],
  makeKey: (id: string) => string = randomApiKey,
): void {
  for (const id of participantIds) {
    d.apiGateways[index]!.credentials.push({
      apiKey: makeKey(id),
      gatewayId: id,
      description: `Generated key for ${id}`,
    });
  }
}

/** Whether every API instance keeps its credentials in a file (credentials_file). */
export function credentialsInFiles(draft: EngineConfigDraft): boolean {
  return draft.apiGateways.length > 0 && draft.apiGateways.every((gw) => gw.credentialsFile !== undefined);
}

/**
 * Turn credentials files on or off for every API instance. On keeps a name
 * an instance already has and gives the others one: api_keys.yaml for a
 * single instance, as pm-config-gen writes, else api_keys_<instance>.yaml,
 * since instances sharing a file would each read every key in it.
 */
export function setCredentialsInFiles(d: EngineConfigDraft, on: boolean): void {
  if (!on) {
    for (const gw of d.apiGateways) delete gw.credentialsFile;
    return;
  }
  const taken = new Set(d.apiGateways.map((gw) => gw.credentialsFile).filter((f) => f !== undefined));
  for (const gw of d.apiGateways) {
    if (gw.credentialsFile !== undefined) continue;
    const base =
      d.apiGateways.length === 1 ? "api_keys" : `api_keys_${gw.name.toLowerCase().replace(/[^a-z0-9_-]/g, "_")}`;
    let name = `${base}.yaml`;
    for (let n = 2; taken.has(name); n++) name = `${base}_${n}.yaml`;
    taken.add(name);
    gw.credentialsFile = name;
  }
}
