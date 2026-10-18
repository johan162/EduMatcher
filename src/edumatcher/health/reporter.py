"""``HealthReporter``: the health beacon every long-running process sends.

See docs-design/EduMatcher-Operator-Dashboard.md §7. Three lines wire it into
a process::

    reporter = HealthReporter.from_compiled_config("pm-engine")
    if reporter is not None:
        reporter.start()
    ...
    while running:
        if reporter is not None:
            reporter.tick()
            if reporter.due():
                reporter.publish(my_samples())
        ...
    if reporter is not None:
        reporter.stop()

Why two halves
--------------
``tick()``, ``due()`` and ``publish()`` run on the process's **main loop** and
only store floats and one tuple reference. A daemon **sampler thread** owns
the ZeroMQ socket, reads ``psutil`` and builds and sends the beacon. If the
main loop hangs, the thread keeps reporting with a growing ``loop_age_ms``,
which is what lets pm-monitor tell HUNG from SILENT from DEAD. A beacon built
on the main loop would simply stop.

The thread never reads application objects -- only the floats ``tick()``
writes and the tuple ``publish()`` hands over -- so there is no lock and no
``dict changed size during iteration``. Each of those values has exactly one
writer, and a float or reference assignment is atomic under the GIL.

A down pm-monitor never slows the process: the socket sends non-blocking with
a small high-water mark, and a beacon that does not fit is dropped and counted
in ``health.beacons_dropped``.
"""

from __future__ import annotations

import gc
import logging
import os
import secrets
import socket
import threading
import time
from collections.abc import Callable, Sequence

import psutil
import zmq

from edumatcher.health.samples import counter
from edumatcher.models.generated._runtime import MessageValidationError
from edumatcher.models.generated.health import MetricSample, make_health_beacon
from edumatcher.monitor.config import load_default_monitor_config

log = logging.getLogger(__name__)

#: Beacons queued for a slow or absent pm-monitor before new ones are dropped.
SNDHWM = 10
#: How long ``stop()`` lets the final beacon drain before closing the socket.
#: The design's LINGER 0 holds for every other beacon; the last one is the
#: only one whose loss changes a verdict (STOPPED instead of DEAD).
FINAL_LINGER_MS = 500
#: At most one warning per this many seconds from the sampler thread, so a
#: down pm-monitor cannot flood the log server.
WARN_EVERY_SEC = 60.0
#: Bound on the host field, as LogRow.host (spec/messages/health.yaml).
MAX_HOST_LEN = 128


class HealthReporter:
    """Samples this process and PUSHes ``health.beacon`` every interval."""

    def __init__(
        self,
        process: str,
        instance: str | None = None,
        *,
        host: str,
        port: int,
        interval_sec: float,
    ) -> None:
        if interval_sec <= 0:
            raise ValueError("interval_sec must be > 0")
        self.process = process
        self.instance = instance
        self.interval_sec = float(interval_sec)
        self.endpoint = f"tcp://{host}:{port}"
        self.boot_id = secrets.token_hex(8)

        # Written by the main loop only.
        self._last_tick = time.monotonic()
        self._max_gap = 0.0
        self._gap_epoch_seen = 0
        self._next_due = 0.0
        self._samples: tuple[MetricSample, ...] = ()

        # Written by the sampler thread only.
        self._gap_epoch = 0
        self._seq = 0
        self._beacons_dropped = 0
        self._samples_rejected = 0
        self._last_warning = float("-inf")

        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @classmethod
    def from_compiled_config(
        cls, process: str, instance: str | None = None
    ) -> HealthReporter | None:
        """A reporter for the deployed ``monitor`` section, or ``None`` when
        monitoring is disabled. A process then simply runs without one."""
        cfg = load_default_monitor_config()
        if not cfg.enabled:
            return None
        return cls(
            process,
            instance,
            host=cfg.host,
            port=cfg.pull_port,
            interval_sec=cfg.beacon_interval_sec,
        )

    @classmethod
    def start_from_compiled_config(
        cls, process: str, instance: str | None = None
    ) -> HealthReporter | None:
        """``from_compiled_config`` + ``start``: what a process's ``main()``
        calls. ``None`` when monitoring is disabled."""
        reporter = cls.from_compiled_config(process, instance)
        if reporter is not None:
            reporter.start()
        return reporter

    # ------------------------------------------------------------------
    # main-loop half
    # ------------------------------------------------------------------

    def tick_and_publish(self, samples: Callable[[], Sequence[MetricSample]]) -> None:
        """``tick()``, then ``publish(samples())`` when due -- the one call a
        service loop makes per iteration. ``samples`` runs on the calling
        (main-loop) thread, so it may read the process's own state freely."""
        self.tick()
        if time.monotonic() >= self._next_due:
            self.publish(samples())

    def start(self) -> None:
        """Start the sampler thread. The first beacon goes out immediately."""
        if self._thread is not None:
            return
        self._last_tick = time.monotonic()
        self._thread = threading.Thread(
            target=self._run, name=f"health-{self.process}", daemon=True
        )
        self._thread.start()

    def tick(self) -> None:
        """Record that the main loop completed an iteration.

        Called once per iteration, so it does nothing but arithmetic on
        floats: no allocation, no lock, no socket.
        """
        now = time.monotonic()
        if self._gap_epoch_seen != self._gap_epoch:
            # The sampler has reported the previous interval's worst gap.
            self._gap_epoch_seen = self._gap_epoch
            self._max_gap = 0.0
        gap = now - self._last_tick
        if gap > self._max_gap:
            self._max_gap = gap
        self._last_tick = now

    def due(self) -> bool:
        """True when a fresh set of application metrics should be published."""
        return time.monotonic() >= self._next_due

    def publish(self, samples: Sequence[MetricSample]) -> None:
        """Hand the latest application metrics to the sampler thread."""
        self._samples = tuple(samples)
        self._next_due = time.monotonic() + self.interval_sec

    def stop(self) -> None:
        """Send a final beacon (``final=True``) and stop the thread.

        Returns within about a second even when pm-monitor is unreachable.
        """
        thread = self._thread
        if thread is None:
            return
        self._stop.set()
        thread.join(timeout=FINAL_LINGER_MS / 1000 + 0.5)
        self._thread = None

    # ------------------------------------------------------------------
    # sampler-thread half
    # ------------------------------------------------------------------

    def _run(self) -> None:
        # Created in the thread that uses it: ZeroMQ sockets are not
        # thread-safe (see log_srv/pubsub.py).
        sock: zmq.Socket[bytes] = zmq.Context.instance().socket(zmq.PUSH)
        sock.setsockopt(zmq.SNDHWM, SNDHWM)
        sock.setsockopt(zmq.LINGER, 0)
        sock.connect(self.endpoint)

        proc = psutil.Process(os.getpid())
        proc.cpu_percent(None)  # the first call always returns 0.0
        started_at_ns = int(proc.create_time() * 1_000_000_000)
        host = (socket.gethostname() or "unknown")[:MAX_HOST_LEN]

        try:
            while not self._stop.is_set():
                self._send_safely(sock, proc, host, started_at_ns, final=False)
                self._stop.wait(self.interval_sec)
            self._send_safely(sock, proc, host, started_at_ns, final=True)
        finally:
            sock.close(linger=FINAL_LINGER_MS)

    def _send_safely(
        self,
        sock: zmq.Socket[bytes],
        proc: psutil.Process,
        host: str,
        started_at_ns: int,
        *,
        final: bool,
    ) -> None:
        try:
            self._send(sock, proc, host, started_at_ns, final=final)
        except Exception as exc:  # the thread must outlive any bug
            self._warn("health beacon failed: %s", exc)

    def _send(
        self,
        sock: zmq.Socket[bytes],
        proc: psutil.Process,
        host: str,
        started_at_ns: int,
        *,
        final: bool,
    ) -> None:
        now = time.monotonic()
        loop_age = max(0.0, now - self._last_tick)
        loop_lag = self._max_gap
        self._gap_epoch += 1

        metrics = [s.to_dict() for s in self._valid_samples()]
        metrics.append(
            counter("health.beacons_dropped", self._beacons_dropped).to_dict()
        )
        metrics.append(
            counter("health.samples_rejected", self._samples_rejected).to_dict()
        )
        metrics.append(
            counter("health.gc_gen2", gc.get_stats()[2]["collections"]).to_dict()
        )

        with proc.oneshot():
            rss = proc.memory_info().rss
            cpu = proc.cpu_percent(None)
            threads = proc.num_threads()
            fds = proc.num_fds() if hasattr(proc, "num_fds") else None

        try:
            frames = make_health_beacon(
                process=self.process,
                instance=self.instance,
                pid=proc.pid,
                host=host,
                boot_id=self.boot_id,
                seq=self._seq,
                started_at_ns=started_at_ns,
                interval_sec=self.interval_sec,
                rss_bytes=rss,
                cpu_pct=cpu,
                threads=threads,
                fds=fds,
                loop_age_ms=loop_age * 1000.0,
                loop_lag_ms=loop_lag * 1000.0,
                final=final,
                metrics=metrics,
            )
        except MessageValidationError as exc:
            self._beacons_dropped += 1
            self._warn("health beacon invalid, dropped: %s", exc)
            return
        self._seq += 1
        try:
            sock.send_multipart(frames, flags=zmq.NOBLOCK)
        except zmq.Again:
            self._beacons_dropped += 1
            self._warn(
                "pm-monitor at %s not accepting beacons (%d dropped so far)",
                self.endpoint,
                self._beacons_dropped,
            )

    def _valid_samples(self) -> list[MetricSample]:
        """The published samples that pass the spec; the rest are counted.

        One bad label must cost one sample, not the whole beacon -- a beacon
        that never validates would turn a labelling bug into a SILENT process.
        """
        valid: list[MetricSample] = []
        for sample in self._samples:
            try:
                sample.validate()
            except MessageValidationError as exc:
                self._samples_rejected += 1
                self._warn("health sample %r rejected: %s", sample.name, exc)
                continue
            valid.append(sample)
        return valid

    def _warn(self, msg: str, *args: object) -> None:
        now = time.monotonic()
        if now - self._last_warning >= WARN_EVERY_SEC:
            self._last_warning = now
            log.warning(msg, *args)
