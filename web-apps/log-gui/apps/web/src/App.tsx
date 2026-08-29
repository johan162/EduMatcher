import { Route, Routes } from "react-router-dom";
import { AppShell } from "./components/layout/AppShell.js";
import { useLogStream } from "./lib/useLogStream.js";
import { AlertsView } from "./views/Alerts.js";
import { DashboardView } from "./views/Dashboard.js";
import { DiagnosticsView } from "./views/Diagnostics.js";
import { ExplorerView } from "./views/Explorer.js";
import { HealthView } from "./views/Health.js";
import { ConnectionsView } from "./views/Connections.js";

export default function App() {
  useLogStream();

  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<DashboardView />} />
        <Route path="logs" element={<ExplorerView />} />
        <Route path="alerts" element={<AlertsView />} />
        <Route path="connections" element={<ConnectionsView />} />
        <Route path="diagnostics" element={<DiagnosticsView />} />
        <Route path="health" element={<HealthView />} />
      </Route>
    </Routes>
  );
}
