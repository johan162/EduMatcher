/**
 * Explain mode: the top-bar switch, and the hook the screens read. What it
 * shows is decided where the figure is drawn, e.g. the evidence banner's
 * line on what "checked, unanchored" proves.
 */
import { GraduationCap } from "lucide-react";
import { useExplainStore } from "@/store/useExplainStore";

export function useExplain(): boolean {
  return useExplainStore((s) => s.explain);
}

export function ExplainToggle() {
  const explain = useExplain();
  const setExplain = useExplainStore((s) => s.setExplain);
  return (
    <button
      type="button"
      aria-pressed={explain}
      onClick={() => setExplain(!explain)}
      title="Explain mode: show how each figure is made"
      className={`flex items-center gap-1 rounded px-1.5 py-0.5 ${
        explain ? "bg-accent/20 text-fg" : "text-fg-dim hover:text-fg"
      }`}
    >
      <GraduationCap size={14} aria-hidden="true" />
      Explain
    </button>
  );
}

/** A figure's explanation in words, under it, in Explain mode. */
export function ExplainLine({ children }: { children: string }) {
  const explain = useExplain();
  if (!explain) return null;
  return (
    <span data-explain className="max-w-[18rem] text-[11px] leading-snug text-fg-dim">
      {children}
    </span>
  );
}
