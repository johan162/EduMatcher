import type { SessionState, Tif } from "@/types/index.js";

/** TIF values allowed per session phase (§12.5). */
export const ALLOWED_TIF: Record<SessionState, Tif[]> = {
  PRE_OPEN: ["DAY", "GTC"],
  OPENING_AUCTION: ["DAY", "GTC", "ATO"],
  CONTINUOUS: ["DAY", "GTC"],
  CLOSING_AUCTION: ["DAY", "GTC", "ATC"],
  CLOSED: [],
};

/** Valid session-state transitions (§15.4). */
export const VALID_TRANSITIONS: Record<SessionState, SessionState[]> = {
  PRE_OPEN: ["OPENING_AUCTION", "CONTINUOUS"],
  OPENING_AUCTION: ["CONTINUOUS"],
  CONTINUOUS: ["CLOSING_AUCTION", "CLOSED"],
  CLOSING_AUCTION: ["CLOSED"],
  CLOSED: ["PRE_OPEN"],
};

/** Session phase display labels and Tailwind background colours (§9.5). */
export const SESSION_PHASE_META: Record<
  SessionState,
  { label: string; bgClass: string; textClass: string }
> = {
  PRE_OPEN: { label: "Pre-Open", bgClass: "bg-slate-500", textClass: "text-white" },
  OPENING_AUCTION: { label: "Opening Auction", bgClass: "bg-amber-500", textClass: "text-black" },
  CONTINUOUS: { label: "Continuous", bgClass: "bg-emerald-500", textClass: "text-black" },
  CLOSING_AUCTION: { label: "Closing Auction", bgClass: "bg-amber-500", textClass: "text-black" },
  CLOSED: { label: "Closed", bgClass: "bg-red-600", textClass: "text-white" },
};

/** Returns true if a given TIF is allowed in the current session phase. */
export function isTifAllowed(tif: Tif, phase: SessionState): boolean {
  return (ALLOWED_TIF[phase] as Tif[]).includes(tif);
}
