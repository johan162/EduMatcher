import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { z } from "zod";
import { ROUTE_SCHEMAS } from "@/api/schemas";
import { examples } from "./helpers";

/**
 * The GUI's Zod schemas against the released REST contract (as in
 * clearing-gui). Every route the GUI reads must parse the contract's
 * example, and each schema must declare exactly the contract's fields with
 * the same required/optional split, so a field added, renamed or dropped on
 * either side fails here instead of rendering a blank or a wrong zero.
 */
const OPENAPI = path.resolve(__dirname, "../../../../../spec/rest/openapi.json");

interface OpenApiSchema {
  $ref?: string;
  type?: string;
  anyOf?: OpenApiSchema[];
  items?: OpenApiSchema;
  properties?: Record<string, OpenApiSchema>;
  required?: string[];
}

interface OpenApi {
  paths: Record<string, Record<string, { responses: Record<string, unknown> }>>;
  components: { schemas: Record<string, OpenApiSchema> };
}

const doc = JSON.parse(readFileSync(OPENAPI, "utf-8")) as OpenApi;

function resolve(schema: OpenApiSchema): OpenApiSchema {
  let s = schema;
  while (s.$ref) s = doc.components.schemas[s.$ref.split("/").pop()!]!;
  return s;
}

function nonNull(schema: OpenApiSchema): OpenApiSchema {
  const s = resolve(schema);
  if (s.anyOf) return resolve(s.anyOf.find((b) => b.type !== "null")!);
  return s;
}

function unwrap(schema: z.ZodType): z.ZodType {
  let s = schema;
  while (s instanceof z.ZodOptional || s instanceof z.ZodNullable || s instanceof z.ZodDefault) {
    s = (s instanceof z.ZodDefault ? s.def.innerType : s.unwrap()) as z.ZodType;
  }
  return s;
}

function compare(where: string, zod: z.ZodType, api: OpenApiSchema): string[] {
  const inner = unwrap(zod);
  const target = nonNull(api);
  if (inner instanceof z.ZodArray) {
    return target.items ? compare(`${where}[]`, inner.element as z.ZodType, target.items) : [];
  }
  if (!(inner instanceof z.ZodObject) || !target.properties) return [];
  const shape = inner.shape as Record<string, z.ZodType>;
  const zodKeys = Object.keys(shape).sort();
  const apiKeys = Object.keys(target.properties).sort();
  if (zodKeys.join() !== apiKeys.join()) {
    return [`${where}: GUI ${zodKeys.join(",")} vs contract ${apiKeys.join(",")}`];
  }
  const problems: string[] = [];
  const required = new Set(target.required ?? []);
  for (const key of zodKeys) {
    const optional = shape[key] instanceof z.ZodOptional || shape[key] instanceof z.ZodDefault;
    if (optional === required.has(key)) {
      problems.push(`${where}.${key}: optional in one, required in the other`);
    }
    problems.push(...compare(`${where}.${key}`, shape[key]!, target.properties[key]!));
  }
  return problems;
}

function okSchema(route: string): OpenApiSchema {
  const op = doc.paths[route]?.["get"];
  expect(op, `${route} is not in the contract`).toBeDefined();
  const ok = op!.responses["200"] as { content: { "application/json": { schema: OpenApiSchema } } };
  return ok.content["application/json"].schema;
}

describe("GUI schemas match the released REST contract", () => {
  const routes = Object.keys(ROUTE_SCHEMAS);

  it("reads the routes R0 needs", () => {
    expect(routes.sort()).toEqual([
      "/api/v1/audit/collections",
      "/api/v1/audit/events",
      "/api/v1/audit/findings",
      "/api/v1/audit/market/{symbol}/heatmap",
      "/api/v1/audit/market/{symbol}/lifelines",
      "/api/v1/audit/snapshots/{snapshot_id}",
      "/api/v1/audit/stories/{entity_kind}/{entity_id}",
      "/api/v1/status",
    ]);
  });

  it.each(routes)("%s: the contract example parses", (route) => {
    const documented = examples(route);
    expect(documented.length).toBeGreaterThan(0);
    for (const value of documented) {
      const parsed = ROUTE_SCHEMAS[route]!.safeParse(value);
      expect(parsed.success, parsed.success ? "" : parsed.error.message).toBe(true);
    }
  });

  it.each(routes)("%s: the schema declares exactly the contract's fields", (route) => {
    expect(compare(route, ROUTE_SCHEMAS[route]!, okSchema(route))).toEqual([]);
  });

  it("POST /audit/snapshots answers the same descriptor as GET", () => {
    const parsed = ROUTE_SCHEMAS["/api/v1/audit/snapshots/{snapshot_id}"]!.safeParse(
      examples("/api/v1/audit/snapshots", "post")[0],
    );
    expect(parsed.success).toBe(true);
  });
});
