import { Navigate, Route, Routes } from "react-router-dom";
import { AppShell } from "./components/layout/AppShell.js";
import { useBookStream } from "./lib/useBookStream.js";
import { useBookStore } from "./store/useBookStore.js";
import { usePrefsStore } from "./store/usePrefsStore.js";
import { BookView } from "./views/BookView.js";

/** `/` opens the last book viewed, else the first listed symbol once the universe is known. */
function Home() {
  const lastSymbol = usePrefsStore((s) => s.lastSymbol);
  const first = useBookStore((s) => s.symbols[0]?.symbol);
  const target = lastSymbol ?? first;
  if (!target) return <p className="m-auto text-sm text-fg-subtle">Waiting for the symbol list…</p>;
  return <Navigate to={`/book/${target}`} replace />;
}

export default function App() {
  useBookStream();
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<Home />} />
        <Route path="book/:symbol" element={<BookView />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
