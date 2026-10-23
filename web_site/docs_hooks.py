"""MkDocs hooks that dress the embedded documentation in the web-site theme.

* adds docs_theme/docs-site.css and docs-site.js to every page (the files are
  injected into the build, so the shared docs/ directory stays untouched);
* before Material paints, copies the site's saved theme choice ("em-theme") into
  Material's own palette storage, so light/dark carries across the whole site.
"""
from __future__ import annotations

from pathlib import Path

from mkdocs.structure.files import File
from mkdocs.utils import get_relative_url

THEME_DIR = Path(__file__).parent / "docs_theme"  # holds assets/docs-site.{css,js}
ASSETS = ("docs-site.css", "docs-site.js")


def on_config(config):
    config.extra_css.append("assets/docs-site.css")
    config.extra_javascript.append("assets/docs-site.js")
    return config


def on_files(files, config):
    for name in ASSETS:
        files.append(File(f"assets/{name}", str(THEME_DIR), config.site_dir, False))
    return files


_THEME_SYNC = """<script>(function(){try{var t=localStorage.getItem("em-theme");if(t!=="light"&&t!=="dark")return;
var s=new URL("%s",location),k=s.pathname+".__palette",d=t==="dark";
localStorage.setItem(k,JSON.stringify({index:d?1:0,color:{media:d?"(prefers-color-scheme: dark)":"(prefers-color-scheme: light)",scheme:d?"slate":"default",primary:"custom",accent:"custom"}}));}catch(e){}})();</script>"""


def on_post_page(output, page, config):
    root = get_relative_url(".", page.url)
    marker = "<body"
    i = output.find(marker)
    if i < 0:
        return output
    j = output.find(">", i) + 1
    return output[:j] + _THEME_SYNC % (root if root.endswith("/") else root + "/") + output[j:]
