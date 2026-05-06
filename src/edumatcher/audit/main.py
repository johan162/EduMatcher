"""
Audit Process — records every event in the system to a rotating log file.

Usage:
  poetry run pm-audit [--log-file data/audit.log] [--terminal]

Subscribes to ALL topics (empty filter) and appends each event as a
single JSON line:

  [2026-04-29T14:32:01.123] [trade.executed] {"id": "...", ...}

Options
-------
  --log-file  Path to log file (default: data/audit.log)
  --terminal  Also print each entry to stdout
"""

from __future__ import annotations

import argparse
import json
import logging
import signal
import sys
import threading
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

import zmq

from edumatcher.config import AUDIT_LOG_FILE, ENGINE_PUB_ADDR
from edumatcher.messaging.bus import make_subscriber
from edumatcher.models.message import decode


def _setup_logger(log_path: Path, to_terminal: bool) -> logging.Logger:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("audit")
    logger.setLevel(logging.INFO)
    logger.propagate = False

    fmt = logging.Formatter("%(message)s")

    fh = RotatingFileHandler(
        log_path, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    if to_terminal:
        ch = logging.StreamHandler()
        ch.setFormatter(fmt)
        logger.addHandler(ch)

    return logger


class AuditProcess:
    def __init__(self, log_path: Path, to_terminal: bool) -> None:
        self.logger = _setup_logger(log_path, to_terminal)
        self._running = True
        self.sub = make_subscriber(ENGINE_PUB_ADDR)  # subscribe to everything

    def _receive(self) -> None:
        poller = zmq.Poller()
        poller.register(self.sub, zmq.POLLIN)
        while self._running:
            try:
                socks = dict(poller.poll(timeout=300))
            except zmq.ZMQError:
                break  # EINTR or socket closed — honour _running flag
            if self.sub in socks:
                frames = self.sub.recv_multipart()
                try:
                    topic, payload = decode(frames)
                    ts = datetime.utcnow().isoformat(timespec="milliseconds")
                    line = f"[{ts}] [{topic}] {json.dumps(payload)}"
                    self.logger.info(line)
                except Exception as exc:
                    # Never let a single bad message kill the receive loop
                    print(
                        f"[AUDIT] WARNING: failed to decode/log message: {exc}",
                        flush=True,
                    )

    def run(self) -> None:
        signal.signal(signal.SIGINT, lambda *_: self._stop())
        signal.signal(signal.SIGTERM, lambda *_: self._stop())

        t = threading.Thread(target=self._receive, daemon=True)
        t.start()
        print("[AUDIT] Logging all events …  (Ctrl-C to stop)")
        while self._running:
            t.join(timeout=0.5)  # re-check _running every 500 ms

    def _stop(self) -> None:
        self._running = False
        print("\n[AUDIT] Stopped.")


def main() -> None:
    parser = argparse.ArgumentParser(description="EduMatcher audit logger")
    parser.add_argument(
        "--log-file",
        default=str(AUDIT_LOG_FILE),
        metavar="PATH",
        help=f"Log file path (default: {AUDIT_LOG_FILE})",
    )
    parser.add_argument(
        "--terminal",
        "-t",
        action="store_true",
        help="Also print each audit entry to stdout",
    )
    args = parser.parse_args()
    try:
        process = AuditProcess(Path(args.log_file), args.terminal)
    except Exception as exc:
        print(f"[AUDIT] FATAL: {exc}", file=sys.stderr)
        sys.exit(1)
    process.run()


if __name__ == "__main__":
    main()
