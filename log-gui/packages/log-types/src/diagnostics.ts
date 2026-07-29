/** Mirrors `edumatcher.log_cli.diagnose.Finding.to_dict()` (design §12). */

export interface DiagnosticFinding {
  heuristic: string;
  severity: "warning" | "error";
  message: string;
  recommendation: string;
  repro_command: string;
  details: Record<string, unknown>;
}

export const ALL_HEURISTICS = [
  "error_rate_spike",
  "repeated_warning",
  "process_silence",
  "clock_skew",
  "truncated_messages",
  "exception_clustering",
  "fallback_to_file",
] as const;

export type HeuristicName = (typeof ALL_HEURISTICS)[number];

export interface DiagnosticsResponse {
  ranAt: string;
  findings: DiagnosticFinding[];
  passedHeuristics: HeuristicName[];
}
