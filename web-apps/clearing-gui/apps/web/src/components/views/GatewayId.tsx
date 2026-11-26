/**
 * A gateway id as it appears in a table. For ADMIN it links to that
 * participant's drawer (`/participants/:id`, over the Participants screen);
 * a participant has no drill-down, so it sees plain text. EXCHANGE, the
 * settlement rounding account, is not a participant and never links.
 */
import { Link } from "react-router-dom";
import { useAuthStore } from "@/store/useAuthStore";

export function participantPath(gatewayId: string): string {
  return `/participants/${encodeURIComponent(gatewayId)}`;
}

export function GatewayId({ id }: { id: string | null }) {
  const admin = useAuthStore((s) => s.role === "ADMIN");
  if (id === null) return <>—</>;
  if (!admin || id === "EXCHANGE") return <>{id}</>;
  return (
    <Link to={participantPath(id)} className="text-link hover:underline">
      {id}
    </Link>
  );
}
