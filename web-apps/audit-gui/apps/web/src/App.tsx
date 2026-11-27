import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Navigate, Route, Routes } from "react-router-dom";
import { AppShell } from "@/components/layout/AppShell";
import { WORKSPACES } from "@/lib/workspaces";
import { LoginPage } from "@/pages/LoginPage";
import { MarketPage } from "@/pages/MarketPage";
import { NotInRelease, OverviewPage } from "@/pages/WorkspacePage";
import { useAuthStore } from "@/store/useAuthStore";

/** On logout (the button, or a 401), drop every cached response. */
function useClearCacheOnLogout() {
  const client = useQueryClient();
  const loggedIn = useAuthStore((s) => s.apiKey !== null);
  useEffect(() => {
    if (!loggedIn) client.clear();
  }, [loggedIn, client]);
}

export default function App() {
  useClearCacheOnLogout();
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route element={<AppShell />}>
        <Route index element={<Navigate to="/overview" replace />} />
        <Route path="/overview" element={<OverviewPage />} />
        <Route path="/market" element={<MarketPage />} />
        {WORKSPACES.filter((w) => !w.built).map((w) => (
          <Route key={w.path} path={w.path} element={<NotInRelease workspace={w} />} />
        ))}
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
