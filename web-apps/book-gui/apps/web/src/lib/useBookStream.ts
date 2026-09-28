/**
 * One bridge socket for the tab's lifetime, wired to the book store.
 *
 * The watched symbol is re-sent on every (re)connect, so a bridge restart or
 * a dropped socket never leaves the tab subscribed to nothing.
 */

import { useEffect } from "react";
import { useBookStore } from "../store/useBookStore.js";
import { BookSocket, streamUrl } from "./ws.js";

export function useBookStream(): void {
  useEffect(() => {
    const store = useBookStore;
    const socket = new BookSocket(streamUrl(), {
      onFrame: (frame) => store.getState().apply(frame),
      onOpen: () => {
        store.getState().setSocketOpen(true);
        const sym = store.getState().watched;
        if (sym) socket.send({ t: "watch", sym });
      },
      onClose: () => store.getState().setSocketOpen(false),
    });
    const unsubscribe = store.subscribe((state, prev) => {
      if (state.watched && state.watched !== prev.watched) socket.send({ t: "watch", sym: state.watched });
    });
    socket.start();
    return () => {
      unsubscribe();
      socket.stop();
    };
  }, []);
}
