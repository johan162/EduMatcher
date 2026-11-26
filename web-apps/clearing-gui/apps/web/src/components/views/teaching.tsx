/**
 * Empty participant tables that teach (CG25): what would fill the table, and
 * which chapter of the Participant Guide explains it. Always shown, whatever
 * the Explain setting: an empty table is where a beginner starts.
 *
 * The wording follows whose data it is: the participant's own ("your"), one
 * gateway an ADMIN opened ("this gateway's"), or every gateway (venue).
 */
import type { ReactNode } from "react";

export interface Subject {
  you: string;
  your: string;
  /** The gateway, as a noun phrase: "your gateway", "this gateway". */
  gateway: string;
}

/** Whose rows a view shows: the caller (no gateway), one gateway, or every gateway. */
export function subject(gateway?: string, venue = false): Subject {
  if (venue) return { you: "a gateway", your: "a gateway's", gateway: "a gateway" };
  if (gateway) return { you: "this gateway", your: "this gateway's", gateway: "this gateway" };
  return { you: "you", your: "your", gateway: "your gateway" };
}

/** The empty-table hint: what fills it, then the guide chapter that explains it. */
export function teachingHint(text: string, chapter: string): ReactNode {
  return (
    <>
      {`${text} Read more in the `}
      <cite>{`Participant Guide, “${chapter}”`}</cite>.
    </>
  );
}
