/**
 * Safe Vite environment variable accessor.
 * Returns the env value in a Vite build context, or `fallback` elsewhere
 * (e.g. in Vitest's Node environment where `import.meta.env` is undefined).
 */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const _env: Record<string, string> = (import.meta as any)?.env ?? {};

export function env(key: string, fallback = ""): string {
  return _env[key] ?? fallback;
}

/**
 * Integer-valued environment accessor.
 * Falls back to `fallback` when unset, non-numeric, or non-positive — a
 * mistyped `VITE_MAX_FOCUS_SYMBOLS=abc` must not collapse the focus set to
 * `NaN` (which compares false against every bound and silently disables the
 * cap).
 */
export function envInt(key: string, fallback: number): number {
  const raw = _env[key];
  if (raw === undefined || raw === "") return fallback;
  const n = Number.parseInt(raw, 10);
  return Number.isFinite(n) && n > 0 ? n : fallback;
}
