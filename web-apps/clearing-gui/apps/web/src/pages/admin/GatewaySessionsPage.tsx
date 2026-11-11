import { PageHeader } from "@/components/shared/Ui";
import { SessionsView } from "@/components/views/SessionsView";

/** Gateway Sessions (ADMIN): every gateway's connect/disconnect history. */
export function GatewaySessionsPage() {
  return (
    <>
      <PageHeader title="Gateway Sessions">When clearing saw each gateway connect and disconnect.</PageHeader>
      <SessionsView label="Gateway sessions" gatewayFilter />
    </>
  );
}
