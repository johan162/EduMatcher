import type { EngineConfigDraft, MinPersona, Persona } from "@edumatcher/schema";
import { personaMeets } from "@edumatcher/schema";

export interface TabDef {
  id: string;
  path: string;
  label: string;
  minPersona: MinPersona;
  /**
   * Optional predicate; when it returns true the tab still appears in the
   * nav (once the persona qualifies) but is shown greyed out and disabled
   * rather than hidden, with `disabledHint` explaining why.
   */
  disabledWhen?: (draft: EngineConfigDraft) => boolean;
  /** Shown as the disabled tab's tooltip / a11y label when disabledWhen is true. */
  disabledHint?: string;
}

export const TABS: TabDef[] = [
  { id: "basics", path: "/basics", label: "Basics", minPersona: "B" },
  { id: "sessions", path: "/sessions", label: "Sessions & Schedule", minPersona: "B" },
  { id: "risk", path: "/risk", label: "Risk & Collars", minPersona: "I" },
  { id: "circuit-breakers", path: "/circuit-breakers", label: "Circuit Breakers", minPersona: "I" },
  {
    id: "market-maker",
    path: "/market-maker",
    label: "Market Maker",
    minPersona: "B",
    disabledWhen: (draft) => !draft.gateways.some((g) => g.role === "MARKET_MAKER"),
    disabledHint: "Add a MARKET_MAKER gateway to configure market-maker obligations and quote seeding.",
  },
  { id: "symbols", path: "/symbols", label: "Symbols", minPersona: "I" },
  { id: "indices", path: "/indices", label: "Indices", minPersona: "I" },
  { id: "combos", path: "/combos", label: "Combos", minPersona: "E" },
  { id: "gateways", path: "/gateways", label: "Auxiliary Gateways", minPersona: "I" },
  { id: "engine-tuning", path: "/engine-tuning", label: "Engine Tuning", minPersona: "E" },
  { id: "review", path: "/review", label: "Review & Export", minPersona: "B" },
];

export function visibleTabs(persona: Persona, draft: EngineConfigDraft): TabDef[] {
  return TABS.filter((tab) => personaMeets(persona, tab.minPersona));
}

export function isTabDisabled(tab: TabDef, draft: EngineConfigDraft): boolean {
  return tab.disabledWhen?.(draft) ?? false;
}

export function tabById(id: string): TabDef | undefined {
  return TABS.find((tab) => tab.id === id);
}
