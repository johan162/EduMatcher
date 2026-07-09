"""Layer 2 — Schema validation: required fields, correct types, value ranges."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from edumatcher.api_gateway.config import validate_api_gateway_sections
from edumatcher.md_gateway.config import validate_market_data_gateway_section
from edumatcher.models.combo import ComboLeg, ComboType
from edumatcher.models.order import TIF
from edumatcher.ralf_gateway.config import validate_ralf_gateway_section
from edumatcher.cverifier.models import CheckResult, Severity

_VALID_ROLES = {"TRADER", "MARKET_MAKER", "ADMIN"}
_VALID_DISCONNECT = {"CANCEL_ALL", "CANCEL_QUOTES_ONLY", "LEAVE_ALL"}
_VALID_RESUMPTION = {"AUCTION", "CONTINUOUS"}
_VALID_TIF = {"DAY", "GTC"}
_VALID_QUOTE_REFRESH = {
    "INACTIVATE_ON_ANY_FILL",
    "INACTIVATE_ON_FULL_FILL",
    "NEVER_INACTIVATE",
}


def _is_positive_int(val: Any) -> bool:
    """Return True if *val* is a non-bool int (or int-like) that is > 0.

    ``bool`` is a subclass of ``int`` in Python, so ``int(True) == 1`` would
    otherwise silently validate a boolean as a positive integer.
    """
    if isinstance(val, bool):
        return False
    try:
        return int(val) > 0
    except (TypeError, ValueError):
        return False


def check(raw: dict[str, Any], path: Path) -> list[CheckResult]:  # noqa: ARG001
    """Run Layer 2 schema checks against the raw YAML dict."""
    results: list[CheckResult] = []
    _check_top_level(raw, results)
    if any(r.severity is Severity.ERROR for r in results):
        # No point checking symbols/gateways if top-level structure is missing
        return results
    _check_runtime_flags(raw, results)
    _check_mm_obligation_defaults_schema(raw, results)
    _check_symbols(raw, results)
    _check_gateways(raw, results)
    _check_market_maker_combos(raw, results)
    _check_indices(raw, results)
    _check_cb_defaults(raw, results)
    _check_risk_controls(raw, results)
    _check_balf_gateway(raw, results)
    _check_post_trade_gateway(raw, results)
    _check_market_data_gateway(raw, results)
    _check_api_gateway_sections(raw, results)
    return results


# ---------------------------------------------------------------------------
# Top-level required keys
# ---------------------------------------------------------------------------


def _check_top_level(raw: dict[str, Any], results: list[CheckResult]) -> None:
    symbols = raw.get("symbols")
    if not isinstance(symbols, dict):
        results.append(
            CheckResult(
                code="S001",
                severity=Severity.ERROR,
                message="'symbols' is required and must be a mapping.",
                suggestion="Add at least one symbol entry under 'symbols:'.",
                path="symbols",
            )
        )
    elif not symbols:
        results.append(
            CheckResult(
                code="S004",
                severity=Severity.ERROR,
                message="'symbols' contains no entries.",
                suggestion="Add at least one symbol (e.g. AAPL) with tick_decimals.",
                path="symbols",
            )
        )

    gateways = raw.get("gateways")
    if not isinstance(gateways, dict):
        results.append(
            CheckResult(
                code="S002",
                severity=Severity.ERROR,
                message="'gateways' is required and must be a mapping containing a 'gateways.alf' list.",
                suggestion="Add a 'gateways:' section with an 'alf:' list.",
                path="gateways",
            )
        )
        return

    alf = gateways.get("alf")
    if not isinstance(alf, list):
        results.append(
            CheckResult(
                code="S003",
                severity=Severity.ERROR,
                message="'gateways.alf' must be a list of gateway entries.",
                suggestion=(
                    "Add a list under 'gateways.alf:'. "
                    "See the configuration guide for the required fields."
                ),
                path="gateways.alf",
            )
        )
    elif not alf:
        results.append(
            CheckResult(
                code="S005",
                severity=Severity.ERROR,
                message="'gateways.alf' contains no gateway entries.",
                suggestion="Add at least one gateway with an id and role.",
                path="gateways.alf",
            )
        )


# ---------------------------------------------------------------------------
# Symbol validation
# ---------------------------------------------------------------------------


def _check_symbols(raw: dict[str, Any], results: list[CheckResult]) -> None:
    symbols = raw.get("symbols", {})
    if not isinstance(symbols, dict):
        return

    defined_levels = _get_defined_risk_levels(raw)

    for sym_raw, cfg in symbols.items():
        sym = str(sym_raw).upper()
        if not isinstance(cfg, dict):
            cfg = {}

        _check_symbol_tick_decimals(sym, cfg, results)
        _check_symbol_prices(sym, cfg, results)
        _check_symbol_outstanding_shares(sym, cfg, results)
        _check_symbol_level(sym, cfg, defined_levels, results)
        _check_symbol_mm_quotes(sym, cfg, results)


def _check_symbol_tick_decimals(
    sym: str, cfg: dict[str, Any], results: list[CheckResult]
) -> None:
    td = cfg.get("tick_decimals", 2)
    try:
        if isinstance(td, bool):
            raise ValueError("bool is not a valid integer")
        td_int = int(td)
        if not (0 <= td_int <= 8):
            raise ValueError("out of range")
    except (TypeError, ValueError):
        results.append(
            CheckResult(
                code="S010",
                severity=Severity.ERROR,
                message=(
                    f"Symbol '{sym}': tick_decimals must be an integer between 0 and 8. "
                    f"Got '{td}'."
                ),
                suggestion=(
                    "Common values are 2 (dollars/cents) or 0 (integer ticks).\n"
                    f"    symbols:\n      {sym}:\n        tick_decimals: 2"
                ),
                path=f"symbols.{sym}.tick_decimals",
            )
        )


def _check_symbol_prices(
    sym: str, cfg: dict[str, Any], results: list[CheckResult]
) -> None:
    for price_field in ("last_buy_price", "last_sell_price"):
        val = cfg.get(price_field)
        if val is not None:
            try:
                float(val)
            except (TypeError, ValueError):
                results.append(
                    CheckResult(
                        code="S011",
                        severity=Severity.ERROR,
                        message=(
                            f"Symbol '{sym}': {price_field} must be numeric. Got '{val}'."
                        ),
                        suggestion="Set to a positive number or omit entirely.",
                        path=f"symbols.{sym}.{price_field}",
                    )
                )


def _check_symbol_outstanding_shares(
    sym: str, cfg: dict[str, Any], results: list[CheckResult]
) -> None:
    val = cfg.get("outstanding_shares")
    if val is not None and not _is_positive_int(val):
        results.append(
            CheckResult(
                code="S012",
                severity=Severity.ERROR,
                message=(
                    f"Symbol '{sym}': outstanding_shares must be a positive integer. "
                    f"Got '{val}'."
                ),
                suggestion="This field is required for index constituents.",
                path=f"symbols.{sym}.outstanding_shares",
            )
        )


def _check_symbol_level(
    sym: str,
    cfg: dict[str, Any],
    defined_levels: set[str],
    results: list[CheckResult],
) -> None:
    level_raw = cfg.get("level")
    if level_raw is not None and defined_levels:
        level = str(level_raw).strip().upper()
        if level not in defined_levels:
            defined_str = ", ".join(sorted(defined_levels)) or "(none)"
            results.append(
                CheckResult(
                    code="S013",
                    severity=Severity.ERROR,
                    message=(
                        f"Symbol '{sym}': level '{level}' is not defined in "
                        f"risk_controls.levels. Defined levels are: {defined_str}."
                    ),
                    suggestion=(
                        f"Either add '{level}' to risk_controls.levels or change "
                        f"the symbol's level to an existing one."
                    ),
                    path=f"symbols.{sym}.level",
                )
            )
    elif level_raw is not None and not defined_levels:
        level = str(level_raw).strip().upper()
        results.append(
            CheckResult(
                code="S013",
                severity=Severity.ERROR,
                message=(
                    f"Symbol '{sym}': level '{level}' is not defined in "
                    f"risk_controls.levels. No risk_controls.levels are defined."
                ),
                suggestion=(
                    "Add risk_controls.levels to the config or remove the level field."
                ),
                path=f"symbols.{sym}.level",
            )
        )


def _check_symbol_mm_quotes(
    sym: str, cfg: dict[str, Any], results: list[CheckResult]
) -> None:
    mm_quotes = cfg.get("market_maker_quotes")
    if mm_quotes is None:
        return
    if not isinstance(mm_quotes, list):
        results.append(
            CheckResult(
                code="S017",
                severity=Severity.ERROR,
                message=(
                    f"Symbol '{sym}': market_maker_quotes must be a list. "
                    f"Got {type(mm_quotes).__name__}."
                ),
                suggestion="Set market_maker_quotes to a YAML list or remove it.",
                path=f"symbols.{sym}.market_maker_quotes",
            )
        )
        return
    for i, quote in enumerate(mm_quotes):
        if not isinstance(quote, dict):
            results.append(
                CheckResult(
                    code="S018",
                    severity=Severity.ERROR,
                    message=(
                        f"Symbol '{sym}': market_maker_quotes[{i}] must be a mapping. "
                        f"Got {type(quote).__name__}."
                    ),
                    suggestion="Each quote seed must be a YAML mapping with required fields.",
                    path=f"symbols.{sym}.market_maker_quotes[{i}]",
                )
            )
            continue
        gateway_id_raw = quote.get("gateway_id")
        if gateway_id_raw is not None and (
            not isinstance(gateway_id_raw, str) or not gateway_id_raw.strip()
        ):
            results.append(
                CheckResult(
                    code="S019",
                    severity=Severity.ERROR,
                    message=(
                        f"Symbol '{sym}': market_maker_quotes[{i}].gateway_id "
                        "must be a non-empty string when present."
                    ),
                    suggestion="Use a configured gateway id, e.g. MM01.",
                    path=f"symbols.{sym}.market_maker_quotes[{i}].gateway_id",
                )
            )
        # Required fields
        for required in ("gateway_id", "bid_price", "ask_price", "bid_qty", "ask_qty"):
            if required not in quote:
                results.append(
                    CheckResult(
                        code="S014",
                        severity=Severity.ERROR,
                        message=(
                            f"Symbol '{sym}': market_maker_quotes[{i}] is missing '{required}'."
                        ),
                        suggestion=(
                            "Each quote seed requires gateway_id, bid_price, ask_price, "
                            "bid_qty, and ask_qty."
                        ),
                        path=f"symbols.{sym}.market_maker_quotes[{i}]",
                    )
                )
        # Bid/ask crossing
        bid = quote.get("bid_price")
        ask = quote.get("ask_price")
        if bid is not None and ask is not None:
            try:
                if float(bid) >= float(ask):
                    results.append(
                        CheckResult(
                            code="S015",
                            severity=Severity.ERROR,
                            message=(
                                f"Symbol '{sym}': market_maker_quotes[{i}] has "
                                f"bid_price ({bid}) >= ask_price ({ask}). "
                                "The bid must be strictly less than the ask."
                            ),
                            suggestion=(
                                "Swap the values or correct the prices:\n"
                                f"    symbols:\n      {sym}:\n        market_maker_quotes:\n"
                                f"          - gateway_id: ...\n"
                                f"            bid_price: {ask}\n"
                                f"            ask_price: {bid}"
                            ),
                            path=f"symbols.{sym}.market_maker_quotes[{i}]",
                        )
                    )
            except (TypeError, ValueError):
                pass

        _check_mm_quote_validity(sym, i, quote, results)


def _check_mm_quote_validity(
    sym: str, i: int, quote: dict[str, Any], results: list[CheckResult]
) -> None:
    """S016 — prices/quantities/tif that the engine would reject at startup."""
    problems: list[str] = []

    for price_field in ("bid_price", "ask_price"):
        val = quote.get(price_field)
        if val is None:
            continue
        try:
            float(val)
        except (TypeError, ValueError):
            problems.append(f"{price_field} must be numeric (got '{val}')")

    for qty_field in ("bid_qty", "ask_qty"):
        val = quote.get(qty_field)
        if val is None:
            continue
        try:
            qty = int(val)
        except (TypeError, ValueError):
            problems.append(f"{qty_field} must be a positive integer (got '{val}')")
            continue
        if qty <= 0:
            problems.append(f"{qty_field} must be positive (got {qty})")

    tif = quote.get("tif")
    if tif is not None and str(tif).upper() not in _VALID_TIF:
        problems.append(
            f"tif '{tif}' is not valid (use {' or '.join(sorted(_VALID_TIF))})"
        )

    if problems:
        results.append(
            CheckResult(
                code="S016",
                severity=Severity.ERROR,
                message=(
                    f"Symbol '{sym}': market_maker_quotes[{i}] is invalid: "
                    + "; ".join(problems)
                    + "."
                ),
                suggestion=(
                    "The engine rejects this seed at startup. "
                    "Quantities must be positive integers, prices numeric, "
                    "and tif one of DAY or GTC."
                ),
                path=f"symbols.{sym}.market_maker_quotes[{i}]",
            )
        )


# ---------------------------------------------------------------------------
# Gateway validation
# ---------------------------------------------------------------------------


def _check_gateways(raw: dict[str, Any], results: list[CheckResult]) -> None:
    gateways = raw.get("gateways", {})
    if not isinstance(gateways, dict):
        return
    alf = gateways.get("alf", [])
    if not isinstance(alf, list):
        return

    seen_ids: dict[str, int] = {}
    gateway_ids: list[tuple[int, str]] = []
    for n, gw in enumerate(alf):
        if not isinstance(gw, dict):
            results.append(
                CheckResult(
                    code="S029",
                    severity=Severity.ERROR,
                    message=(
                        f"gateways.alf[{n}] must be a mapping. "
                        f"Got {type(gw).__name__}."
                    ),
                    suggestion="Each gateways.alf entry must be a YAML mapping.",
                    path=f"gateways.alf[{n}]",
                )
            )
            continue
        gw_id = gw.get("id")
        if not gw_id or not isinstance(gw_id, str) or not str(gw_id).strip():
            results.append(
                CheckResult(
                    code="S020",
                    severity=Severity.ERROR,
                    message=f"gateways.alf[{n}] has no 'id' field.",
                    suggestion="Every gateway must have a unique alphanumeric id.",
                    path=f"gateways.alf[{n}]",
                )
            )
            continue
        gw_id = str(gw_id).strip().upper()
        if gw_id in seen_ids:
            results.append(
                CheckResult(
                    code="S021",
                    severity=Severity.ERROR,
                    message=(
                        f"Duplicate gateway id '{gw_id}' at gateways.alf[{n}] "
                        f"and gateways.alf[{seen_ids[gw_id]}]."
                    ),
                    suggestion="Each gateway must have a unique id.",
                    path=f"gateways.alf[{n}].id",
                )
            )
        else:
            seen_ids[gw_id] = n
            gateway_ids.append((n, gw_id))

        role = gw.get("role", "TRADER")
        if str(role).upper() not in _VALID_ROLES:
            results.append(
                CheckResult(
                    code="S022",
                    severity=Severity.ERROR,
                    message=(f"Gateway '{gw_id}': role '{role}' is not valid."),
                    suggestion=f"Accepted values: {', '.join(sorted(_VALID_ROLES))}.",
                    path=f"gateways.alf[{n}].role",
                )
            )

        disconnect = gw.get("disconnect_behaviour")
        if disconnect is not None and str(disconnect).upper() not in _VALID_DISCONNECT:
            results.append(
                CheckResult(
                    code="S023",
                    severity=Severity.ERROR,
                    message=(
                        f"Gateway '{gw_id}': disconnect_behaviour '{disconnect}' is not valid."
                    ),
                    suggestion=(
                        f"Accepted values: {', '.join(sorted(_VALID_DISCONNECT))}."
                    ),
                    path=f"gateways.alf[{n}].disconnect_behaviour",
                )
            )

        quote_refresh = gw.get("quote_refresh_policy")
        if (
            quote_refresh is not None
            and str(quote_refresh).upper() not in _VALID_QUOTE_REFRESH
        ):
            results.append(
                CheckResult(
                    code="S024",
                    severity=Severity.ERROR,
                    message=(
                        f"Gateway '{gw_id}': quote_refresh_policy '{quote_refresh}' is not valid."
                    ),
                    suggestion=(
                        "Accepted values: "
                        + ", ".join(sorted(_VALID_QUOTE_REFRESH))
                        + "."
                    ),
                    path=f"gateways.alf[{n}].quote_refresh_policy",
                )
            )

        enforce_mm = gw.get("enforce_mm_obligation")
        if enforce_mm is not None and not isinstance(enforce_mm, bool):
            results.append(
                CheckResult(
                    code="S025",
                    severity=Severity.ERROR,
                    message=(
                        f"Gateway '{gw_id}': enforce_mm_obligation must be a boolean. "
                        f"Got '{enforce_mm}'."
                    ),
                    suggestion="Set to true or false.",
                    path=f"gateways.alf[{n}].enforce_mm_obligation",
                )
            )

        for field in ("mm_max_spread_ticks", "mm_min_qty"):
            val = gw.get(field)
            if val is None:
                continue
            if not _is_positive_int(val):
                results.append(
                    CheckResult(
                        code="S026",
                        severity=Severity.ERROR,
                        message=(
                            f"Gateway '{gw_id}': {field} must be a positive integer. "
                            f"Got '{val}'."
                        ),
                        suggestion=f"Set gateways.alf[{n}].{field} to an integer > 0.",
                        path=f"gateways.alf[{n}].{field}",
                    )
                )

        mm_obligations = gw.get("mm_obligations")
        if mm_obligations is not None and not isinstance(mm_obligations, dict):
            results.append(
                CheckResult(
                    code="S027",
                    severity=Severity.ERROR,
                    message=(
                        f"Gateway '{gw_id}': mm_obligations must be a mapping when present."
                    ),
                    suggestion="Use symbol keys under mm_obligations, each with a mapping value.",
                    path=f"gateways.alf[{n}].mm_obligations",
                )
            )
        elif isinstance(mm_obligations, dict):
            for sym_raw, obl_raw in mm_obligations.items():
                sym = str(sym_raw).upper()
                if not isinstance(obl_raw, dict):
                    results.append(
                        CheckResult(
                            code="S028",
                            severity=Severity.ERROR,
                            message=(
                                f"Gateway '{gw_id}': mm_obligations.{sym} must be a mapping."
                            ),
                            suggestion="Provide enforce_mm_obligation, max_spread_ticks, min_qty fields.",
                            path=f"gateways.alf[{n}].mm_obligations.{sym}",
                        )
                    )
                    continue

                enforce = obl_raw.get("enforce_mm_obligation")
                if enforce is not None and not isinstance(enforce, bool):
                    results.append(
                        CheckResult(
                            code="S028",
                            severity=Severity.ERROR,
                            message=(
                                f"Gateway '{gw_id}': mm_obligations.{sym}.enforce_mm_obligation "
                                "must be a boolean."
                            ),
                            suggestion="Set enforce_mm_obligation to true or false.",
                            path=(
                                f"gateways.alf[{n}].mm_obligations.{sym}.enforce_mm_obligation"
                            ),
                        )
                    )

                for field in ("max_spread_ticks", "min_qty"):
                    val = obl_raw.get(field)
                    if val is None:
                        continue
                    if not _is_positive_int(val):
                        results.append(
                            CheckResult(
                                code="S028",
                                severity=Severity.ERROR,
                                message=(
                                    f"Gateway '{gw_id}': mm_obligations.{sym}.{field} "
                                    f"must be a positive integer. Got '{val}'."
                                ),
                                suggestion=f"Set {field} to an integer > 0.",
                                path=f"gateways.alf[{n}].mm_obligations.{sym}.{field}",
                            )
                        )

    for i, (idx_a, gw_a) in enumerate(gateway_ids):
        for _idx_b, gw_b in gateway_ids[i + 1 :]:
            if gw_a.startswith(gw_b) or gw_b.startswith(gw_a):
                results.append(
                    CheckResult(
                        code="S084",
                        severity=Severity.ERROR,
                        message=(
                            "gateways.alf IDs must not be prefixes of each other "
                            f"('{gw_a}', '{gw_b}')."
                        ),
                        suggestion=(
                            "Rename one of the gateway IDs so neither ID is a "
                            "prefix of another."
                        ),
                        path=f"gateways.alf[{idx_a}].id",
                    )
                )


def _check_market_maker_combos(raw: dict[str, Any], results: list[CheckResult]) -> None:
    combos = raw.get("market_maker_combos")
    if combos is None:
        return
    if not isinstance(combos, list):
        results.append(
            CheckResult(
                code="S055",
                severity=Severity.ERROR,
                message="'market_maker_combos' must be a list.",
                suggestion="Set market_maker_combos to a YAML list of combo mappings.",
                path="market_maker_combos",
            )
        )
        return

    symbol_names = {str(sym).upper() for sym in raw.get("symbols", {})}
    for i, combo in enumerate(combos):
        if not isinstance(combo, dict):
            results.append(
                CheckResult(
                    code="S056",
                    severity=Severity.ERROR,
                    message=(
                        f"market_maker_combos[{i}] must be a mapping. "
                        f"Got {type(combo).__name__}."
                    ),
                    suggestion="Each combo seed entry must be a YAML mapping.",
                    path=f"market_maker_combos[{i}]",
                )
            )
            continue

        combo_id = combo.get("combo_id")
        if not isinstance(combo_id, str) or not combo_id.strip():
            results.append(
                CheckResult(
                    code="S056",
                    severity=Severity.ERROR,
                    message=(
                        f"market_maker_combos[{i}].combo_id must be a non-empty string."
                    ),
                    suggestion="Set combo_id to a non-empty identifier.",
                    path=f"market_maker_combos[{i}].combo_id",
                )
            )

        try:
            ComboType(str(combo.get("combo_type", ComboType.AON.value)).upper())
        except ValueError:
            results.append(
                CheckResult(
                    code="S057",
                    severity=Severity.ERROR,
                    message=f"market_maker_combos[{i}].combo_type is invalid.",
                    suggestion="Use a valid combo_type value (currently AON).",
                    path=f"market_maker_combos[{i}].combo_type",
                )
            )

        try:
            TIF(str(combo.get("tif", TIF.DAY.value)).upper())
        except ValueError:
            results.append(
                CheckResult(
                    code="S057",
                    severity=Severity.ERROR,
                    message=f"market_maker_combos[{i}].tif is invalid.",
                    suggestion="Use one of DAY, GTC, ATO, or ATC.",
                    path=f"market_maker_combos[{i}].tif",
                )
            )

        legs = combo.get("legs")
        if not isinstance(legs, list):
            results.append(
                CheckResult(
                    code="S058",
                    severity=Severity.ERROR,
                    message=f"market_maker_combos[{i}].legs must be a list.",
                    suggestion="Set legs to a YAML list with 2 to 10 leg entries.",
                    path=f"market_maker_combos[{i}].legs",
                )
            )
            continue
        if len(legs) < 2 or len(legs) > 10:
            results.append(
                CheckResult(
                    code="S058",
                    severity=Severity.ERROR,
                    message=f"market_maker_combos[{i}] must have 2 to 10 legs.",
                    suggestion="Adjust the legs list length to be within 2..10.",
                    path=f"market_maker_combos[{i}].legs",
                )
            )

        seen_symbols: set[str] = set()
        for j, leg in enumerate(legs):
            if not isinstance(leg, dict):
                results.append(
                    CheckResult(
                        code="S059",
                        severity=Severity.ERROR,
                        message=(
                            f"market_maker_combos[{i}].legs[{j}] must be a mapping. "
                            f"Got {type(leg).__name__}."
                        ),
                        suggestion="Each combo leg must be a YAML mapping.",
                        path=f"market_maker_combos[{i}].legs[{j}]",
                    )
                )
                continue

            payload = dict(leg)
            if "symbol" in payload:
                payload["symbol"] = str(payload["symbol"]).upper()
            if "side" in payload:
                payload["side"] = str(payload["side"]).upper()
            if "order_type" in payload:
                payload["order_type"] = str(payload["order_type"]).upper()
            if "smp_action" in payload and payload["smp_action"] is not None:
                payload["smp_action"] = str(payload["smp_action"]).upper()

            try:
                parsed_leg = ComboLeg.from_dict(payload)
            except (KeyError, TypeError, ValueError):
                results.append(
                    CheckResult(
                        code="S059",
                        severity=Severity.ERROR,
                        message=f"market_maker_combos[{i}].legs[{j}] is invalid.",
                        suggestion=(
                            "Use valid combo leg fields (symbol, side, order_type, "
                            "quantity, and required price/stop fields)."
                        ),
                        path=f"market_maker_combos[{i}].legs[{j}]",
                    )
                )
                continue

            if parsed_leg.symbol in seen_symbols:
                results.append(
                    CheckResult(
                        code="S059",
                        severity=Severity.ERROR,
                        message=(
                            f"market_maker_combos[{i}] contains duplicate symbol "
                            f"'{parsed_leg.symbol}'."
                        ),
                        suggestion="Each symbol may appear at most once per combo.",
                        path=f"market_maker_combos[{i}].legs[{j}].symbol",
                    )
                )
            seen_symbols.add(parsed_leg.symbol)

            if parsed_leg.symbol not in symbol_names:
                results.append(
                    CheckResult(
                        code="S059",
                        severity=Severity.ERROR,
                        message=(
                            f"market_maker_combos[{i}] references unknown symbol "
                            f"'{parsed_leg.symbol}'."
                        ),
                        suggestion=(
                            f"Add '{parsed_leg.symbol}' under symbols or update the leg symbol."
                        ),
                        path=f"market_maker_combos[{i}].legs[{j}].symbol",
                    )
                )


def _check_indices(raw: dict[str, Any], results: list[CheckResult]) -> None:
    indices = raw.get("indices")
    if indices is None:
        return
    if not isinstance(indices, list):
        results.append(
            CheckResult(
                code="S043",
                severity=Severity.ERROR,
                message="'indices' must be a list.",
                suggestion="Set indices to a YAML list of index mappings.",
                path="indices",
            )
        )
        return

    seen_ids: set[str] = set()
    for i, idx in enumerate(indices):
        if not isinstance(idx, dict):
            results.append(
                CheckResult(
                    code="S044",
                    severity=Severity.ERROR,
                    message=(
                        f"indices[{i}] must be a mapping. Got {type(idx).__name__}."
                    ),
                    suggestion="Each index entry must be a YAML mapping.",
                    path=f"indices[{i}]",
                )
            )
            continue

        idx_id_raw = idx.get("id")
        idx_id = str(idx_id_raw).strip().upper() if isinstance(idx_id_raw, str) else ""
        if not idx_id:
            results.append(
                CheckResult(
                    code="S045",
                    severity=Severity.ERROR,
                    message=f"indices[{i}].id must be a non-empty string.",
                    suggestion="Set id to a non-empty alphanumeric string.",
                    path=f"indices[{i}].id",
                )
            )
        elif not idx_id.isalnum():
            results.append(
                CheckResult(
                    code="S045",
                    severity=Severity.ERROR,
                    message=f"indices[{i}].id must be alphanumeric.",
                    suggestion="Use only letters and digits in the index id.",
                    path=f"indices[{i}].id",
                )
            )
        elif idx_id in seen_ids:
            results.append(
                CheckResult(
                    code="S045",
                    severity=Severity.ERROR,
                    message=f"Duplicate index id in indices: {idx_id}",
                    suggestion="Ensure each index id is unique.",
                    path=f"indices[{i}].id",
                )
            )
        else:
            seen_ids.add(idx_id)

        desc = idx.get("description")
        if not isinstance(desc, str) or not desc.strip():
            results.append(
                CheckResult(
                    code="S046",
                    severity=Severity.ERROR,
                    message=f"indices[{i}].description must be a non-empty string.",
                    suggestion="Provide a human-readable index description.",
                    path=f"indices[{i}].description",
                )
            )

        for field in ("base_value", "publish_interval_sec"):
            if field not in idx:
                continue
            raw_val = cast(object, idx[field])
            if isinstance(raw_val, bool) or not isinstance(raw_val, (int, float, str)):
                results.append(
                    CheckResult(
                        code="S047",
                        severity=Severity.ERROR,
                        message=f"indices[{i}].{field} must be a number > 0.",
                        suggestion=f"Set {field} to a positive numeric value.",
                        path=f"indices[{i}].{field}",
                    )
                )
                continue
            try:
                num_val = float(raw_val)
                if num_val <= 0:
                    raise ValueError
            except ValueError:
                results.append(
                    CheckResult(
                        code="S047",
                        severity=Severity.ERROR,
                        message=f"indices[{i}].{field} must be a number > 0.",
                        suggestion=f"Set {field} to a positive numeric value.",
                        path=f"indices[{i}].{field}",
                    )
                )

        for field in ("history_file", "state_file"):
            path_val = idx.get(field)
            if path_val is None:
                continue
            if not isinstance(path_val, str) or not path_val.strip():
                results.append(
                    CheckResult(
                        code="S048",
                        severity=Severity.ERROR,
                        message=f"indices[{i}].{field} must be a non-empty string.",
                        suggestion=f"Set {field} to a non-empty path string.",
                        path=f"indices[{i}].{field}",
                    )
                )

        constituents = idx.get("constituents")
        if constituents is None:
            continue
        if not isinstance(constituents, list) or not constituents:
            results.append(
                CheckResult(
                    code="S049",
                    severity=Severity.ERROR,
                    message=f"indices[{i}].constituents must be a non-empty list.",
                    suggestion="Provide a non-empty list of symbol ids.",
                    path=f"indices[{i}].constituents",
                )
            )
            continue

        seen_constituents: set[str] = set()
        for sym in constituents:
            sym_id = str(sym).upper()
            if sym_id in seen_constituents:
                results.append(
                    CheckResult(
                        code="S049",
                        severity=Severity.ERROR,
                        message=(
                            f"indices[{i}].constituents contains duplicate symbol '{sym_id}'."
                        ),
                        suggestion="Remove duplicate symbol entries from constituents.",
                        path=f"indices[{i}].constituents",
                    )
                )
            seen_constituents.add(sym_id)


# ---------------------------------------------------------------------------
# Circuit breaker defaults
# ---------------------------------------------------------------------------


def _check_cb_defaults(raw: dict[str, Any], results: list[CheckResult]) -> None:
    cb = raw.get("circuit_breaker_defaults")
    if cb is None:
        return
    if not isinstance(cb, dict):
        results.append(
            CheckResult(
                code="S030",
                severity=Severity.ERROR,
                message="'circuit_breaker_defaults' must be a mapping.",
                suggestion="Change circuit_breaker_defaults to a mapping with a 'levels:' key.",
                path="circuit_breaker_defaults",
            )
        )
        return

    levels = cb.get("levels")
    if levels is None:
        return
    if not isinstance(levels, dict):
        results.append(
            CheckResult(
                code="S030",
                severity=Severity.ERROR,
                message="'circuit_breaker_defaults.levels' must be a mapping.",
                suggestion=(
                    "Each key is a level name (e.g. L1) and each value must have price_shift_pct."
                ),
                path="circuit_breaker_defaults.levels",
            )
        )
        return

    thresholds: list[tuple[str, float]] = []
    for name, level_cfg in levels.items():
        if not isinstance(level_cfg, dict):
            continue
        psp = level_cfg.get("price_shift_pct")
        if psp is None:
            results.append(
                CheckResult(
                    code="S031",
                    severity=Severity.ERROR,
                    message=(
                        f"circuit_breaker_defaults.levels.{name}: "
                        "price_shift_pct is required."
                    ),
                    suggestion="Must be a float in (0, 1), e.g. 0.07 for 7%.",
                    path=f"circuit_breaker_defaults.levels.{name}.price_shift_pct",
                )
            )
        else:
            try:
                psp_f = float(psp)
                if not (0 < psp_f < 1):
                    raise ValueError("out of range")
                thresholds.append((str(name), psp_f))
            except (TypeError, ValueError):
                results.append(
                    CheckResult(
                        code="S032",
                        severity=Severity.ERROR,
                        message=(
                            f"circuit_breaker_defaults.levels.{name}: "
                            f"price_shift_pct {psp} is outside (0, 1)."
                        ),
                        suggestion="Set a fraction such as 0.07 for 7%.",
                        path=f"circuit_breaker_defaults.levels.{name}.price_shift_pct",
                    )
                )

        hd = level_cfg.get("halt_duration_ns")
        if hd is not None:
            try:
                hd_i = int(hd)
                if hd_i <= 0:
                    raise ValueError("must be positive")
            except (TypeError, ValueError):
                results.append(
                    CheckResult(
                        code="S033",
                        severity=Severity.ERROR,
                        message=(
                            f"circuit_breaker_defaults.levels.{name}: "
                            f"halt_duration_ns must be a positive integer or null. Got '{hd}'."
                        ),
                        suggestion="Use nanoseconds (e.g. 300000000000 for 5 minutes).",
                        path=f"circuit_breaker_defaults.levels.{name}.halt_duration_ns",
                    )
                )

        rm = level_cfg.get("resumption_mode")
        if rm is not None and str(rm).upper() not in _VALID_RESUMPTION:
            results.append(
                CheckResult(
                    code="S034",
                    severity=Severity.ERROR,
                    message=(
                        f"circuit_breaker_defaults.levels.{name}: "
                        f"resumption_mode '{rm}' is not valid."
                    ),
                    suggestion="Use AUCTION or CONTINUOUS.",
                    path=f"circuit_breaker_defaults.levels.{name}.resumption_mode",
                )
            )

    # Warn if thresholds are not strictly increasing
    if len(thresholds) >= 2:
        sorted_by_pct = sorted(thresholds, key=lambda x: x[1])
        if [n for n, _ in thresholds] != [n for n, _ in sorted_by_pct]:
            detail = ", ".join(f"{n}={v:.0%}" for n, v in thresholds)
            results.append(
                CheckResult(
                    code="M014",
                    severity=Severity.WARN,
                    message=(
                        "circuit_breaker_defaults levels are not in ascending order of "
                        f"price_shift_pct: {detail}."
                    ),
                    suggestion="Reorder the levels from smallest to largest threshold.",
                    path="circuit_breaker_defaults.levels",
                )
            )


# ---------------------------------------------------------------------------
# Risk controls
# ---------------------------------------------------------------------------


def _check_risk_controls(raw: dict[str, Any], results: list[CheckResult]) -> None:
    rc = raw.get("risk_controls")
    if rc is None:
        return
    if not isinstance(rc, dict):
        return

    defined_levels = _get_defined_risk_levels(raw)

    default_level = rc.get("default_level")
    if default_level is not None and defined_levels:
        dl = str(default_level).strip().upper()
        if dl not in defined_levels:
            results.append(
                CheckResult(
                    code="S040",
                    severity=Severity.ERROR,
                    message=(
                        f"risk_controls.default_level '{default_level}' is not defined "
                        f"in risk_controls.levels."
                    ),
                    suggestion=(
                        "Add it or change default_level to a name that exists: "
                        + ", ".join(sorted(defined_levels))
                    ),
                    path="risk_controls.default_level",
                )
            )

    levels = rc.get("levels", {})
    if not isinstance(levels, dict):
        return

    for level_name, level_cfg in levels.items():
        if not isinstance(level_cfg, dict):
            continue

        # S035: CB should not be in risk_controls.levels
        if "circuit_breaker" in level_cfg:
            results.append(
                CheckResult(
                    code="S035",
                    severity=Severity.ERROR,
                    message=(
                        f"risk_controls.levels.{level_name}: circuit_breaker is no longer "
                        "supported here."
                    ),
                    suggestion=(
                        "Move it to the top-level circuit_breaker_defaults section."
                    ),
                    path=f"risk_controls.levels.{level_name}.circuit_breaker",
                )
            )

        collar = level_cfg.get("collar")
        if not isinstance(collar, dict):
            continue

        sbp = collar.get("static_band_pct")
        if sbp is not None:
            try:
                sbp_f = float(sbp)
                if not (0 < sbp_f < 1):
                    raise ValueError("out of range")
            except (TypeError, ValueError):
                results.append(
                    CheckResult(
                        code="S041",
                        severity=Severity.ERROR,
                        message=(
                            f"risk_controls.levels.{level_name}.collar.static_band_pct "
                            f"{sbp} is outside (0, 1)."
                        ),
                        suggestion="A typical value is 0.20 (20%).",
                        path=f"risk_controls.levels.{level_name}.collar.static_band_pct",
                    )
                )

        dbp = collar.get("dynamic_band_pct")
        if dbp is not None:
            try:
                dbp_f = float(dbp)
                if not (0 < dbp_f < 1):
                    raise ValueError("out of range")
            except (TypeError, ValueError):
                results.append(
                    CheckResult(
                        code="S042",
                        severity=Severity.ERROR,
                        message=(
                            f"risk_controls.levels.{level_name}.collar.dynamic_band_pct "
                            f"{dbp} is outside (0, 1)."
                        ),
                        suggestion="A typical value is 0.02 (2%).",
                        path=f"risk_controls.levels.{level_name}.collar.dynamic_band_pct",
                    )
                )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_defined_risk_levels(raw: dict[str, Any]) -> set[str]:
    rc = raw.get("risk_controls")
    if not isinstance(rc, dict):
        return set()
    levels = rc.get("levels")
    if not isinstance(levels, dict):
        return set()
    return {str(k).strip().upper() for k in levels}


def _check_runtime_flags(raw: dict[str, Any], results: list[CheckResult]) -> None:
    sessions_enabled = raw.get("sessions_enabled")
    if sessions_enabled is not None and not isinstance(sessions_enabled, bool):
        results.append(
            CheckResult(
                code="S060",
                severity=Severity.ERROR,
                message=(
                    f"'sessions_enabled' must be a boolean when provided. Got '{sessions_enabled}'."
                ),
                suggestion="Set sessions_enabled to true or false.",
                path="sessions_enabled",
            )
        )

    snapshot_interval = raw.get("snapshot_interval_sec")
    if snapshot_interval is not None:
        try:
            snap = float(snapshot_interval)
            if snap <= 0:
                raise ValueError
        except (TypeError, ValueError):
            results.append(
                CheckResult(
                    code="S061",
                    severity=Severity.ERROR,
                    message=(
                        "'snapshot_interval_sec' must be a positive number. "
                        f"Got '{snapshot_interval}'."
                    ),
                    suggestion="Set snapshot_interval_sec to a value > 0, e.g. 0.5.",
                    path="snapshot_interval_sec",
                )
            )

    enforce_collars = raw.get("enforce_collars")
    if enforce_collars is not None and not isinstance(enforce_collars, bool):
        results.append(
            CheckResult(
                code="S062",
                severity=Severity.ERROR,
                message=(
                    f"'enforce_collars' must be a boolean when provided. Got '{enforce_collars}'."
                ),
                suggestion="Set enforce_collars to true or false.",
                path="enforce_collars",
            )
        )

    enforce_cb = raw.get("enforce_circuit_breakers")
    if enforce_cb is not None and not isinstance(enforce_cb, bool):
        results.append(
            CheckResult(
                code="S063",
                severity=Severity.ERROR,
                message=(
                    "'enforce_circuit_breakers' must be a boolean when provided. "
                    f"Got '{enforce_cb}'."
                ),
                suggestion="Set enforce_circuit_breakers to true or false.",
                path="enforce_circuit_breakers",
            )
        )

    schedule = raw.get("schedule")
    if schedule is not None and not isinstance(schedule, dict):
        results.append(
            CheckResult(
                code="S064",
                severity=Severity.ERROR,
                message=f"'schedule' must be a mapping when provided. Got '{schedule}'.",
                suggestion="Set schedule to a YAML mapping with HH:MM fields.",
                path="schedule",
            )
        )


def _check_mm_obligation_defaults_schema(
    raw: dict[str, Any], results: list[CheckResult]
) -> None:
    section = raw.get("mm_obligation_defaults")
    if section is None:
        return

    if not isinstance(section, dict):
        results.append(
            CheckResult(
                code="S070",
                severity=Severity.ERROR,
                message="'mm_obligation_defaults' must be a mapping.",
                suggestion="Set mm_obligation_defaults to a mapping with policy fields.",
                path="mm_obligation_defaults",
            )
        )
        return

    enforce = section.get("enforce_mm_obligation")
    if enforce is not None and not isinstance(enforce, bool):
        results.append(
            CheckResult(
                code="S071",
                severity=Severity.ERROR,
                message=(
                    "'mm_obligation_defaults.enforce_mm_obligation' must be a boolean. "
                    f"Got '{enforce}'."
                ),
                suggestion="Set to true or false.",
                path="mm_obligation_defaults.enforce_mm_obligation",
            )
        )

    for field, code in (
        ("mm_max_spread_ticks", "S072"),
        ("mm_min_qty", "S073"),
    ):
        val = section.get(field)
        if val is None:
            continue
        try:
            parsed = int(val)
            if parsed <= 0:
                raise ValueError
        except (TypeError, ValueError):
            results.append(
                CheckResult(
                    code=code,
                    severity=Severity.ERROR,
                    message=(
                        f"'mm_obligation_defaults.{field}' must be a positive integer. "
                        f"Got '{val}'."
                    ),
                    suggestion=f"Set {field} to an integer > 0.",
                    path=f"mm_obligation_defaults.{field}",
                )
            )

    sym_map = section.get("symbols")
    if sym_map is not None and not isinstance(sym_map, dict):
        results.append(
            CheckResult(
                code="S074",
                severity=Severity.ERROR,
                message="'mm_obligation_defaults.symbols' must be a mapping.",
                suggestion="Use symbol keys (e.g. AAPL) with mapping values.",
                path="mm_obligation_defaults.symbols",
            )
        )
        return

    if not isinstance(sym_map, dict):
        return

    for sym_raw, sym_cfg in sym_map.items():
        sym = str(sym_raw).upper()
        if not isinstance(sym_cfg, dict):
            results.append(
                CheckResult(
                    code="S075",
                    severity=Severity.ERROR,
                    message=(
                        f"'mm_obligation_defaults.symbols.{sym}' must be a mapping."
                    ),
                    suggestion=(
                        "Set symbol override to a mapping with enforce_mm_obligation, "
                        "mm_max_spread_ticks, and mm_min_qty."
                    ),
                    path=f"mm_obligation_defaults.symbols.{sym}",
                )
            )
            continue

        sym_enforce = sym_cfg.get("enforce_mm_obligation")
        if sym_enforce is not None and not isinstance(sym_enforce, bool):
            results.append(
                CheckResult(
                    code="S076",
                    severity=Severity.ERROR,
                    message=(
                        "'mm_obligation_defaults.symbols."
                        f"{sym}.enforce_mm_obligation' must be a boolean."
                    ),
                    suggestion="Set enforce_mm_obligation to true or false.",
                    path=f"mm_obligation_defaults.symbols.{sym}.enforce_mm_obligation",
                )
            )

        for field in ("mm_max_spread_ticks", "mm_min_qty"):
            val = sym_cfg.get(field)
            if val is None:
                continue
            try:
                parsed = int(val)
                if parsed <= 0:
                    raise ValueError
            except (TypeError, ValueError):
                results.append(
                    CheckResult(
                        code="S077",
                        severity=Severity.ERROR,
                        message=(
                            "'mm_obligation_defaults.symbols."
                            f"{sym}.{field}' must be a positive integer. Got '{val}'."
                        ),
                        suggestion=f"Set {field} to an integer > 0.",
                        path=f"mm_obligation_defaults.symbols.{sym}.{field}",
                    )
                )


# ---------------------------------------------------------------------------
# balf_gateway section
# ---------------------------------------------------------------------------

_VALID_BALF_DUPLICATE_POLICY = {"REJECT_NEW", "EVICT_OLD"}

_BALF_POSITIVE_INT_FIELDS = (
    "max_connections",
    "max_client_queue",
    "max_messages_per_second",
    "max_errors_before_disconnect",
)

_BALF_POSITIVE_FLOAT_FIELDS = (
    "heartbeat_interval_sec",
    "heartbeat_timeout_sec",
    "idle_timeout_sec",
    "auth_timeout_sec",
    "error_window_sec",
)


def _check_balf_gateway(raw: dict[str, Any], results: list[CheckResult]) -> None:
    """Validate the optional balf_gateway section (S050–S054)."""
    section = raw.get("balf_gateway")
    if section is None:
        return

    if not isinstance(section, dict):
        results.append(
            CheckResult(
                code="S050",
                severity=Severity.ERROR,
                message="'balf_gateway' must be a mapping.",
                suggestion="Change balf_gateway to a mapping with field=value pairs.",
                path="balf_gateway",
            )
        )
        return

    # port
    port = section.get("port")
    if port is not None:
        if (
            isinstance(port, bool)
            or not isinstance(port, int)
            or not (1 <= port <= 65535)
        ):
            results.append(
                CheckResult(
                    code="S051",
                    severity=Severity.ERROR,
                    message="'balf_gateway.port' must be an integer in 1\u201365535.",
                    suggestion="Set port to a valid TCP port number, e.g. 5560.",
                    path="balf_gateway.port",
                )
            )

    # positive integer capacity fields
    for field in _BALF_POSITIVE_INT_FIELDS:
        val = section.get(field)
        if val is not None:
            if isinstance(val, bool) or not isinstance(val, int) or val <= 0:
                results.append(
                    CheckResult(
                        code="S052",
                        severity=Severity.ERROR,
                        message=f"'balf_gateway.{field}' must be a positive integer.",
                        suggestion=f"Set {field} to an integer > 0.",
                        path=f"balf_gateway.{field}",
                    )
                )

    # positive numeric timeout/interval fields
    for field in _BALF_POSITIVE_FLOAT_FIELDS:
        val = section.get(field)
        if val is not None:
            try:
                fval = float(val)
                if fval <= 0:
                    raise ValueError
            except (TypeError, ValueError):
                results.append(
                    CheckResult(
                        code="S053",
                        severity=Severity.ERROR,
                        message=f"'balf_gateway.{field}' must be a positive number.",
                        suggestion=f"Set {field} to a number > 0.",
                        path=f"balf_gateway.{field}",
                    )
                )

    # duplicate_session_policy
    dup_policy = section.get("duplicate_session_policy")
    if dup_policy is not None:
        if str(dup_policy).upper() not in _VALID_BALF_DUPLICATE_POLICY:
            results.append(
                CheckResult(
                    code="S054",
                    severity=Severity.ERROR,
                    message=(
                        "'balf_gateway.duplicate_session_policy' must be "
                        "'REJECT_NEW' or 'EVICT_OLD'."
                    ),
                    suggestion="Use REJECT_NEW (default) or EVICT_OLD.",
                    path="balf_gateway.duplicate_session_policy",
                )
            )


def _check_api_gateway_sections(
    raw: dict[str, Any], results: list[CheckResult]
) -> None:
    """Validate api_gateways using the runtime loader semantics."""

    try:
        validate_api_gateway_sections(raw)
    except ValueError as exc:
        msg = str(exc)
        path = "api_gateway" if "api_gateway" in msg else "api_gateways"
        section = "api_gateway" if path == "api_gateway" else "api_gateways"
        results.append(
            CheckResult(
                code="S080",
                severity=Severity.ERROR,
                message=f"'{section}' section is invalid: {msg}",
                suggestion=(
                    "Match the pm-api-gwy loader schema for api_gateways "
                    "(named mapping entries, unique non-null gateway_id ownership, "
                    "and valid credentials/rate_limit/timeouts/port values)."
                ),
                path=path,
            )
        )


def _check_post_trade_gateway(raw: dict[str, Any], results: list[CheckResult]) -> None:
    try:
        validate_ralf_gateway_section(raw)
    except ValueError as exc:
        results.append(
            CheckResult(
                code="S082",
                severity=Severity.ERROR,
                message=f"'post_trade_gateway' section is invalid: {exc}",
                suggestion=(
                    "Match the pm-ralf-gwy loader schema for post_trade_gateway "
                    "(mapping shape, allowed_roles list, and positive integer limits)."
                ),
                path="post_trade_gateway",
            )
        )


def _check_market_data_gateway(raw: dict[str, Any], results: list[CheckResult]) -> None:
    try:
        validate_market_data_gateway_section(raw)
    except ValueError as exc:
        results.append(
            CheckResult(
                code="S083",
                severity=Severity.ERROR,
                message=f"'market_data_gateway' section is invalid: {exc}",
                suggestion=(
                    "Match the pm-md-gwy loader schema for market_data_gateway "
                    "(mapping shape and positive integer limits)."
                ),
                path="market_data_gateway",
            )
        )
