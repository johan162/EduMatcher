/**
 * CALF channel vocabulary, mirroring `md_gateway/gateway.py`'s own constants.
 *
 * Kept in sync with `_ALLOWED_CHANNELS` and `_WILDCARD_ELIGIBLE_CHANNELS`
 * there. The gateway advertises its actual set in `WELCOME|CH_SUPPORTED=`, so
 * these are the bridge's *expectations*, checked against that advertisement at
 * handshake time rather than assumed.
 */

export const CHANNELS = ["TOP", "TRADE", "STATE", "INDEX", "DEPTH", "AUCTION", "CB"] as const;
export type Channel = (typeof CHANNELS)[number];

/**
 * Channels that accept `SYM=*` on a `SUB` line.
 *
 * `INDEX` needs an explicit index id; `DEPTH` is too heavy per message to fan
 * out across every symbol; `CB` is a rare per-symbol event the gateway
 * deliberately does not firehose. All three are rejected with
 * `ERR|CODE=INVALID_SYMBOL` if a client tries.
 */
export const WILDCARD_ELIGIBLE = new Set<Channel>(["STATE", "TOP", "TRADE", "AUCTION"]);

/**
 * Channels the gateway sends an automatic baseline `SNAP` for on first `SUB`.
 *
 * `TRADE` and `AUCTION` are absent by design — they are event streams with no
 * "current state" to snapshot, so a subscriber only ever sees future events
 * (design §4.3 gap 3).
 */
export const SNAPSHOT_ELIGIBLE = new Set<Channel>(["TOP", "STATE", "INDEX", "DEPTH", "CB"]);

export function isChannel(value: string): value is Channel {
  return (CHANNELS as readonly string[]).includes(value);
}

/** Whether `SUB|CH=<ch>|SYM=*` will be accepted rather than rejected. */
export function acceptsWildcard(ch: Channel): boolean {
  return WILDCARD_ELIGIBLE.has(ch);
}
