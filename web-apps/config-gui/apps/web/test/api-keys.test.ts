/** Generated API keys and the credentials-file switch. */

import { describe, expect, it } from "vitest";
import { createApiGateway, createBlankDraft, createGateway, type EngineConfigDraft } from "@edumatcher/schema";
import {
  addGeneratedKeys,
  credentialsInFiles,
  keyCandidates,
  randomApiKey,
  setCredentialsInFiles,
} from "../src/lib/apiKeys";

function draft(): EngineConfigDraft {
  const d = createBlankDraft();
  d.gateways = [createGateway("T1"), createGateway("T2"), createGateway("MM1", "MARKET_MAKER"), createGateway("")];
  d.apiGateways = [createApiGateway("desk"), { ...createApiGateway("dash"), port: 8081 }];
  return d;
}

describe("generated API keys", () => {
  it("has pm-config-gen's shape with the chosen token length", () => {
    expect(randomApiKey("MM1")).toMatch(/^key-mm1-[a-z0-9]{6}$/);
    expect(randomApiKey("T1", 32)).toMatch(/^key-t1-[a-z0-9]{32}$/);
    expect(randomApiKey("T1")).not.toBe(randomApiKey("T1"));
  });

  it("lists every named participant with the instance already holding its key", () => {
    const d = draft();
    d.apiGateways[1]!.credentials = [
      { apiKey: "x", gatewayId: "T2", description: "" },
      { apiKey: "ro", gatewayId: null, description: "" },
    ];
    expect(keyCandidates(d)).toEqual([
      { id: "T1", role: "TRADER", holder: undefined },
      { id: "T2", role: "TRADER", holder: "dash" },
      { id: "MM1", role: "MARKET_MAKER", holder: undefined },
    ]);
  });

  it("adds one key per participant, described as pm-config-gen does", () => {
    const d = draft();
    addGeneratedKeys(d, 0, ["T1", "MM1"], (id) => `k-${id}`);
    expect(d.apiGateways[0]!.credentials).toEqual([
      { apiKey: "k-T1", gatewayId: "T1", description: "Generated key for T1" },
      { apiKey: "k-MM1", gatewayId: "MM1", description: "Generated key for MM1" },
    ]);
  });
});

describe("credentials in separate files", () => {
  it("gives each instance its own file, keeping existing names, and turns off cleanly", () => {
    const d = draft();
    d.apiGateways[1]!.credentialsFile = "api_keys_dash.yaml";
    expect(credentialsInFiles(d)).toBe(false);
    setCredentialsInFiles(d, true);
    expect(d.apiGateways.map((g) => g.credentialsFile)).toEqual(["api_keys_desk.yaml", "api_keys_dash.yaml"]);
    expect(credentialsInFiles(d)).toBe(true);
    setCredentialsInFiles(d, false);
    expect(d.apiGateways.map((g) => g.credentialsFile)).toEqual([undefined, undefined]);
  });

  it("uses api_keys.yaml for a single instance and avoids taken names", () => {
    const d = draft();
    d.apiGateways = [d.apiGateways[0]!];
    setCredentialsInFiles(d, true);
    expect(d.apiGateways[0]!.credentialsFile).toBe("api_keys.yaml");

    const two = draft();
    two.apiGateways[1]!.name = "my desk";
    two.apiGateways[0]!.credentialsFile = "api_keys_my_desk.yaml";
    setCredentialsInFiles(two, true);
    expect(two.apiGateways[1]!.credentialsFile).toBe("api_keys_my_desk_2.yaml");
  });

  it("is off without API instances", () => {
    const d = draft();
    d.apiGateways = [];
    expect(credentialsInFiles(d)).toBe(false);
  });
});
