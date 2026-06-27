"""Shared raw-dict navigation helpers used across the verification layers."""

from __future__ import annotations

from typing import Any


def gateway_ids_by_role(raw: dict[str, Any], role: str) -> list[str]:
    """Return upper-cased gateway ids whose role matches *role*."""
    gateways = raw.get("gateways", {})
    if not isinstance(gateways, dict):
        return []
    alf = gateways.get("alf", [])
    if not isinstance(alf, list):
        return []
    target = role.upper()
    result: list[str] = []
    for gw in alf:
        if not isinstance(gw, dict):
            continue
        gw_id = gw.get("id")
        if gw_id and str(gw.get("role", "TRADER")).upper() == target:
            result.append(str(gw_id).strip().upper())
    return result


def all_gateway_ids(raw: dict[str, Any]) -> set[str]:
    """Return the set of all upper-cased gateway ids."""
    gateways = raw.get("gateways", {})
    if not isinstance(gateways, dict):
        return set()
    alf = gateways.get("alf", [])
    if not isinstance(alf, list):
        return set()
    return {
        str(gw["id"]).strip().upper()
        for gw in alf
        if isinstance(gw, dict) and gw.get("id")
    }


def symbol_cfg_by_upper_name(raw: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Map upper-cased symbol name -> its config mapping (skipping non-dicts)."""
    symbols = raw.get("symbols", {})
    if not isinstance(symbols, dict):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for key, cfg in symbols.items():
        if isinstance(cfg, dict):
            out[str(key).upper()] = cfg
    return out
