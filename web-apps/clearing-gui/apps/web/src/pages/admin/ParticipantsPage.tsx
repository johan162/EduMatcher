import { useEffect, useRef } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { PageHeader } from "@/components/shared/Ui";
import { ParticipantDrawer } from "@/components/views/ParticipantDrawer";
import { ParticipantsTable } from "@/components/views/ParticipantsTable";

/**
 * Participants (ADMIN): every gateway with a position row. `/participants/:id`
 * opens that participant in a drawer over this list (CG21); closing it
 * returns here with focus on the participant's row.
 */
export function ParticipantsPage() {
  const gatewayId = useParams()["gatewayId"]?.toUpperCase();
  const navigate = useNavigate();

  // When the drawer closes, focus goes back to the row it was opened from.
  const lastOpen = useRef<string | undefined>(undefined);
  useEffect(() => {
    if (lastOpen.current && !gatewayId) {
      const rows = document.querySelectorAll<HTMLElement>("[data-row-key]");
      [...rows].find((r) => r.dataset["rowKey"] === lastOpen.current)?.focus();
    }
    lastOpen.current = gatewayId;
  }, [gatewayId]);

  return (
    <>
      <PageHeader title="Participants">
        P&amp;L per participant gateway in display currency, refreshed with each clearing write (5 s).
      </PageHeader>
      <ParticipantsTable selected={gatewayId} />
      {gatewayId && <ParticipantDrawer gatewayId={gatewayId} onClose={() => navigate("/participants")} />}
    </>
  );
}
