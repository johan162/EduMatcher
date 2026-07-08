"""
Audit Process — records every event in the system to a rotating log file.

Usage:
  poetry run pm-audit [--log-file data/audit.log] [--terminal] [--buffer-size 100] [--flush-interval 10]

Subscribes to ALL topics (empty filter) and appends each event as a
single JSON line:

  [2026-04-29T14:32:01.123] [trade.executed] {"id": "...", ...}

Options
-------
  --log-file       Path to log file (default: data/audit.log)
  --terminal       Also print each entry to stdout
  --buffer-size    Number of messages to buffer before writing to disk (default: 100)
  --flush-interval Maximum seconds to wait before flushing buffer (default: 10)
"""

from __future__ import annotations

import argparse
import errno
import json
import logging
import signal
import sys
import threading
import time
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import List

import zmq

from edumatcher.config import AUDIT_LOG_FILE, ENGINE_PUB_ADDR
from edumatcher.messaging.bus import make_subscriber
from edumatcher.models.message import decode

_POLL_TIMEOUT_MS = 300
_JOIN_POLL_SEC = 0.5
_DEFAULT_BUFFER_SIZE = 100
_DEFAULT_FLUSH_INTERVAL = 10.0


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
    def __init__(
        self,
        log_path: Path,
        to_terminal: bool,
        buffer_size: int = _DEFAULT_BUFFER_SIZE,
        flush_interval: float = _DEFAULT_FLUSH_INTERVAL,
    ) -> None:
        self.logger = _setup_logger(log_path, to_terminal)
        self._running = True
        self.sub = make_subscriber(ENGINE_PUB_ADDR)  # subscribe to everything
        self.buffer_size = buffer_size
        self.flush_interval = flush_interval
        self._buffer: List[str] = []
        self._buffer_lock = threading.Lock()
        self._last_flush_time = time.time()
        self._flush_timer: threading.Timer | None = None

    def _flush_buffer(self) -> None:
        """Flush buffered messages to disk."""
        with self._buffer_lock:
            if self._buffer:
                for line in self._buffer:
                    self.logger.info(line)
                self._buffer.clear()
                self._last_flush_time = time.time()

    def _schedule_flush(self) -> None:
        """Schedule a flush after flush_interval seconds."""
        if self._flush_timer is not None:
            self._flush_timer.cancel()
        self._flush_timer = threading.Timer(self.flush_interval, self._flush_buffer)
        self._flush_timer.daemon = True
        self._flush_timer.start()

    def _add_to_buffer(self, line: str) -> None:
        """Add a line to the buffer and flush if needed."""
        with self._buffer_lock:
            self._buffer.append(line)
            buffer_len = len(self._buffer)

        # Check if we need to flush based on buffer size
        if buffer_len >= self.buffer_size:
            self._flush_buffer()
            # Reschedule the timer since we just flushed
            self._schedule_flush()
        elif buffer_len == 1:
            # First message in buffer, start the flush timer
            self._schedule_flush()

    def _receive(self) -> None:
        poller = zmq.Poller()
        poller.register(self.sub, zmq.POLLIN)
        while self._running:
            try:
                socks = dict(poller.poll(timeout=_POLL_TIMEOUT_MS))
            except zmq.ZMQError as exc:
                if exc.errno != errno.EINTR:
                    raise
                break  # EINTR — honour _running flag
            if self.sub in socks:
                frames = self.sub.recv_multipart()
                try:
                    topic, payload = decode(frames)
                    ts = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
                    line = f"[{ts}] [{topic}] {json.dumps(payload)}"
                    self._add_to_buffer(line)
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
        print(
            f"[AUDIT] Logging all events (buffer: {self.buffer_size} msgs, "
            f"flush: {self.flush_interval}s) …  (Ctrl-C to stop)"
        )
        try:
            while self._running:
                t.join(timeout=_JOIN_POLL_SEC)  # re-check _running every 500 ms
        finally:
            # Flush any remaining messages before exiting
            if self._flush_timer is not None:
                self._flush_timer.cancel()
            self._flush_buffer()
            t.join(timeout=1.0)
            self.sub.close()

    def _stop(self) -> None:
        self._running = False
        print("\n[AUDIT] Stopped.")


def main() -> None:
    parser = argparse.ArgumentParser(description="EduMatcher audit logger")
    from edumatcher.cli_version import add_version_argument

    add_version_argument(parser, "pm-audit")
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
    parser.add_argument(
        "--buffer-size",
        type=int,
        default=_DEFAULT_BUFFER_SIZE,
        metavar="N",
        help=f"Number of messages to buffer before writing to disk (default: {_DEFAULT_BUFFER_SIZE})",
    )
    parser.add_argument(
        "--flush-interval",
        type=float,
        default=_DEFAULT_FLUSH_INTERVAL,
        metavar="SECONDS",
        help=f"Maximum seconds to wait before flushing buffer (default: {_DEFAULT_FLUSH_INTERVAL})",
    )
    args = parser.parse_args()

    # Validate arguments
    if args.buffer_size < 1:
        print("[AUDIT] ERROR: --buffer-size must be at least 1", file=sys.stderr)
        sys.exit(1)
    if args.flush_interval <= 0:
        print("[AUDIT] ERROR: --flush-interval must be positive", file=sys.stderr)
        sys.exit(1)

    try:
        process = AuditProcess(
            Path(args.log_file),
            args.terminal,
            buffer_size=args.buffer_size,
            flush_interval=args.flush_interval,
        )
    except Exception as exc:
        print(f"[AUDIT] FATAL: {exc}", file=sys.stderr)
        sys.exit(1)
    process.run()


if __name__ == "__main__":
    main()
