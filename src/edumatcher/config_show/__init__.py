"""pm-config-show — read-only viewer for ``engine_config.yaml``.

The package is deliberately layered so that three renderers (terminal, the
tiny fallback, and PDF) can never disagree about content:

``model``       frozen dataclasses describing what a config *says*
``extract``     raw YAML mapping -> model, defensively
``theme``       the entire palette and glyph set
``panels``      one build function per panel, each sized to a given width
``layout``      panel descriptors, packing, width distribution, gap fill
``render_term`` panel selection, breakpoints, tiny mode
``render_pdf``  A4-landscape multi-page document
``cli``         argparse surface and dispatch

Nothing in this package writes to the configuration or to the data directory.
"""

from __future__ import annotations

__all__ = ["main"]


def main(argv: list[str] | None = None) -> int:
    """Console-script entry point; imported lazily to keep --help fast."""
    from edumatcher.config_show.cli import main as _main

    return _main(argv)
