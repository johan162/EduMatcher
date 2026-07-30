/**
 * Client -> gateway command builders.
 */

import { buildLine } from "./line.js";
import type { Channel } from "./channels.js";

export function buildHello(clientId: string): string {
  return buildLine("HELLO", { CLIENT: clientId, PROTO: "CALF1" });
}

/**
 * Replay one `(CH, SYM)` stream from `lastSeq`, instead of a `SNAP` baseline.
 *
 * One stream per message, and repeatable — `LASTSEQ` describes a single
 * stream's position, so a multi-stream form would be meaningless. `SYM=*` is
 * rejected on every channel, including the four where `SUB` accepts it.
 *
 * CALF previously carried this as a `RESUME=1` flag on `HELLO`, which the
 * gateway only ever processed once per connection. The bridge does not use
 * this yet: it reconnects with a plain `HELLO` and re-subscribes, letting the
 * automatic `SNAP` baselines restore state — see `apps/bridge/src/calf/uplink.ts`.
 */
export function buildResume(ch: Channel, symbol: string, lastSeq: number): string {
  return buildLine("RESUME", { CH: ch, SYM: symbol, LASTSEQ: String(lastSeq) });
}

/**
 * `SUB|CH=a,b|SYM=x,y` subscribes to the full cross product of channels and
 * symbols — that is how the gateway expands it (`requested_pairs`), so only
 * group channels that should share the same symbol set.
 */
export function buildSub(channels: Channel[], symbols: string[]): string {
  return buildLine("SUB", { CH: channels.join(","), SYM: symbols.join(",") });
}

export function buildUnsub(channels: Channel[], symbols: string[]): string {
  return buildLine("UNSUB", { CH: channels.join(","), SYM: symbols.join(",") });
}

/**
 * The gateway's idle timer only advances on *inbound* client bytes
 * (`ClientSession.last_activity` is set in `_read_client_data`); its own
 * outbound `HB` does not reset it. A bridge that only ever listens is
 * therefore disconnected after `idle_timeout_sec` (default 300). A periodic
 * `PING` — answered with `PONG` — is what keeps the session alive.
 */
export function buildPing(): string {
  return buildLine("PING");
}

export function buildExit(): string {
  return buildLine("EXIT");
}

/**
 * Ask the gateway which instruments it knows about.
 *
 * `WELCOME|SYMBOLS=` is not a substitute: it is optional, sent once, and
 * omitted entirely when the gateway started without a readable engine config —
 * which is exactly what a misconfigured deployment looks like from the client
 * side. The gateway's set also grows as instruments appear on the engine bus,
 * so a client that connected early would otherwise never learn of them.
 */
export function buildSymbolsRequest(): string {
  return buildLine("SYMBOLS");
}
