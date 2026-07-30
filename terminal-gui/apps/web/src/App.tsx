import { Route, Routes } from "react-router-dom";
import { AppShell } from "./components/layout/AppShell.js";
import { useTerminalStream } from "./lib/useTerminalStream.js";
import { OverviewView } from "./views/Overview.js";
import { Placeholder } from "./views/Placeholder.js";
import { SymbolDetailView } from "./views/SymbolDetail.js";
import { SessionView } from "./views/Session.js";

export default function App() {
  useTerminalStream();

  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<OverviewView />} />
        <Route path="symbol" element={<SymbolDetailView />} />
        <Route path="symbol/:sym" element={<SymbolDetailView />} />
        <Route path="index" element={<Placeholder title="Index" phase="Phase 8" />} />
        <Route path="tape" element={<Placeholder title="Trade tape" phase="Phase 8" />} />
        <Route path="movers" element={<Placeholder title="Movers" phase="Phase 8" />} />
        <Route path="session" element={<SessionView />} />
      </Route>
    </Routes>
  );
}
