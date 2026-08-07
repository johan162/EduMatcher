"""pm-msgen — generate message bindings from the canonical specification.

One YAML file per message family under ``spec/messages/`` is the single source
of truth for a message's fields, units and validation rules. This package turns
that into the Python binding committed under
``edumatcher/models/generated/``, and ``pm-msgen check`` fails the build when
the committed output no longer matches the spec.

See ``docs-design/EduMatcher-Message-Generator.md`` for the design and
``docs/developer/06-msgen.md`` for usage.

Phase 1 generates the Python binding only. C generation and the documentation
appendix are Phases 4 and 6.
"""
