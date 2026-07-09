import { create } from "zustand";
import {
  createBlankDraft,
  type Diagnostic,
  type EngineConfigDraft,
  type Persona,
} from "@edumatcher/schema";
import { evaluateDiagnostics } from "@edumatcher/diagnostics";

export type Theme = "light" | "dark";

const DRAFT_KEY = "edumatcher.config-gui.draft.v1";
const PERSONA_KEY = "edumatcher.config-gui.persona.v1";
const THEME_KEY = "edumatcher.config-gui.theme.v1";
const TOUR_KEY = "edumatcher.config-gui.tour-seen.v1";

interface StoredDraft {
  draft: EngineConfigDraft;
  savedAt: number;
}

function loadPersona(): Persona {
  const raw = localStorage.getItem(PERSONA_KEY);
  return raw === "INTERMEDIATE" || raw === "EXPERT" ? raw : "BEGINNER";
}

function loadTheme(): Theme {
  const raw = localStorage.getItem(THEME_KEY);
  if (raw === "light" || raw === "dark") return raw;
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function applyTheme(theme: Theme): void {
  document.documentElement.classList.toggle("dark", theme === "dark");
}

let saveTimer: ReturnType<typeof setTimeout> | undefined;
function scheduleAutosave(draft: EngineConfigDraft): void {
  if (saveTimer) clearTimeout(saveTimer);
  saveTimer = setTimeout(() => {
    const payload: StoredDraft = { draft, savedAt: Date.now() };
    try {
      localStorage.setItem(DRAFT_KEY, JSON.stringify(payload));
    } catch {
      /* storage full or unavailable — non-fatal for a local tool */
    }
  }, 500);
}

export function readAutosavedDraft(): StoredDraft | null {
  const raw = localStorage.getItem(DRAFT_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as StoredDraft;
  } catch {
    return null;
  }
}

interface DraftState {
  draft: EngineConfigDraft;
  persona: Persona;
  theme: Theme;
  diagnostics: Diagnostic[];
  /** Field paths to briefly highlight (set by "Jump →" from diagnostics). */
  highlightedPaths: string[];
  /** Sections preserved as unmapped passthrough from the last import. */
  unmappedSections: string[];
  /** One-time acknowledgement that warnings will be included on export. */
  warningsAcknowledged: boolean;

  update: (mutator: (draft: EngineConfigDraft) => void) => void;
  replaceDraft: (draft: EngineConfigDraft, unmapped?: string[]) => void;
  newDraft: () => void;
  setPersona: (persona: Persona) => void;
  toggleTheme: () => void;
  setHighlightedPaths: (paths: string[]) => void;
  acknowledgeWarnings: () => void;
}

function recompute(draft: EngineConfigDraft): Diagnostic[] {
  return evaluateDiagnostics(draft);
}

const initialDraft = createBlankDraft();

export const useDraftStore = create<DraftState>((set, get) => ({
  draft: initialDraft,
  persona: loadPersona(),
  theme: loadTheme(),
  diagnostics: recompute(initialDraft),
  highlightedPaths: [],
  unmappedSections: [],
  warningsAcknowledged: false,

  update: (mutator) => {
    const next = structuredClone(get().draft);
    mutator(next);
    scheduleAutosave(next);
    set({ draft: next, diagnostics: recompute(next), warningsAcknowledged: false });
  },

  replaceDraft: (draft, unmapped = []) => {
    scheduleAutosave(draft);
    set({
      draft,
      diagnostics: recompute(draft),
      unmappedSections: unmapped,
      warningsAcknowledged: false,
    });
  },

  newDraft: () => {
    const fresh = createBlankDraft();
    scheduleAutosave(fresh);
    set({
      draft: fresh,
      diagnostics: recompute(fresh),
      unmappedSections: [],
      warningsAcknowledged: false,
    });
  },

  setPersona: (persona) => {
    localStorage.setItem(PERSONA_KEY, persona);
    set({ persona });
  },

  toggleTheme: () => {
    const theme = get().theme === "dark" ? "light" : "dark";
    localStorage.setItem(THEME_KEY, theme);
    applyTheme(theme);
    set({ theme });
  },

  setHighlightedPaths: (paths) => set({ highlightedPaths: paths }),

  acknowledgeWarnings: () => set({ warningsAcknowledged: true }),
}));

/** Initialise theme class and (optionally) restore an autosaved draft. */
export function initStore(): void {
  applyTheme(useDraftStore.getState().theme);
}

export function hasSeenTour(): boolean {
  return localStorage.getItem(TOUR_KEY) === "1";
}

export function markTourSeen(): void {
  localStorage.setItem(TOUR_KEY, "1");
}
