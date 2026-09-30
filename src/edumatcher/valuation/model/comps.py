"""Comparables cross-check and the fair-value blend (design §10)."""

from __future__ import annotations


def comps_enterprise_value(ntm_revenue: float, multiple: float) -> float:
    """EV at the peers' EV / next-twelve-months revenue multiple."""
    return multiple * ntm_revenue


def blend(dcf_price: float, comps_price: float, dcf_weight: float) -> float:
    """Fair value per share: the bankers' triangulation of the two methods."""
    return dcf_weight * dcf_price + (1 - dcf_weight) * comps_price
