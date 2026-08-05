import { Route, Routes } from "react-router-dom";
import { AppShell } from "./components/layout/AppShell.js";
import { useTerminalStream } from "./lib/useTerminalStream.js";
import { OverviewView } from "./views/Overview.js";
import { Placeholder } from "./views/Placeholder.js";
import { SymbolDetailView } from "./views/SymbolDetail.js";
import { IndexView } from "./views/IndexView.js";
import { MoversView } from "./views/Movers.js";
import { TradeTapeView } from "./views/TradeTape.js";
import { SessionView } from "./views/Session.js";

export default function App() {
  useTerminalStream();

  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<OverviewView />} />
        <Route path="symbol" element={<SymbolDetailView />} />
        <Route path="symbol/:sym" element={<SymbolDetailView />} />
        <Route path="index" element={<IndexView />} />
        <Route path="tape" element={<TradeTapeView />} />
        <Route path="movers" element={<MoversView />} />
        <Route path="session" element={<SessionView />} />
      </Route>
    </Routes>
  );
}
