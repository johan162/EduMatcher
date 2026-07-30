import { Route, Routes } from "react-router-dom";
import { AppShell } from "./components/layout/AppShell.js";
import { useTerminalStream } from "./lib/useTerminalStream.js";
import { Placeholder } from "./views/Placeholder.js";
import { SessionView } from "./views/Session.js";

export default function App() {
  useTerminalStream();

  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<Placeholder title="Market overview" phase="Phase 6" />} />
        <Route path="symbol" element={<Placeholder title="Symbol detail" phase="Phase 7" />} />
        <Route path="index" element={<Placeholder title="Index" phase="Phase 8" />} />
        <Route path="tape" element={<Placeholder title="Trade tape" phase="Phase 8" />} />
        <Route path="movers" element={<Placeholder title="Movers" phase="Phase 8" />} />
        <Route path="session" element={<SessionView />} />
      </Route>
    </Routes>
  );
}
