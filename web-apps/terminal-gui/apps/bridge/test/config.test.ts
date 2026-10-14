import { afterEach, describe, expect, it } from "vitest";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { loadBridgeConfig } from "../src/config.js";

const savedEnv = { ...process.env };
const tempDirs: string[] = [];

afterEach(() => {
  process.env = { ...savedEnv };
  for (const dir of tempDirs.splice(0)) rmSync(dir, { recursive: true, force: true });
});

function useDataDir(config?: object): void {
  const dir = mkdtempSync(join(tmpdir(), "terminal-bridge-config-"));
  tempDirs.push(dir);
  process.env["EDUMATCHER_DATA_DIR"] = dir;
  delete process.env["SESSION_TIMEZONE"];
  if (config) {
    const refDataDir = join(dir, "ref_data");
    mkdirSync(refDataDir);
    writeFileSync(join(refDataDir, "engine_config.json"), JSON.stringify(config));
  }
}

describe("loadBridgeConfig session timezone", () => {
  it("reads the timezone from the compiled engine config", () => {
    useDataDir({ engine: { locale: { session_timezone: "Asia/Tokyo" } } });

    expect(loadBridgeConfig().sessionTimezone).toBe("Asia/Tokyo");
  });

  it("uses the engine default before a config has been deployed", () => {
    useDataDir();

    expect(loadBridgeConfig().sessionTimezone).toBe("Europe/Stockholm");
  });
});