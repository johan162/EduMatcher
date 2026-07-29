/** Top bar (design §7.2): source status, unacked badge, theme toggle. */

import { Moon, Sun, SunMoon } from "lucide-react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../../lib/api.js";
import { cycleTheme, type ThemePreference } from "../../lib/theme.js";
import { useLiveStore, type SourceState } from "../../store/useLiveStore.js";

const VERSION = "v0.1.0";

const STATE_LABEL: Record<SourceState, string> = {
  LIVE: "log-srv up",
  RECONNECTING: "reconnecting…",
  LOG_SERVER_DOWN: "log server down",
  HISTORY_UNAVAILABLE: "log.db unavailable",
};

const STATE_DOT: Record<SourceState, string> = {
  LIVE: "bg-green-500",
  RECONNECTING: "bg-yellow-500",
  LOG_SERVER_DOWN: "bg-red-500",
  HISTORY_UNAVAILABLE: "bg-red-500",
};

export function TopBar({
  theme,
  onThemeChange,
}: {
  theme: ThemePreference;
  onThemeChange: (t: ThemePreference) => void;
}) {
  const connectionState = useLiveStore((s) => s.connectionState());
  const serverName = useLiveStore((s) => s.serverState?.server ?? "log-srv");

  const { data: unackedIssues } = useQuery({
    queryKey: ["issues", { acked: false, minLevel: "ERROR" }],
    queryFn: () => api.issues({ acked: false, minLevel: "ERROR" }),
    refetchInterval: 15_000,
  });
  const unackedCount = unackedIssues?.issues.length ?? 0;

  const ThemeIcon = theme === "dark" ? Moon : theme === "light" ? Sun : SunMoon;

  return (
    <header className="flex h-12 shrink-0 items-center gap-4 border-b border-border bg-bg-subtle px-4 text-sm">
      <span className="font-semibold">pm-log-ui</span>
      <span className="text-fg-subtle">{VERSION}</span>

      <span className="flex items-center gap-1.5">
        <span className={`h-2 w-2 rounded-full ${STATE_DOT[connectionState]}`} />
        {serverName} {STATE_LABEL[connectionState]}
      </span>

      <Link
        to="/alerts"
        className={
          unackedCount > 0
            ? "flex items-center gap-1 rounded bg-level-error/20 px-2 py-0.5 font-semibold text-level-error"
            : "flex items-center gap-1 text-fg-subtle"
        }
      >
        ⚠ {unackedCount} unacked
      </Link>

      <div className="ml-auto flex items-center gap-3">
        <button
          type="button"
          onClick={() => onThemeChange(cycleTheme(theme))}
          className="flex items-center gap-1 rounded p-1.5 hover:bg-bg-inset"
          title={`Theme: ${theme}`}
        >
          <ThemeIcon size={16} />
        </button>
      </div>
    </header>
  );
}
