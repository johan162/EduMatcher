import { useEffect, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { ApiError, apiFetch } from "@/api/apiFetch.js";
import { hydrateFromBootstrap } from "@/lib/bootstrap.js";
import { useAuthStore } from "@/store/useAuthStore.js";
import { env } from "@/lib/env.js";
import { Loader2, KeyRound } from "lucide-react";
import type { BootstrapAdmin, BootstrapTrader, StatusResponse } from "@/types/index.js";

/**
 * Probe with the candidate key passed explicitly rather than through
 * `useAuthStore`. Storing it first would flip the app to "authenticated" with
 * a guessed role, and `useWebSocketManager` would open three sockets against
 * a key that may turn out to be invalid. `apiFetch` merges `init.headers`
 * last, so this override wins over the store-derived header.
 */
function withKey(key: string): RequestInit {
  return { headers: { Authorization: `Bearer ${key}` } };
}

/**
 * Login (§7.2).
 *
 * `GET /status` is the login probe rather than `/symbols` because it returns
 * `gateway_role` in the same call, so role-aware routing needs no second
 * round-trip. `GET /bootstrap/{role}` then hydrates the stores before the
 * WebSockets open.
 *
 * The key lives in memory only (§7.1) — never localStorage/sessionStorage. A
 * page reload therefore returns here, which is intentional for a classroom
 * system on localhost.
 */
export function LoginPage() {
  const navigate = useNavigate();
  const login = useAuthStore((s) => s.login);
  const authed = useAuthStore((s) => s.apiKey !== null);

  const [key, setKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Already authenticated (e.g. back-navigation): go to the role landing.
  useEffect(() => {
    if (authed) navigate("/", { replace: true });
  }, [authed, navigate]);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    const trimmed = key.trim();
    if (!trimmed || busy) return;
    setBusy(true);
    setError(null);

    try {
      const status = await apiFetch<StatusResponse>("/api/v1/status", withKey(trimmed));
      const role = status.gateway_role;
      if (role !== "TRADER" && role !== "MARKET_MAKER" && role !== "ADMIN") {
        throw new ApiError(403, "ROLE_UNSUPPORTED", `Unsupported role: ${String(role)}`);
      }

      const bootstrap =
        role === "ADMIN"
          ? await apiFetch<BootstrapAdmin>("/api/v1/bootstrap/admin", withKey(trimmed))
          : await apiFetch<BootstrapTrader>("/api/v1/bootstrap/trader", withKey(trimmed));

      hydrateFromBootstrap(bootstrap);
      if (bootstrap.incomplete.length > 0) {
        console.warn("[login] bootstrap incomplete:", bootstrap.incomplete);
      }
      // Last: this is what opens the WebSockets and unblocks the AppShell.
      login(trimmed, bootstrap.gateway_id ?? "", role, status.gateway_count);
      navigate("/", { replace: true });
    } catch (err) {
      setError(describeLoginError(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex items-center justify-center h-screen bg-[#0a0a0f] text-[#e8e8f0]">
      <form
        onSubmit={onSubmit}
        className="w-[380px] bg-[#12121a] border border-[#2a2a45] rounded-lg p-6 shadow-xl"
      >
        <div className="mb-6">
          <h1 className="font-mono font-bold text-lg">EduMatcher</h1>
          <p className="text-xs text-[#505070]">
            {env("VITE_APP_TITLE", "EduMatcher Trading")} · pm-trading-ui
          </p>
        </div>

        <label htmlFor="api-key" className="block text-xs text-[#9090b0] mb-1">
          API key
        </label>
        <div className="relative">
          <KeyRound size={14} className="absolute left-2 top-1/2 -translate-y-1/2 text-[#505070]" />
          <input
            id="api-key"
            type="password"
            autoFocus
            autoComplete="off"
            spellCheck={false}
            value={key}
            onChange={(e) => setKey(e.target.value)}
            placeholder="key-gw01-…"
            aria-invalid={error !== null}
            aria-describedby={error ? "login-error" : undefined}
            className="w-full bg-[#1a1a28] border border-[#2a2a45] rounded pl-7 pr-2 py-2 font-mono text-sm focus:outline-none focus:border-[#3a3a60]"
          />
        </div>

        {error && (
          <p id="login-error" role="alert" className="mt-2 text-xs text-ask">
            {error}
          </p>
        )}

        <button
          type="submit"
          disabled={busy || key.trim() === ""}
          className="mt-5 w-full flex items-center justify-center gap-2 bg-bid text-black font-medium text-sm rounded py-2 disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {busy && <Loader2 size={14} className="animate-spin" />}
          {busy ? "Connecting…" : "Connect"}
        </button>

        <p className="mt-4 text-[10px] text-[#505070] leading-relaxed">
          The key is held in memory for this tab only and is never written to browser storage.
          Reloading the page requires re-entering it.
        </p>
      </form>
    </div>
  );
}

function describeLoginError(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 401 || err.status === 403) return "Invalid API key.";
    if (err.status === 503) {
      return "Gateway reached, but the engine did not answer. Is pm-engine running?";
    }
    return `${err.code}: ${err.message}`;
  }
  // fetch() rejects (rather than resolving non-ok) when the gateway is down.
  return "Cannot reach the API gateway. Is pm-api-gwy running?";
}
