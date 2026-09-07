"""Scenario schema, parser, and validator.

Defines the pydantic models for the declarative Scenario DSL (``id``,
``title``, ``tags``, ``symbols``, ``session``, ``actors``, ``steps``, and
``verify``), the loader that parses a Scenario YAML file into those models,
and the load-time validators (duplicate Label detection, undeclared Actor
detection) that reject a malformed Scenario before any Step executes.

See design.md Data Models §1 (Scenario Schema) and Components §3 (Runner).
"""
