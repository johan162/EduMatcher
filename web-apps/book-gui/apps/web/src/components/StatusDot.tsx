import clsx from "clsx";

/** Coloured dot plus label, used for the connection indicator (terminal-gui's `StatusDot`). */
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
