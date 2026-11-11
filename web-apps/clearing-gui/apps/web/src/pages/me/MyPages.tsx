/**
 * The participant's own clearing screens (TRADER and MARKET_MAKER). None of
 * them names a gateway: the API scopes every request to the logged-in one.
 */
import { PageHeader } from "@/components/shared/Ui";
import { HistoryView } from "@/components/views/HistoryView";
import { PositionsView } from "@/components/views/PositionsView";
import { SessionsView } from "@/components/views/SessionsView";
import { SettlementView } from "@/components/views/SettlementView";
import { TradesView } from "@/components/views/TradesView";

export function MyPositionsPage() {
  return (
    <>
      <PageHeader title="My Positions">Current positions at their marks, as clearing last committed them.</PageHeader>
      <PositionsView label="My" />
    </>
  );
}

export function MyTradesPage() {
  return (
    <>
      <PageHeader title="My Trades">The executions clearing holds for your gateway, newest first.</PageHeader>
      <TradesView label="My" />
    </>
  );
}

export function MyHistoryPage() {
  return (
    <>
      <PageHeader title="Daily & Close History">
        What you traded each day, and your position and P&amp;L at every session close.
      </PageHeader>
      <HistoryView />
    </>
  );
}

export function MySettlementPage() {
  return (
    <>
      <PageHeader title="EOD Settlement">Your daily settlement amounts and the balance they add up to.</PageHeader>
      <SettlementView mode="self" caption="My settlements" />
    </>
  );
}
export function MySessionsPage() {
  return (
    <>
      <PageHeader title="Gateway Sessions">When clearing saw your gateway connect and disconnect.</PageHeader>
      <SessionsView label="My gateway sessions" />
    </>
  );
}
