"""Swarm launcher for autonomous AI traders.

Usage examples:
  poetry run pm-ai-swarm --count 10 --duration 30
  poetry run pm-ai-swarm --count 30 --symbols AAPL,MSFT,TSLA
"""

from __future__ import annotations

import argparse
import logging
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path

from edumatcher.ai_trader.personality import available_profiles
from edumatcher.config import ENGINE_CONFIG_FILE
from edumatcher.engine.config_loader import load_engine_config

log = logging.getLogger(__name__)


def build_gateway_ids(prefix: str, start_index: int, count: int) -> list[str]:
    return [f"{prefix}{i:02d}" for i in range(start_index, start_index + count)]


def assign_primary_symbols(
    gateway_ids: list[str], symbols: list[str]
) -> dict[str, str]:
    if not symbols:
        raise ValueError("At least one symbol is required for swarm assignment")
    out: dict[str, str] = {}
    for i, gw in enumerate(gateway_ids):
        out[gw] = symbols[i % len(symbols)].upper()
    return out


def _parse_profile_cycle(raw: str) -> list[str]:
    if not raw.strip():
        return available_profiles()
    values = [x.strip().lower() for x in raw.split(",") if x.strip()]
    allowed = set(available_profiles())
    invalid = [v for v in values if v not in allowed]
    if invalid:
        raise ValueError(f"Unknown profile(s): {', '.join(invalid)}")
    if not values:
        return available_profiles()
    return values


def _load_symbols(symbols_arg: str, config_path: Path) -> list[str]:
    if symbols_arg.strip():
        return [s.strip().upper() for s in symbols_arg.split(",") if s.strip()]
    cfg = load_engine_config(config_path)
    return sorted(cfg.allowed_symbols)


def build_bot_command(
    python_executable: str,
    gateway_id: str,
    profile: str,
    symbol: str,
    seed: int,
    duration: float,
    run_id: str,
    max_position: int,
    max_rejects: int,
    reject_window: float,
    reject_cooldown: float,
    stale_data: float,
) -> list[str]:
    return [
        python_executable,
        "-m",
        "edumatcher.ai_trader.main",
        "--id",
        gateway_id,
        "--profile",
        profile,
        "--symbols",
        symbol,
        "--seed",
        str(seed),
        "--duration",
        str(duration),
        "--run-id",
        run_id,
        "--max-position",
        str(max_position),
        "--max-rejects",
        str(max_rejects),
        "--reject-window",
        str(reject_window),
        "--reject-cooldown",
        str(reject_cooldown),
        "--stale-data",
        str(stale_data),
    ]


def _configure_logging(args: argparse.Namespace) -> int:
    log_level = getattr(args, "log_level", None)
    verbose = int(getattr(args, "verbose", 0) or 0)
    quiet = bool(getattr(args, "quiet", False))

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

    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
        stream=sys.stdout,
    )
    return int(level)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="EduMatcher AI trader swarm launcher")
    from edumatcher.cli_version import add_version_argument

    add_version_argument(parser, "pm-ai-swarm")
    parser.add_argument(
        "--count", type=int, default=10, help="Number of bots to launch"
    )
    parser.add_argument("--prefix", default="AI", help="Gateway id prefix, e.g. AI")
    parser.add_argument("--start-index", type=int, default=1)
    parser.add_argument(
        "--profiles",
        default="",
        help="Comma-separated profile cycle. Default: all available profiles",
    )
    parser.add_argument(
        "--symbols",
        default="",
        help="Comma-separated symbols; default loads all symbols from engine config",
    )
    parser.add_argument(
        "--config",
        default=str(ENGINE_CONFIG_FILE),
        help="Engine config path used to discover symbols",
    )
    parser.add_argument("--seed-base", type=int, default=1000)
    parser.add_argument("--duration", type=float, default=60.0)
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--max-position", type=int, default=1000)
    parser.add_argument("--max-rejects", type=int, default=25)
    parser.add_argument("--reject-window", type=float, default=10.0)
    parser.add_argument("--reject-cooldown", type=float, default=5.0)
    parser.add_argument("--stale-data", type=float, default=4.0)
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
        help="Increase verbosity (-v: INFO, -vv: DEBUG); forwarded to child bots",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Reduce output to warnings/errors; forwarded to child bots",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    resolved_level = _configure_logging(args)
    log.info(
        "starting pm-ai-swarm with log level %s",
        logging.getLevelName(resolved_level),
    )
    if args.count <= 0:
        log.error("invalid startup value: --count must be > 0 (got %s)", args.count)
        raise SystemExit("--count must be > 0")

    config_path = Path(str(args.config))
    symbols = _load_symbols(str(args.symbols), config_path)
    if not symbols:
        log.error("no symbols available for swarm")
        raise SystemExit("No symbols available for swarm")

    profiles = _parse_profile_cycle(str(args.profiles))
    gateway_ids = build_gateway_ids(
        str(args.prefix).upper(), int(args.start_index), int(args.count)
    )
    symbol_by_gw = assign_primary_symbols(gateway_ids, symbols)
    run_id = f"swarm-{uuid.uuid4().hex[:8]}"
    child_verbose = int(getattr(args, "verbose", 0) or 0)
    child_quiet = bool(getattr(args, "quiet", False))
    child_log_level = str(getattr(args, "log_level", "") or "")

    procs: list[subprocess.Popen[bytes]] = []
    print(f"[SWARM] run_id={run_id} count={len(gateway_ids)} symbols={len(symbols)}")
    log.info(
        "swarm resolved config run_id=%s count=%s symbols=%s profiles=%s",
        run_id,
        len(gateway_ids),
        len(symbols),
        ",".join(profiles),
    )

    try:
        for i, gw in enumerate(gateway_ids):
            profile = profiles[i % len(profiles)]
            symbol = symbol_by_gw[gw]
            cmd = build_bot_command(
                python_executable=str(args.python),
                gateway_id=gw,
                profile=profile,
                symbol=symbol,
                seed=int(args.seed_base) + i,
                duration=float(args.duration),
                run_id=run_id,
                max_position=int(args.max_position),
                max_rejects=int(args.max_rejects),
                reject_window=float(args.reject_window),
                reject_cooldown=float(args.reject_cooldown),
                stale_data=float(args.stale_data),
            )
            if child_log_level:
                cmd.extend(["--log-level", child_log_level])
            if child_verbose > 0:
                cmd.extend(["-" + ("v" * child_verbose)])
            if child_quiet:
                cmd.append("-q")
            print(f"[SWARM] launching {gw} profile={profile} symbol={symbol}")
            log.debug("launch command for %s: %s", gw, " ".join(cmd))
            procs.append(subprocess.Popen(cmd))
            time.sleep(0.02)

        exit_code = 0
        for p in procs:
            rc = p.wait()
            if rc != 0:
                exit_code = rc
                log.warning("child process exited non-zero rc=%s", rc)

        log.info("swarm finished run_id=%s exit_code=%s", run_id, exit_code)
        raise SystemExit(exit_code)
    except KeyboardInterrupt:
        log.info("swarm interrupted; stopping bots")
        print("\n[SWARM] interrupted; stopping bots...")
        for p in procs:
            if p.poll() is None:
                p.send_signal(signal.SIGTERM)
        deadline = time.monotonic() + 2.0
        for p in procs:
            if p.poll() is not None:
                continue
            timeout = max(0.0, deadline - time.monotonic())
            if timeout == 0.0:
                break
            try:
                p.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                pass
        for p in procs:
            if p.poll() is None:
                p.kill()
        log.info("swarm shutdown complete after interrupt")
        raise SystemExit(130)
