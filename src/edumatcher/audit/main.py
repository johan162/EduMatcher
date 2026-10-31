"""
Audit Process — records every event in the system to a day-closing log file.

Usage:
  poetry run pm-audit [--audit-log-file data/audit.log] [--terminal] [--buffer-size 100] [--flush-interval 10]
                      [--max-file-mb 10]

Subscribes to ALL topics (empty filter) and appends each event as a
single JSON line:

  [2026-04-29T14:32:01.123] [trade.executed] {"id": "...", ...}

Binds (AUDIT_HEALTH_BIND_ADDR, a REP socket):
  answers `pm-audit-cli health`'s ping with the current UTC time, proving the
  receive loop is alive and pumping rather than just the OS process existing.

Options
-------
  --audit-log-file Path to the audit-trail log file (default: data/audit.log)
  --terminal       Also print each entry to stdout
  --buffer-size    Number of messages to buffer before writing to disk (default: 100)
  --flush-interval Maximum seconds to wait before flushing buffer (default: 10)
  --max-file-mb    Close the audit log as a day part at this size in MB (default: 10)
  --keep-days      Delete archives older than N days (default: 0 = keep all)

The active file holds one trading day (midnight in the engine config's
``locale.session_timezone``, by each line's receive time).  At the date change
or at --max-file-mb it is closed as ``audit/audit-YYYY-MM-DD.N.log`` beside
it.  Closed days are compressed to ``audit-YYYY-MM-DD.log.zst`` by a child
``pm-audit-cli archive --pending`` (at start-up and after each day closes);
only --keep-days ever deletes anything, and only archives.

This process's own *operational* logging (``log.info(...)``/``log.warning(...)``
calls below, distinct from the audit trail above) is sent to ``pm-log-srv``
when one is running, auto-detected at startup — see
``--log-target``/``--log-file``/``--log-failover-timeout``
(docs-design/EduMatcher-log-srv.md §8).
"""

from __future__ import annotations

import argparse
from collections import defaultdict
import errno
from itertools import groupby
from operator import itemgetter
import json
import logging
import signal
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone, tzinfo
from pathlib import Path
from typing import IO, Callable

import zmq

from edumatcher.health import HealthReporter, counter, gauge
from edumatcher.models.generated.health import MetricSample
from edumatcher.audit.archive import parse_ratio, session_timezone
from edumatcher.audit.writer import AuditFile
from edumatcher.config import AUDIT_HEALTH_BIND_ADDR, AUDIT_LOG_FILE, ENGINE_PUB_ADDR
from edumatcher.log_srv.config import (
    load_default_log_client_config,
    load_default_log_server_config,
    resolve_host_default,
)
from edumatcher.logclient.discovery import resolve_handler
from edumatcher.healthcheck import answer_health_ping
from edumatcher.messaging.bus import make_replier, make_subscriber
from edumatcher.models.message import (
    decode,
    decode_envelope,
    decode_publisher_sequence,
    decode_sequence,
)
from edumatcher.models.generated.book import PREFIX_BOOK_SNAPSHOT
from edumatcher.models.generated.system import TOPIC_EOD

_CLIENT_NAME = "pm-audit"

_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s - %(message)s"

_POLL_TIMEOUT_MS = 300
_JOIN_POLL_SEC = 0.5
#: How long a stopped receive loop keeps reading for the engine's
#: ``system.eod`` (see AuditProcess._drain).
_DRAIN_SEC = 5.0
#: Receive high-water mark for the engine subscription. Deep enough to ride
#: out a burst without dropping, bounded so a stalled writer cannot grow
#: the process without limit.
_SUB_RCVHWM = 200_000

_DEFAULT_BUFFER_SIZE = 100
_DEFAULT_FLUSH_INTERVAL = 10.0
_DEFAULT_MAX_FILE_MB = 10
_DEBUG_SUMMARY_INTERVAL_SEC = 5.0
#: How often the receive loop looks for a day that ended without a line.
_DAY_CHECK_INTERVAL_SEC = 1.0

log = logging.getLogger(__name__)


def _meta_section(frames: list[bytes]) -> str | None:
    """The bracketed metadata section for one message, or None if it has none.

    The audit trail used to record only the topic and the payload, discarding
    the frames behind them — which meant the per-topic sequence that exists
    precisely to reveal PUB/SUB drops was thrown away by the one process whose
    job is to miss nothing. The causal envelope would have shared that fate.

    Rendered as `key=value` pairs so the line stays greppable by eye and a new
    key can be added without breaking readers of the old ones.
    """
    seq = decode_sequence(frames)
    env = decode_envelope(frames)
    if seq is None and env is None:
        return None
    parts: list[str] = []
    if seq is not None:
        parts.append(f"seq={seq}")
        eseq = decode_publisher_sequence(frames)
        if eseq is not None:
            parts.append(f"eseq={eseq}")
    if env is not None:
        parts.append(f"msg={env.msg_id}")
        if env.causation_id:
            parts.append(f"cause={env.causation_id}")
        if env.correlation_id:
            parts.append(f"chain={env.correlation_id}")
    return " ".join(parts)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="EduMatcher audit logger")
    from edumatcher.cli_version import add_version_argument

    add_version_argument(parser, "pm-audit")
    parser.add_argument(
        "--audit-log-file",
        default=str(AUDIT_LOG_FILE),
        metavar="PATH",
        help=f"Audit-trail log file path (default: {AUDIT_LOG_FILE})",
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
    parser.add_argument(
        "--max-file-mb",
        type=int,
        default=_DEFAULT_MAX_FILE_MB,
        metavar="MB",
        help=f"Close the audit log as a day part at this size (default: {_DEFAULT_MAX_FILE_MB})",
    )
    parser.add_argument(
        "--keep-days",
        type=int,
        default=0,
        metavar="N",
        help="Delete archives older than N days (default: 0 = keep all)",
    )
    parser.add_argument(
        "--log-level",
        choices=["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"],
        help="Logging level override (default: WARNING)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="Increase log verbosity (-v: INFO, -vv: DEBUG)",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Reduce output to warnings/errors",
    )
    parser.add_argument(
        "--log-target",
        choices=["server", "stdout", "file"],
        default=None,
        help=(
            "Where this process's own operational log records go: "
            "server (default, auto-detected pm-log-srv), stdout, or file"
        ),
    )
    parser.add_argument(
        "--log-file",
        default=None,
        metavar="PATH",
        help="Operational log file path — required when --log-target file",
    )
    parser.add_argument(
        "--log-failover-timeout",
        type=float,
        default=None,
        metavar="SECONDS",
        help=(
            "Grace window before falling back to a local log file once "
            "pm-log-srv becomes unreachable (default: 30, from config)"
        ),
    )
    return parser


def _configure_logging(args: argparse.Namespace) -> int:
    log_level = getattr(args, "log_level", None)
    verbose = getattr(args, "verbose", 0)
    quiet = getattr(args, "quiet", False)

    if log_level:
        level_name = str(log_level).upper()
        level = getattr(logging, level_name, logging.WARNING)
    elif verbose >= 2:
        level = logging.DEBUG
    elif verbose == 1:
        level = logging.INFO
    elif quiet:
        level = logging.WARNING
    else:
        level = logging.WARNING

    client_config = load_default_log_client_config()
    server_config = load_default_log_server_config()
    failover_timeout = getattr(args, "log_failover_timeout", None)
    handler = resolve_handler(
        log_target=getattr(args, "log_target", None),
        log_file=getattr(args, "log_file", None),
        client_name=_CLIENT_NAME,
        instance=None,
        host=resolve_host_default(),
        port=server_config.port,
        connect_timeout_sec=client_config.connect_timeout_sec,
        failover_timeout_sec=(
            failover_timeout
            if failover_timeout is not None
            else client_config.failover_timeout_sec
        ),
        failover_dir=client_config.failover_dir,
    )
    logging.basicConfig(level=level, format=_LOG_FORMAT, handlers=[handler])
    return int(level)


class AuditProcess:
    def __init__(
        self,
        log_path: Path,
        to_terminal: bool,
        buffer_size: int = _DEFAULT_BUFFER_SIZE,
        flush_interval: float = _DEFAULT_FLUSH_INTERVAL,
        max_file_mb: int = _DEFAULT_MAX_FILE_MB,
        session_tz: tzinfo = timezone.utc,
        keep_days: int = 0,
    ) -> None:
        self._session_tz = session_tz
        self._keep_days = keep_days
        # Archiving: a child process, so compression stays off this process's
        # GIL and CPU and a crash in it cannot take the recorder down.
        self._archive_wanted = False
        self._archiver: subprocess.Popen[str] | None = None
        #: The running archiver's (stdout, stderr).
        self._archiver_output: tuple[IO[str], IO[str]] | None = None
        self._archives = 0
        self._archive_errors = 0
        self._archive_ratio = 0.0
        #: Wall clock; audit timestamps are wall time even under a fast
        #: simulation clock.  Replaceable so a test can cross midnight.
        self._now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)
        self._file = AuditFile(
            log_path,
            max_file_mb * 1024 * 1024,
            session_tz,
            on_day_closed=self._want_archive,
        )
        self._log_path = log_path
        self._to_terminal = to_terminal
        self._running = True
        #: The engine's ``system.eod`` has been recorded -- its last message,
        #: so a stopped receive loop knows there is nothing left to drain.
        self._eod_seen = False
        # Health beacon (operator dashboard §8.5), attached by main(); ticked
        # on the receive thread, which does the work (finding F7).
        self._reporter: HealthReporter | None = None
        self._records = 0
        self._bytes = 0
        self._decode_errors = 0
        # Subscribe to everything, with a deep receive buffer. Past the
        # high-water mark a SUB socket drops *silently*, and this is the one
        # process in the system whose whole job is to miss nothing: a hole in
        # the audit trail is invisible in the trail itself. ZMQ's default of
        # 1000 is a burst of well under a second at the engine's rate.
        self.sub = make_subscriber(ENGINE_PUB_ADDR, rcvhwm=_SUB_RCVHWM)
        # Bound, not connected: pm-audit-cli health's ZMQ ping is the only
        # thing that speaks to this socket, proving the receive loop itself
        # is alive rather than just the OS process.
        try:
            self.health_rep = make_replier(AUDIT_HEALTH_BIND_ADDR)
        except BaseException:
            self.sub.close()
            raise
        self.buffer_size = buffer_size
        self.flush_interval = flush_interval
        # (session-timezone date of receipt, line)
        self._buffer: list[tuple[str, str]] = []
        self._buffer_lock = threading.Lock()
        self._last_flush_time = time.time()
        self._flush_timer: threading.Timer | None = None
        self._debug_counts: defaultdict[str, int] = defaultdict(int)
        self._debug_last_summary = time.monotonic()
        self._last_day_check = time.monotonic()
        # A day that ended while pm-audit was down is closed before the first line.
        self._close_ended_day()

    def _dbg_count(self, key: str, amount: int = 1) -> None:
        if not log.isEnabledFor(logging.DEBUG):
            return
        self._debug_counts[key] += amount
        self._flush_debug_summary()

    def _flush_debug_summary(self, force: bool = False) -> None:
        if not log.isEnabledFor(logging.DEBUG):
            return
        now = time.monotonic()
        if not force and now - self._debug_last_summary < _DEBUG_SUMMARY_INTERVAL_SEC:
            return
        if not self._debug_counts:
            self._debug_last_summary = now
            return
        summary = ", ".join(
            f"{key}={value}" for key, value in sorted(self._debug_counts.items())
        )
        log.debug("audit flow summary: %s", summary)
        self._debug_counts.clear()
        self._debug_last_summary = now

    @staticmethod
    def _topic_family(topic: str) -> str:
        if topic.startswith(PREFIX_BOOK_SNAPSHOT):
            return "book"
        if topic.startswith("order."):
            return "order"
        if topic.startswith("quote."):
            return "quote"
        if topic.startswith("combo."):
            return "combo"
        if topic.startswith("oco."):
            return "oco"
        if topic.startswith("trade."):
            return "trade"
        if topic.startswith("session."):
            return "session"
        if topic.startswith("system."):
            return "system"
        if topic.startswith("risk."):
            return "risk"
        return "other"

    def _flush_buffer(self) -> None:
        """Flush buffered messages to disk."""
        with self._buffer_lock:
            self._flush_locked()

    def _flush_locked(self) -> None:
        if self._buffer:
            flushed = len(self._buffer)
            # Consecutive lines of one day go out in one write; a flush
            # that straddles midnight is split at the date change.
            for day, group in groupby(self._buffer, key=itemgetter(0)):
                lines = [line for _, line in group]
                self._file.write(day, lines)
                if self._to_terminal:
                    print("\n".join(lines))
            self._buffer.clear()
            self._last_flush_time = time.time()
            self._dbg_count("flush_calls")
            self._dbg_count("lines_flushed", flushed)

    def _close_ended_day(self) -> None:
        """Close the active file if it holds a day that has ended.

        Needed because a quiet exchange sends no line to trigger the date
        split in ``AuditFile.write``.
        """
        with self._buffer_lock:
            today = self._now().astimezone(self._session_tz).date().isoformat()
            # The ended day's buffered lines go out first, or they would
            # reopen it in the new audit.log.  Otherwise the buffer is left to
            # --buffer-size / --flush-interval.
            if self._buffer and self._buffer[0][0] < today:
                self._flush_locked()
            self._file.close_days_before(today)

    def _want_archive(self) -> None:
        """A day just closed (called under the buffer lock, from any thread)."""
        self._archive_wanted = True

    def _archiver_command(self) -> list[str]:
        return [
            "nice",
            "-n",
            "10",
            sys.executable,
            "-m",
            "edumatcher.audit.cli",
            "--log-file",
            str(self._log_path),
            "archive",
            "--pending",
            "--keep-days",
            str(self._keep_days),
        ]

    def _service_archiver(self) -> None:
        """Reap a finished archiver, then start one if a day closed meanwhile.

        Runs on the receive thread.  At most one archiver runs at a time; a
        day that closes while one runs is picked up by the next, since
        ``--pending`` takes every closed day it finds.
        """
        child = self._archiver
        if child is not None:
            if child.poll() is None:
                return
            assert self._archiver_output is not None
            out, err = (self._read_archiver_output(fh) for fh in self._archiver_output)
            self._archiver = None
            self._archiver_output = None
            if child.returncode != 0:
                self._archive_errors += 1
                log.error("audit archiver exited %s: %s", child.returncode, err.strip())
            for line in out.splitlines():
                if (ratio := parse_ratio(line)) is not None:
                    self._archives += 1
                    self._archive_ratio = ratio
                    log.info("audit archive: %s", line.strip())
        if self._archive_wanted and self._archiver is None:
            self._archive_wanted = False
            # Unlinked temp files, not pipes: a child that outlives this
            # process (shutdown does not stop it) can still print its result,
            # and its output is read only once it has exited.
            self._archiver_output = (
                tempfile.TemporaryFile("w+"),
                tempfile.TemporaryFile("w+"),
            )
            try:
                self._archiver = subprocess.Popen(
                    self._archiver_command(),
                    stdout=self._archiver_output[0],
                    stderr=self._archiver_output[1],
                    text=True,
                )
            except OSError as exc:
                for fh in self._archiver_output:
                    fh.close()
                self._archiver_output = None
                self._archive_errors += 1
                log.error("cannot start the audit archiver: %s", exc)

    @staticmethod
    def _read_archiver_output(fh: IO[str]) -> str:
        with fh:
            fh.seek(0)
            return fh.read()

    def _schedule_flush(self) -> None:
        """Schedule a flush after flush_interval seconds."""
        if self._flush_timer is not None:
            self._flush_timer.cancel()
        self._flush_timer = threading.Timer(self.flush_interval, self._flush_buffer)
        self._flush_timer.daemon = True
        self._flush_timer.start()
        self._dbg_count("flush_timer_scheduled")

    def _add_to_buffer(self, day: str, line: str) -> None:
        """Add a line to the buffer and flush if needed."""
        with self._buffer_lock:
            self._buffer.append((day, line))
            buffer_len = len(self._buffer)
        self._dbg_count("messages_buffered")

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
        poller.register(self.health_rep, zmq.POLLIN)
        log.debug("audit receive loop enabled")
        reporter = self._reporter
        while self._running:
            if reporter is not None:
                reporter.tick_and_publish(self.metric_samples)
            if time.monotonic() - self._last_day_check >= _DAY_CHECK_INTERVAL_SEC:
                self._last_day_check = time.monotonic()
                self._close_ended_day()
                self._service_archiver()
            try:
                socks = dict(poller.poll(timeout=_POLL_TIMEOUT_MS))
            except zmq.ZMQError as exc:
                if exc.errno != errno.EINTR:
                    raise
                break  # EINTR — honour _running flag
            if self.health_rep in socks:
                answer_health_ping(self.health_rep, log)
            if self.sub in socks:
                self._receive_one_message()
        self._drain()

    def _receive_one_message(self) -> None:
        frames = self.sub.recv_multipart()
        try:
            topic, payload = decode(frames)
            if topic == TOPIC_EOD:
                self._eod_seen = True
            self._dbg_count("messages_received")
            self._dbg_count(f"topic_family_{self._topic_family(topic)}")
            now = self._now()
            ts = now.isoformat(timespec="milliseconds")
            day = now.astimezone(self._session_tz).date().isoformat()
            meta = _meta_section(frames)
            if meta is None:
                self._dbg_count("messages_without_envelope")
                line = f"[{ts}] [{topic}] {json.dumps(payload)}"
            else:
                line = f"[{ts}] [{topic}] [{meta}] {json.dumps(payload)}"
            self._add_to_buffer(day, line)
            self._records += 1
            self._bytes += len(line) + 1  # the newline written with it
        except Exception as exc:
            # Never let a single bad message kill the receive loop
            self._dbg_count("decode_errors")
            self._decode_errors += 1
            log.warning("failed to decode/log message: %s", exc)

    def _drain(self) -> None:
        """After a stop, keep recording until the engine's ``system.eod``.

        A stop arrives while the engine is still shutting down: it saves its
        state, publishes the EOD book checkpoints (S25), and ends with
        ``system.eod``. Leaving the loop at once cut that round out of the
        trail (X34: one checkpoint of 300 recorded, G3 failed on a book the
        engine kept perfectly). ``system.eod`` is the engine's last message,
        so reading up to it loses nothing; bounded by _DRAIN_SEC so a live
        engine (a lone pm-audit restart) cannot hold the shutdown open, and
        run() joins this thread for a second longer than that.
        """
        deadline = time.monotonic() + _DRAIN_SEC
        while not self._eod_seen and time.monotonic() < deadline:
            if self.sub.poll(timeout=50):
                self._receive_one_message()

    def run(self) -> None:
        signal.signal(signal.SIGINT, lambda *_: self._stop())
        signal.signal(signal.SIGTERM, lambda *_: self._stop())

        # Catch up on days closed while pm-audit was down or whose archive failed.
        self._archive_wanted = True
        t = threading.Thread(target=self._receive, daemon=True)
        t.start()
        log.info(
            "starting audit runtime log_file=%s terminal=%s buffer_size=%d flush_interval=%ss pub=%s health=%s",
            self._log_path,
            self._to_terminal,
            self.buffer_size,
            self.flush_interval,
            ENGINE_PUB_ADDR,
            AUDIT_HEALTH_BIND_ADDR,
        )
        log.info("pm-audit waiting for pm-engine events")
        try:
            while self._running:
                t.join(timeout=_JOIN_POLL_SEC)  # re-check _running every 500 ms
        finally:
            # The receive loop stops first (draining up to _DRAIN_SEC for the
            # engine's system.eod), so no line arrives after the last flush
            # or is written to the closed file.
            t.join(timeout=_DRAIN_SEC + 1.0)
            if self._flush_timer is not None:
                self._flush_timer.cancel()
            self._flush_buffer()
            self._file.close()
            self._flush_debug_summary(force=True)
            if self._reporter is not None:
                self._reporter.stop()
            self.sub.close()
            self.health_rep.close()
            log.info("audit process shutdown complete")

    def _stop(self) -> None:
        self._running = False
        log.info("stop requested")

    def attach_reporter(self, reporter: HealthReporter) -> None:
        """Ship this process's health beacon through ``reporter`` (main())."""
        self._reporter = reporter

    def metric_samples(self) -> list[MetricSample]:
        """Design §8.5: records and bytes accepted for the audit file."""
        return [
            counter("audit.records", self._records),
            counter("audit.bytes", self._bytes),
            counter("audit.decode_errors", self._decode_errors),
            counter("audit.archives", self._archives),
            counter("audit.archive_errors", self._archive_errors),
            gauge("audit.archive_ratio", self._archive_ratio),
        ]


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    log_level = _configure_logging(args)
    log.info("starting pm-audit with log level %s", logging.getLevelName(log_level))
    log.debug(
        "resolved audit config: audit_log_file=%s terminal=%s buffer_size=%d "
        "flush_interval=%s max_file_mb=%d",
        args.audit_log_file,
        args.terminal,
        args.buffer_size,
        args.flush_interval,
        args.max_file_mb,
    )

    # Validate arguments
    if args.buffer_size < 1:
        parser.error("--buffer-size must be at least 1")
    if args.flush_interval <= 0:
        parser.error("--flush-interval must be positive")
    if args.max_file_mb < 1:
        parser.error("--max-file-mb must be at least 1")
    if args.keep_days < 0:
        parser.error("--keep-days must be >= 0")

    try:
        session_tz = session_timezone()
    except ValueError as exc:
        parser.error(str(exc))
    try:
        process = AuditProcess(
            Path(args.audit_log_file),
            args.terminal,
            buffer_size=args.buffer_size,
            flush_interval=args.flush_interval,
            max_file_mb=args.max_file_mb,
            session_tz=session_tz,
            keep_days=args.keep_days,
        )
    except Exception as exc:
        log.error("fatal startup error: %s", exc)
        sys.exit(1)
    reporter = HealthReporter.start_from_compiled_config(_CLIENT_NAME)
    if reporter is not None:
        process.attach_reporter(reporter)
    process.run()


if __name__ == "__main__":
    main()
