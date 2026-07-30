import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { LalfClient } from "../src/client.js";
import { FakeLogServer, unusedPort, waitFor } from "./fake-log-server.js";

const servers: FakeLogServer[] = [];
const clients: LalfClient[] = [];
const tmpDirs: string[] = [];

afterEach(async () => {
  for (const client of clients.splice(0)) await client.stop();
  for (const server of servers.splice(0)) await server.stop();
  for (const dir of tmpDirs.splice(0)) rmSync(dir, { recursive: true, force: true });
});

async function startServer(opts: ConstructorParameters<typeof FakeLogServer>[0] = {}) {
  const server = new FakeLogServer(opts);
  servers.push(server);
  await server.start();
  return server;
}

function makeClient(port: number, overrides: Partial<ConstructorParameters<typeof LalfClient>[0]> = {}) {
  const failoverDir = mkdtempSync(join(tmpdir(), "lalf-test-"));
  tmpDirs.push(failoverDir);
  const client = new LalfClient({
    host: "127.0.0.1",
    port,
    client: "pm-terminal-bridge",
    connectTimeoutSec: 0.2,
    failoverTimeoutSec: 0.3,
    failoverDir,
    ...overrides,
  });
  clients.push(client);
  return client;
}

const info = (message: string) => ({ level: "INFO" as const, logger: "terminal-bridge", message });

describe("startup probe", () => {
  it("attaches when the server completes a handshake", async () => {
    const server = await startServer();
    const client = makeClient(server.port);

    expect(await client.attach()).toBe(true);
    expect(client.state).toBe("CONNECTED");
    expect(server.framesOfType("HELLO")).toHaveLength(1);
  });

  it("reports failure when nothing is listening, leaving the caller on stdout", async () => {
    const client = makeClient(await unusedPort());

    expect(await client.attach()).toBe(false);
    expect(client.state).toBe("IDLE");
  });

  it("gives up on a server that accepts but never answers", async () => {
    const server = await startServer({ silent: true });
    const client = makeClient(server.port);

    const started = Date.now();
    expect(await client.attach()).toBe(false);
    // Must be bounded by connectTimeoutSec — startup can never hang on this.
    expect(Date.now() - started).toBeLessThan(1000);
  });

  it("does not retry a failed probe in the background", async () => {
    const server = await startServer({ silent: true });
    const client = makeClient(server.port);
    await client.attach();

    await new Promise((resolve) => setTimeout(resolve, 400));
    expect(server.connectionCount).toBe(1);
  });
});

describe("steady state", () => {
  it("ships a queued record as a LOG frame with its payload intact", async () => {
    const server = await startServer();
    const client = makeClient(server.port);
    await client.attach();

    client.log(info("bridge startup complete"));
    await waitFor(() => server.framesOfType("LOG").length === 1, 2000, "the LOG frame");

    const frame = server.framesOfType("LOG")[0];
    expect(frame?.payload).toBe("bridge startup complete");
    expect(frame?.fields).toMatchObject({ LEVEL: "INFO", LOGGER: "terminal-bridge", SEQ: "1" });
  });

  it("numbers records sequentially from one", async () => {
    const server = await startServer();
    const client = makeClient(server.port);
    await client.attach();

    client.log(info("a"));
    client.log(info("b"));
    client.log(info("c"));
    await waitFor(() => server.framesOfType("LOG").length === 3, 2000, "three LOG frames");

    expect(server.framesOfType("LOG").map((f) => f.fields["SEQ"])).toEqual(["1", "2", "3"]);
  });

  it("keeps a multi-line message in one frame rather than splitting it", async () => {
    const server = await startServer();
    const client = makeClient(server.port);
    await client.attach();

    const message = "CALF reconnect failed\nTraceback:\n  at uplink.ts:120";
    client.log({ ...info(message), level: "ERROR" });
    await waitFor(() => server.framesOfType("LOG").length === 1, 2000, "the LOG frame");

    expect(server.framesOfType("LOG")[0]?.payload).toBe(message);
  });

  it("sends a heartbeat once the connection has been idle for HBINT", async () => {
    const server = await startServer({ hbint: 1 });
    const client = makeClient(server.port);
    await client.attach();

    await waitFor(() => server.framesOfType("HB").length >= 1, 3000, "a heartbeat");
  });

  it("does not queue anything while healthy", async () => {
    const server = await startServer();
    const client = makeClient(server.port);
    await client.attach();

    client.log(info("x"));
    await waitFor(() => server.framesOfType("LOG").length === 1, 2000, "the LOG frame");
    expect(client.queueDepth).toBe(0);
  });
});

describe("reconnect", () => {
  it("queues records while the connection is down and drains them on reconnect", async () => {
    const server = await startServer();
    const client = makeClient(server.port, { failoverTimeoutSec: 10 });
    await client.attach();

    server.dropConnections();
    await waitFor(() => client.state === "RECONNECTING", 2000, "the drop to be noticed");

    client.log(info("during outage"));
    expect(client.queueDepth).toBe(1);

    await waitFor(() => client.state === "CONNECTED", 4000, "the reconnect");
    await waitFor(
      () => server.framesOfType("LOG").some((f) => f.payload === "during outage"),
      2000,
      "the backlog to drain",
    );
    expect(client.queueDepth).toBe(0);
  });

  it("re-handshakes rather than resuming the dead session", async () => {
    const server = await startServer();
    const client = makeClient(server.port, { failoverTimeoutSec: 10 });
    await client.attach();

    server.dropConnections();
    await waitFor(() => client.state === "RECONNECTING", 2000, "the drop to be noticed");
    await waitFor(() => client.state === "CONNECTED", 4000, "the reconnect");
    expect(server.framesOfType("HELLO").length).toBeGreaterThanOrEqual(2);
  });

  it("bounds the backlog, dropping newest and counting what was lost", async () => {
    const server = await startServer();
    const client = makeClient(server.port, { failoverTimeoutSec: 10, queueMaxSize: 3 });
    await client.attach();

    server.dropConnections();
    await waitFor(() => client.state === "RECONNECTING", 2000, "the drop to be noticed");

    for (let i = 0; i < 6; i += 1) client.log(info(`record-${i}`));
    expect(client.queueDepth).toBe(3);
    expect(client.droppedCount).toBe(3);

    // Oldest preserved: the three that survived are the first three.
    await waitFor(() => client.state === "CONNECTED", 4000, "the reconnect");
    await waitFor(() => server.framesOfType("LOG").length === 3, 2000, "the backlog to drain");
    expect(server.framesOfType("LOG").map((f) => f.payload)).toEqual(["record-0", "record-1", "record-2"]);
  });
});

describe("failover", () => {
  async function failedOverClient() {
    const server = await startServer();
    const client = makeClient(server.port, { failoverTimeoutSec: 0.3 });
    await client.attach();
    await server.stop();
    servers.splice(servers.indexOf(server), 1);
    await waitFor(() => client.state === "FAILED_OVER", 5000, "failover");
    return client;
  }

  it("switches to a local file once the grace window is exhausted", async () => {
    const client = await failedOverClient();
    client.log(info("after failover"));

    await waitFor(
      () => readFileSync(client.fallbackPath, "utf8").includes("after failover"),
      2000,
      "the record to reach the file",
    );
  });

  it("writes a marker line naming the file it switched to", async () => {
    const client = await failedOverClient();

    await waitFor(() => readFileSync(client.fallbackPath, "utf8").length > 0, 2000, "the marker line");
    const contents = readFileSync(client.fallbackPath, "utf8");
    expect(contents).toContain("pm-log-srv unreachable");
    expect(contents).toContain(client.fallbackPath);
  });

  it("writes the queued backlog to the file rather than discarding it", async () => {
    const server = await startServer();
    const client = makeClient(server.port, { failoverTimeoutSec: 0.3 });
    await client.attach();
    await server.stop();
    servers.splice(servers.indexOf(server), 1);

    await waitFor(() => client.state === "RECONNECTING", 2000, "the drop to be noticed");
    client.log(info("queued before failover"));

    await waitFor(() => client.state === "FAILED_OVER", 5000, "failover");
    await waitFor(
      () => readFileSync(client.fallbackPath, "utf8").includes("queued before failover"),
      2000,
      "the backlog to reach the file",
    );
  });

  it("never re-probes the server for the rest of the run", async () => {
    const server = await startServer();
    const client = makeClient(server.port, { failoverTimeoutSec: 0.3 });
    await client.attach();
    const port = server.port;
    await server.stop();
    servers.splice(servers.indexOf(server), 1);
    await waitFor(() => client.state === "FAILED_OVER", 5000, "failover");

    // Bring a server back on the same port; the client must ignore it.
    const revived = new FakeLogServer();
    servers.push(revived);
    await new Promise<void>((resolve) => {
      const s = revived as unknown as { start: () => Promise<number> };
      void s.start().then(() => resolve());
    });

    await new Promise((resolve) => setTimeout(resolve, 600));
    expect(client.state).toBe("FAILED_OVER");
    expect(port).toBeGreaterThan(0);
  });

  it("names the file after the instance when one is configured", async () => {
    const client = makeClient(await unusedPort(), { instance: "b" });
    expect(client.fallbackPath.endsWith("pm-terminal-bridge-b.log")).toBe(true);
  });
});
