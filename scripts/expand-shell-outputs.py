#!/usr/bin/env python3
"""Expand {{!cmd:head:tail}} shell-command placeholders in markdown files.

Each placeholder is replaced with the command's stdout wrapped in triple-backtick
blocks. Files are processed in parallel. Any command failure causes an immediate
exit with a non-zero status.

Placeholder syntax
------------------
  {{!cmd}}                Full output in one ```...``` block.
  {{!cmd:N}}              First N lines of output in one ```...``` block.
  {{!cmd:N:M}}            First N lines in one ```...``` block, blank line, then
                          last M lines in a second ```...``` block.
  {{!cmd:N:M:P}}          First N lines in one ```...``` block, blank line, then
                          the next M lines in a second ```...``` block, blank line,
                          then the last P lines in a third ```...``` block.
  {{!cmd@A4:25:25,B5:20:20}}  Format-specific truncation. When --format a4 is
                              passed, use A4 spec (25:25); when --format b5,
                              use B5 spec (20:20). If format not present in
                              specs, use full output for that format.
  {{!cmd@A4:10:20:30}}    Triple variant with format spec: first 10 lines,
                          next 20 lines, last 30 lines.
  {{!cmd@B5:20:20}}       Only B5 format has a spec; other formats use full output.
  {{!cmd@A4:10*}}         Remainder variant: first 10 lines, then all remaining
                          lines to the end of output.
  {{!cmd@A4:10:20*}}      First 10 lines, next 20 lines, then all remaining lines.
                          With *, the second number means "next N" not "last N".
  {{!cmd@L}}              Add zero-padded line numbers at the left edge of every
                          line. The number reflects the actual line position in the
                          command output. Width is the minimum digits needed for the
                          highest line number shown (e.g. 1: … 9:, then 01: … 99:).
  {{!cmd@A4:10,L}}        Format spec + line numbers.
  {{!cmd@A4:10:10,B5:5:10,L}}  Format spec with triple variant + line numbers.

Usage
-----
  expand-shell-outputs.py --output-dir DIR [--cwd DIR] [--format FORMAT] FILE [FILE ...]

The basename of each FILE is preserved; expanded copies are written under
--output-dir. The script exits 1 if any file or command fails.
"""

import argparse
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# Match {{!...content...}} where content may include @ for format specs.
# Uses non-greedy .*? so it does not cross line boundaries and does not
# consume more than one placeholder per match.
_PLACEHOLDER = re.compile(r"\{\{!(.*?)\}\}")


def _run_command(cmd: str, cwd: Path) -> list[str]:
    """Run *cmd* in a shell and return its stdout lines.

    Raises RuntimeError if the command exits with a non-zero status.
    """
    result = subprocess.run(
        cmd,
        shell=True,
        capture_output=True,
        text=True,
        cwd=cwd,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Command exited with status {result.returncode}: {cmd!r}\n"
            f"stderr:\n{result.stderr.strip()}"
        )
    return result.stdout.splitlines()


def _fence(lines: list[str]) -> str:
    """Wrap *lines* in a fenced code block."""
    return "```\n" + "\n".join(lines) + "\n```"


def _fence_numbered(lines: list[str], start: int, width: int) -> str:
    """Wrap *lines* in a fenced code block with zero-padded line numbers.

    *start* is the 1-based line number of the first line in *lines*.
    *width* is the total digit width for zero-padding.
    """
    numbered = [f"{str(i).zfill(width)}: {line}" for i, line in enumerate(lines, start=start)]
    return "```\n" + "\n".join(numbered) + "\n```"


def _parse_format_specs(
    spec_str: str,
) -> dict[str, tuple[int | None, int | None, int | None, bool]]:
    """Parse format specification string like 'A4:25:25,B5:20:20'.

    Returns dict like {'a4': (25, None, 25, False), 'b5': (20, None, 20, False), ...}
    where tuples are (head, mid, tail, remainder). Any numeric value can be None.
    Two-number specs without * use head+tail; with * they use head+mid (remainder=True).
    Three-number specs always use head+mid+tail.
    """
    specs: dict[str, tuple[int | None, int | None, int | None, bool]] = {}
    for part in spec_str.split(","):
        part = part.strip()
        if not part:
            continue
        pieces = part.split(":")
        if len(pieces) < 1:
            continue
        fmt = pieces[0].strip().lower()
        num_pieces = [p.strip() for p in pieces[1:] if p.strip() or p.strip() == ""]
        # Re-collect to preserve empty slots, then strip for value parsing
        num_pieces = [p.strip() for p in pieces[1:]]
        remainder = False
        if num_pieces and num_pieces[-1].endswith("*"):
            remainder = True
            num_pieces[-1] = num_pieces[-1][:-1]
        head: int | None = None
        mid: int | None = None
        tail: int | None = None
        if len(num_pieces) >= 1 and num_pieces[0]:
            head = int(num_pieces[0])
        if len(num_pieces) >= 3:
            # Three-number variant: head:mid:tail
            mid = int(num_pieces[1]) if num_pieces[1] else None
            tail = int(num_pieces[2]) if num_pieces[2] else None
        elif len(num_pieces) == 2 and num_pieces[1]:
            if remainder:
                # second number is "next N", then take rest
                mid = int(num_pieces[1])
            else:
                tail = int(num_pieces[1])
        specs[fmt] = (head, mid, tail, remainder)
    return specs


def _expand_match(
    match: re.Match, cwd: Path, target_format: str | None = None  # type: ignore
) -> str:
    """Return the replacement text for a single placeholder match.

    Args:
        match: The regex match object
        cwd: Working directory for commands
        target_format: The target format (e.g. 'a4', 'b5'), or None for full output
    """
    content = match.group(1).strip()

    # Split on @ to separate command+inline_specs from format_specs
    if "@" in content:
        cmd_part, format_specs_str = content.split("@", 1)
    else:
        cmd_part = content
        format_specs_str = None

    # Extract the L (line-numbers) flag from the format-specs string.
    line_numbers = False
    if format_specs_str:
        parts = [p.strip() for p in format_specs_str.split(",")]
        if "L" in parts:
            line_numbers = True
            parts = [p for p in parts if p != "L"]
        format_specs_str = ",".join(parts) if parts else None

    # Parse inline head:tail or head:mid:tail from cmd_part (backward compatibility).
    # Look for :N, :N:M, or :N:M:P (optionally followed by *) at the very end.
    inline_match = re.search(r":(\d+)(?::(\d+)(?::(\d+))?)?(\*)?$", cmd_part)
    inline_head: int | None = None
    inline_mid: int | None = None
    inline_tail: int | None = None
    inline_remainder: bool = False
    if inline_match:
        inline_remainder = inline_match.group(4) == "*"
        inline_head = int(inline_match.group(1))
        if inline_match.group(3) is not None:
            # Three-number variant: head:mid:tail
            inline_mid = int(inline_match.group(2))
            inline_tail = int(inline_match.group(3))
        elif inline_match.group(2) is not None:
            if inline_remainder:
                # second number is "next N", then take rest
                inline_mid = int(inline_match.group(2))
            else:
                inline_tail = int(inline_match.group(2))
        cmd = cmd_part[: inline_match.start()].strip()
    else:
        cmd = cmd_part.strip()

    # Parse format-specific specs if present
    format_specs: dict[str, tuple[int | None, int | None, int | None, bool]] = {}
    if format_specs_str:
        format_specs = _parse_format_specs(format_specs_str)

    # Determine which head/mid/tail/remainder to use based on target_format
    head: int | None = None
    mid: int | None = None
    tail: int | None = None
    remainder: bool = False
    if target_format and target_format.lower() in format_specs:
        head, mid, tail, remainder = format_specs[target_format.lower()]
    else:
        # Use inline specs if available (backward compat), else full output
        head = inline_head
        mid = inline_mid
        tail = inline_tail
        remainder = inline_remainder

    lines = _run_command(cmd, cwd)
    n = len(lines)

    if not line_numbers:
        if head is None:
            return _fence(lines)
        if remainder:
            result = _fence(lines[:head])
            if mid is not None:
                result += "\n\n" + _fence(lines[head : head + mid])
                rest = lines[head + mid :]
            else:
                rest = lines[head:]
            if rest:
                result += "\n\n" + _fence(rest)
            return result
        if mid is None and tail is None:
            return _fence(lines[:head])
        if mid is None:
            tail_lines = lines[-tail:] if tail and tail > 0 else []
            return _fence(lines[:head]) + "\n\n" + _fence(tail_lines)
        mid_lines = lines[head : head + mid]
        tail_lines = lines[-tail:] if tail and tail > 0 else []
        return _fence(lines[:head]) + "\n\n" + _fence(mid_lines) + "\n\n" + _fence(tail_lines)

    # --- Line-numbered output ---
    # Width is always based on n when remainder is True (we show to end of output).
    if head is None:
        max_line_no = n
    elif remainder:
        max_line_no = n
    else:
        max_line_no = head
        if mid is not None:
            max_line_no = max(max_line_no, head + mid)
        if tail is not None and tail > 0:
            max_line_no = max(max_line_no, n)
    width = len(str(max(max_line_no, 1)))

    if head is None:
        return _fence_numbered(lines, 1, width)

    if remainder:
        result = _fence_numbered(lines[:head], 1, width)
        if mid is not None:
            result += "\n\n" + _fence_numbered(lines[head : head + mid], head + 1, width)
            rest_start = head + mid
        else:
            rest_start = head
        rest = lines[rest_start:]
        if rest:
            result += "\n\n" + _fence_numbered(rest, rest_start + 1, width)
        return result

    if mid is None and tail is None:
        return _fence_numbered(lines[:head], 1, width)

    if mid is None:
        tail_slice = lines[-tail:] if tail and tail > 0 else []
        result = _fence_numbered(lines[:head], 1, width)
        if tail_slice:
            result += "\n\n" + _fence_numbered(tail_slice, n - len(tail_slice) + 1, width)
        return result

    # Three-section
    mid_lines = lines[head : head + mid]
    tail_slice = lines[-tail:] if tail and tail > 0 else []
    result = _fence_numbered(lines[:head], 1, width)
    result += "\n\n" + _fence_numbered(mid_lines, head + 1, width)
    if tail_slice:
        result += "\n\n" + _fence_numbered(tail_slice, n - len(tail_slice) + 1, width)
    return result


def _process_file(src: Path, out_dir: Path, cwd: Path, target_format: str | None) -> None:
    """Expand all placeholders in *src* and write the result to *out_dir/src.name*."""
    text = src.read_text(encoding="utf-8")
    expanded = _PLACEHOLDER.sub(
        lambda m: _expand_match(m, cwd, target_format), text
    )
    (out_dir / src.name).write_text(expanded, encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Expand {{!cmd:head:tail}} and format-aware placeholders in markdown files."
    )
    ap.add_argument(
        "--output-dir",
        required=True,
        type=Path,
        metavar="DIR",
        help="Directory to write expanded copies into.",
    )
    ap.add_argument(
        "--cwd",
        default=".",
        type=Path,
        metavar="DIR",
        help="Working directory for shell commands (default: current directory).",
    )
    ap.add_argument(
        "--format",
        default=None,
        metavar="FORMAT",
        help="Target format (e.g. 'a4', 'b5'). When specified, format-specific "
        "truncation rules are applied if present in placeholders (e.g. @A4:25:25). "
        "If the format is not specified in a placeholder, full output is used.",
    )
    ap.add_argument("files", nargs="+", type=Path, help="Markdown files to process.")
    args = ap.parse_args()

    out_dir: Path = args.output_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    cwd: Path = args.cwd.resolve()

    failed = False
    with ThreadPoolExecutor() as pool:
        futures = {
            pool.submit(_process_file, Path(f), out_dir, cwd, args.format): f
            for f in args.files
        }
        for fut in as_completed(futures):
            try:
                fut.result()
            except Exception as exc:
                print(f"ERROR processing {futures[fut]}: {exc}", file=sys.stderr)
                failed = True

    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
    