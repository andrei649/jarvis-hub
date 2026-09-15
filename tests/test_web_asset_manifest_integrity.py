"""Every asset a committed page references must be committed alongside it.

From a real Windows startup log:

    GET /v2/assets/index-CiaMdBw0.css → 200
    GET /v2/assets/index-Dnsy9sQO.js  → 404

The CSS resolved and the JS did not, which is the signature of `index.html` and
`assets/` having been committed out of step: Vite content-hashes each bundle, so
a rebuild that lands the new HTML without the new JS (or vice versa) leaves a
dangling reference. There is no error surface for it — the HUD is a blank page
with a 404 in the network tab, and the server logs one line that is easy to read
past.

Nothing about it needs a browser to catch, so this pins it at the tree level:
resolve every local reference in every committed page against the directories
`agents/web.py` actually mounts, and fail on the first one that is missing.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

WEB_ROOT = repo_root / "agents" / "web"

# Mirrors the mounts in agents/web.py: /static → web/static, /v2/assets →
# web/v2/assets. Anything else local resolves against the page's own directory.
MOUNTS = {
    "/static/": WEB_ROOT / "static",
    "/v2/assets/": WEB_ROOT / "v2" / "assets",
}

REFERENCE = re.compile(r'(?:src|href)\s*=\s*"([^"]+)"')

# References that are not files on disk: inline data URIs, absolute URLs,
# template placeholders, and anything a JS string builds at runtime.
SKIP = ("http://", "https://", "//", "data:", "mailto:", "#", "{{")


def _pages() -> list[Path]:
    return sorted(WEB_ROOT.rglob("*.html"))


def _resolve(page: Path, reference: str) -> Path | None:
    """Map a page reference to the file that must exist, or None if not a file."""
    if not reference or reference.startswith(SKIP) or "'+" in reference:
        return None
    path = reference.split("?", 1)[0].split("#", 1)[0]
    if not path:
        return None
    for prefix, directory in MOUNTS.items():
        if path.startswith(prefix):
            return directory / path[len(prefix):]
    if path.startswith("/"):
        # Root-relative and not under a mount: served by a route in web.py,
        # whose files live beside the page tree (e.g. /v2/sw-v2.js).
        return WEB_ROOT / path.lstrip("/")
    return page.parent / path


def test_there_are_pages_to_check():
    """A guard that silently checks nothing is worse than no guard."""
    assert _pages(), f"no committed pages found under {WEB_ROOT}"


@pytest.mark.parametrize("page", _pages(), ids=lambda p: str(p.relative_to(WEB_ROOT)))
def test_every_local_reference_in_a_committed_page_exists(page):
    missing = []
    for reference in REFERENCE.findall(page.read_text(encoding="utf-8")):
        target = _resolve(page, reference)
        if target is not None and not target.exists():
            missing.append(f"{reference} → {target.relative_to(repo_root)}")

    assert not missing, (
        f"{page.relative_to(repo_root)} references files that are not committed:\n  "
        + "\n  ".join(missing)
        + "\n\nThis is the /v2/assets 404 that blanks the HUD. Vite content-hashes "
        "each bundle, so re-run the frontend build and commit agents/web/v2/ as one "
        "unit — index.html and assets/ must never land separately."
    )


def test_the_hud_entry_point_is_wired_to_a_real_bundle():
    """The specific page whose drift was observed, named so the failure is obvious."""
    index = WEB_ROOT / "v2" / "index.html"
    references = REFERENCE.findall(index.read_text(encoding="utf-8"))

    bundles = [r for r in references if r.startswith(("/v2/assets/", "./assets/"))]
    assert any(r.endswith(".js") for r in bundles), "the HUD has no script bundle"
    assert any(r.endswith(".css") for r in bundles), "the HUD has no stylesheet"
    for reference in bundles:
        assert _resolve(index, reference).exists(), reference


def test_no_committed_bundle_is_orphaned():
    """The other half of the drift: bundles left behind by an older build.

    An orphaned hash is dead weight in the repo *and* the tell that the build
    output was committed piecemeal — the same mistake that leaves a page
    pointing at a bundle nobody committed, caught from the opposite side.
    """
    assets = WEB_ROOT / "v2" / "assets"
    roots = [
        _resolve(page, reference)
        for page in _pages()
        for reference in REFERENCE.findall(page.read_text(encoding="utf-8"))
        if reference.startswith(("/v2/assets/", "./assets/"))
    ]
    reachable, missing = _bundle_graph(roots)
    assert not missing, f"missing imported bundles: {sorted(map(str, missing))}"
    orphans = [
        f.name for f in assets.iterdir()
        if f.is_file() and f.resolve() not in reachable and f.suffix in (".js", ".css")
    ]
    assert not orphans, f"stale build output with no reachable entry point: {orphans}"


# Literal module specifiers emitted by Vite: static imports/re-exports, bare
# imports and dynamic imports. This deliberately does not evaluate JavaScript.
MODULE_REFERENCE = re.compile(
    r"(?:\bfrom\s*|\bimport\s*(?:\(\s*)?)[\"'`]([^\"'`]+)[\"'`]"
)
CSS_REFERENCE = re.compile(r"@import\s+(?:url\(\s*)?[\"']([^\"']+)[\"']")
VITE_DEPS = re.compile(r"__vite__mapDeps=.*?m\.f=\[(.*?)\]", re.S)
QUOTED_REFERENCE = re.compile(r"[\"']([^\"']+)[\"']")


def _bundle_graph(roots: list[Path]) -> tuple[set[Path], set[Path]]:
    pending = list(roots)
    seen: set[Path] = set()
    missing: set[Path] = set()
    while pending:
        path = pending.pop().resolve()
        if path in seen:
            continue
        seen.add(path)
        if not path.is_file():
            missing.add(path)
            continue
        source = path.read_text(encoding="utf-8")
        references = MODULE_REFERENCE.findall(source) if path.suffix == ".js" else CSS_REFERENCE.findall(source)
        targets = [_resolve(path, ref) for ref in references if ref.startswith((".", "/"))]
        if path.suffix == ".js":
            # Absolute-base builds use build-root maps; relative-base builds use
            # importer-relative maps (resolved against import.meta.url by Vite).
            for dependency_map in VITE_DEPS.findall(source):
                targets.extend((path.parent if ref.startswith(".") else path.parent.parent) / ref
                               for ref in QUOTED_REFERENCE.findall(dependency_map))
        pending.extend(target for target in targets if target is not None and target.suffix in (".js", ".css"))
    return seen, missing


def test_bundle_graph_follows_nested_imports_and_cycles(tmp_path):
    (tmp_path / "entry.js").write_text('import {x} from "./shared.js"; import("./lazy.js");')
    (tmp_path / "shared.js").write_text('import "./entry.js";')
    (tmp_path / "lazy.js").write_text('export {x} from "./shared.js"; import("./nested.js");')
    (tmp_path / "nested.js").write_text('export const x = 1;')
    (tmp_path / "orphan.js").write_text('export const unused = 1;')
    reachable, missing = _bundle_graph([tmp_path / "entry.js"])
    assert not missing
    assert {p.name for p in reachable} == {"entry.js", "shared.js", "lazy.js", "nested.js"}
    assert tmp_path / "orphan.js" not in reachable


def test_bundle_graph_reports_missing_dynamic_chunk(tmp_path):
    (tmp_path / "entry.js").write_text('import("./missing.js");')
    _, missing = _bundle_graph([tmp_path / "entry.js"])
    assert missing == {tmp_path / "missing.js"}


def test_bundle_graph_follows_vite_preload_css(tmp_path):
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "entry.js").write_text('const __vite__mapDeps=(i,m=__vite__mapDeps,d=(m.f||(m.f=["assets/lazy.css"])))=>i.map(i=>d[i]);')
    (assets / "lazy.css").write_text('@import "./nested.css";')
    _, missing = _bundle_graph([assets / "entry.js"])
    assert missing == {assets / "nested.css"}


def test_bundle_graph_follows_relative_vite_preload_and_missing_css(tmp_path):
    assets = tmp_path / 'assets'
    assets.mkdir()
    (assets / 'entry.js').write_text('const __vite__mapDeps=(i,m=__vite__mapDeps,d=(m.f||(m.f=["./lazy.css"])))=>i.map(i=>d[i]);')
    _, missing = _bundle_graph([assets / 'entry.js'])
    assert missing == {assets / 'lazy.css'}
