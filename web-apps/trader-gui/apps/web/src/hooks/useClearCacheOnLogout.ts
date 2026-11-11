import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useAuthStore } from "@/store/useAuthStore.js";

/**
 * Empties the query cache whenever the key goes (logout button, 401, dead WS
 * key), so no response of one login -- positions, fills, quotes -- can be
 * shown to the next login on the same tab (CG10). Query keys do not carry the
 * caller, so a cached entry is only safe for the login that fetched it.
 */
export function useClearCacheOnLogout(): void {
  const client = useQueryClient();
  const loggedIn = useAuthStore((s) => s.apiKey !== null);
  useEffect(() => {
    if (!loggedIn) client.clear();
  }, [loggedIn, client]);
}
