"""T-0.29 — the PWA surface for HUD v2 (the shipped default surface).

Before this, the manifest + service worker existed only for the **legacy v1**
shell (`agents/web/static/`), which is not what anyone actually loads: `/` serves
v2 unless `JARVIS_HUD=v1`. So the shipped HUD was not installable and had no
offline shell at all.

These tests pin the wiring and — more importantly — the privacy rule that makes a
service worker safe in a local-first product: it must never cache API responses,
because a cached copy of personal data in the browser's Cache Storage is
unreachable by `forget` and would quietly break the erasure promise in PRIVACY.md.
"""

import re
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents import web  # noqa: E402

V2_DIR = repo_root / "agents" / "web" / "v2"
SW_SRC = repo_root / "frontend" / "public" / "sw-v2.js"
MANIFEST_SRC = repo_root / "frontend" / "public" / "manifest.webmanifest"

pytestmark = pytest.mark.skipif(
    not (V2_DIR / "index.html").is_file(),
    reason="v2 bundle not built (npm run build in frontend/)",
)


@pytest.fixture
def client():
    return TestClient(web.app)


@pytest.mark.parametrize("path", ["/manifest.webmanifest", "/v2/manifest.webmanifest"])
def test_manifest_is_served_on_both_paths(client, path):
    """Vite rewrites the <link rel=manifest> to /v2/... because of `base`, while a
    root-scoped install wants /manifest.webmanifest — both must resolve to the
    real file, not to the /v2/{path} HTML catch-all."""
    r = client.get(path)
    assert r.status_code == 200
    assert "manifest" in r.headers["content-type"]
    body = r.json()
    assert body["start_url"] == "/" and body["scope"] == "/"
    assert body["display"] == "standalone"
    assert body["icons"], "an installable PWA needs at least one icon"


@pytest.mark.parametrize("path", ["/sw-v2.js", "/v2/sw-v2.js"])
def test_service_worker_is_served_with_root_scope(client, path):
    r = client.get(path)
    assert r.status_code == 200
    assert "javascript" in r.headers["content-type"]
    assert r.headers.get("Service-Worker-Allowed") == "/"
    assert "addEventListener" in r.text


def test_index_html_registers_the_worker_and_links_the_manifest():
    html = (V2_DIR / "index.html").read_text(encoding="utf-8")
    assert "manifest" in html, "built shell must link a manifest"
    # Registered from the ROOT path — a worker under /v2/ could only scope /v2/.
    assert "'/sw-v2.js'" in html or '"/sw-v2.js"' in html


def test_service_worker_never_caches_api_responses():
    """The load-bearing privacy rule: only content-hashed assets and the
    navigation shell may be cached. Any /api/ response placed in Cache Storage
    would survive a `forget`, since purge_data cannot reach the browser."""
    code = _code_only(SW_SRC.read_text(encoding="utf-8"))
    # The only cache-write sites must be the immutable-asset and shell branches.
    put_calls = re.findall(r"\.put\(([^,)]+)", code)
    assert put_calls, "expected the SW to cache something"
    for target in put_calls:
        assert target.strip() in {"req", "SHELL"}, f"unexpected cache target: {target}"
    # Non-GET is refused outright, so a mutation can never be replayed from cache.
    assert "req.method !== 'GET'" in code
    # Cross-origin requests are left entirely alone.
    assert "url.origin !== self.location.origin" in code
    # No /api/ path may appear in a caching decision at all.
    assert "/api/" not in code


def test_only_a_shell_navigation_may_refresh_the_cached_shell():
    """Regression: the navigate branch once wrote EVERY successful navigation
    under the SHELL key, so visiting /docs or /admin replaced the cached HUD
    shell and the offline fallback then served that page's HTML. The SHELL put
    must be gated on the navigation actually targeting the shell's own path."""
    code = _code_only(SW_SRC.read_text(encoding="utf-8"))
    assert "res.ok && refreshesShell" in code, \
        "the SHELL put must be conditioned on a shell-path navigation"
    assert re.search(r"refreshesShell\s*=\s*url\.pathname\s*===\s*SHELL", code), \
        "refreshesShell must compare url.pathname against the SHELL path"


def _code_only(src: str) -> str:
    """Strip block and line comments — these assertions are about the worker's
    CODE, and the file's own prose explains the very anti-patterns being banned."""
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return re.sub(r"^\s*//.*$", "", src, flags=re.M)


def test_service_worker_does_not_precache_a_hardcoded_asset_list():
    """v1's worker pre-caches a fixed path list; v2's filenames are content-hashed
    per build, so a list would go stale and `cache.addAll` fails atomically on a
    single 404 — silently breaking the whole install."""
    code = _code_only(SW_SRC.read_text(encoding="utf-8"))
    assert "addAll" not in code
    assert not re.search(r"/v2/assets/[A-Za-z0-9_-]{6,}\.(js|css)", code), \
        "SW must not reference a specific hashed filename"


def test_manifest_source_and_built_copy_agree():
    """The build copies frontend/public/ verbatim; a drifted committed bundle
    would make the served manifest differ from the reviewed source."""
    assert (V2_DIR / "manifest.webmanifest").read_text(encoding="utf-8").strip() \
        == MANIFEST_SRC.read_text(encoding="utf-8").strip()
    assert (V2_DIR / "sw-v2.js").read_text(encoding="utf-8").strip() \
        == SW_SRC.read_text(encoding="utf-8").strip()
