/** `GET /api/ui-config` — bridge settings the frontend must not hard-code. */

import type { FastifyInstance } from "fastify";
import type { UiConfig } from "@edumatcher/log-types";
import type { BridgeConfig } from "../config.js";

export function registerUiConfigRoutes(app: FastifyInstance, config: BridgeConfig): void {
  app.get("/api/ui-config", async (): Promise<UiConfig> => {
    return {
      alertLevel: config.issues.alertLevel,
      issuesMinLevel: config.issues.minLevel,
      processSilenceSec: config.thresholds.processSilenceSec,
      errorRate: {
        normalPerMin: config.thresholds.errorRateNormalPerMin,
        elevatedPerMin: config.thresholds.errorRateElevatedPerMin,
        severePerMin: config.thresholds.errorRateSeverePerMin,
      },
    };
  });
}
