/**
 * Stub for the five views still to be built.
 *
 * Design §7.3 wants all six destinations reachable from the first release so
 * the tab row never shifts under the viewer. A tab that navigates to an
 * honest "not built yet" is better than one that is missing, or worse, present
 * but dead.
 */

import { Panel } from "../components/Panel.js";

export function Placeholder({ title, phase }: { title: string; phase: string }) {
  return (
    <div className="mx-auto max-w-6xl">
      <Panel title={title}>
        <p className="py-8 text-center text-sm text-fg-faint">Not built yet — arrives in {phase}.</p>
      </Panel>
    </div>
  );
}
