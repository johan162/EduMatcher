/**
 * Per-tab WebSocket fan-out (design §6.5, §17.3).
 *
 * The bridge holds one CALF session; every tab gets its own socket off it.
 * Most frames go to everyone — the wildcard channels are always-on regardless
 * of what any tab is rendering, so filtering them would be work for no gain.
 * The exceptions are `depth` and `halt_context`, whose CALF channels refuse
 * `SYM=*` and so cost a real subscription per symbol: those go only to tabs
 * that asked.
 *
 * This class also implements the second `CB` trigger from design §13.2. The
 * Session & Halt board wants halt detail for *every* currently halted symbol,
 * which it cannot enumerate in advance, so a tab declares the board open and
 * the hub acquires `CB` on its behalf as symbols halt and releases as they
 * resume.
 */

import type { WebSocket } from "ws";
import type { ClientFrame, ServerFrame, WatchChannel } from "@edumatcher/terminal-types";

/** What the hub needs from the CALF uplink — narrowed for testability. */
export interface SubscriptionSink {
  watch(ch: WatchChannel, sym: string): void;
  unwatch(ch: WatchChannel, sym: string): void;
}

interface Tab {
  socket: WebSocket;
  /** `${ch}|${sym}` the tab asked for explicitly (Symbol Detail, Depth toggle). */
  viewHolds: Set<string>;
  /** Symbols this tab's Session board holds `CB` for. */
  boardHolds: Set<string>;
  haltBoardOpen: boolean;
}

const holdKey = (ch: WatchChannel, sym: string) => `${ch}|${sym}`;

export class WsHub {
  private readonly tabs = new Set<Tab>();
  /** Symbols currently in `SESSION=HALTED`, tracked from the `state` stream. */
  private readonly halted = new Set<string>();

  constructor(
    private readonly subs: SubscriptionSink,
    private readonly maxClients: number,
  ) {}

  get clientCount(): number {
    return this.tabs.size;
  }

  /**
   * Adopt a new tab. Returns false when at capacity, in which case the caller
   * should close the socket — the cap bounds the bridge's own fan-out cost,
   * which is its concern rather than a CALF-side limit (design §18).
   */
  register(socket: WebSocket): boolean {
    if (this.tabs.size >= this.maxClients) return false;

    const tab: Tab = { socket, viewHolds: new Set(), boardHolds: new Set(), haltBoardOpen: false };
    this.tabs.add(tab);

    socket.on("message", (raw: Buffer) => {
      let frame: ClientFrame;
      try {
        frame = JSON.parse(raw.toString("utf8")) as ClientFrame;
      } catch {
        return;
      }
      this.onClientFrame(tab, frame);
    });

    socket.on("close", () => this.unregister(tab));
    socket.on("error", () => this.unregister(tab));
    return true;
  }

  /** Route one frame to whichever tabs should see it. */
  broadcast(frame: ServerFrame): void {
    if (frame.type === "state") this.trackHalt(frame.sym, frame.session);

    if (frame.type === "depth" || frame.type === "halt_context") {
      const ch: WatchChannel = frame.type === "depth" ? "DEPTH" : "CB";
      const encoded = JSON.stringify(frame);
      for (const tab of this.tabs) {
        if (this.interested(tab, ch, frame.sym)) this.send(tab, encoded);
      }
      return;
    }

    const encoded = JSON.stringify(frame);
    for (const tab of this.tabs) this.send(tab, encoded);
  }

  /** Send one frame to a single tab — used for its `hello` on connect. */
  sendTo(socket: WebSocket, frame: ServerFrame): void {
    if (socket.readyState === socket.OPEN) socket.send(JSON.stringify(frame));
  }

  // -- client control frames ---------------------------------------------------

  private onClientFrame(tab: Tab, frame: ClientFrame): void {
    switch (frame.t) {
      case "subscribe": {
        const key = holdKey(frame.ch, frame.sym);
        // A tab that asks twice must not acquire twice, or one unsubscribe
        // would leave a hold nothing will ever release.
        if (tab.viewHolds.has(key)) return;
        tab.viewHolds.add(key);
        this.subs.watch(frame.ch, frame.sym);
        return;
      }
      case "unsubscribe": {
        const key = holdKey(frame.ch, frame.sym);
        if (!tab.viewHolds.delete(key)) return;
        this.subs.unwatch(frame.ch, frame.sym);
        return;
      }
      case "halt_board":
        return frame.open ? this.openHaltBoard(tab) : this.closeHaltBoard(tab);
      case "ping":
        return;
    }
  }

  private openHaltBoard(tab: Tab): void {
    if (tab.haltBoardOpen) return;
    tab.haltBoardOpen = true;
    for (const sym of this.halted) this.acquireForBoard(tab, sym);
  }

  private closeHaltBoard(tab: Tab): void {
    if (!tab.haltBoardOpen) return;
    tab.haltBoardOpen = false;
    for (const sym of tab.boardHolds) this.subs.unwatch("CB", sym);
    tab.boardHolds.clear();
  }

  private acquireForBoard(tab: Tab, sym: string): void {
    if (tab.boardHolds.has(sym)) return;
    tab.boardHolds.add(sym);
    this.subs.watch("CB", sym);
  }

  /**
   * Keep the halted set current, and move every open board's `CB` holds with
   * it. `SYM=*` is an exchange-wide session change, not a symbol halt.
   */
  private trackHalt(sym: string, session: string): void {
    if (sym === "*") return;

    if (session === "HALTED") {
      if (this.halted.has(sym)) return;
      this.halted.add(sym);
      for (const tab of this.tabs) {
        if (tab.haltBoardOpen) this.acquireForBoard(tab, sym);
      }
      return;
    }

    if (!this.halted.delete(sym)) return;
    for (const tab of this.tabs) {
      if (!tab.boardHolds.delete(sym)) continue;
      this.subs.unwatch("CB", sym);
    }
  }

  // -- lifecycle ----------------------------------------------------------------

  private unregister(tab: Tab): void {
    if (!this.tabs.delete(tab)) return;

    // Release everything this tab was holding, or its subscriptions outlive it.
    for (const key of tab.viewHolds) {
      const [ch, sym] = key.split("|") as [WatchChannel, string];
      this.subs.unwatch(ch, sym);
    }
    tab.viewHolds.clear();

    for (const sym of tab.boardHolds) this.subs.unwatch("CB", sym);
    tab.boardHolds.clear();
  }

  private interested(tab: Tab, ch: WatchChannel, sym: string): boolean {
    if (tab.viewHolds.has(holdKey(ch, sym))) return true;
    return ch === "CB" && tab.boardHolds.has(sym);
  }

  private send(tab: Tab, encoded: string): void {
    if (tab.socket.readyState === tab.socket.OPEN) tab.socket.send(encoded);
  }
}
