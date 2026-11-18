/** The live tail's mark for rows it did not receive (L038). */

import type { GapMarker } from "../store/useLiveStore.js";

export function gapText(gap: GapMarker): string {
  switch (gap.reason) {
    case "dropped":
      return `${gap.lost ?? "some"} rows not received (the log server shed them for this viewer)`;
    case "msg_no":
      return "rows not received (a message from the log server was lost)";
    case "restart":
      return "log server restarted: rows from the restart may be missing";
  }
}

export function GapMarkerRow({ gap }: { gap: GapMarker }) {
  return (
    <div
      data-gap={gap.reason}
      className="flex items-center gap-2 border-l-2 border-level-warning bg-bg-inset px-2 font-mono text-xs text-level-warning"
    >
      ⋯ {gapText(gap)} — switch to history to read them from log.db
    </div>
  );
}
