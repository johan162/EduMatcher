/**
 * Severity is never signalled by colour alone (design §14.2, §18): every
 * level carries a distinct text label too.
 */

import clsx from "clsx";
import type { LogLevel } from "@edumatcher/log-types";

const LABELS: Record<LogLevel, string> = {
  DEBUG: "DBG",
  INFO: "INF",
  WARNING: "WRN",
  ERROR: "ERR",
  CRITICAL: "CRI",
};

const CLASSES: Record<LogLevel, string> = {
  DEBUG: "text-level-debug",
  INFO: "text-level-info",
  WARNING: "text-level-warning",
  ERROR: "text-level-error",
  CRITICAL: "text-level-critical bg-level-critical-bg",
};

export function SeverityBadge({ level }: { level: LogLevel }) {
  return (
    <span
      className={clsx(
        "inline-flex items-center rounded px-1.5 py-0.5 text-xs font-mono font-semibold",
        CLASSES[level],
      )}
    >
      {LABELS[level]}
    </span>
  );
}
