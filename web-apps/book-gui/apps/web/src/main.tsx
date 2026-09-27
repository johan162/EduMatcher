import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App.js";
import { applyThemeToDocument, usePrefsStore } from "./store/usePrefsStore.js";
import { applyFontSizeToDocument, useFontSizeStore } from "./store/useFontSizeStore.js";
import "./index.css";

// Apply the stored theme and font size before first paint, as terminal-gui does.
applyThemeToDocument(usePrefsStore.getState().theme);
applyFontSizeToDocument(useFontSizeStore.getState().fontSize);
useFontSizeStore.subscribe((s) => applyFontSizeToDocument(s.fontSize));

const rootEl = document.getElementById("root");
if (!rootEl) throw new Error("root element missing");

createRoot(rootEl).render(
  <StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </StrictMode>,
);
