"""0.50 Publishing Studio — offline publish packager.

Validates platform metadata + builds a pre-publish checklist; never publishes (release is
kernel-held). Violations are surfaced, never silently trimmed into a false pass.
"""
import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from core.creative import publishing as pub  # noqa: E402


def test_clean_youtube_package_is_ready():
    pkg = pub.build_publish_package("youtube", {
        "title": "Meet Jarvis", "description": "a governed local AI cabinet",
        "thumbnail": "thumb.png", "disclosed": True,
    }, title="meet-jarvis")
    assert pkg["violations"] == []
    assert pkg["ready"] is True
    assert pkg["generated"] is False
    assert pkg["export_spec"]["format"] == "mp4"
    # publish is held by the kernel (irreversible risk tier on the payload)
    assert "risk_tier" in pkg["release_payload"]


def test_missing_required_field_is_surfaced_not_passed():
    pkg = pub.build_publish_package("youtube", {"title": "x", "description": "y", "disclosed": True})
    assert "missing required field: thumbnail" in pkg["violations"]
    assert pkg["ready"] is False


def test_title_over_limit_is_a_violation():
    v = pub.validate_metadata("youtube", {"title": "T" * 101, "description": "d", "thumbnail": "t"})
    assert any("title exceeds 100" in x for x in v)


def test_instagram_hashtag_cap_and_readme_takes_none():
    ig = pub.validate_metadata("instagram", {"caption": "hi", "hashtags": ["#a"] * 31})
    assert any("too many hashtags" in x for x in ig)
    rd = pub.validate_metadata("readme", {"title": "t", "body": "b", "hashtags": ["#a"]})
    assert any("no hashtags" in x for x in rd)


def test_unknown_platform_is_honest():
    assert pub.validate_metadata("tiktok", {"title": "x"}) == ["unknown platform: tiktok"]
    pkg = pub.build_publish_package("tiktok", {"title": "x"})
    assert pkg["ready"] is False and pkg["export_spec"] is None


def test_checklist_requires_disclosure():
    pkg = pub.build_publish_package("youtube", {
        "title": "t", "description": "d", "thumbnail": "th", "disclosed": False,
    })
    disclosure = next(c for c in pkg["checklist"] if "disclosure" in c["check"])
    assert disclosure["ok"] is False and pkg["ready"] is False
