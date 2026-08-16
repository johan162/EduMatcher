/** Shared diagnostic type produced by the cross-field rule engine (design §8). */

export type DiagnosticSeverity = "info" | "warning" | "error";

export interface Diagnostic {
  /** Stable rule id, e.g. "undefined-risk-level". Mirrors warnings.py ids where one exists. */
  id: string;
  severity: DiagnosticSeverity;
  message: string;
  /** One or more field paths this diagnostic links (for cross-field highlighting). */
  fieldPaths: string[];
  /** Which tab to jump to. */
  tab: string;
}

/** Worst-severity ranking helper: error > warning > info. */
export const SEVERITY_RANK: Record<DiagnosticSeverity, number> = {
  info: 1,
  warning: 2,
  error: 3,
};
