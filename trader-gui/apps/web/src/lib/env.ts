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
