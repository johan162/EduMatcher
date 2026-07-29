"""Auto-detection of ``pm-log-srv`` for every ``pm-*`` process (§8.3).

:func:`resolve_handler` is the single integration point each process's
``_configure_logging()`` calls to decide where its root logger's records
should go — a plain ``StreamHandler``/``FileHandler`` (today's behaviour,
or an explicit ``--log-target`` override) or a live ``TcpLogHandler``
talking to a detected ``pm-log-srv`` (§8.2).
"""

from __future__ import annotations

import logging
import os
import socket
import sys
from pathlib import Path
from typing import TextIO

from edumatcher.logclient.handler import TcpLogHandler
from edumatcher.logclient.protocol import (
    LalfProtocolError,
    build_hello_frame,
    parse_header_line,
    parse_welcome,
)

_RECV_BUFFER_BYTES = 4096


def _probe_server(
    host: str,
    port: int,
    client: str,
    instance: str | None,
    connect_timeout_sec: float,
) -> bool:
    """One-shot check: does ``HELLO``/``WELCOME`` succeed against host:port?

    This probe opens its own short-lived socket purely to decide whether a
    server is present (§8.3, step 2-3) — it is not reused by
    :class:`TcpLogHandler`, which opens its own connection once attached.
    """
    try:
        with socket.create_connection(
            (host, port), timeout=connect_timeout_sec
        ) as sock:
            sock.sendall(
                build_hello_frame(
                    client=client,
                    pid=os.getpid(),
                    host=socket.gethostname(),
                    instance=instance,
                )
            )
            sock.settimeout(connect_timeout_sec)
            welcome_bytes = sock.recv(_RECV_BUFFER_BYTES)
        line = welcome_bytes.decode("utf-8", errors="replace")
        msg_type, fields = parse_header_line(line)
        if msg_type != "WELCOME":
            return False
        parse_welcome(fields)
        return True
    except (OSError, LalfProtocolError, ValueError):
        return False


def resolve_handler(
    *,
    log_target: str | None,
    log_file: str | None,
    client_name: str,
    instance: str | None,
    host: str,
    port: int,
    connect_timeout_sec: float,
    failover_timeout_sec: float,
    failover_dir: Path | str,
    fallback_stream: TextIO | None = None,
) -> logging.Handler:
    """Resolve which ``logging.Handler`` this process should use (§8.3).

    ``log_target`` is the resolved ``--log-target`` value (``None`` means
    unset/default, i.e. auto-detect). ``log_file`` is required and used
    only when ``log_target == "file"``. ``fallback_stream`` is where log
    records go when ``log_target`` is unset/"server" and no server is
    detected (default: ``sys.stdout``, resolved at call time); pass
    ``sys.stderr`` for processes that reserve stdout for piped data output.
    """
    if fallback_stream is None:
        fallback_stream = sys.stdout
    if log_target == "stdout":
        return logging.StreamHandler(stream=sys.stdout)

    if log_target == "file":
        if not log_file:
            raise ValueError("--log-file is required when --log-target file")
        return logging.FileHandler(log_file, encoding="utf-8")

    # log_target is None (default) or explicitly "server": probe first.
    detected = _probe_server(host, port, client_name, instance, connect_timeout_sec)

    if detected:
        return TcpLogHandler(
            host,
            port,
            client_name,
            instance,
            connect_timeout_sec=connect_timeout_sec,
            failover_timeout_sec=failover_timeout_sec,
            failover_dir=failover_dir,
        )

    if log_target == "server":
        # Explicit request for the server target that could not be
        # satisfied — a real error the user should see (§8.3, step 5).
        fallback_name = "stderr" if fallback_stream is sys.stderr else "stdout"
        print(
            f"pm-log-srv not reachable at {host}:{port}, "
            f"falling back to {fallback_name}",
            file=sys.stderr,
        )

    # log_target is None (unset) or "server" (unreachable): fall back to
    # today's plain stdout behaviour, silently in the unset case (§8.3,
    # step 4) — "no log server running" is a normal, common condition.
    return logging.StreamHandler(stream=fallback_stream)
