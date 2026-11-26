/**
 * Gains and losses add up to zero (CG27, Explain mode): each gateway's total
 * P&L as a bar either side of a line, and their sum. Gateways trade with each
 * other, so one's gain is another's loss and the sum is zero, give or take
 * rounding; a sum that is not is shown as it is. The numbers are the
 * Participants table's.
 */
import { DivergingBars } from "@/components/shared/Bars";
import { useExplain } from "@/components/shared/Explain";
import { Panel } from "@/components/shared/Ui";
import type { ParticipantRowT } from "@/api/schemas";
import { formatCurrency } from "@/lib/money";

const DRAWN = 20;

export function PnlBalance({ rows, hasMore }: { rows: ParticipantRowT[]; hasMore: boolean }) {
  const explain = useExplain();
  if (!explain || rows.length === 0) return null;
  const sum = rows.reduce((total, r) => total + r.total_pnl, 0);
  const drawn = [...rows].sort((a, b) => Math.abs(b.total_pnl) - Math.abs(a.total_pnl)).slice(0, DRAWN);
  return (
    <Panel title="Gains and losses add up to zero">
      <p className="text-xs">
        {`Sum over all gateways: ${formatCurrency(sum)}${hasMore ? ` (the first ${rows.length} gateways)` : ""}. `}
        Gateways trade with each other, so every gain is someone else&apos;s loss: the total P&amp;L of all
        gateways is zero, give or take rounding.
        {rows.length > DRAWN && ` The ${DRAWN} largest are drawn.`} The table above has the numbers.
      </p>
      <DivergingBars
        leftLabel="loss"
        rightLabel="gain"
        rows={drawn.map((r) => ({
          key: r.gateway_id,
          label: r.gateway_id,
          left: r.total_pnl < 0 ? -r.total_pnl : 0,
          right: r.total_pnl > 0 ? r.total_pnl : 0,
        }))}
      />
    </Panel>
  );
}
