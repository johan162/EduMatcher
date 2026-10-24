#!/usr/bin/env python3
"""Build the EduMatcher web site.

    python web_site/build.py                  # pages + embedded docs + download links
    python web_site/build.py --no-docs        # pages only (fast, for design work)
    python web_site/build.py --downloads local    # self-host books/wheels found in docs/dist and dist/
    python web_site/build.py --downloads local --strict   # release build: every file must be self-hosted
    python web_site/build.py --downloads release  # no self-hosting: link what the GitHub release carries
    python web_site/build.py --build-dist     # also `poetry build` the wheel/sdist if missing
    python web_site/build.py --serve          # build, then serve on http://localhost:8000

Everything that changes between releases is derived, never typed in by hand:

  version ............ pyproject.toml
  command / test /
  code-size counts ... pyproject.toml, tests/, src/
  documentation ...... docs/ + mkdocs.yml  ->  web_site/docs/   (via mkdocs-site.yml)
  intro book ......... docs-exchange-intro/version.toml (its own version) + dist/ files, shown
                       and downloaded separately from the guide books
  book downloads ..... data/books.json x version  ->  copies of the PDFs/EPUBs in docs/dist
                       (self-hosted) plus a link to the all-formats ZIP on the GitHub release
  system downloads ... wheel / sdist (self-hosted from dist/) and source archives of the tag
  benchmark figures .. data/facts.json (edit by hand after re-running benchmarks)

scripts/mkghrelease.sh runs this script (with --strict) and uploads the result with
scripts/mkweb.sh at the end of every release — see web_site/README.md.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import shutil
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path

SITE = Path(__file__).resolve().parent
REPO = SITE.parent
SRC = SITE / "src"
REPO_URL = "https://github.com/johan162/EduMatcher"

NAV_PAGES = ("platform", "apps", "learn", "docs", "download")


# --------------------------------------------------------------------------- facts
def project_facts() -> dict[str, str]:
    meta = tomllib.loads((REPO / "pyproject.toml").read_text())
    poetry = meta["tool"]["poetry"]
    scripts = poetry.get("scripts", {})
    tests = sum(
        len(re.findall(r"^\s*(?:async )?def test_", f.read_text(errors="ignore"), re.M))
        for f in (REPO / "tests").rglob("test_*.py")
    )
    loc = sum(sum(1 for _ in f.open(errors="ignore")) for f in (REPO / "src").rglob("*.py"))
    facts_file = json.loads((SITE / "data" / "facts.json").read_text())
    facts = {
        "VERSION": poetry["version"],
        "N_COMMANDS": str(sum(1 for k in scripts if k.startswith("pm-"))),
        "N_TESTS": str(tests // 100 * 100),
        "N_LOC": str(loc // 1000 * 1000),
        "N_LOC_FMT": f"{loc // 1000 * 1000:,}",
        "N_TESTS_FMT": f"{tests // 100 * 100:,}",
        "PYTHON": poetry["dependencies"]["python"].lstrip("^~>="),
    }
    for k, v in facts_file.items():
        if not k.startswith("_"):
            facts["F_" + k.upper()] = f"{v:,}" if isinstance(v, int) else str(v)
    return facts


# --------------------------------------------------------------------------- downloads
def fmt_size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}".replace(".0 ", " ")
        n /= 1024
    return ""


class Downloads:
    """Resolve each artifact to a self-hosted copy (if allowed and present) or a release URL."""

    def __init__(self, mode: str, version: str):
        self.mode, self.version = mode, version
        self.local_dir = SITE / "downloads"
        self.sums: list[tuple[str, str]] = []
        self.used_local = 0
        self.missing: list[str] = []  # files that should be self-hosted but were not found locally
        if self.local_dir.exists():
            shutil.rmtree(self.local_dir)

    def release_url(self, name: str) -> str:
        return f"{REPO_URL}/releases/download/v{self.version}/{name}"

    def resolve(self, name: str, *candidates: Path, group: str,
                on_release: bool = True) -> tuple[str | None, str | None]:
        """Return (href, size). A local copy wins; otherwise the GitHub release asset if the
        release really carries this file (`on_release`), otherwise (None, None)."""
        if self.mode != "release":
            for c in candidates:
                if c.is_file():
                    dest = self.local_dir / group / name
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(c, dest)
                    self.sums.append((hashlib.sha256(dest.read_bytes()).hexdigest(), f"{group}/{name}"))
                    self.used_local += 1
                    return f"downloads/{group}/{name}", fmt_size(dest.stat().st_size)
        self.missing.append(name)
        return (self.release_url(name), None) if on_release else (None, None)

    def write_sums(self) -> None:
        if self.sums:
            (self.local_dir / "SHA256SUMS.txt").write_text(
                "".join(f"{h}  {n}\n" for h, n in sorted(self.sums, key=lambda x: x[1]))
            )


ICON_FILE = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" '
             'stroke-linejoin="round"><path d="M12 3v12m0 0l-4-4m4 4l4-4M4 20h16"/></svg>')


def book_artifacts(book: dict, dl: Downloads) -> dict[str, tuple[str | None, str | None]]:
    """Per-format files are self-hosted (the GitHub release only carries the all-formats ZIP)."""
    v, stem, dist = dl.version, book["stem"], REPO / "docs" / "dist"
    names = {
        "A4": f"edumatcher_{stem}_a4-{v}.pdf",
        "B5": f"edumatcher_{stem}_b5-{v}.pdf",
        "A4 dark": f"edumatcher_{stem}_dark_a4-{v}.pdf",
        "B5 dark": f"edumatcher_{stem}_dark_b5-{v}.pdf",
        "EPUB": f"edumatcher_{stem}-{v}.epub",
    }
    out = {k: dl.resolve(n, dist / n, group="books", on_release=False) for k, n in names.items()}
    out["ZIP"] = (dl.release_url(f"edumatcher_{stem}_all-{v}.zip"), None)  # attached by mkghrelease.sh
    return out


def books_download_html(books: list[dict], dl: Downloads) -> str:
    rows = []
    for b in books:
        links = "".join(
            f'<a href="{html.escape(h)}" download title="{html.escape(b["title"])} — {k}'
            f'{" · " + sz if sz else ""}">{k}</a>' if h else
            f'<a class="na" title="not hosted for this build">{k}</a>'
            for k, (h, sz) in book_artifacts(b, dl).items()
        )
        rows.append(
            f'<tr><td><img src="assets/img/covers/{b["cover"]}" alt="" width="46" loading="lazy" '
            f'style="border-radius:3px;display:inline-block;vertical-align:middle;margin-right:14px">'
            f'{html.escape(b["title"])}</td><td>{html.escape(b["audience"])}</td><td class="fmt">{links}</td></tr>'
        )
    return "\n".join(rows)


def system_download_html(dl: Downloads) -> str:
    v = dl.version
    whl, sdist = f"edumatcher-{v}-py3-none-any.whl", f"edumatcher-{v}.tar.gz"
    items = [
        (whl, "Python wheel", dl.resolve(whl, REPO / "dist" / whl, group="system")),
        (sdist, "Source distribution (sdist)", dl.resolve(sdist, REPO / "dist" / sdist, group="system")),
        (f"EduMatcher-{v}-source.zip", "Complete source tree, this release", (f"{REPO_URL}/archive/refs/tags/v{v}.zip", None)),
        (f"EduMatcher-{v}-source.tar.gz", "Complete source tree, this release", (f"{REPO_URL}/archive/refs/tags/v{v}.tar.gz", None)),
    ]
    out = []
    for name, label, (href, size) in items:
        out.append(
            f'<a class="file" href="{html.escape(href)}" download>{ICON_FILE}<span><span class="nm">{name}</span>'
            f'<br><span class="muted small">{label}</span></span><span class="sz">{size or "GitHub"}</span></a>'
        )
    return "\n".join(out)


def deck_download_html() -> str:
    """Slide decks ship inside docs/ (and so inside the embedded docs site); list whatever is there."""
    pres = REPO / "docs" / "presentations"
    out = []
    for pdf in sorted(pres.rglob("*.pdf")):
        if "Lattice" in pdf.name:  # unrelated finance side-material
            continue
        rel = pdf.relative_to(REPO / "docs").as_posix()
        label = re.sub(r"\b(Alf|Api|Calf|Ralf|Gwy|Msg)\b", lambda m: m.group(1).upper() if m.group(1) != "Gwy" else "Gateway",
                       pdf.stem.replace("-", " ").replace("_", " ").title()).replace("Edumatcher", "EduMatcher")
        out.append(
            f'<a class="file" href="docs/{html.escape(rel)}" download>{ICON_FILE}<span class="nm">{html.escape(label)}</span>'
            f'<span class="sz">{fmt_size(pdf.stat().st_size)}</span></a>'
        )
    return "\n".join(out)


def intro_info(intro: dict) -> dict[str, str]:
    """Facts about the general-introduction book, which is versioned independently of EduMatcher."""
    src = REPO / intro["source"]
    version = tomllib.loads((src / "version.toml").read_text())["config"]["version"]
    manifest = tomllib.loads((src / "book.toml").read_text())
    chapters = sum(1 for part in manifest.get("parts", []) for f in part["files"] if not f.startswith("00-part"))
    return {"INTRO_VERSION": version, "INTRO_CHAPTERS": str(chapters), "INTRO_TITLE": intro["title"],
            "INTRO_BLURB": intro["blurb"], "INTRO_URL": f'docs/{intro["read_online"]}/'}


def _links(items: dict[str, tuple[str | None, str | None]], title: str) -> str:
    return "".join(
        f'<a href="{html.escape(h)}" download title="{html.escape(title)} — {k}{" · " + sz if sz else ""}">{k}</a>'
        if h else f'<a class="na" title="not hosted for this build">{k}</a>'
        for k, (h, sz) in items.items()
    )


def intro_downloads_html(intro: dict, iv: str, dl: Downloads) -> str:
    """Table rows for the introduction book: complete book, by part, quizzes (its own version `iv`)."""
    stem, dist, title = intro["stem"], REPO / intro["source"] / "dist", intro["title"]
    names = {"A4": f"{stem}_a4-{iv}.pdf", "B5": f"{stem}_b5-{iv}.pdf", "A4 dark": f"{stem}_dark_a4-{iv}.pdf",
             "B5 dark": f"{stem}_dark_b5-{iv}.pdf", "EPUB": f"{stem}-{iv}.epub"}
    complete = {k: dl.resolve(n, dist / n, group="intro", on_release=k == "EPUB") for k, n in names.items()}

    # The four part PDFs are shipped as one ZIP; unpack them so each part is a direct download.
    parts: dict[str, tuple[str | None, str | None]] = {}
    zip_name = f"{stem}_parts_a4_bundle-{iv}.zip"
    if dl.mode != "release" and (dist / zip_name).is_file():
        out = dl.local_dir / "intro"
        out.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(dist / zip_name) as zf:
            for info in sorted(zf.infolist(), key=lambda i: i.filename):
                m = re.search(r"part-([IV]+)-", info.filename)
                if not m or not info.filename.endswith(".pdf"):
                    continue
                dest = out / Path(info.filename).name
                dest.write_bytes(zf.read(info))
                dl.sums.append((hashlib.sha256(dest.read_bytes()).hexdigest(), f"intro/{dest.name}"))
                dl.used_local += 1
                parts[f"Part {m.group(1)}"] = (f"downloads/intro/{dest.name}", fmt_size(dest.stat().st_size))
    if not parts:
        parts["ZIP"] = dl.resolve(zip_name, dist / zip_name, group="intro")

    quiz_name = f"{stem}_quiz_bundle-{iv}.zip"
    quiz = {"ZIP": dl.resolve(quiz_name, dist / quiz_name, group="intro")}

    rows = [("Complete book", complete), ("By part (A4 PDF)", parts), ("Quizzes &amp; self-study", quiz)]
    return "\n".join(f'<tr><td>{label}</td><td class="fmt">{_links(items, title)}</td></tr>' for label, items in rows)


def books_cards_html(books: list[dict]) -> str:
    out = []
    for b in books:
        entry = b["entry"].removesuffix("/index")
        out.append(
            f'<a class="book rv" href="docs/{entry}/"><div class="cover"><img src="assets/img/covers/{b["cover"]}" '
            f'alt="Cover of the {html.escape(b["title"])}" loading="lazy" width="720" height="1019"></div>'
            f'<h3>{html.escape(b["title"])}</h3><p>{html.escape(b["blurb"])}</p>'
            f'<span class="meta">{html.escape(b["audience"])}</span></a>'
        )
    return "\n".join(out)


def check_entries(books: list[dict], intro: dict) -> None:
    missing = [b["entry"] for b in books if not (REPO / "docs" / f'{b["entry"]}.md').exists()]
    if not (REPO / "docs" / f'{intro["read_online"]}.md').exists():
        missing.append(intro["read_online"])
    if missing:
        sys.exit("books.json points at docs pages that do not exist: " + ", ".join(missing))


# --------------------------------------------------------------------------- pages
def render_pages(vars_: dict[str, str]) -> list[str]:
    partials = {p.stem: p.read_text() for p in (SRC / "partials").glob("*.html")}
    written = []
    for src in sorted((SRC / "pages").glob("*.html")):
        text = src.read_text()
        meta: dict[str, str] = {}
        if text.startswith("---\n"):
            head, text = text[4:].split("\n---\n", 1)
            for line in head.splitlines():
                k, _, v = line.partition(":")
                meta[k.strip()] = v.strip()
        page = src.stem
        v = dict(vars_)
        v["TITLE"] = html.escape(meta.get("title", "EduMatcher"))
        v["DESC"] = html.escape(meta.get("desc", ""), quote=True)
        for p in NAV_PAGES:
            v[f"CUR_{p}"] = 'aria-current="page"' if meta.get("nav", page) == p else ""
        body = text
        for _ in range(2):  # partials may contain placeholders but not other partials
            for name, content in partials.items():
                body = body.replace("{{> %s}}" % name, content)
        body = re.sub(r"\{\{([A-Za-z0-9_]+)\}\}", lambda m: v.get(m.group(1), m.group(0)), body)
        left = re.findall(r"\{\{[A-Za-z0-9_> ]+\}\}", body)
        if left:
            sys.exit(f"{src.name}: unresolved placeholders {sorted(set(left))}")
        (SITE / f"{page}.html").write_text(body)
        written.append(f"{page}.html")
    return written


def build_docs() -> None:
    cmd = None
    for cand in (REPO / ".venv" / "bin" / "mkdocs", shutil.which("mkdocs")):
        if cand and Path(cand).exists():
            cmd = [str(cand)]
            break
    if cmd is None and shutil.which("poetry"):
        cmd = ["poetry", "run", "mkdocs"]
    if cmd is None:
        sys.exit("mkdocs not found. Install the docs group (poetry install --with docs) or use --no-docs.")
    print("• building documentation with mkdocs …")
    subprocess.run(cmd + ["build", "-q", "-f", str(SITE / "mkdocs-site.yml")], check=True, cwd=REPO)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-docs", action="store_true", help="skip the mkdocs build (about 25 s)")
    ap.add_argument("--downloads", choices=("auto", "local", "release"), default="auto",
                    help="auto/local: self-host files found in docs/dist and dist/ (the rest link to the "
                         "GitHub release); release: link everything to the GitHub release")
    ap.add_argument("--strict", action="store_true",
                    help="fail if any file that should be self-hosted (wheel, sdist, book PDFs/EPUBs) is missing "
                         "locally; used by the release script so a half-empty download page is never published")
    ap.add_argument("--build-dist", action="store_true",
                    help="run `poetry build` first if the wheel/sdist for this version are missing from dist/")
    ap.add_argument("--serve", action="store_true", help="serve web_site/ on :8000 after building")
    a = ap.parse_args()

    f = project_facts()
    cfg = json.loads((SITE / "data" / "books.json").read_text())
    books, intro = cfg["books"], cfg["intro"]
    check_entries(books, intro)
    intro_facts = intro_info(intro)

    if a.build_dist and not (REPO / "dist" / f"edumatcher-{f['VERSION']}.tar.gz").exists():
        print("• building wheel and sdist with poetry …")
        subprocess.run(["poetry", "build"], check=True, cwd=REPO)

    dl = Downloads(a.downloads, f["VERSION"])
    f.update(
        BOOKS_CARDS=books_cards_html(books),
        BOOKS_DOWNLOAD_ROWS=books_download_html(books, dl),
        SYSTEM_FILES=system_download_html(dl),
        DECK_FILES=deck_download_html(),
        N_BOOKS=str(len(books)),
        INTRO_DOWNLOAD_ROWS=intro_downloads_html(intro, intro_facts["INTRO_VERSION"], dl),
        **intro_facts,
        REPO_URL=REPO_URL,
        RELEASE_URL=f"{REPO_URL}/releases/tag/v{f['VERSION']}",
        LATEST_URL=f"{REPO_URL}/releases/latest",
        SUMS_LINK=('<a href="downloads/SHA256SUMS.txt">SHA256SUMS.txt</a>' if dl.sums
                   else "the checksums attached to the GitHub release"),
    )
    if a.strict and dl.missing:
        sys.exit("--strict: not found locally (build them first, see web_site/README.md):\n  " + "\n  ".join(dl.missing))
    dl.write_sums()
    pages = render_pages(f)
    if not a.no_docs:
        build_docs()
    print(f"✓ v{f['VERSION']}: {len(pages)} pages, {dl.used_local} self-hosted downloads"
          f"{' (docs skipped)' if a.no_docs else ''}")
    if a.serve:
        import functools
        import http.server

        h = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(SITE))
        print("serving http://localhost:8000  (Ctrl-C to stop)")
        http.server.ThreadingHTTPServer(("", 8000), h).serve_forever()


if __name__ == "__main__":
    main()
