/**
 * Whether a displayed quote is something anyone could actually trade on.
 *
 * A grid renders the last known bid and ask identically whether the market
 * is open, halted, in a call auction, or closed for the night — same digits,
 * same spread, same conviction. That is the most dangerous thing a market
 * data screen can do, because a spread is not a number, it is an offer: a
 * reader who sees `150.10 / 150.12` reads "I can buy at 150.12", and after
 * the close, or under a halt, nobody can.
 *
 * The quote is not *wrong* in those states — it is the last real book, and
 * hiding it would lose information a trader wants. What is wrong is showing
 * it in the register reserved for a live market. So the values stay and the
 * presentation changes.
 */

/**
 * Session phases in which continuous trading is happening.
 *
 * `CONTINUOUS` alone. The call phases (`OPENING_AUCTION`, `CLOSING_AUCTION`)
 * accept orders but match nothing until they uncross, so a bid and an ask
 * can sit crossed for minutes with no trade — the one moment a spread is
 * least meaningful and most likely to be misread. `PRE_OPEN`, `POST_CLOSE`
 * and `CLOSED` are not trading at all.
 */
const CONTINUOUS_PHASES = new Set(["CONTINUOUS"]);

/** Why a quote cannot be acted on. `null` when it can. */
export type NotExecutableReason = "halted" | "auction" | "closed";

export interface QuoteStatusInput {
  /** Exchange-wide session phase, from `STATE` with `SYM=*`. */
  sessionPhase: string | null | undefined;
  /** Whether this particular symbol is halted. */
  halted: boolean;
}

/**
 * Why this symbol's quote is not executable, or `null` if it is.
 *
 * The symbol's own halt outranks the session phase: a halted symbol during
 * `CONTINUOUS` is halted, and saying "closed" would be false. An unknown or
 * not-yet-received phase is treated as executable rather than not — the
 * terminal has no business marking the whole board untradable because it has
 * not heard from the feed yet, which is a connection problem and is reported
 * as one.
 */
export function notExecutableReason(input: QuoteStatusInput): NotExecutableReason | null {
  if (input.halted) return "halted";

  const phase = input.sessionPhase;
  if (phase === undefined || phase === null || phase === "") return null;
  if (CONTINUOUS_PHASES.has(phase)) return null;

  return phase.endsWith("AUCTION") ? "auction" : "closed";
}

/** Short label for a cell tooltip or a footnote. */
export function notExecutableLabel(reason: NotExecutableReason): string {
  switch (reason) {
    case "halted":
      return "Symbol halted — this quote is the last book before the halt and is not executable";
    case "auction":
      return "Call auction — orders are accepted but nothing matches until the uncross, so this is an indication rather than an executable quote";
    case "closed":
      return "Market closed — this is the last book of the session and is not executable";
  }
}

/** One word for the status strip and the grid footnote. */
export function notExecutableShortLabel(reason: NotExecutableReason): string {
  switch (reason) {
    case "halted":
      return "halted";
    case "auction":
      return "in auction";
    case "closed":
      return "closed";
  }
}
