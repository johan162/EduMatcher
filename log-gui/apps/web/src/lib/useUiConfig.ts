/**
 * Bridge-owned settings, fetched once.
 *
 * Deliberately has no fallback values. A local default here is how the
 * frontend and the bridge drifted apart in the first place — the bridge
 * parsed ISSUES_ALERT_LEVEL and PROCESS_SILENCE_SEC while the UI used its own
 * hard-coded constants, so the environment variables did nothing. Callers
 * render a neutral placeholder until this resolves instead.
 */

import { useQuery } from "@tanstack/react-query";
import type { UiConfig } from "@edumatcher/log-types";
import { api } from "./api.js";

export function useUiConfig(): UiConfig | undefined {
  const { data } = useQuery({
    queryKey: ["ui-config"],
    queryFn: api.uiConfig,
    // Bridge config is fixed for the process's lifetime; refetching it would
    // be pure noise.
    staleTime: Infinity,
    gcTime: Infinity,
  });
  return data;
}
