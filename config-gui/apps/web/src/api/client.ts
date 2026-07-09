import type { Diagnostic, EngineConfigDraft } from "@edumatcher/schema";

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(path, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    let detail = "";
    try {
      detail = JSON.stringify(await res.json());
    } catch {
      detail = res.statusText;
    }
    const error = new Error(`Request to ${path} failed (${res.status}): ${detail}`);
    (error as { status?: number }).status = res.status;
    throw error;
  }
  return (await res.json()) as T;
}

export interface ImportResponse {
  draft: EngineConfigDraft;
  unmapped: string[];
}

export function importYaml(yaml: string): Promise<ImportResponse> {
  return postJson<ImportResponse>("/api/config/import", { yaml });
}

export function generate(
  draft: EngineConfigDraft,
  filename?: string,
): Promise<{ yaml: string; filename: string }> {
  return postJson("/api/config/generate", { draft, filename });
}

export function validate(draft: EngineConfigDraft): Promise<{ diagnostics: Diagnostic[] }> {
  return postJson("/api/config/validate", { draft });
}

export interface VerifyResponse {
  available: boolean;
  exitCode: number | null;
  report: unknown;
  raw: string;
}

export async function verify(
  yaml: string,
): Promise<{ ok: true; result: VerifyResponse } | { ok: false; message: string }> {
  try {
    const result = await postJson<VerifyResponse>("/api/config/verify", { yaml });
    return { ok: true, result };
  } catch (err) {
    const status = (err as { status?: number }).status;
    if (status === 503) {
      return {
        ok: false,
        message:
          "pm-cverifier is not available on this deployment. The GUI's own diagnostics still apply.",
      };
    }
    return { ok: false, message: err instanceof Error ? err.message : "Verification failed." };
  }
}
