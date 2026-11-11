import { PageHeader } from "@/components/shared/Ui";
import { ParticipantsTable } from "@/components/views/ParticipantsTable";

/** Participants (ADMIN): every gateway with a position row; open one to drill down. */
export function ParticipantsPage() {
  return (
    <>
      <PageHeader title="Participants">
        P&amp;L per participant gateway in display currency, refreshed with each clearing write (5 s).
      </PageHeader>
      <ParticipantsTable />
    </>
  );
}
