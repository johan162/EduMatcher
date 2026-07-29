/** Wires the WS client into the Zustand live store and TanStack Query cache (design §15). */

import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import type { ServerFrame } from "@edumatcher/log-types";
import { LogStreamClient } from "./ws.js";
import { useLiveStore } from "../store/useLiveStore.js";

export function useLogStream(): void {
  const queryClient = useQueryClient();

  useEffect(() => {
    const store = useLiveStore.getState();

    const handleFrame = (frame: ServerFrame) => {
      const s = useLiveStore.getState();
      switch (frame.t) {
        case "event":
          s.pushRow(frame.row);
          break;
        case "events":
          for (const row of frame.rows) s.pushRow(row);
          break;
        case "counters":
          s.setCounters(frame.window);
          break;
        case "server_state":
          s.setServerState(frame.state);
          break;
        case "bridge_status":
          s.setLogDbHealthy(frame.logDb.ok);
          break;
        case "issue":
          void queryClient.invalidateQueries({ queryKey: ["issues"] });
          break;
        case "ack":
          void queryClient.invalidateQueries({ queryKey: ["issues"] });
          break;
        case "hello":
          break;
      }
    };

    const client = new LogStreamClient(handleFrame, (status) => {
      useLiveStore.getState().setWsStatus(status);
    });
    client.connect();

    return () => client.close();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
}
