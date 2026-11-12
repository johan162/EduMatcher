import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import App from "./App";
import { ContractError, isForbidden } from "./api/errors";
import { applyFontSizeToDocument, useFontSizeStore } from "./store/useFontSizeStore";
import "./index.css";

/**
 * One retry: a transient 503 (a ledger briefly locked by a write) should not
 * flash an error, but a refused or broken request must not be hammered.
 * Polling and caching are set per query (api/queries.ts).
 */
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: (failures, error) => failures < 1 && !isForbidden(error) && !(error instanceof ContractError),
    },
  },
});

// Zoom-based font size from the settings popover, before first paint and on change.
applyFontSizeToDocument(useFontSizeStore.getState().fontSize);
useFontSizeStore.subscribe((s) => applyFontSizeToDocument(s.fontSize));

const root = document.getElementById("root");
if (!root) throw new Error("No #root element found");

createRoot(root).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
);
