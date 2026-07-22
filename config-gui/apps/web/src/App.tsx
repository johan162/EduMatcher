import { useEffect, useState } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { AppShell } from "@/components/layout/AppShell";
import { ConfirmDialog } from "@/components/ui/Dialog";
import { readAutosavedDraft, useDraftStore } from "@/store/draftStore";
import { BasicsTab } from "@/tabs/BasicsTab";
import { SessionsTab } from "@/tabs/SessionsTab";
import { RiskTab } from "@/tabs/RiskTab";
import { CircuitBreakersTab } from "@/tabs/CircuitBreakersTab";
import { MarketMakerTab } from "@/tabs/MarketMakerTab";
import { SymbolsTab } from "@/tabs/SymbolsTab";
import { IndicesTab } from "@/tabs/IndicesTab";
import { CombosTab } from "@/tabs/CombosTab";
import { GatewaysTab } from "@/tabs/GatewaysTab";
import { EngineTuningTab } from "@/tabs/EngineTuningTab";
import { ReviewTab } from "@/tabs/ReviewTab";

export default function App() {
  const replaceDraft = useDraftStore((s) => s.replaceDraft);
  const [restorePrompt, setRestorePrompt] = useState(false);
  const [restorable, setRestorable] = useState<ReturnType<typeof readAutosavedDraft>>(null);

  useEffect(() => {
    const saved = readAutosavedDraft();
    if (saved && (saved.draft.symbolOrder.length > 0 || saved.draft.gateways.length > 0)) {
      setRestorable(saved);
      setRestorePrompt(true);
    }
  }, []);

  return (
    <>
      <Routes>
        <Route element={<AppShell />}>
          <Route index element={<Navigate to="/basics" replace />} />
          <Route path="/basics" element={<BasicsTab />} />
          <Route path="/sessions" element={<SessionsTab />} />
          <Route path="/risk" element={<RiskTab />} />
          <Route path="/circuit-breakers" element={<CircuitBreakersTab />} />
          <Route path="/market-maker" element={<MarketMakerTab />} />
          <Route path="/symbols" element={<SymbolsTab />} />
          <Route path="/indices" element={<IndicesTab />} />
          <Route path="/combos" element={<CombosTab />} />
          <Route path="/gateways" element={<GatewaysTab />} />
          <Route path="/engine-tuning" element={<EngineTuningTab />} />
          <Route path="/review" element={<ReviewTab />} />
          <Route path="*" element={<Navigate to="/basics" replace />} />
        </Route>
      </Routes>

      <ConfirmDialog
        open={restorePrompt}
        onOpenChange={setRestorePrompt}
        title="Restore previous draft?"
        description="An autosaved draft from a previous session was found in this browser. Restore it, or start fresh."
        confirmLabel="Restore"
        cancelLabel="Start fresh"
        onConfirm={() => {
          if (restorable) replaceDraft(restorable.draft);
        }}
      />
    </>
  );
}
