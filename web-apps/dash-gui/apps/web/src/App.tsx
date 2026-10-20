import { Navigate, Route, Routes } from "react-router-dom";
import { AppShell } from "./components/layout/AppShell.js";
import { useDashStream } from "./lib/ws.js";
import { DashboardView } from "./views/DashboardView.js";
import { WidgetGallery } from "./views/WidgetGallery.js";

export default function App() {
  useDashStream();
  return (
    <Routes>
      {/* Unlinked: every widget with synthetic data, outside the live shell (WP-D2). */}
      <Route path="widgets" element={<WidgetGallery />} />
      <Route element={<AppShell />}>
        <Route index element={<DashboardView />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
