/** Process entry point: config, logging, listen, and clean shutdown. */

import { loadBridgeConfig } from "./config.js";
import { createLogger } from "./logging/logger.js";
import { buildBridge } from "./server.js";

const config = loadBridgeConfig();
const log = await createLogger(config);
const bridge = await buildBridge(config, log);

log.info(
  "dash-bridge.main",
  `startup: bind=${config.host}:${config.port} monitor=${config.monitor.host}:${config.monitor.pubPort} calf=${config.calf.host}:${config.calf.port} metrics_db=${config.metricsDbPath} logging=${log.destination()} log_gui=${config.links.logGui ?? "-"} book_gui=${config.links.bookGui ?? "-"}`,
);

async function shutdown(signal: string): Promise<void> {
  log.info("dash-bridge.main", `${signal} received; shutting down`);
  await bridge.close();
  await log.close();
  process.exit(0);
}
process.on("SIGINT", () => void shutdown("SIGINT"));
process.on("SIGTERM", () => void shutdown("SIGTERM"));

try {
  await bridge.app.listen({ host: config.host, port: config.port });
  log.info("dash-bridge.main", `listening on http://${config.host}:${config.port}`);
} catch (err) {
  log.critical("dash-bridge.main", `failed to bind ${config.host}:${config.port}: ${String(err)}`);
  process.exit(1);
}
