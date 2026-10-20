/**
 * A stand-in for the browser `WebSocket`, installed globally so the real app
 * (`useDashStream` → `DashSocket`) talks to it. Tests play the bridge: they
 * `open()` it and `deliver()` server frames.
 */

import { act } from "@testing-library/react";
import type { ServerFrame } from "@edumatcher/dash-types";

export class FakeSocket {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSED = 3;
  static instances: FakeSocket[] = [];

  readyState = FakeSocket.CONNECTING;
  onopen: (() => void) | null = null;
  onmessage: ((e: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;

  constructor(readonly url: string) {
    FakeSocket.instances.push(this);
  }

  static latest(): FakeSocket {
    const s = FakeSocket.instances.at(-1);
    if (!s) throw new Error("no socket opened");
    return s;
  }

  send(): void {
    // The dashboard sends nothing to the bridge.
  }

  close(): void {
    this.readyState = FakeSocket.CLOSED;
    this.onclose?.();
  }

  open(): void {
    act(() => {
      this.readyState = FakeSocket.OPEN;
      this.onopen?.();
    });
  }

  deliver(...frames: ServerFrame[]): void {
    act(() => {
      for (const f of frames) this.onmessage?.({ data: JSON.stringify(f) });
    });
  }

  /** The bridge went away. */
  drop(): void {
    act(() => this.close());
  }
}
