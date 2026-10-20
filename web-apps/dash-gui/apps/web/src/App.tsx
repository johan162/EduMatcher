import { Route, Routes } from "react-router-dom";
import { AppShell } from "./components/layout/AppShell.js";
import { useDashStream } from "./lib/ws.js";
import { DashboardView } from "./views/DashboardView.js";
import { BookDrawer } from "./views/drawers/BookDrawer.js";
import { ToDashboard } from "./views/drawers/common.js";
import { ParticipantDrawer } from "./views/drawers/ParticipantDrawer.js";
import { ProcessDrawer } from "./views/drawers/ProcessDrawer.js";
import { WidgetGallery } from "./views/WidgetGallery.js";

export default function App() {
  useDashStream();
  return (
    <Routes>
      {/* Unlinked: every widget with synthetic data, outside the live shell (WP-D2). */}
      <Route path="widgets" element={<WidgetGallery />} />
      <Route element={<AppShell />}>
        {/* The drawers (§12.4) are children, so opening one keeps the dashboard mounted and its history loaded. */}
        <Route element={<DashboardView />}>
          <Route index element={null} />
          {/* A splat: a key typed in with a raw "/" (pm-api-gwy/desk@host) works as well as an encoded one. */}
          <Route path="process/*" element={<ProcessDrawer />} />
          <Route path="participant/:id" element={<ParticipantDrawer />} />
          <Route path="book/:symbol" element={<BookDrawer />} />
        </Route>
        <Route path="*" element={<ToDashboard />} />
      </Route>
    </Routes>
  );
}
