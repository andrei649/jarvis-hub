"""T-0.50 — the publish-readiness surface over `creative/publishing.py`.

The module (platform metadata/asset validation, pre-publish checklist, package
builder) was complete and had **no route and no HUD** — a repo-wide grep found
its only mention outside its own file was a docstring line. So the whole
publish-readiness story was invisible to the product.

The rule these tests protect is the one that matters: this surface **never
publishes**. `release_payload` stays `None` until every automatic and manual
check passes, and even then the payload is only something the Action Kernel may
be asked to approve — the terminal upload remains owner-gated (per-platform
OAuth) and approval-held, per MOONSHOT §5.
"""

import asyncio
import json
import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.routers import creative as creative_router  # noqa: E402

# The real platform schema, not a guess: youtube requires a thumbnail, and an
# asset must carry artifact_id / filename / an allowed media type / duration.
_META = {
    "title": "My video",
    "description": "A description",
    "tags": ["a"],
    "thumbnail": "thumb.png",
}
_ASSET = {
    "artifact_id": "art-1",
    "filename": "out.mp4",
    "media_type": "video/mp4",
    "duration_seconds": 42,
    "bytes": 1024,
}
_CONFIRMED = {"disclosure": True, "rights": True, "preview": True}
_MANUAL_IDS = {"disclosure.confirmed", "rights.confirmed", "preview.confirmed"}


def _body(resp):
    return json.loads(resp.body)


def _checklist(**kw):
    payload = creative_router.PublishBody(platform="youtube", **kw)
    return _body(asyncio.run(creative_router.creative_publish_checklist(payload)))


def _package(**kw):
    payload = creative_router.PublishBody(platform="youtube", **kw)
    return _body(asyncio.run(creative_router.creative_publish_package(payload)))


# ── the checklist ─────────────────────────────────────────────────────────────

def test_checklist_lists_automatic_and_manual_checks():
    body = _checklist(meta=_META, asset=_ASSET)
    ids = {c["id"] for c in body["checklist"]}
    assert {"platform.known", "asset.valid", "metadata.required"} <= ids
    # the three manual confirmations are always surfaced, unconfirmed by default
    assert ids >= _MANUAL_IDS
    manual = [c for c in body["checklist"] if c["id"] in _MANUAL_IDS]
    assert all(c["ok"] is False for c in manual), "manual checks must default to unconfirmed"


def test_a_valid_asset_and_metadata_pass_their_automatic_checks():
    """Guards the fixtures themselves: if these stop satisfying the real
    platform schema, the readiness tests below would pass vacuously."""
    body = _checklist(meta=_META, asset=_ASSET)
    auto = {c["id"]: c["ok"] for c in body["checklist"]}
    assert auto["asset.valid"] is True
    assert auto["metadata.required"] is True
    assert body["violations"] == []


def test_checklist_reports_platform_violations_by_name():
    body = _checklist(meta={"title": ""}, asset=None)
    assert body["violations"], "an empty title must be named, not silently accepted"


def test_unknown_platform_is_refused_not_guessed():
    payload = creative_router.PublishBody(platform="myspace", meta=_META)
    resp = asyncio.run(creative_router.creative_publish_checklist(payload))
    assert resp.status_code == 400
    assert "myspace" in _body(resp)["error"] or _body(resp).get("platform") == "myspace"


# ── the package: the never-publishes contract ─────────────────────────────────

def test_package_withholds_the_release_payload_until_everything_passes():
    body = _package(meta=_META, asset=_ASSET)          # no confirmations
    assert body["ready_for_approval"] is False
    assert body["release_payload"] is None, "an unconfirmed package must carry no payload"


def test_package_becomes_approval_ready_only_with_every_confirmation():
    body = _package(meta=_META, asset=_ASSET, confirmations=_CONFIRMED)
    assert body["ready_for_approval"] is True
    assert body["release_payload"] is not None


def test_ready_for_approval_never_means_published():
    """The load-bearing distinction: approval-ready is a request, not an act."""
    body = _package(meta=_META, asset=_ASSET, confirmations=_CONFIRMED)
    assert body["publish_state"] != "published"
    assert body.get("generated") is False


def test_a_missing_asset_blocks_approval_even_when_confirmed():
    body = _package(meta=_META, asset=None, confirmations=_CONFIRMED)
    assert body["ready_for_approval"] is False
    assert body["release_payload"] is None


def test_package_is_deterministic_for_the_same_input():
    a = _package(meta=_META, asset=_ASSET, confirmations=_CONFIRMED)
    b = _package(meta=_META, asset=_ASSET, confirmations=_CONFIRMED)
    assert a["package_id"] == b["package_id"]


# ── wiring ────────────────────────────────────────────────────────────────────

def test_routes_registered_and_user_guarded():
    paths = {r.path for r in creative_router.router.routes}
    assert {"/api/creative/publish/checklist", "/api/creative/publish/package"} <= paths
    for route in creative_router.router.routes:
        names = {getattr(d.call, "__name__", "") for d in route.dependant.dependencies}
        assert "user_guard" in names, f"{route.path} must be user-guarded"


def test_no_publish_route_exists_anywhere_on_this_router():
    """There must be no endpoint that performs the terminal upload — the executor
    is owner-gated and publication stays kernel/approval-held."""
    paths = {r.path for r in creative_router.router.routes}
    assert not any(p.endswith("/publish") or p.endswith("/upload") for p in paths)


def test_http_roundtrip():
    from fastapi.testclient import TestClient

    from agents import web

    r = TestClient(web.app).post("/api/creative/publish/checklist", json={
        "platform": "youtube", "meta": _META, "asset": _ASSET,
    })
    assert r.status_code == 200
    assert "checklist" in r.json()
