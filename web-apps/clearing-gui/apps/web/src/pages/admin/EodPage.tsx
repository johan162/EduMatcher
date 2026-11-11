import { PageHeader } from "@/components/shared/Ui";
import { SettlementView } from "@/components/views/SettlementView";

/** EOD Settlement (ADMIN): every account's settlements, balances and pm-eod's runs. */
export function EodPage() {
  return (
    <>
      <PageHeader title="EOD Settlement">
        pm-eod&apos;s daily settlements per account. The rows of a day sum to zero; EXCHANGE holds the rounding
        residual.
      </PageHeader>
      <SettlementView mode="venue" caption="Settlements" />
    </>
  );
}
