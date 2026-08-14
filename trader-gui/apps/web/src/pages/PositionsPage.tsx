import { PositionPanel } from "@/components/orders/PositionPanel.js";

/**
 * Positions screen (§13.6, §14.4) — the shared Position Summary Panel with
 * per-row Flatten and Flatten All. Available to TRADER and MARKET_MAKER.
 */
export function PositionsPage() {
  return (
    <div className="p-4">
      <h1 className="text-lg font-semibold text-[#e8e8f0] mb-3">Positions</h1>
      <PositionPanel />
    </div>
  );
}
