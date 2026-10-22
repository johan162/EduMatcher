/**
 * The connection indicator of the top bar (WP-UI05): a dot and a word, the
 * same in every web app. The file is copied unchanged into each app; the
 * colours are the `live`, `warning` and `offline` tokens each app declares.
 */

export type ConnectionBadgeState = "live" | "connecting" | "reconnecting" | "offline";

const LOOK: Record<ConnectionBadgeState, { dot: string; label: string }> = {
  live: { dot: "bg-live", label: "LIVE" },
  connecting: { dot: "bg-warning", label: "CONNECTING" },
  reconnecting: { dot: "bg-warning", label: "RECONNECTING" },
  offline: { dot: "bg-offline", label: "OFFLINE" },
};

export function ConnectionBadge({
  state,
  detail,
  title,
}: {
  state: ConnectionBadgeState;
  /** Where the data comes from, or why it is not live: shown after the word, dimmed. */
  detail?: string;
  title?: string;
}) {
  const { dot, label } = LOOK[state];
  return (
    <span data-testid="connection-badge" data-state={state} title={title} className="flex items-center gap-1.5">
      <span className={`h-2 w-2 rounded-full ${dot}`} aria-hidden="true" />
      <span className="text-xs font-semibold tracking-wider text-fg">{label}</span>
      {detail && <span className="text-xs text-fg opacity-60">{detail}</span>}
    </span>
  );
}
