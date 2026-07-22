/**
 * Renders a plain engine_config document to YAML text.
 *
 * Ported from `src/edumatcher/config_gen/renderer.py`: same section ordering,
 * header block, top-level/inline hint comments, and the market_maker_quotes
 * fill-in warning. js-yaml is configured (`noArrayIndent`, `lineWidth: -1`) to
 * emit PyYAML-style block sequences.
 *
 * MAINTENANCE: keep aligned with renderer.py.
 */

import yaml from "js-yaml";
import type { PlainConfig } from "./build.js";
import { buildDefaultEngineFieldCommentLines } from "./defaultFieldComments.js";

export interface RenderOptions {
  command: string;
  generatedVersion: string;
  generatedDate: string;
  includeDefaultFieldComments: boolean;
}

const SECTION_ORDER: Array<[string, string[]]> = [
  ["Session control", ["sessions_enabled"]],
  ["Engine behavior", ["enforce_collars", "enforce_circuit_breakers"]],
  ["Engine tuning", ["engine_tuning"]],
  ["Market-maker obligation defaults", ["mm_obligation_defaults"]],
  ["Collar profiles", ["risk_controls"]],
  ["Circuit-breaker ladder", ["circuit_breaker_defaults"]],
  ["ALF gateway allowlist", ["gateways"]],
  ["RALF post-trade gateway", ["post_trade_gateway"]],
  ["CALF market-data gateway", ["market_data_gateway"]],
  ["REST API gateways", ["api_gateways"]],
  ["Symbol universe", ["symbols"]],
  ["Startup market-maker combo seeds", ["market_maker_combos"]],
  ["Session schedule", ["schedule"]],
];

const TOP_LEVEL_HINTS: Record<string, string[]> = {
  sessions_enabled: [
    "true lets pm-scheduler drive session transitions;",
    "false keeps the engine in continuous mode",
  ],
  enforce_collars: ["enables per-symbol collar checks on incoming orders"],
  enforce_circuit_breakers: ["enables per-symbol circuit-breaker enforcement"],
  engine_tuning: ["runtime retention and throttling knobs with memory/latency trade-offs"],
  mm_obligation_defaults: ["default market-maker obligation settings"],
  risk_controls: ["collar profiles by risk level"],
  circuit_breaker_defaults: ["circuit-breaker ladder definitions"],
  gateways: ["ALF gateway allowlist"],
  post_trade_gateway: ["RALF post-trade gateway settings"],
  api_gateways: ["REST/WebSocket API gateway process settings"],
  market_data_gateway: ["CALF market-data gateway settings"],
  symbols: ["symbol universe"],
  market_maker_combos: ["startup market-maker combo seeds"],
  schedule: ["session schedule"],
};

const INLINE_HINTS: Record<string, string[]> = {
  "bid_price: null": ["REQUIRED: set display bid price (e.g. 209.00)"],
  "ask_price: null": ["REQUIRED: set display ask price (e.g. 211.00)"],
  "last_buy_price: null": ["REQUIRED: set last buy reference price"],
  "last_sell_price: null": ["REQUIRED: set last sell reference price"],
  "halt_duration_ns: null": ["null = rest-of-day halt"],
};

const ENGINE_TUNING_HINTS: Record<string, string[]> = {
  snapshot_interval_sec: ["seconds between book snapshot publications for dirty books"],
  quote_history_maxlen: ["per-gateway RECENT/ALL quote history retained in memory"],
  drop_copy_buffer_size: ["drop-copy replay messages retained in memory"],
  recent_trades_maxlen: ["recent trades retained per symbol snapshot"],
  depth_snapshot_tolerance_ticks: [
    "depth window around last trade in ticks; larger values publish more depth",
  ],
};

function dumpBlock(payload: PlainConfig): string {
  return yaml.dump(payload, {
    sortKeys: false,
    noArrayIndent: true,
    lineWidth: -1,
    quotingType: '"',
    forceQuotes: false,
  });
}

function commentLines(indent: number, hints: string[]): string[] {
  const prefix = " ".repeat(indent) + "# ";
  return hints.map((h) => `${prefix}${h}`);
}

function indentOf(line: string): number {
  return line.length - line.trimStart().length;
}

/** Inject operator-facing hint comments into serialised YAML (port of renderer._annotate). */
function annotate(dumped: string): string[] {
  const source = dumped.split("\n");
  const out: string[] = [];
  let idx = 0;
  let inEngineTuning = false;
  while (idx < source.length) {
    const line = source[idx]!;
    const stripped = line.trim();
    const indent = indentOf(line);

    if (indent === 0 && stripped) {
      inEngineTuning = stripped === "engine_tuning:";
    }

    if (indent === 0) {
      const key = stripped.split(":", 1)[0]!;
      const hint = TOP_LEVEL_HINTS[key];
      if (hint !== undefined) {
        out.push(...commentLines(indent, hint));
        out.push(line);
        idx += 1;
        continue;
      }
    }

    if (inEngineTuning && indent === 2) {
      const key = stripped.split(":", 1)[0]!;
      const hint = ENGINE_TUNING_HINTS[key];
      if (hint !== undefined) {
        out.push(...commentLines(indent, hint));
        out.push(line);
        idx += 1;
        continue;
      }
    }

    if (stripped === "market_maker_quotes:") {
      out.push(line);
      let blockEnd = idx + 1;
      while (blockEnd < source.length) {
        const candidate = source[blockEnd]!;
        const candidateIndent = indentOf(candidate);
        if (
          candidate.trim() &&
          (candidateIndent < indent ||
            (candidateIndent === indent && !candidate.trimStart().startsWith("-")))
        ) {
          break;
        }
        blockEnd += 1;
      }
      let hasNull = false;
      for (let look = idx + 1; look < blockEnd; look += 1) {
        const t = source[look]!.trim();
        if (t === "bid_price: null" || t === "ask_price: null") {
          hasNull = true;
          break;
        }
      }
      if (hasNull) {
        out.push(
          " ".repeat(indent + 2) +
            "# WARNING: pm-config-gen cannot set prices. Fill these in before starting.",
        );
      }
      idx += 1;
      continue;
    }

    const suffix = INLINE_HINTS[stripped];
    if (suffix !== undefined) {
      out.push(...commentLines(indent, suffix));
      out.push(line);
      idx += 1;
      continue;
    }

    out.push(line);
    idx += 1;
  }
  return out;
}

function dumpAndAnnotate(payload: PlainConfig): string {
  return annotate(dumpBlock(payload)).join("\n");
}

export function renderYaml(config: PlainConfig, options: RenderOptions): string {
  const lines: string[] = [
    `# Generated by pm-config-gen v${options.generatedVersion} on ${options.generatedDate}`,
    `# Command: ${options.command}`,
    "#",
    "# Validate with:",
    "#   poetry run python -c 'from pathlib import Path; \\",
    "#     from edumatcher.engine.config_loader import load_engine_config; \\",
    '#     print(load_engine_config(Path("engine_config.yaml")))\'',
    "",
  ];

  if (options.includeDefaultFieldComments) {
    lines.push("# Defaultable engine_config fields and default values:");
    for (const entry of buildDefaultEngineFieldCommentLines()) {
      if (entry === "#" || entry === "") {
        lines.push("#");
      } else {
        lines.push(`#   ${entry}`);
      }
    }
    lines.push("");
  }

  const emittedKeys = new Set<string>();
  for (const [title, keys] of SECTION_ORDER) {
    const block: PlainConfig = {};
    for (const k of keys) {
      if (k in config) block[k] = config[k];
    }
    if (Object.keys(block).length === 0) continue;
    lines.push(`# -- ${title} --`);
    lines.push(dumpAndAnnotate(block).replace(/\s+$/, ""));
    lines.push("");
    for (const k of Object.keys(block)) emittedKeys.add(k);
  }

  const remaining: PlainConfig = {};
  for (const [k, v] of Object.entries(config)) {
    if (!emittedKeys.has(k)) remaining[k] = v;
  }
  if (Object.keys(remaining).length > 0) {
    lines.push("# -- Additional fields --");
    lines.push(dumpAndAnnotate(remaining).replace(/\s+$/, ""));
    lines.push("");
  }

  return lines.join("\n").replace(/\s+$/, "") + "\n";
}
