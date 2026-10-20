/**
 * Opening and closing a drawer (design §12.4, D4.1): each is a navigation
 * that keeps the query string, so the time range survives both and a
 * drawer's URL is the incident view to paste.
 */

import { useCallback } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { drawerPath, type DrawerKind } from "../lib/links.js";

export function useOpenDrawer(): (kind: DrawerKind, id: string) => void {
  const navigate = useNavigate();
  const { search } = useLocation();
  return useCallback((kind, id) => navigate({ pathname: drawerPath(kind, id), search }), [navigate, search]);
}

export function useCloseDrawer(): () => void {
  const navigate = useNavigate();
  const { search } = useLocation();
  return useCallback(() => navigate({ pathname: "/", search }), [navigate, search]);
}
