import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { DatabaseSync } from "node:sqlite";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { LOG_DB_SCHEMA_VERSION, LogDb } from "../src/log-db.js";

describe("LogDb schema version", () => {
  let dir: string;
  let path: string;

  beforeEach(() => {
    dir = mkdtempSync(join(tmpdir(), "log-db-"));
    path = join(dir, "log.db");
  });
  afterEach(() => rmSync(dir, { recursive: true, force: true }));

  function write(sql: string): void {
    const db = new DatabaseSync(path);
    db.exec(sql);
    db.close();
  }

  it("opens a log.db of the current version", () => {
    write(
      `CREATE TABLE schema_version (id INTEGER PRIMARY KEY, version INTEGER NOT NULL);
       INSERT INTO schema_version VALUES (1, ${LOG_DB_SCHEMA_VERSION});`,
    );
    const logDb = new LogDb(path);
    expect(logDb.open()).toBe(true);
    expect(logDb.health).toEqual({ ok: true, detail: "connected" });
  });

  it("refuses a log.db written before the version table existed", () => {
    write("CREATE TABLE log_events (seq INTEGER PRIMARY KEY, message TEXT);");
    const logDb = new LogDb(path);
    expect(logDb.open()).toBe(false);
    expect(logDb.health.ok).toBe(false);
    expect(logDb.health.detail).toMatch(/schema version 1, this bridge needs 2; .* delete it/);
  });
});
