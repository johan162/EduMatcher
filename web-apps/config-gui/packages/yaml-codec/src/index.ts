import type { EngineConfigDraft } from "@edumatcher/schema";
import { buildConfigDocument } from "./build.js";
import { renderYaml, type RenderOptions } from "./renderer.js";

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
  const document = buildConfigDocument(draft);
  const renderOptions: RenderOptions = {
    command: options.command ?? "config-gui (interactive)",
    generatedVersion: options.generatedVersion ?? "1.0.0-gui",
    generatedDate: options.generatedDate ?? new Date().toISOString().slice(0, 10),
    includeDefaultFieldComments: draft.output.commentDefaultFields,
  };
  return renderYaml(document, renderOptions);
}
