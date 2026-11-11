import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { z } from "zod";
import { ROUTE_SCHEMAS } from "@/api/schemas";
import { examples } from "./helpers";

/**
 * The GUI's Zod schemas against the released REST contract.
 *
 * `spec/rest/openapi.json` is what pm-api-gwy serves (the Python suite holds
 * it to the code and its examples to the response models). Here every
 * clearing route's 200 example must parse with the GUI's schema, and the
 * schema must declare exactly the contract's fields, with the same
 * required/optional split -- so a field added, renamed or dropped on either
 * side fails this test instead of quietly rendering a blank column.
 */
const OPENAPI = path.resolve(__dirname, "../../../../../spec/rest/openapi.json");

interface OpenApiSchema {
  $ref?: string;
  type?: string;
  anyOf?: OpenApiSchema[];
  items?: OpenApiSchema;
  properties?: Record<string, OpenApiSchema>;
  required?: string[];
  additionalProperties?: OpenApiSchema | boolean;
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

/** The non-null branch of an `anyOf: [X, null]`, resolved. */
function nonNull(schema: OpenApiSchema): OpenApiSchema {
  const s = resolve(schema);
  if (s.anyOf) return resolve(s.anyOf.find((b) => b.type !== "null")!);
  return s;
}

/** The Zod schema inside optional/nullable wrappers. */
function unwrap(schema: z.ZodType): z.ZodType {
  let s = schema;
  while (s instanceof z.ZodOptional || s instanceof z.ZodNullable) {
    s = s.unwrap() as z.ZodType;
  }
  return s;
}

/** Every field-set mismatch between a Zod schema and an OpenAPI schema. */
function compare(where: string, zod: z.ZodType, api: OpenApiSchema): string[] {
  const inner = unwrap(zod);
  const target = nonNull(api);
  if (inner instanceof z.ZodArray) {
    return target.items ? compare(`${where}[]`, inner.element as z.ZodType, target.items) : [];
  }
  if (!(inner instanceof z.ZodObject) || !target.properties) return [];
  const problems: string[] = [];
  const shape = inner.shape as Record<string, z.ZodType>;
  const zodKeys = Object.keys(shape).sort();
  const apiKeys = Object.keys(target.properties).sort();
  if (zodKeys.join() !== apiKeys.join()) {
    problems.push(`${where}: GUI ${zodKeys.join(",")} vs contract ${apiKeys.join(",")}`);
    return problems;
  }
  const required = new Set(target.required ?? []);
  for (const key of zodKeys) {
    const optional = shape[key] instanceof z.ZodOptional;
    if (optional === required.has(key)) {
      problems.push(`${where}.${key}: optional in one, required in the other`);
    }
    problems.push(...compare(`${where}.${key}`, shape[key]!, target.properties[key]!));
  }
  return problems;
}

function okResponse(route: string) {
  const op = doc.paths[route]?.["get"];
  expect(op, `${route} is not in the contract`).toBeDefined();
  return op!.responses["200"] as {
    content: {
      "application/json": {
        schema: OpenApiSchema;
        example?: unknown;
        examples?: Record<string, { value: unknown }>;
      };
    };
  };
}

describe("GUI schemas match the released REST contract", () => {
  const routes = Object.keys(ROUTE_SCHEMAS);

  it("covers every clearing route in the contract", () => {
    const released = Object.keys(doc.paths).filter((p) => p.startsWith("/api/v1/clearing/"));
    expect(routes.filter((r) => r.startsWith("/api/v1/clearing/")).sort()).toEqual(
      released.sort(),
    );
  });

  it.each(routes)("%s: the contract example parses", (route) => {
    const documented = examples(route);
    expect(documented.length).toBeGreaterThan(0);
    for (const example of documented) {
      const parsed = ROUTE_SCHEMAS[route]!.safeParse(example);
      expect(parsed.success, parsed.success ? "" : parsed.error.message).toBe(true);
    }
  });

  it.each(routes)("%s: the schema declares exactly the contract's fields", (route) => {
    const schema = okResponse(route).content["application/json"].schema;
    expect(compare(route, ROUTE_SCHEMAS[route]!, schema)).toEqual([]);
  });
});
