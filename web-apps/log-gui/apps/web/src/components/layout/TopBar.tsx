/** Top bar (design §7.2): source status, unacked badge, session indicator (WP-UI01), theme toggle. */

import { Moon, Sun } from "lucide-react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ConnectionBadge, type ConnectionBadgeState } from "../ConnectionBadge.js";
import { SettingsPopover } from "../shared/SettingsPopover.js";
import { SessionIndicator } from "../SessionIndicator.js";
import { api } from "../../lib/api.js";
import { useUiConfig } from "../../lib/useUiConfig.js";
import type { ThemePreference } from "../../lib/theme.js";
import { useLiveStore, type SourceState } from "../../store/useLiveStore.js";
import appVersion from "../../version.json";

/** Icon shown is the theme a click will switch *to*, not the active one. */
const NEXT_THEME_ICON: Record<ThemePreference, typeof Moon> = {
  dark: Sun,
  light: Moon,
};

const STATE_BADGE: Record<SourceState, { state: ConnectionBadgeState; cause: string }> = {
  LIVE: { state: "live", cause: "" },
  RECONNECTING: { state: "reconnecting", cause: "" },
  LOG_SERVER_DOWN: { state: "offline", cause: "log server down" },
  HISTORY_UNAVAILABLE: { state: "offline", cause: "log.db unavailable" },
};

export function TopBar({
  theme,
  onThemeChange,
}: {
  theme: ThemePreference;
  onThemeChange: () => void;
}) {
  const connectionState = useLiveStore((s) => s.connectionState());
  const serverName = useLiveStore((s) => s.serverState?.server ?? "log-srv");
  const session = useLiveStore((s) => s.marketSession);

  const uiConfig = useUiConfig();
  const alertLevel = uiConfig?.alertLevel;
  const { data: unackedIssues } = useQuery({
    queryKey: ["issues", { acked: false, minLevel: alertLevel }],
    queryFn: () => api.issues({ acked: false, minLevel: alertLevel }),
    // Waits for the configured level rather than guessing ERROR: a badge
    // computed from the wrong threshold is worse than a badge one tick late.
    enabled: alertLevel !== undefined,
    refetchInterval: 15_000,
  });
  const unackedCount = unackedIssues?.issues.length ?? 0;

  const badge = STATE_BADGE[connectionState];
  const ThemeIcon = NEXT_THEME_ICON[theme];

  return (
    <header className="flex h-12 shrink-0 items-center gap-4 border-b border-border bg-bg-subtle px-4 text-sm">
      <span className="flex items-baseline gap-2">
        <span className="font-mono font-bold text-sm text-fg">EduMatcher</span>
        <span className="font-mono text-xs text-accent">pm-log</span>
        <span className="font-mono text-xs text-brand-version">v{appVersion.version}</span>
      </span>

      <Link
        to="/alerts"
        className={
          unackedCount > 0
            ? "flex items-center gap-1 rounded bg-level-error-bg px-2 py-0.5 font-semibold text-level-error"
            : "flex items-center gap-1 text-fg-subtle"
        }
      >
        ⚠ {unackedCount} unacked
      </Link>

      <SessionIndicator
        state={session?.state ?? null}
        nextState={session?.nextState ?? null}
        nextAt={session?.nextAt ?? null}
        timeZone={uiConfig?.timezone ?? "UTC"}
      />

      <div className="ml-auto flex items-center gap-3">
        <button
          type="button"
          onClick={onThemeChange}
          className="flex items-center gap-1 rounded p-1.5 hover:bg-bg-inset"
          title={`Theme: ${theme}`}
        >
          <ThemeIcon size={16} />
        </button>

        <SettingsPopover />

        <ConnectionBadge
          state={badge.state}
          detail={badge.cause ? `${serverName} · ${badge.cause}` : serverName}
          title="Whether pm-log-srv, the process that collects every log line, is alive. LIVE: it is publishing its heartbeat. OFFLINE: it announced a shutdown or its heartbeat stopped, or the log database cannot be read; the numbers then show only what was stored before."
        />
      </div>
    </header>
  );
}
