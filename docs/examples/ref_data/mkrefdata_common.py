#!/usr/bin/env python3
"""Central generator for the s1/s3/s10/s30 *-setup reference-data examples.

Every s{N}-{basic,nominal,complex}[-nomm]-setup directory under
docs/examples/ref_data/ delegates here via a one-line mkrefdata.sh wrapper
that passes its own directory as the first argument. All per-setup
behaviour (symbol count, trader/market-maker count, profile flags, combo
generation) is derived from that directory name -- the directories
themselves hold only the generated engine_config.yaml and a README.
Mirrors the pattern already used by mks150.sh / mks300.sh for the larger
s150-*/s300-* setups.
"""

from __future__ import annotations

import argparse
import random
import re
import shutil
import subprocess
import sys
from pathlib import Path

# Ticker -> outstanding shares, in the canonical symbol order used by every
# s1/s3/s10/s30 setup. Only the first N are used for a given setup size.
OUTSTANDING_SHARES = {
    "AAPL": 15_400_000_000,
    "MSFT": 7_430_000_000,
    "TSLA": 3_200_000_000,
    "AMZN": 10_600_000_000,
    "GOOGL": 12_200_000_000,
    "META": 2_560_000_000,
    "NVDA": 24_600_000_000,
    "NFLX": 430_000_000,
    "INTC": 4_300_000_000,
    "ORCL": 2_800_000_000,
    "IBM": 910_000_000,
    "ADBE": 460_000_000,
    "CRM": 970_000_000,
    "QCOM": 1_690_000_000,
    "AMD": 1_620_000_000,
    "AVGO": 4_700_000_000,
    "TXN": 910_000_000,
    "NOW": 205_000_000,
    "SHOP": 1_320_000_000,
    "UBER": 2_130_000_000,
    "PYPL": 1_080_000_000,
    "SQ": 600_000_000,
    "BABA": 2_200_000_000,
    "SONY": 1_240_000_000,
    "SAP": 1_150_000_000,
    "ASML": 415_000_000,
    "CSCO": 4_060_000_000,
    "MU": 1_100_000_000,
    "BKNG": 44_000_000,
    "TSM": 5_180_000_000,
}
CANONICAL_SYMBOLS = list(OUTSTANDING_SHARES)

SETUP_RE = re.compile(r"^s(\d+)-(basic|nominal|complex)(-nomm)?-setup$")

POST_TRADE_MARKET_DATA_TAIL_SMALL = [
    "--post-trade-gateway",
    "--post-trade-bind-address",
    "0.0.0.0",
    "--post-trade-port",
    "5580",
    "--post-trade-replay-retention-sec",
    "3600",
    "--post-trade-heartbeat-interval-sec",
    "1",
    "--post-trade-idle-timeout-sec",
    "10",
    "--post-trade-max-client-queue",
    "5000",
    "--post-trade-allowed-roles",
    "CLEARING",
    "DROP_COPY",
    "AUDIT",
    "--market-data-gateway",
    "--market-data-enabled",
    "--market-data-name",
    "md-gwy01",
    "--market-data-bind-address",
    "0.0.0.0",
    "--market-data-port",
    "5570",
    "--market-data-heartbeat-interval-sec",
    "1",
    "--market-data-idle-timeout-sec",
    "5",
    "--market-data-replay-window-sec",
    "30",
    "--market-data-max-symbols-per-client",
    "200",
    "--market-data-max-client-queue",
    "10000",
]

COMPLEX_SCHEDULE = [
    "--sessions-enabled",
    "--schedule",
    "--pre-open",
    "08:45",
    "--opening-auction",
    "08:55",
    "--continuous",
    "09:00",
    "--closing-auction",
    "16:00",
    "--closing-end",
    "16:10",
    "--snapshot-interval",
    "0.25",
    "--quote-history-maxlen",
    "30",
    "--drop-copy-buffer-size",
    "10000",
    "--recent-trades-maxlen",
    "20",
    "--depth-snapshot-tolerance-ticks",
    "100",
    "--static-band",
    "0.20",
    "--dynamic-band",
    "0.02",
    "--risk-level",
    "CORE:0.18:0.02",
    "--risk-level",
    "HIGH_BETA:0.12:0.04",
    "--cb-levels",
    "L1:0.07:5",
    "L2:0.13:15",
    "L3:0.20:0",
    "--cb-window-ns",
    "300000000000",
]

POST_TRADE_MARKET_DATA_TAIL_COMPLEX = [
    "--post-trade-gateway",
    "--post-trade-name",
    "ralf-gwy01",
    "--post-trade-bind-address",
    "0.0.0.0",
    "--post-trade-port",
    "5580",
    "--post-trade-replay-retention-sec",
    "14400",
    "--post-trade-heartbeat-interval-sec",
    "1",
    "--post-trade-idle-timeout-sec",
    "10",
    "--post-trade-max-client-queue",
    "8000",
    "--post-trade-allowed-roles",
    "CLEARING",
    "DROP_COPY",
    "AUDIT",
    "--market-data-gateway",
    "--market-data-enabled",
    "--market-data-name",
    "md-gwy01",
    "--market-data-bind-address",
    "0.0.0.0",
    "--market-data-port",
    "5570",
    "--market-data-heartbeat-interval-sec",
    "1",
    "--market-data-idle-timeout-sec",
    "5",
    "--market-data-replay-window-sec",
    "120",
    "--market-data-max-symbols-per-client",
    "500",
    "--market-data-max-client-queue",
    "20000",
]


def parse_setup_dir(setup_dir: Path) -> tuple[int, str, bool]:
    m = SETUP_RE.match(setup_dir.name)
    if not m:
        sys.exit(f"Error: unsupported setup directory: {setup_dir.name}")
    size, profile, nomm = int(m.group(1)), m.group(2), bool(m.group(3))
    if size > len(CANONICAL_SYMBOLS):
        sys.exit(f"Error: no outstanding-shares data for {size} symbols")
    return size, profile, not nomm  # size, profile, seed_quotes


def existing_seed(config_path: Path) -> int | None:
    """Pull the --seed value out of a previously generated config's header
    comment, so re-running without --seed reproduces the same book instead
    of drawing a new random one."""
    if not config_path.exists():
        return None
    header_words = []
    with config_path.open() as f:
        for line in f:
            if not line.startswith("#"):
                break
            word = line[1:].strip()
            if word.endswith("\\"):  # the command block wraps long lines with a
                word = word[:-1].rstrip()  # trailing "\"; drop it so a wrap
            header_words.append(word)  # between --seed and its value still joins.
    m = re.search(r"--seed\s+(-?\d+)\b", " ".join(header_words))
    return int(m.group(1)) if m else None


def resolve_config_gen() -> list[str]:
    if shutil.which("pm-config-gen"):
        return ["pm-config-gen"]
    if shutil.which("poetry"):
        return ["poetry", "run", "pm-config-gen"]
    sys.exit("Error: neither pm-config-gen nor poetry is available in PATH")


def build_gateways(profile: str) -> tuple[list[str], list[str], list[str]]:
    trader_count = 2 if profile in ("basic", "nominal") else 5
    trader_ids = [f"TRADER{n:02d}" for n in range(1, trader_count + 1)]
    gateways = [
        f"{tid}:TRADER:CANCEL_ALL:Student desk {n}"
        for n, tid in enumerate(trader_ids, 1)
    ]
    gateways.append("OPS01:ADMIN:LEAVE_ALL:Instructor console")
    if profile == "complex":
        mm_ids = ["MM01", "MM02"]
        gateways += [
            "MM01:MARKET_MAKER:CANCEL_QUOTES_ONLY:Primary market maker",
            "MM02:MARKET_MAKER:CANCEL_QUOTES_ONLY:Backup market maker",
        ]
    else:
        mm_ids = ["MM01"]
        gateways.append("MM01:MARKET_MAKER:CANCEL_QUOTES_ONLY:Market maker")
    return gateways, trader_ids, mm_ids


def profile_extra_args(
    profile: str, seed_quotes: bool, symbols: list[str]
) -> list[str]:
    """The flags specific to (profile, seed_quotes), beyond --symbols,
    --participants, --participant-smp, --output/--force/--seed/
    --outstanding-shares/--api-gateway-* which are built generically."""
    if profile == "basic":
        if seed_quotes:
            head = [
                "--seed-mm-mid-range",
                "20:300",
                "--mm-seed-spread-ticks",
                "10",
                "--seed-last-prices-from-mm",
                "--no-collars",
                "--no-circuit-breakers",
                "--enforce-mm-obligations",
            ]
        else:
            head = [
                "--no-mm-seed-quotes",
                "--no-collars",
                "--no-circuit-breakers",
                "--no-enforce-mm-obligations",
                "--seed-mm-mid-range",
                "20:300",
                "--seed-last-prices-from-mm",
            ]
        return head + POST_TRADE_MARKET_DATA_TAIL_SMALL

    if profile == "nominal":
        if seed_quotes:
            head = [
                "--seed-mm-mid-range",
                "20:300",
                "--mm-seed-spread-ticks",
                "10",
                "--seed-last-prices-from-mm",
                "--no-collars",
                "--enforce-mm-obligations",
            ]
        else:
            head = [
                "--no-collars",
                "--no-enforce-mm-obligations",
                "--seed-mm-mid-range",
                "20:300",
                "--seed-last-prices-from-mm",
                "--no-mm-seed-quotes",
            ]
        return head + ["--sessions-enabled"] + POST_TRADE_MARKET_DATA_TAIL_SMALL

    # complex
    symbol_opts = []
    if seed_quotes:
        symbol_opts += [
            "--symbol-opts",
            f"{symbols[0]}:level=CORE,mm_spread_ticks=20,mm_min_qty=300",
        ]
    else:
        symbol_opts += ["--symbol-opts", f"{symbols[0]}:level=CORE"]
    # The high-beta risk-level example is always applied to TSLA specifically
    # (a recognizably volatile ticker), not to "whichever symbol is second" --
    # that's a separate role filled by symbols[1] in the combo pair below.
    if "TSLA" in symbols:
        symbol_opts += [
            "--symbol-opts",
            "TSLA:level=HIGH_BETA,dynamic_band=0.04,cb_halt_l1=10",
        ]

    if seed_quotes:
        head = [
            "--seed-mm-mid-range",
            "20:300",
            "--mm-seed-spread-ticks",
            "10",
            "--seed-last-prices-from-mm",
        ]
        mid = [
            "--mm-spread-ticks",
            "20",
            "--mm-min-qty",
            "200",
            "--enforce-mm-obligations",
            "--tick-decimals",
            "2",
        ]
    else:
        head = ["--no-mm-seed-quotes"]
        mid = [
            "--seed-mm-mid-range",
            "20:300",
            "--seed-last-prices-from-mm",
            "--no-enforce-mm-obligations",
            "--tick-decimals",
            "2",
        ]
    return (
        head
        + COMPLEX_SCHEDULE
        + mid
        + symbol_opts
        + POST_TRADE_MARKET_DATA_TAIL_COMPLEX
    )


def last_buy_price(config_path: Path, symbol: str) -> str | None:
    """Port of the awk one-liner the original complex-profile scripts used
    to pull a seeded symbol's last_buy_price back out of the generated
    config, for reuse as a combo leg price."""
    in_symbols = False
    current = None
    with config_path.open() as f:
        for raw in f:
            line = raw.rstrip("\n")
            if line == "symbols:":
                in_symbols = True
                continue
            if not in_symbols:
                continue
            if re.match(r"^  [A-Z0-9_.-]+:$", line):
                current = line.strip().rstrip(":")
                continue
            if current == symbol:
                parts = line.split()
                if parts and parts[0] == "last_buy_price:":
                    return parts[1]
    return None


def run_config_gen(config_gen: list[str], args: list[str], setup_dir: Path) -> None:
    # --output is relative; run inside the setup directory, as mks150.sh and
    # mks300.sh do with ``cd``, or the config lands in the caller's cwd.
    subprocess.run(config_gen + args, check=True, cwd=setup_dir)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate engine_config.yaml for an s1/s3/s10/s30 *-setup example."
    )
    parser.add_argument("setup_dir", type=Path)
    parser.add_argument("--seed", type=int, default=None)
    args = parser.parse_args()

    setup_dir = args.setup_dir.resolve()
    size, profile, seed_quotes = parse_setup_dir(setup_dir)
    symbols = CANONICAL_SYMBOLS[:size]
    config_path = setup_dir / "engine_config.yaml"

    seed = args.seed
    if seed is None:
        seed = existing_seed(config_path)
        if seed is not None:
            print(
                f"[INFO] Reusing seed {seed} from existing engine_config.yaml "
                f"-- pass --seed to override.",
                file=sys.stderr,
            )
    if seed is None:
        seed = random.randint(0, 2_147_483_647)
        print(
            f"[INFO] Auto-generated seed {seed} -- re-run with --seed {seed} "
            f"for identical output.",
            file=sys.stderr,
        )

    config_gen = resolve_config_gen()
    gateways, trader_ids, mm_ids = build_gateways(profile)
    smp_args = [
        a
        for gw in gateways
        for a in ("--participant-smp", f"{gw.split(':')[0]}:CANCEL_AGGRESSOR")
    ]
    outstanding_args = [
        a
        for sym in symbols
        for a in ("--outstanding-shares", f"{sym}:{OUTSTANDING_SHARES[sym]}")
    ]
    desk_list = ",".join(trader_ids + mm_ids + ["OPS01"])

    common = (
        ["--symbols", *symbols, "--participants", *gateways, *smp_args]
        + outstanding_args
        + [
            "--output",
            "engine_config.yaml",
            "--force",
            "--comment-default-config-fields",
            "--seed",
            str(seed),
            "--api-gateway-instance",
            f"desk:{desk_list}:8080",
            "--api-gateway-instance",
            "dashboards::8081",
            "--api-gateway-readonly-key",
        ]
    )
    extra = profile_extra_args(profile, seed_quotes, symbols)

    if profile == "complex" and len(symbols) >= 2:
        combo_a, combo_b = symbols[0], symbols[1]
        if seed_quotes:
            # Pass 1: generate the base config to obtain seeded MM quote /
            # last-price values.
            run_config_gen(config_gen, common + extra, setup_dir)
            price_a = last_buy_price(config_path, combo_a)
            price_b = last_buy_price(config_path, combo_b)
            if not price_a or not price_b:
                sys.exit(
                    "Error: failed to extract seeded prices from engine_config.yaml"
                )
        else:
            # This nomm example seeds no market_maker_quotes and no
            # MM-derived last_buy_price, so the combo leg prices are fixed
            # placeholders rather than values derived from a book seed.
            price_a = price_b = "150.00"
        combo = (
            f"SEED-PAIR-{combo_a}-{combo_b}:AON:DAY:"
            f"{combo_a}/BUY/LIMIT/100/{price_a},{combo_b}/SELL/LIMIT/100/{price_b}"
        )
        # Pass 2 (or only pass, for nomm): regenerate with --combo so
        # pm-config-gen validates the combo entry. The same seed guarantees
        # identical MM quote prices across both passes.
        run_config_gen(config_gen, common + extra + ["--combo", combo], setup_dir)
    else:
        run_config_gen(config_gen, common + extra, setup_dir)

    print(f"Generated {config_path}")


if __name__ == "__main__":
    main()
