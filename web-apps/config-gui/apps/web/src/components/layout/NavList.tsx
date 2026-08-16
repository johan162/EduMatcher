import clsx from "clsx";
import { NavLink } from "react-router-dom";
import {
  DEFAULT_DEPTH_SNAPSHOT_TOLERANCE_TICKS,
  DEFAULT_DROP_COPY_BUFFER_SIZE,
  DEFAULT_QUOTE_HISTORY_MAXLEN,
  DEFAULT_RECENT_TRADES_MAXLEN,
  DEFAULT_SNAPSHOT_INTERVAL_SEC,
  type EngineConfigDraft,
} from "@edumatcher/schema";
import { useDraftStore } from "@/store/draftStore";
import { visibleTabs, type TabDef } from "@/lib/tabs";

type Glyph = "error" | "warning" | "ok" | "none";

const MANDATORY = new Set(["basics", "sessions", "risk", "circuit-breakers", "review"]);

function isConfigured(draft: EngineConfigDraft, tabId: string): boolean {
  switch (tabId) {
    case "basics":
      return draft.symbolOrder.length > 0 && draft.gateways.length > 0;
    case "sessions":
      return draft.sessionsEnabled;
    case "risk":
      return (
        draft.riskControls.globalStaticBandPct !== undefined ||
        Object.keys(draft.riskControls.levels).length > 0
      );
    case "circuit-breakers":
      return draft.enforceCircuitBreakers;
    case "market-maker":
      return draft.seeding.mmMidRange !== undefined || draft.mmObligationDefaults.enforceMmObligation;
    case "symbols":
      return Object.values(draft.symbols).some(
        (s) => s.level || s.collar || s.circuitBreaker || s.marketMaker || s.outstandingShares !== undefined,
      );
    case "indices":
      return draft.indices.length > 0;
    case "combos":
      return draft.combos.length > 0;
    case "gateways":
      return (
        draft.postTradeGateway.enabled ||
        draft.marketDataGateway.enabled ||
        draft.balfGateway.enabled ||
        draft.apiGateways.length > 0
      );
    case "engine-tuning":
      return (
        draft.snapshotIntervalSec !== DEFAULT_SNAPSHOT_INTERVAL_SEC ||
        draft.quoteHistoryMaxlen !== DEFAULT_QUOTE_HISTORY_MAXLEN ||
        draft.dropCopyBufferSize !== DEFAULT_DROP_COPY_BUFFER_SIZE ||
        draft.recentTradesMaxlen !== DEFAULT_RECENT_TRADES_MAXLEN ||
        draft.depthSnapshotToleranceTicks !== DEFAULT_DEPTH_SNAPSHOT_TOLERANCE_TICKS
      );
    case "review":
      return true;
    default:
      return false;
  }
}

function glyphFor(draft: EngineConfigDraft, tab: TabDef, diagnostics: ReturnType<typeof useDraftStore.getState>["diagnostics"]): Glyph {
  const tabDiags = diagnostics.filter((d) => d.tab === tab.id);
  if (tabDiags.some((d) => d.severity === "error")) return "error";
  if (tabDiags.some((d) => d.severity === "warning")) return "warning";
  if (isConfigured(draft, tab.id) || MANDATORY.has(tab.id)) return "ok";
  return "none";
}

const GLYPH_META: Record<Glyph, { char: string; className: string; label: string }> = {
  error: { char: "✗", className: "text-error", label: "has errors" },
  warning: { char: "!", className: "text-warning", label: "has warnings" },
  ok: { char: "✓", className: "text-success", label: "complete" },
  none: { char: "—", className: "text-optional-default", label: "not configured" },
};

export function NavList() {
  const persona = useDraftStore((s) => s.persona);
  const draft = useDraftStore((s) => s.draft);
  const diagnostics = useDraftStore((s) => s.diagnostics);
  const tabs = visibleTabs(persona, draft);

  return (
    <nav aria-label="Configuration sections" className="flex flex-col gap-0.5 p-3">
      {tabs.map((tab) => {
        const glyph = glyphFor(draft, tab, diagnostics);
        const meta = GLYPH_META[glyph];
        return (
          <NavLink
            key={tab.id}
            to={tab.path}
            className={({ isActive }) =>
              clsx(
                "flex items-center justify-between rounded-md px-3 py-2 text-sm",
                isActive ? "bg-accent text-accent-fg" : "hover:bg-muted",
              )
            }
          >
            {({ isActive }) => (
              <>
                <span>{tab.label}</span>
                <span
                  className={clsx("ml-2 font-semibold", isActive ? "text-accent-fg" : meta.className)}
                  aria-label={meta.label}
                  title={meta.label}
                >
                  {meta.char}
                </span>
              </>
            )}
          </NavLink>
        );
      })}
    </nav>
  );
}
