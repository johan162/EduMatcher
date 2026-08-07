"""Shared runtime support for generated message bindings.

Hand-written and committed - this is the one file under ``generated/`` that is
NOT generated, so it carries no ``DO NOT EDIT`` banner. Every generated family
module imports from here rather than declaring its own error type, which is
what lets a caller write one ``except`` clause for all of them.
"""

from __future__ import annotations


class MessageValidationError(ValueError):
    """A message failed a validation rule declared in its specification.

    Subclasses ``ValueError`` deliberately. The tree already has three
    unrelated validation errors - ``CalfParseError``,
    ``alf_gwy.protocol.ValidationError`` and
    ``balf_gwy.protocol.BalfValidationError`` - none of which fits a generated
    binding, and existing call sites that guard with ``except ValueError``
    keep working unchanged.

    Raised only by a generated ``validate()`` (and therefore by ``make_*`` and
    ``parse_*``, which call it). ``from_dict`` never raises this: it coerces
    without validating, so a reader of historical data can opt out of the
    rules. See section 5.1.1 of
    ``docs-design/EduMatcher-Message-Generator.md``.
    """
