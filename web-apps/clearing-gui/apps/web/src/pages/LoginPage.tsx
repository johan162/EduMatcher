import { useEffect, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { KeyRound, Loader2 } from "lucide-react";
import { apiFetch } from "@/api/apiFetch";
import { ApiError, NetworkError } from "@/api/errors";
import { Status } from "@/api/schemas";
import { landingPath } from "@/router/RoleGuard";
import { useAuthStore, type Role } from "@/store/useAuthStore";

const ROLES: readonly string[] = ["TRADER", "MARKET_MAKER", "ADMIN"];

/**
 * Login with an API key, probed with `GET /api/v1/status`, which answers the
 * gateway id and its engine role in one call. The key is passed to the probe
 * explicitly and stored only once it has proved valid, and only in memory
 * (useAuthStore), so a reload asks for it again.
 */
export function LoginPage() {
  const navigate = useNavigate();
  const login = useAuthStore((s) => s.login);
  const role = useAuthStore((s) => s.role);
  const [key, setKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Already logged in (back navigation): go to the role's landing page.
  useEffect(() => {
    if (role) navigate(landingPath(role), { replace: true });
  }, [role, navigate]);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    const candidate = key.trim();
    if (!candidate || busy) return;
    setBusy(true);
    setError(null);
    try {
      const status = await apiFetch("/api/v1/status", Status, { apiKey: candidate });
      if (!ROLES.includes(status.gateway_role)) {
        throw new ApiError(403, "ROLE_UNSUPPORTED", `Unsupported role: ${status.gateway_role}`);
      }
      const gotRole = status.gateway_role as Role;
      login(candidate, status.gateway_id, gotRole);
      navigate(landingPath(gotRole), { replace: true });
    } catch (err) {
      setError(describeLoginError(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="flex h-screen items-center justify-center bg-app text-fg">
      <form onSubmit={onSubmit} className="w-[400px] rounded-lg border border-line bg-panel p-6 shadow-xl">
        <h1 className="font-mono text-lg font-bold">EduMatcher Clearing</h1>
        <p className="mb-6 text-xs text-fg-dim">Read-only positions, P&amp;L and settlement · pm-clearing-ui</p>
        <label htmlFor="api-key" className="mb-1 block text-xs text-fg-dim">
          API key
        </label>
        <div className="relative">
          <KeyRound size={14} aria-hidden="true" className="absolute left-2 top-1/2 -translate-y-1/2 text-fg-faint" />
          <input
            id="api-key"
            type="password"
            autoFocus
            autoComplete="off"
            spellCheck={false}
            value={key}
            onChange={(e) => setKey(e.target.value)}
            aria-invalid={error !== null}
            aria-describedby={error ? "login-error" : undefined}
            className="w-full rounded border border-line bg-raised py-2 pl-7 pr-2 font-mono text-sm"
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
          className="mt-5 flex w-full items-center justify-center gap-2 rounded bg-accent py-2 text-sm font-medium text-accent-fg disabled:cursor-not-allowed disabled:opacity-40"
        >
          {busy && <Loader2 size={14} className="animate-spin" aria-hidden="true" />}
          Connect
        </button>
        <p className="mt-4 text-[11px] leading-relaxed text-fg-faint">
          Use the key of your trading gateway (or an ADMIN gateway). Read-only keys have no clearing
          data. The key is kept in memory for this tab only.
        </p>
      </form>
    </main>
  );
}

/** Only a 401 means the key is unknown; a 403 is a known key that is refused. */
export function describeLoginError(err: unknown): string {
  if (err instanceof NetworkError) return "Cannot reach the API gateway. Is pm-api-gwy running?";
  if (err instanceof ApiError) {
    if (err.status === 401) return "Invalid API key.";
    if (err.code === "READ_ONLY") return "This is a read-only key: it has no clearing data.";
    if (err.status === 503) return "Gateway reached, but the engine did not answer. Is pm-engine running?";
    return `${err.code}: ${err.message}`;
  }
  return err instanceof Error ? err.message : "Login failed.";
}
