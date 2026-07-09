import type { EngineConfigDraft, MinPersona, Persona } from "@edumatcher/schema";
import { personaMeets } from "@edumatcher/schema";

export interface TabDef {
  id: string;
  path: string;
  label: string;
  minPersona: MinPersona;
  /** Optional predicate; tab is only shown when this returns true. */
  showWhen?: (draft: EngineConfigDraft) => boolean;
}

export const TABS: TabDef[] = [
  { id: "basics", path: "/basics", label: "Basics", minPersona: "B" },
  { id: "sessions", path: "/sessions", label: "Sessions & Schedule", minPersona: "B" },
  { id: "risk", path: "/risk", label: "Risk & Collars", minPersona: "B" },
  { id: "circuit-breakers", path: "/circuit-breakers", label: "Circuit Breakers", minPersona: "B" },
  {
    id: "market-maker",
    path: "/market-maker",
    label: "Market Maker",
    minPersona: "B",
    showWhen: (draft) => draft.gateways.some((g) => g.role === "MARKET_MAKER"),
  },
  { id: "symbols", path: "/symbols", label: "Symbols", minPersona: "I" },
  { id: "indices", path: "/indices", label: "Indices", minPersona: "I" },
  { id: "combos", path: "/combos", label: "Combos", minPersona: "E" },
  { id: "gateways", path: "/gateways", label: "Auxiliary Gateways", minPersona: "I" },
  { id: "review", path: "/review", label: "Review & Export", minPersona: "B" },
];

export function visibleTabs(persona: Persona, draft: EngineConfigDraft): TabDef[] {
  return TABS.filter(
    (tab) => personaMeets(persona, tab.minPersona) && (tab.showWhen?.(draft) ?? true),
  );
}

export function tabById(id: string): TabDef | undefined {
  return TABS.find((tab) => tab.id === id);
}
