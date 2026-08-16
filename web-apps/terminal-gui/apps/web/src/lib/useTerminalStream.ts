/**
 * Wires the bridge WebSocket into the live store (design §16).
 *
 * The client is held at module scope rather than in context because control
 * frames are sent from view components that mount and unmount independently of
 * the socket's lifetime — a Symbol Detail view declaring `DEPTH` interest, or
 * the Session board declaring itself open. Reaching for it directly keeps
 * those call sites to one line and avoids threading a provider through every
 * view for a single method.
 */

import { useEffect } from "react";
import type { ClientFrame } from "@edumatcher/terminal-types";
import { TerminalStreamClient } from "./ws.js";
import { useLiveStore } from "../store/useLiveStore.js";

let client: TerminalStreamClient | null = null;

/** Send a control frame, if the socket is up. A no-op before it connects. */
export function sendControl(frame: ClientFrame): void {
  client?.send(frame);
}

export function useTerminalStream(): void {
  useEffect(() => {
    const stream = new TerminalStreamClient(
      (frame) => useLiveStore.getState().applyFrame(frame),
      (status) => useLiveStore.getState().setWsStatus(status),
    );
    client = stream;
    stream.connect();

    return () => {
      stream.close();
      client = null;
    };
  }, []);
}
