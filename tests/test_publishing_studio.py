"""0.50 Publishing Studio — finished-asset packaging without direct publishing.

The studio validates the asset manifest and platform metadata, emits an explicit
pre-publish checklist, and only prepares a kernel-held release payload after every
required check passes. It has no transport or publish side effect.
"""

from agents.core.creative import publishing
from agents.core.autonomy.policy import RiskTier


ASSET = {
    "artifact_id": "artifact_01",
    "filename": "meet-jarvis-youtube.mp4",
    "media_type": "video/mp4",
    "bytes": 12_345,
    "duration_seconds": 42,
}
META = {
    "title": "Meet Jarvis",
    "description": "A governed local AI cabinet.",
    "thumbnail": "artifact_thumb_01",
    "hashtags": ["#localai", "#jarvis"],
}
CONFIRMED = {"disclosure": True, "rights": True, "preview": True}


def test_clean_youtube_package_is_ready_for_kernel_approval():
    pkg = publishing.build_publish_package(
        "youtube", META, asset=ASSET, confirmations=CONFIRMED
    )

    assert pkg["violations"] == []
    assert pkg["ready"] is True
    assert pkg["ready_for_approval"] is True
    assert pkg["generated"] is False
    assert pkg["publish_state"] == "kernel-held"
    assert pkg["export_spec"]["format"] == "mp4"
    assert pkg["release_payload"]["filename"] == ASSET["filename"]
    assert pkg["release_payload"]["risk_tier"] == int(
        RiskTier.IRREVERSIBLE_OR_MONEY
    )
    assert len(pkg["package_id"]) == 64


def test_finished_asset_is_required_before_package_can_be_ready():
    pkg = publishing.build_publish_package(
        "youtube", META, confirmations=CONFIRMED
    )

    assert "missing finished asset" in pkg["violations"]
    assert pkg["ready_for_approval"] is False
    assert pkg["release_payload"] is None


def test_asset_format_and_filename_are_validated():
    bad = {**ASSET, "filename": "../escape.mov", "media_type": "video/quicktime"}
    violations = publishing.validate_asset("youtube", bad)

    assert "asset filename must be a basename" in violations
    assert any("expected .mp4" in item for item in violations)
    assert any("media type" in item for item in violations)


def test_video_duration_must_fit_the_target_contract():
    long_asset = {**ASSET, "duration_seconds": 601}
    violations = publishing.validate_asset("youtube", long_asset)

    assert any("duration exceeds 600 seconds" in item for item in violations)


def test_missing_required_metadata_is_surfaced_not_passed():
    pkg = publishing.build_publish_package(
        "youtube",
        {"title": "x", "description": "y"},
        asset=ASSET,
        confirmations=CONFIRMED,
    )

    assert "missing required field: thumbnail" in pkg["violations"]
    assert pkg["ready_for_approval"] is False


def test_length_validation_uses_the_real_value_and_never_hides_truncation():
    violations = publishing.validate_metadata(
        "readme",
        {"title": "t", "body": "b" * 100_001, "alt_text": "Jarvis HUD"},
    )

    assert "body exceeds 100000 chars (100001)" in violations


def test_hashtags_must_be_a_list_and_respect_platform_cap():
    wrong_type = publishing.validate_metadata("instagram", {"caption": "hi", "hashtags": "#one"})
    too_many = publishing.validate_metadata(
        "instagram", {"caption": "hi", "hashtags": ["#a"] * 31}
    )

    assert "hashtags must be a list" in wrong_type
    assert "too many hashtags: 31 > 30" in too_many


def test_unknown_platform_is_honest_and_cannot_prepare_release():
    pkg = publishing.build_publish_package(
        "tiktok",
        {"title": "x"},
        asset=ASSET,
        confirmations=CONFIRMED,
    )

    assert "unknown platform: tiktok" in pkg["violations"]
    assert pkg["export_spec"] is None
    assert pkg["ready_for_approval"] is False
    assert pkg["release_payload"] is None


def test_manual_disclosure_rights_and_preview_checks_are_explicit():
    pkg = publishing.build_publish_package(
        "youtube",
        META,
        asset=ASSET,
        confirmations={"disclosure": True},
    )
    by_id = {item["id"]: item for item in pkg["checklist"]}

    assert by_id["disclosure.confirmed"]["ok"] is True
    assert by_id["rights.confirmed"]["status"] == "manual"
    assert by_id["preview.confirmed"]["status"] == "manual"
    assert pkg["ready_for_approval"] is False


def test_packaging_is_deterministic_and_does_not_mutate_inputs():
    asset = dict(ASSET)
    meta = {**META, "hashtags": list(META["hashtags"])}
    first = publishing.build_publish_package(
        "youtube", meta, asset=asset, confirmations=CONFIRMED
    )
    second = publishing.build_publish_package(
        "youtube", meta, asset=asset, confirmations=CONFIRMED
    )

    assert first == second
    assert asset == ASSET
    assert meta == META


def test_no_direct_publish_api_exists():
    assert not hasattr(publishing, "publish")
    assert not hasattr(publishing, "upload")

def test_truthy_non_boolean_confirmations_do_not_unlock_release():
    pkg = publishing.build_publish_package(
        "youtube",
        META,
        asset=ASSET,
        confirmations={
            "disclosure": "false",
            "rights": "no",
            "preview": 1,
        },
    )
    by_id = {item["id"]: item for item in pkg["checklist"]}

    assert by_id["disclosure.confirmed"]["ok"] is False
    assert by_id["rights.confirmed"]["ok"] is False
    assert by_id["preview.confirmed"]["ok"] is False
    assert pkg["ready_for_approval"] is False
    assert pkg["release_payload"] is None


def test_asset_manifest_requires_positive_size_and_video_duration():
    no_size = {key: value for key, value in ASSET.items() if key != "bytes"}
    no_duration = {
        key: value for key, value in ASSET.items() if key != "duration_seconds"
    }

    assert "missing asset bytes" in publishing.validate_asset("youtube", no_size)
    assert "missing asset duration_seconds" in publishing.validate_asset(
        "youtube", no_duration
    )


def test_asset_duration_must_be_finite():
    for value in (float("nan"), float("inf"), float("-inf")):
        bad = {**ASSET, "duration_seconds": value}
        violations = publishing.validate_asset("youtube", bad)
        assert "asset duration_seconds must be finite" in violations


def test_required_metadata_fields_must_be_text():
    violations = publishing.validate_metadata(
        "youtube",
        {
            "title": {"not": "text"},
            "description": "description",
            "thumbnail": "artifact_thumb_01",
        },
    )

    assert "title must be text" in violations


def test_unknown_metadata_keys_never_crash_warning_sort():
    pkg = publishing.build_publish_package(
        "youtube",
        {**META, 1: "ignored"},
        asset=ASSET,
        confirmations=CONFIRMED,
    )

    assert pkg["ready_for_approval"] is True
    assert pkg["warnings"] == ["ignored metadata fields: 1"]

def test_hashtag_entries_must_be_text():
    violations = publishing.validate_metadata(
        "instagram", {"caption": "hi", "hashtags": [1]}
    )

    assert "hashtag 0 must be text" in violations


def test_unknown_asset_keys_never_crash_warning_sort():
    pkg = publishing.build_publish_package(
        "youtube",
        META,
        asset={**ASSET, 1: "ignored"},
        confirmations=CONFIRMED,
    )

    assert pkg["ready_for_approval"] is True
    assert pkg["warnings"] == ["ignored asset fields: 1"]


def test_required_metadata_checklist_agrees_with_type_validation():
    pkg = publishing.build_publish_package(
        "youtube",
        {
            "title": {"not": "text"},
            "description": "description",
            "thumbnail": "artifact_thumb_01",
        },
        asset=ASSET,
        confirmations=CONFIRMED,
    )
    by_id = {item["id"]: item for item in pkg["checklist"]}

    assert by_id["metadata.required"]["ok"] is False
    assert pkg["ready_for_approval"] is False

