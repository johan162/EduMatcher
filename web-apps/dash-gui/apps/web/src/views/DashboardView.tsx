/** The dashboard (design §12.3). WP-C1 scaffold: the rows arrive in WP-D3. */

import { useDashStore } from "../store/useDashStore.js";

export function DashboardView() {
  const connection = useDashStore((s) => s.connection());
  return (
    <section aria-label="Dashboard" className="m-auto text-center text-sm text-fg-subtle">
      <p>The dashboard rows arrive here.</p>
      {connection === "NO_MONITOR" && (
        <p className="mt-2">Waiting for pm-monitor — no health snapshot is arriving.</p>
      )}
    </section>
  );
}
