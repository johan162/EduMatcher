"""Report → Markdown, for --export."""

from __future__ import annotations

from edumatcher.valuation.report.build import (
    Block,
    Bullets,
    Paragraph,
    Report,
    Section,
    Table,
)


def _cell(text: str) -> str:
    return text.replace("|", "\\|")


def _block(block: Block) -> str:
    if isinstance(block, Table):
        rule = "|".join("---:" if a == "r" else "---" for a in block.align)
        lines = [
            "| " + " | ".join(_cell(h) for h in block.headers) + " |",
            f"|{rule}|",
            *("| " + " | ".join(_cell(c) for c in row) + " |" for row in block.rows),
        ]
        return "\n".join(lines)
    if isinstance(block, Paragraph):
        return block.text
    if isinstance(block, Bullets):
        return "\n".join(f"- {item}" for item in block.items)
    return f"```text\n{block.text}\n```"


def render_section(section: Section) -> str:
    return f"## {section.title}\n\n" + "\n\n".join(_block(b) for b in section.blocks)


def render_markdown(report: Report) -> str:
    parts = [f"# {report.title}", *(render_section(s) for s in report.sections)]
    return "\n\n".join(parts) + "\n"
