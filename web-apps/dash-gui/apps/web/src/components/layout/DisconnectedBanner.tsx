/**
 * The red banner under the top bar while the figures are not live (design
 * §12.2, D1.4): the bridge is unreachable, or pm-monitor is down. It says
 * when the data on screen froze -- the last snapshot's `ts` on the session
 * clock -- while the panels below dim.
 */

import { formatDateTime, formatTime } from "../../lib/time.js";
import { useDashStore } from "../../store/useDashStore.js";

export function DisconnectedBanner() {
  const socket = useDashStore((s) => s.socket);
  const monitor = useDashStore((s) => s.monitor);
  const ts = useDashStore((s) => s.snapshot?.ts);
  const tz = useDashStore((s) => s.sessionTz);

  let what: string;
  if (socket === "CLOSED") what = "pm-dash-bridge unreachable, reconnecting";
  else if (socket === "OPEN" && monitor === "DOWN") what = "pm-monitor down";
  else return null;

  return (
    <div role="alert" className="shrink-0 border-b border-error bg-error-bg px-4 py-1.5 text-sm font-semibold text-error">
      {what} —{" "}
      {ts ? (
        <span title={`${formatDateTime(ts, tz)} (${tz})`}>
          data frozen at <span className="tabular">{formatTime(ts, tz)}</span>
        </span>
      ) : (
        "no data yet"
      )}
    </div>
  );
}
