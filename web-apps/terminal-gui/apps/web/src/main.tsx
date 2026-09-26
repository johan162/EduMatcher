import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";
import App from "./App.js";
import { applyThemeToDocument, usePrefsStore } from "./store/usePrefsStore.js";
import { applyFontSizeToDocument, useFontSizeStore } from "./store/useFontSizeStore.js";
import "./index.css";

// Apply the stored theme before first paint, so a light-theme user does not
// see a dark flash on every load.
applyThemeToDocument(usePrefsStore.getState().theme);

// Same pattern, for the zoom-based font-size preference (settings popover).
applyFontSizeToDocument(useFontSizeStore.getState().fontSize);
useFontSizeStore.subscribe((s) => applyFontSizeToDocument(s.fontSize));

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      refetchOnWindowFocus: true,
    },
  },
});

const rootEl = document.getElementById("root");
if (!rootEl) throw new Error("root element missing");

createRoot(rootEl).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
);
