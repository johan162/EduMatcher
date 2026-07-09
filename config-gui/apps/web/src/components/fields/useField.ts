import { useEffect, useRef } from "react";
import type { Diagnostic, DiagnosticSeverity } from "@edumatcher/schema";
import { SEVERITY_RANK } from "@edumatcher/schema";
import { useDraftStore } from "@/store/draftStore";

export interface FieldStatus {
  severity: DiagnosticSeverity | null;
  messages: string[];
  linked: boolean;
}

/** Diagnostics and highlight state for a given field path. */
export function useFieldStatus(path: string | undefined): FieldStatus {
  const diagnostics = useDraftStore((s) => s.diagnostics);
  const highlighted = useDraftStore((s) => s.highlightedPaths);

  if (!path) return { severity: null, messages: [], linked: false };

  const matching: Diagnostic[] = diagnostics.filter((d) => d.fieldPaths.includes(path));
  let severity: DiagnosticSeverity | null = null;
  for (const d of matching) {
    if (!severity || SEVERITY_RANK[d.severity] > SEVERITY_RANK[severity]) {
      severity = d.severity;
    }
  }
  return {
    severity,
    messages: matching.map((d) => d.message),
    linked: highlighted.includes(path),
  };
}

/** Attaches a flash animation to an element when its path is highlighted. */
export function useFlashOnHighlight(path: string | undefined) {
  const highlighted = useDraftStore((s) => s.highlightedPaths);
  const ref = useRef<HTMLDivElement>(null);
  const active = path ? highlighted.includes(path) : false;

  useEffect(() => {
    if (active && ref.current) {
      const el = ref.current;
      el.classList.remove("field-flash");
      // Force reflow so the animation restarts on repeated jumps.
      void el.offsetWidth;
      el.classList.add("field-flash");
      el.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }, [active]);

  return ref;
}
