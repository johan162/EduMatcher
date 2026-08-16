import { personaMeets, type MinPersona } from "@edumatcher/schema";
import { useDraftStore } from "@/store/draftStore";

/** Returns the current persona plus a `canSee(min)` view-filter helper. */
export function usePersona() {
  const persona = useDraftStore((s) => s.persona);
  return {
    persona,
    canSee: (min: MinPersona) => personaMeets(persona, min),
  };
}
