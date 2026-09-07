"""Canonicalisation rules R1-R9 and Label/Actor identifier mapping.

Reduces raw, time-dependent evidence captured by the Collectors into a
stable, comparable Canonical Outcome: dropping volatile fields, remapping
real order/trade/gateway/session identifiers to scenario Labels and Actor
names, normalising price representation, and sorting unordered collections
into a deterministic order.

See design.md Components §11 (Canonicaliser).
"""
