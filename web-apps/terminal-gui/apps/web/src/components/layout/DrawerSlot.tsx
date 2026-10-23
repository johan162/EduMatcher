import { createContext } from "react";

/**
 * Where a drawer is drawn: an element of the shell that sits over the view
 * area and does not scroll with it. Null outside the shell (tests), where the
 * drawer renders in place.
 */
export const DrawerSlotContext = createContext<HTMLElement | null>(null);
