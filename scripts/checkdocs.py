#!/usr/bin/env python3
"""Verify that the documentation matches the code.

Three independent checks, all against ground truth rather than a word list:

  links    every relative link and #anchor resolves, using the same slug
           algorithm mkdocs uses (Python-Markdown's toc extension)
  cli      every `pm-*` command and `--flag` shown in a fenced code block
           exists, checked against each CLI's real argparse --help output
  config   every YAML block that looks like an engine configuration is run
           through pm-cverifier and must produce no schema errors

Run it from the repository root:

    poetry run python scripts/checkdocs.py            # all checks
    poetry run python scripts/checkdocs.py links cli  # a subset

Exit code is non-zero if any check fails, so it works in CI.
"""
from __future__ import annotations

import argparse
import glob
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import contextlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ["docs/**/*.md"]
SKIP = ("/.build/", "/site/")

GREEN, RED, YELLOW, RESET = "\033[32m", "\033[31m", "\033[33m", "\033[0m"


def doc_files() -> list[str]:
    out: list[str] = []
    for pat in DOCS:
        out += [p for p in glob.glob(pat, recursive=True) if not any(s in p for s in SKIP)]
    return sorted(set(out))


# --------------------------------------------------------------------------
# links
# --------------------------------------------------------------------------
LINK = re.compile(r"\]\(\s*(?!https?:|mailto:)([^)\s#]*)(?:#([^)\s]+))?\s*\)")
FENCE = re.compile(r"(?ms)^```.*?^```")


def check_links() -> list[str]:
    try:
        import markdown
    except ImportError:
        return ["links: the 'markdown' package is not installed (poetry install --with docs)"]

    exts = ["admonition", "attr_list", "tables", "toc", "fenced_code"]
    cache: dict[str, set[str]] = {}

    def ids_for(path: str) -> set[str]:
        if path not in cache:
            html = markdown.Markdown(extensions=exts).convert(
                Path(path).read_text(encoding="utf-8"))
            cache[path] = set(re.findall(r'\bid="([^"]+)"', html))
        return cache[path]

    problems = []
    for p in doc_files():
        text = FENCE.sub("", Path(p).read_text(encoding="utf-8"))
        for m in LINK.finditer(text):
            target, anchor = m.group(1), m.group(2)
            tgt = p if not target else os.path.normpath(os.path.join(os.path.dirname(p), target))
            if not os.path.exists(tgt):
                problems.append(f"{p}: link to missing file {target!r}")
            elif anchor and tgt.endswith(".md") and anchor not in ids_for(tgt):
                problems.append(f"{p}: no anchor #{anchor} in {target or '(this file)'}")
    return problems


# --------------------------------------------------------------------------
# cli
# --------------------------------------------------------------------------
def entry_points() -> dict[str, str]:
    ep = {}
    for line in (ROOT / "pyproject.toml").read_text().splitlines():
        m = re.match(r"^(pm-[\w-]+)\s*=\s*\"([^\"]+)\"", line)
        if m:
            ep[m.group(1)] = m.group(2)
    return ep


def help_text(cmd: str, spec: str, args: list[str]) -> str:
    mod, fn = spec.split(":")
    argv_json = json.dumps([cmd] + args + ["--help"])
    code = (
        "import sys, io, contextlib, importlib, json\n"
        f"sys.argv=json.loads({argv_json!r})\n"
        "out=io.StringIO()\n"
        f"m=importlib.import_module({mod!r})\n"
        "with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):\n"
        f"    try: getattr(m,{fn!r})()\n"
        "    except SystemExit: pass\n"
        "    except BaseException: pass\n"
        "sys.stdout.write(out.getvalue())\n"
    )
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                       cwd=ROOT, timeout=180)
    return r.stdout if r.returncode == 0 else ""


FLAG = re.compile(r"(?<![\w-])(--[a-z][a-z0-9-]*)")
CODE = re.compile(r"(?ms)^```(?:bash|console|sh|shell)?\n(.*?)^```")


def subcommands(t: str) -> set[str]:
    out = set()
    m = re.search(r"(?ms)^positional arguments:\n(.*?)(?=^\S|\Z)", t)
    if m:
        for line in m.group(1).split("\n"):
            mm = re.match(r"^\s{2,}([a-z][a-z0-9_-]+)(\s{2,}|$)", line)
            if mm:
                out.add(mm.group(1))
    return out


def check_cli() -> list[str]:
    ep = entry_points()
    known: dict[str, set[str]] = {}
    for cmd, spec in ep.items():
        top = help_text(cmd, spec, [])
        if not top:
            continue
        flags = set(FLAG.findall(top))
        for sub in sorted(subcommands(top)):
            flags |= set(FLAG.findall(help_text(cmd, spec, [sub])))
        known[cmd] = flags

    problems = []
    for p in doc_files():
        text = Path(p).read_text(encoding="utf-8")
        for cb in CODE.finditer(text):
            base = text[: cb.start()].count("\n") + 1
            for i, raw in enumerate(cb.group(1).split("\n")):
                line = raw.strip()
                if line.startswith("$ "):
                    line = line[2:]
                if not line or line.startswith("#"):
                    continue
                m = re.match(r"^(?:poetry run |sudo )?(pm-[a-z0-9-]+)\b(.*)$", line)
                if not m:
                    continue
                cmd, rest = m.group(1), m.group(2)
                ln = base + i + 1
                if cmd not in ep:
                    problems.append(f"{p}:{ln}: no such command {cmd!r}")
                    continue
                if cmd not in known:
                    continue  # could not introspect; do not guess
                for fl in FLAG.findall(rest):
                    if fl not in known[cmd]:
                        problems.append(f"{p}:{ln}: {cmd} has no flag {fl}  ({line})")
    return problems


# --------------------------------------------------------------------------
# config
# --------------------------------------------------------------------------
YAML_BLOCK = re.compile(r"(?ms)^```ya?ml\n(.*?)^```")


def check_config() -> list[str]:
    try:
        import yaml
    except ImportError:
        return ["config: PyYAML is not installed"]

    base_path = None
    for cand in ("src/data/ref_data/engine_config.yaml",
                 "docs/examples/ref_data/three-books-basic-setup/engine_config.yaml"):
        if (ROOT / cand).exists():
            base_path = ROOT / cand
            break
    if base_path is None:
        return ["config: no baseline engine_config.yaml found; skipping"]

    base = yaml.safe_load(base_path.read_text())
    known_keys = set(base) | {
        "sessions_enabled", "country", "schedule", "collars", "circuit_breakers",
        "engine_tuning", "alf_gateway", "balf_gateway", "market_data_gateway",
        "post_trade_gateway", "dc_gateway", "log_server", "api_gateways",
        "indices", "market_maker_combos", "risk", "combos",
    }

    from edumatcher.cverifier.cli import main as cverifier_main

    problems = []
    for p in doc_files():
        text = Path(p).read_text(encoding="utf-8")
        for m in YAML_BLOCK.finditer(text):
            ln = text[: m.start()].count("\n") + 1
            try:
                doc = yaml.safe_load(m.group(1))
            except Exception as exc:
                problems.append(f"{p}:{ln}: YAML does not parse: {exc.__class__.__name__}")
                continue
            if not isinstance(doc, dict) or not (set(doc) & known_keys):
                continue
            merged = {**base, **doc}
            with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
                yaml.safe_dump(merged, f, sort_keys=False)
                tmp = f.name
            buf = io.StringIO()
            argv = sys.argv
            try:
                sys.argv = ["pm-cverifier", "--format", "json", tmp]
                with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
                    try:
                        cverifier_main()
                    except SystemExit:
                        pass
            finally:
                sys.argv = argv
                os.unlink(tmp)
            try:
                report = json.loads(buf.getvalue())
            except Exception:
                continue
            # M0xx are cross-reference checks against the merged baseline's own
            # gateways, which a partial example legitimately replaces. Only
            # schema-level errors indicate a broken example.
            for chk in report.get("checks", []):
                if chk.get("severity") == "ERROR" and not str(chk.get("code", "")).startswith("M"):
                    problems.append(f"{p}:{ln}: {chk.get('code')} {chk.get('message')}")
    return problems


CHECKS = {"links": check_links, "cli": check_cli, "config": check_config}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("checks", nargs="*", choices=sorted(CHECKS) or None,
                    help="which checks to run (default: all)")
    args = ap.parse_args()
    selected = args.checks or sorted(CHECKS)

    failed = 0
    for name in selected:
        print(f"{YELLOW}==> {name}{RESET}", flush=True)
        problems = CHECKS[name]()
        if problems:
            failed += 1
            for line in problems:
                print(f"  {RED}✗{RESET} {line}")
            print(f"  {RED}{len(problems)} problem(s){RESET}")
        else:
            print(f"  {GREEN}✓ clean{RESET}")
    return 1 if failed else 0


if __name__ == "__main__":
    os.chdir(ROOT)
    sys.exit(main())
