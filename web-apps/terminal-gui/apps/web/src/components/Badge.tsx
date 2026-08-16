import clsx from "clsx";
import type { SessionPhase } from "@edumatcher/terminal-types";

/**
 * Session-phase badge (design §15).
 *
 * `CONTINUOUS` deliberately renders nothing: the absence of a badge *is* the
 * "normal" signal, so anything showing a badge is by definition worth looking
 * at. Adding a green "all fine" pill would dilute exactly that.
 */
export function SessionBadge({ phase }: { phase: SessionPhase | null | undefined }) {
  if (!phase || phase === "CONTINUOUS") return null;

  const halted = phase === "HALTED";
  const auction = phase.endsWith("AUCTION");

  return (
    <span
      className={clsx(
        "rounded px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider",
        halted && "bg-halt-bg text-halt halt-pulse",
        auction && "bg-auction-bg text-auction",
        !halted && !auction && "bg-bg-inset text-fg-subtle",
      )}
    >
      {phase.replace(/_/g, " ")}
    </span>
  );
}

/** Coloured dot plus label, used for the connection indicator. */
export function StatusDot({ tone, children }: { tone: "live" | "warn" | "down"; children: React.ReactNode }) {
  return (
    <span className="flex items-center gap-1.5">
      <span
        className={clsx(
          "h-2 w-2 rounded-full",
          tone === "live" && "bg-live",
          tone === "warn" && "bg-halt",
          tone === "down" && "bg-offline",
        )}
      />
      {children}
    </span>
  );
}
