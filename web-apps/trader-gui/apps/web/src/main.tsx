import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Toaster } from "sonner";
import App from "./App.js";
import { applyThemeToDocument, useThemeStore } from "./store/useThemeStore.js";
import "./index.css";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      staleTime: 30_000,
    },
  },
});

// Apply the stored theme before first paint and on every change. Done here,
// not in AppShell, so the login page (which has no top bar) follows it too.
applyThemeToDocument(useThemeStore.getState().theme);
useThemeStore.subscribe((s) => applyThemeToDocument(s.theme));

function ThemedToaster() {
  const theme = useThemeStore((s) => s.theme);
  return <Toaster position="bottom-right" theme={theme} richColors closeButton duration={5000} />;
}

const root = document.getElementById("root");
if (!root) throw new Error("No #root element found");

createRoot(root).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <App />
        <ThemedToaster />
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
);
