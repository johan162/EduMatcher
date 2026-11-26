/**
 * Who traded with whom (CG30, ADMIN Overview, Explain mode), from
 * `GET /clearing/flows`: the latest trading day as a buyer × seller grid,
 * each cell the value its row's gateway bought from its column's, shaded by
 * size and written in. Gateways are ordered by how much they traded; beyond
 * the 20 largest they are gathered as "others", while the pair list under
 * the grid keeps every pair. Gateway headers open the participant's drawer.
 */
import { DataTable, type Column } from "@/components/shared/DataTable";
import { useExplain } from "@/components/shared/Explain";
import { QueryState } from "@/components/shared/QueryState";
import { Panel } from "@/components/shared/Ui";
import { useFlows } from "@/api/queries";
import type { FlowPairT, FlowsT } from "@/api/schemas";
import { formatCurrency } from "@/lib/money";
import { gatewayColumn, qtyColumn } from "./columns";
import { GatewayId } from "./GatewayId";

const DRAWN = 20;
const OTHERS = "others";

const COLUMNS: Column<FlowPairT>[] = [
  gatewayColumn("buyer", "Buyer", (r) => r.buyer, "The gateway that bought"),
  gatewayColumn("seller", "Seller", (r) => r.seller, "The gateway that sold to it"),
  qtyColumn("trades", "Trades", (r) => r.trades, "Trades between the two that day"),
  qtyColumn("qty", "Qty", (r) => r.quantity, "Shares the buyer bought from the seller"),
  {
    id: "value",
    header: "Value",
    title: "Their value, every symbol converted, display currency",
    align: "right",
    cell: (r) => formatCurrency(r.value),
    sortValue: (r) => r.value,
  },
];

/** The drawn gateways, largest traded value first, and the grid's cells. */
export function flowGrid(pairs: FlowPairT[]): { gateways: string[]; hidden: number; cells: Map<string, number> } {
  const traded = new Map<string, number>();
  for (const p of pairs) {
    traded.set(p.buyer, (traded.get(p.buyer) ?? 0) + p.value);
    traded.set(p.seller, (traded.get(p.seller) ?? 0) + p.value);
  }
  const ranked = [...traded.entries()].sort((a, b) => b[1] - a[1] || (a[0] < b[0] ? -1 : 1)).map(([g]) => g);
  const drawn = new Set(ranked.slice(0, DRAWN));
  const hidden = ranked.length - drawn.size;
  const cells = new Map<string, number>();
  for (const p of pairs) {
    const key = `${drawn.has(p.buyer) ? p.buyer : OTHERS}\u0000${drawn.has(p.seller) ? p.seller : OTHERS}`;
    cells.set(key, (cells.get(key) ?? 0) + p.value);
  }
  return { gateways: hidden > 0 ? [...drawn, OTHERS] : [...drawn], hidden, cells };
}

function Header({ id }: { id: string }) {
  return id === OTHERS ? <>{OTHERS}</> : <GatewayId id={id} />;
}

function who(id: string): string {
  return id === OTHERS ? `every gateway beyond the ${DRAWN} largest` : id;
}

function Grid({ pairs }: { pairs: FlowPairT[] }) {
  const { gateways, cells } = flowGrid(pairs);
  const max = Math.max(0, ...cells.values());
  return (
    <div className="overflow-x-auto">
      <table className="border-collapse text-[11px]">
        <caption className="sr-only">Value bought, by buyer (rows) from seller (columns)</caption>
        <thead>
          <tr>
            <th
              scope="col"
              title="Each row is a buying gateway, each column a selling one"
              className="px-1 text-left font-normal text-fg-dim"
            >
              buyer \ seller
            </th>
            {gateways.map((g) => (
              <th key={g} scope="col" title={`What ${who(g)} sold, to each buyer`} className="px-1 font-mono font-normal">
                <Header id={g} />
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {gateways.map((buyer) => (
            <tr key={buyer}>
              <th scope="row" title={`What ${who(buyer)} bought, from each seller`} className="px-1 text-left font-mono font-normal">
                <Header id={buyer} />
              </th>
              {gateways.map((seller) => {
                const value = cells.get(`${buyer}\u0000${seller}`);
                return (
                  <td
                    key={seller}
                    className="num border border-line px-1 text-right"
                    style={value ? { backgroundColor: `rgb(var(--accent) / ${0.1 + 0.5 * (value / max)})` } : undefined}
                  >
                    {value ? formatCurrency(value) : ""}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function sentence(f: FlowsT): string {
  const gateways = new Set(f.pairs.flatMap((p) => [p.buyer, p.seller])).size;
  const scope = f.symbol ? ` in ${f.symbol}` : "";
  return `On ${f.trade_date}${scope}, ${gateways} gateways traded with each other in ${f.pairs.length} buyer–seller pairs.`;
}

export function FlowsPanel() {
  const explain = useExplain();
  const flows = useFlows(explain);
  if (!explain) return null;
  return (
    <Panel title="Who traded with whom">
      <QueryState query={flows} skeletonColumns={4}>
        {(f) => {
          if (f.trade_date === null) return <p className="text-xs">No trading day yet.</p>;
          if (!f.trades_retained) {
            return <p className="text-xs">{`Raw trades for ${f.trade_date} are no longer kept, so who traded with whom is not known.`}</p>;
          }
          if (f.pairs.length === 0) return <p className="text-xs">{`Nothing traded on ${f.trade_date}.`}</p>;
          const { hidden } = flowGrid(f.pairs);
          return (
            <div className="flex flex-col gap-2 text-xs">
              <p>
                {`${sentence(f)} Each cell is what the row's gateway bought from the column's. Clearing does not settle cell by cell: it nets each gateway's buys against its sells, so each gateway is left with one amount (see Netting).`}
                {hidden > 0 && ` The ${DRAWN} gateways that traded most are drawn; the other ${hidden} are gathered as ${OTHERS}.`}
              </p>
              <Grid pairs={f.pairs} />
              <DataTable caption="Trades by pair" columns={COLUMNS} rows={f.pairs} rowKey={(r) => `${r.buyer}\u0000${r.seller}`} />
            </div>
          );
        }}
      </QueryState>
    </Panel>
  );
}
