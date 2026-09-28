/**
 * A stand-in for the browser `WebSocket`, installed globally so the real app
 * (`useBookStream` → `BookSocket`) talks to it. Tests play the bridge: they
 * `open()` it, `deliver()` server frames and read what the tab `sent`.
 */

import { act } from "@testing-library/react";
import type { ClientFrame, ServerFrame } from "@edumatcher/book-types";

export class FakeSocket {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSED = 3;
  static instances: FakeSocket[] = [];

  readyState = FakeSocket.CONNECTING;
  readonly sent: ClientFrame[] = [];
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

  send(data: string): void {
    this.sent.push(JSON.parse(data) as ClientFrame);
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

  watches(): string[] {
    return this.sent.filter((f) => f.t === "watch").map((f) => (f.t === "watch" ? f.sym : ""));
  }
}
