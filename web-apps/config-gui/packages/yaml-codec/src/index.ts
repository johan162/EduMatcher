import { SPLIT_FILES, type EngineConfigDraft } from "@edumatcher/schema";
import { buildConfigDocument, credentialPayload } from "./build.js";
import { renderCredentialsFile, renderIncludeFile, renderYaml, type RenderOptions } from "./renderer.js";

export * from "./build.js";
export * from "./renderer.js";
export * from "./parse.js";
export { buildDefaultEngineFieldCommentLines } from "./defaultFieldComments.js";

export interface GenerateOptions {
  generatedVersion?: string;
  generatedDate?: string;
  /** Optional human-readable command summary for the header comment. */
  command?: string;
}

/**
 * Full draft -> canonical engine_config.yaml text. Convenience wrapper over
 * buildConfigDocument + renderYaml used by the backend generate endpoint.
 */
export function generateYaml(
  draft: EngineConfigDraft,
  options: GenerateOptions = {},
): string {
  return renderYaml(buildConfigDocument(draft), renderOptions(draft, options));
}

function renderOptions(draft: EngineConfigDraft, options: GenerateOptions): RenderOptions {
  return {
    command: options.command ?? "config-gui (interactive)",
    generatedVersion: options.generatedVersion ?? "1.0.0-gui",
    generatedDate: options.generatedDate ?? new Date().toISOString().slice(0, 10),
    includeDefaultFieldComments: draft.output.commentDefaultFields,
  };
}

export interface GeneratedFile {
  name: string;
  text: string;
}

/**
 * The files to download: the main file, then, with
 * `draft.output.splitIncludes`, symbols.yaml and participants.yaml (listed
 * under `include:` in the main file), then each API gateway credentials
 * file. The engine merges them all back into the config
 * `generateYaml(inlineCredentials(draft))` writes as one file.
 */
export function generateFiles(
  draft: EngineConfigDraft,
  options: GenerateOptions = {},
): GeneratedFile[] {
  const name = draft.output.filename || "engine_config.yaml";
  const document = buildConfigDocument(draft);
  const opts = renderOptions(draft, options);
  const files: GeneratedFile[] = [];
  if (!draft.output.splitIncludes) {
    files.push({ name, text: renderYaml(document, opts) });
  } else {
    files.push({ name, text: renderYaml(document, { ...opts, included: SPLIT_FILES }) });
    for (const [key, file] of Object.entries(SPLIT_FILES)) {
      files.push({ name: file, text: renderIncludeFile(document, key, opts.generatedVersion, opts.generatedDate) });
    }
  }
  // Gateways sharing a file each read all of it, so it is written once, from
  // the first; diagnostics flag sharers whose credentials differ.
  const written = new Set<string>();
  for (const gw of draft.apiGateways) {
    if (gw.credentialsFile === undefined || written.has(gw.credentialsFile)) continue;
    written.add(gw.credentialsFile);
    files.push({
      name: gw.credentialsFile,
      text: renderCredentialsFile(credentialPayload(gw), opts.generatedVersion, opts.generatedDate),
    });
  }
  return files;
}

/** The draft with every API gateway's credentials written inline, as the engine sees them. */
export function inlineCredentials(draft: EngineConfigDraft): EngineConfigDraft {
  return {
    ...draft,
    apiGateways: draft.apiGateways.map(({ credentialsFile: _file, ...gw }) => gw),
  };
}
