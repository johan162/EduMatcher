/**
 * The snapshot the tests build on: one captured from a running exchange
 * (the mini profile on s10-basic, two traders, WP-D3), so the rows are
 * tested on what pm-monitor really sends. Each call returns a fresh copy,
 * with `exchange` merged and anything else replaced by `overrides`.
 */

import type { HealthSnapshot } from "@edumatcher/dash-types";
import captured from "./snapshot.json";

export const CAPTURED = captured as unknown as HealthSnapshot;

export function fixtureSnapshot(overrides: Partial<Omit<HealthSnapshot, "exchange">> & { exchange?: Partial<HealthSnapshot["exchange"]> } = {}): HealthSnapshot {
  const base = structuredClone(CAPTURED);
  const { exchange, ...rest } = overrides;
  return { ...base, ...rest, exchange: { ...base.exchange, ...exchange } };
}
