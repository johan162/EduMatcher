/**
 * EOD settlement and the derived balance, from pm-eod's ledger.
 *
 * Amounts are integer minor units of the display currency (`*_minor`) and go
 * through `formatMinor` only -- never the tick formatter. A settlement is the
 * transfer of a day's close-to-close P&L; the balance is the roster's opening
 * balance plus those settlements, computed by the API and not stored
 * anywhere. Neither is margin, collateral or a completed payment, and the
 * screen says so. Settlement data changes only when pm-eod runs, so nothing
 * here is polled.
 *
 * Three uses: the participant's own (`self`), an ADMIN drill-down (`gateway`
 * fixed) and the ADMIN venue view (`venue`: every account, filterable).
 */
import { useState } from "react";
import { DataTable, type Column } from "@/components/shared/DataTable";
import { FilterForm, filterDate, filterText, type FilterField, type FilterValues } from "@/components/shared/Filters";
import { QueryState } from "@/components/shared/QueryState";
import { Time } from "@/components/shared/Time";
import { Badge, MoreRows, Panel, Stat } from "@/components/shared/Ui";
import { useAccountOptions, useBalances, useSettlements } from "@/api/queries";
import type { BalanceRowT, EodRunT, SettlementRowT } from "@/api/schemas";
import { formatMinor, signClass } from "@/lib/money";
import { GatewayId } from "./GatewayId";
import { textColumn } from "./columns";
import { NettingPanel } from "./NettingPanel";
import { subject, teachingHint } from "./teaching";

const EXCHANGE = "EXCHANGE";

type Mode = "self" | "gateway" | "venue";

interface SettlementViewProps {
  mode: Mode;
  /** The gateway of a drill-down (`mode="gateway"`). */
  gateway?: string;
  /** Names the settlement table, e.g. "My settlements". */
  caption: string;
}

function direction(account: string, amount: number, mode: Mode): string {
  if (account === EXCHANGE) return "rounding residual";
  if (amount === 0) return "—";
  if (mode === "self") return amount > 0 ? "Exchange owes you" : "You owe the exchange";
  return amount > 0 ? "Exchange owes the gateway" : "Gateway owes the exchange";
}

/** `AAPL 25.0000000000002; MSFT 0` -- the unrounded per-symbol parts. */
function detailText(detail: Record<string, string>): string {
  return Object.entries(detail)
    .map(([symbol, value]) => `${symbol} ${value}`)
    .join("; ");
}

function runTone(status: string | null): "ok" | "bad" | "neutral" {
  if (status === null) return "neutral";
  return status === "ok" ? "ok" : "bad";
}

function settlementColumns(mode: Mode): Column<SettlementRowT>[] {
  return [
    textColumn("date", "Date", (r) => r.trade_date, "The trading day settled"),
    {
      id: "account",
      header: "Account",
      title: "The participant gateway settled with; EXCHANGE holds the rounding residual",
      cell: (r) => (r.account === EXCHANGE ? `${EXCHANGE} (rounding residual account)` : <GatewayId id={r.account} />),
      sortValue: (r) => r.account,
    },
    {
      id: "amount",
      header: "Amount",
      title: "The day's change in close-to-close P&L, rounded to 2 decimals of the display currency; positive: the exchange owes the account",
      align: "right",
      cell: (r) => <span className={signClass(r.amount_minor)}>{formatMinor(r.amount_minor)}</span>,
      sortValue: (r) => r.amount_minor,
    },
    textColumn("direction", "Direction", (r) => direction(r.account, r.amount_minor, mode), "Who owes whom, from the amount's sign"),
    {
      id: "run",
      header: "Run",
      title: "The status of the pm-eod run that settled the day",
      cell: (r) => <Badge tone={runTone(r.run_status)}>{r.run_status ?? "no run recorded"}</Badge>,
      sortValue: (r) => r.run_status,
    },
    textColumn("detail", "Per symbol (unrounded)", (r) => detailText(r.detail), "Each symbol's share of the amount, before rounding"),
  ];
}

const RUN_COLUMNS: Column<EodRunT>[] = [
  textColumn("date", "Trading day", (r) => r.trade_date, "The trading day pm-eod ran for"),
  {
    id: "status",
    header: "Status",
    title: "How the run ended: ok, or the failure pm-eod recorded",
    cell: (r) => <Badge tone={runTone(r.status)}>{r.status}</Badge>,
    sortValue: (r) => r.status,
  },
  {
    id: "finished",
    header: "Finished",
    title: "When the run finished, on the venue's clock",
    cell: (r) => <Time iso={r.finished_at} />,
    sortValue: (r) => Date.parse(r.finished_at),
  },
  textColumn(
    "steps",
    "Steps",
    (r) => (r.steps ? r.steps.map((s) => `${s.step}: ${s.status}${s.message ? ` — ${s.message}` : ""}`).join("; ") : null),
    "Each step of the run with its outcome (ADMIN only)",
  ),
];

function minorColumn(
  id: string,
  header: string,
  value: (r: BalanceRowT) => BalanceRowT["balance_minor"],
  title: string,
): Column<BalanceRowT> {
  return {
    id,
    header,
    title,
    align: "right",
    cell: (r) => <span className={signClass(value(r))}>{formatMinor(value(r))}</span>,
    sortValue: value,
  };
}

const BALANCE_COLUMNS: Column<BalanceRowT>[] = [
  {
    id: "account",
    header: "Account",
    title: "The participant gateway; EXCHANGE holds the rounding residual",
    cell: (r) => (r.account === EXCHANGE ? `${EXCHANGE} (rounding residual account)` : <GatewayId id={r.account} />),
    sortValue: (r) => r.account,
  },
  minorColumn("opening", "Opening balance", (r) => r.opening_balance_minor, "From pm-eod's roster; 0 when the account is not on it"),
  minorColumn("settled", "Settlements to date", (r) => r.settlement_total_minor, "Sum of the account's settlements up to the last settled day"),
  minorColumn("balance", "Derived balance", (r) => r.balance_minor, "Opening balance + settlements to date: derived here, not a stored balance"),
];

function SingleBalance({ gateway }: { gateway?: string }) {
  const [asOf, setAsOf] = useState<string | undefined>(undefined);
  const balances = useBalances({ gateway, as_of: asOf });
  return (
    <Panel title="Derived balance">
      <p className="text-xs text-fg-dim">
        Opening balance from pm-eod&apos;s roster plus every settlement up to the date: derived here, not a
        stored account balance.
      </p>
      <FilterForm
        label="Balance date"
        fields={[{ name: "as_of", label: "Balance as of", type: "date" }]}
        submitLabel="Show balance"
        onApply={(v) => setAsOf(filterDate(v["as_of"]))}
      />
      <QueryState query={balances} skeletonColumns={3} isEmpty={(d) => d.balances.length === 0} emptyTitle="No balance">
        {(d) => {
          const b = d.balances[0]!;
          return (
            <div className="flex flex-wrap gap-3">
              <Stat label="Opening balance" value={formatMinor(b.opening_balance_minor)} sub="from the roster" title="The account's starting balance in pm-eod's roster; 0 when it is not on it" />
              <Stat label="Settlements to date" value={formatMinor(b.settlement_total_minor)} sub={`to ${d.last_settled_date ?? "—"}`} title="Sum of the account's daily settlements up to the date" />
              <Stat label="Derived balance" value={formatMinor(b.balance_minor)} sub={d.as_of ? `as of ${d.as_of}` : "all settled days"} title="Opening balance + settlements to date: derived here, not a stored account balance, margin or collateral" />
            </div>
          );
        }}
      </QueryState>
    </Panel>
  );
}

function VenueBalances() {
  const balances = useBalances({});
  return (
    <Panel title="Derived balances">
      <QueryState query={balances} isEmpty={(d) => d.balances.length === 0} emptyTitle="No accounts">
        {(d) => (
          <>
            <p className="text-xs text-fg-dim">{`Through ${d.last_settled_date ?? "no settled day"}; opening balance plus settlements, derived here.`}</p>
            <DataTable caption="Balances" columns={BALANCE_COLUMNS} rows={d.balances} rowKey={(r) => r.account} />
          </>
        )}
      </QueryState>
    </Panel>
  );
}

const DATE_FIELDS: FilterField[] = [
  { name: "date", label: "Date", type: "date" },
  { name: "from", label: "From", type: "date" },
  { name: "to", label: "To", type: "date" },
];

export function SettlementView({ mode, gateway, caption }: SettlementViewProps) {
  const [filters, setFilters] = useState<FilterValues>({});
  const account = mode === "venue" ? filterText(filters["account"]) : gateway;
  const settlements = useSettlements({
    gateway: account,
    date: filterDate(filters["date"]),
    from: filterDate(filters["from"]),
    to: filterDate(filters["to"]),
  });
  const accounts = useAccountOptions(mode === "venue");
  const fields: FilterField[] =
    mode === "venue" ? [{ name: "account", label: "Account", type: "combobox", suggestions: accounts }, ...DATE_FIELDS] : DATE_FIELDS;
  return (
    <>
      <p className="mb-3 text-xs text-fg-dim">
        A settlement moves one trading day&apos;s change in close-to-close P&amp;L between the exchange and a gateway.
        It is not margin, collateral or a completed payment, and it exists only once pm-eod has settled the day.
        Amounts are in the display currency with 2 decimals.
      </p>
      {mode !== "venue" && <NettingPanel gateway={gateway} />}
      {mode === "venue" ? <VenueBalances /> : <SingleBalance gateway={gateway} />}
      <Panel title="Settlements">
        <FilterForm label="Settlement filters" fields={fields} onApply={setFilters} />
        <QueryState
          query={settlements}
          isEmpty={(d) => d.settlements.length === 0 && d.runs.length === 0}
          emptyTitle="No settlements"
          emptyHint={teachingHint(
            `pm-eod has not settled a day in this range: pm-eod settles each trading day after the close, moving the day's change in P&L between the exchange and ${subject(gateway, mode === "venue").you}.`,
            "Your End-of-Day Statement",
          )}
        >
          {(d) => (
            <>
              {d.settlements.length === 0 ? (
                <p className="text-xs text-fg-dim">No settlement in this range; the runs below say why.</p>
              ) : (
                <DataTable
                  caption={caption}
                  columns={settlementColumns(mode)}
                  rows={d.settlements}
                  rowKey={(r) => `${r.trade_date}/${r.account}`}
                />
              )}
              <MoreRows hasMore={d.has_more} count={d.count} />
              {d.runs.length > 0 && (
                <DataTable caption="EOD runs" columns={RUN_COLUMNS} rows={d.runs} rowKey={(r) => r.trade_date} />
              )}
            </>
          )}
        </QueryState>
      </Panel>
    </>
  );
}
