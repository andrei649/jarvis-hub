"""Offline Publishing Studio for a finished asset.

This module turns an already-produced asset manifest into a deterministic,
platform-specific review package. It validates the asset and metadata, emits
automatic and manual pre-publish checks, and may prepare an irreversible release
payload for the Action Kernel. It has no uploader, transport, or publish function.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
from typing import Any

from .pipeline import EXPORT_TARGETS, release_action_payload

PLATFORM_RULES: dict[str, dict[str, Any]] = {
    "youtube": {
        "needs": ("title", "description", "thumbnail"),
        "field_limits": {"title": 100, "description": 5000},
        "hashtags_max": 15,
        "media_types": ("video/mp4",),
    },
    "instagram": {
        "needs": ("caption",),
        "field_limits": {"caption": 2200, "alt_text": 1000},
        "hashtags_max": 30,
        "media_types": ("video/mp4",),
    },
    "readme": {
        "needs": ("title", "body", "alt_text"),
        "field_limits": {"title": 120, "body": 100000, "alt_text": 1000},
        "hashtags_max": 0,
        "media_types": ("image/png",),
    },
}

_CONFIRMATIONS = ("disclosure", "rights", "preview")
_ASSET_FIELDS = frozenset(
    {"artifact_id", "filename", "media_type", "bytes", "duration_seconds"}
)


def _platform(value: Any) -> str:
    return str(value if value is not None else "").strip().lower()


def _text(value: Any) -> str:
    return str(value if value is not None else "").strip()


def _known_metadata_fields(rules: dict[str, Any]) -> set[str]:
    return (
        set(rules.get("needs", ()))
        | set(rules.get("field_limits", {}))
        | {"hashtags", "disclosed"}
    )


def validate_metadata(platform: str, meta: dict | None) -> list[str]:
    """Return all metadata violations without trimming or mutating input values."""

    target = _platform(platform)
    rules = PLATFORM_RULES.get(target)
    if not rules:
        return [f"unknown platform: {target}"]

    if not isinstance(meta, dict):
        return ["metadata must be an object"]

    violations: list[str] = []
    text_fields = set(rules["needs"]) | set(rules["field_limits"])
    for field in sorted(text_fields):
        value = meta.get(field)
        if value is not None and not isinstance(value, str):
            violations.append(f"{field} must be text")

    for field in rules["needs"]:
        value = meta.get(field)
        if not isinstance(value, str) or not value.strip():
            violations.append(f"missing required field: {field}")

    for field, limit in rules["field_limits"].items():
        value = meta.get(field)
        if isinstance(value, str) and len(value.strip()) > limit:
            length = len(value.strip())
            violations.append(f"{field} exceeds {limit} chars ({length})")

    hashtags = meta.get("hashtags", [])
    if hashtags is None:
        hashtags = []
    if not isinstance(hashtags, (list, tuple)):
        violations.append("hashtags must be a list")
    else:
        present: list[tuple[int, str]] = []
        for index, tag in enumerate(hashtags):
            if tag is None or (isinstance(tag, str) and not tag.strip()):
                continue
            if not isinstance(tag, str):
                violations.append(f"hashtag {index} must be text")
                continue
            present.append((index, tag.strip()))

        cap = rules["hashtags_max"]
        if cap == 0 and present:
            violations.append("this platform takes no hashtags")
        elif len(present) > cap:
            violations.append(f"too many hashtags: {len(present)} > {cap}")
        for index, text in present:
            if len(text) > 100:
                violations.append(f"hashtag {index} exceeds 100 chars")
            if any(char.isspace() for char in text):
                violations.append(f"hashtag {index} contains whitespace")

    return violations


def validate_asset(platform: str, asset: dict | None) -> list[str]:
    """Validate the bounded manifest of the finished asset; never reads host paths."""

    target = _platform(platform)
    spec = EXPORT_TARGETS.get(target)
    rules = PLATFORM_RULES.get(target)
    if spec is None or rules is None:
        return []

    if not isinstance(asset, dict) or not asset:
        return ["missing finished asset"]

    violations: list[str] = []
    artifact_id = _text(asset.get("artifact_id"))
    filename = _text(asset.get("filename"))
    media_type = _text(asset.get("media_type")).lower()

    if not artifact_id:
        violations.append("missing asset artifact_id")
    elif len(artifact_id) > 200:
        violations.append("asset artifact_id exceeds 200 chars")

    if not filename:
        violations.append("missing asset filename")
    else:
        if "/" in filename or "\\" in filename or filename in {".", ".."}:
            violations.append("asset filename must be a basename")
        expected_suffix = f".{spec['format']}".lower()
        if not filename.lower().endswith(expected_suffix):
            violations.append(
                f"asset filename format mismatch: expected {expected_suffix}"
            )

    if media_type not in rules["media_types"]:
        expected = ", ".join(rules["media_types"])
        violations.append(f"asset media type must be one of: {expected}")

    size = asset.get("bytes")
    if size is None:
        violations.append("missing asset bytes")
    elif isinstance(size, bool) or not isinstance(size, int) or size <= 0:
        violations.append("asset bytes must be a positive integer")

    duration = asset.get("duration_seconds")
    max_seconds = spec.get("max_seconds", 0)
    if duration is None and max_seconds:
        violations.append("missing asset duration_seconds")
    elif duration is not None:
        try:
            seconds = float(duration)
        except (TypeError, ValueError):
            violations.append("asset duration_seconds must be a non-negative number")
        else:
            if not math.isfinite(seconds):
                violations.append("asset duration_seconds must be finite")
            elif isinstance(duration, bool) or seconds < 0:
                violations.append("asset duration_seconds must be a non-negative number")
            elif max_seconds and seconds > max_seconds:
                violations.append(
                    f"asset duration exceeds {max_seconds} seconds ({seconds:g})"
                )

    return violations


def _automatic_check(
    check_id: str, label: str, ok: bool, *, detail: str = ""
) -> dict[str, Any]:
    return {
        "id": check_id,
        "label": label,
        "required": True,
        "status": "pass" if ok else "fail",
        "ok": ok,
        "detail": detail,
    }


def _manual_check(check_id: str, label: str, confirmed: bool) -> dict[str, Any]:
    return {
        "id": check_id,
        "label": label,
        "required": True,
        "status": "pass" if confirmed else "manual",
        "ok": confirmed,
        "detail": "confirmed" if confirmed else "owner confirmation required",
    }


def prepublish_checklist(
    platform: str,
    meta: dict | None,
    *,
    asset: dict | None = None,
    confirmations: dict | None = None,
) -> list[dict[str, Any]]:
    """Build explicit automatic and manual checks before kernel approval."""

    target = _platform(platform)
    rules = PLATFORM_RULES.get(target)
    metadata_violations = validate_metadata(target, meta)
    asset_violations = validate_asset(target, asset)
    metadata = meta if isinstance(meta, dict) else {}
    provided = confirmations if isinstance(confirmations, dict) else {}

    required_ok = bool(rules) and all(
        isinstance(metadata.get(field), str)
        and bool(metadata.get(field).strip())
        for field in rules.get("needs", ())
    )
    limit_prefixes = (
        "title exceeds",
        "description exceeds",
        "caption exceeds",
        "body exceeds",
        "alt_text exceeds",
        "hashtag",
        "too many hashtags",
    )
    limits_ok = not any(
        item.startswith(limit_prefixes)
        or item in {"hashtags must be a list", "this platform takes no hashtags"}
        for item in metadata_violations
    )

    confirmed = {
        "disclosure": (
            provided.get("disclosure", metadata.get("disclosed", False)) is True
        ),
        "rights": provided.get("rights") is True,
        "preview": provided.get("preview") is True,
    }

    return [
        _automatic_check(
            "platform.known",
            "Target platform is supported",
            target in PLATFORM_RULES,
        ),
        _automatic_check(
            "asset.valid",
            "Finished asset matches the target contract",
            bool(rules) and bool(asset) and not asset_violations,
            detail="; ".join(asset_violations),
        ),
        _automatic_check(
            "metadata.required",
            "Required metadata is present",
            required_ok,
        ),
        _automatic_check(
            "metadata.limits",
            "Metadata fits platform limits",
            bool(rules) and limits_ok,
        ),
        _manual_check(
            "disclosure.confirmed",
            "Disclosure and consent reviewed",
            confirmed["disclosure"],
        ),
        _manual_check(
            "rights.confirmed",
            "Rights and licenses cleared",
            confirmed["rights"],
        ),
        _manual_check(
            "preview.confirmed",
            "Final platform preview reviewed",
            confirmed["preview"],
        ),
    ]


def _package_id(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _warnings(
    rules: dict[str, Any] | None,
    meta: dict | None,
    asset: dict | None,
) -> list[str]:
    warnings: list[str] = []
    if rules and isinstance(meta, dict):
        unknown = sorted(
            str(key) for key in set(meta) - _known_metadata_fields(rules)
        )
        if unknown:
            warnings.append(f"ignored metadata fields: {', '.join(unknown)}")
    if isinstance(asset, dict):
        unknown_asset = sorted(
            str(key) for key in set(asset) - _ASSET_FIELDS
        )
        if unknown_asset:
            warnings.append(f"ignored asset fields: {', '.join(unknown_asset)}")
    return warnings


def build_publish_package(
    platform: str,
    meta: dict | None,
    *,
    asset: dict | None = None,
    confirmations: dict | None = None,
    title: str = "",
) -> dict[str, Any]:
    """Package one finished asset for review; never upload or publish it.

    ready_for_approval means the package may be submitted to the Action Kernel.
    It never means published. release_payload remains None until asset, metadata,
    and manual checks all pass. title is retained for call compatibility only.
    """

    del title
    target = _platform(platform)
    rules = PLATFORM_RULES.get(target)
    spec = EXPORT_TARGETS.get(target)
    metadata_violations = validate_metadata(target, meta)
    asset_violations = validate_asset(target, asset)
    violations = metadata_violations + asset_violations
    checklist = prepublish_checklist(
        target, meta, asset=asset, confirmations=confirmations
    )
    ready = not violations and all(item["ok"] for item in checklist)

    metadata = meta if isinstance(meta, dict) else {}
    asset_manifest = asset if isinstance(asset, dict) else {}
    canonical_meta = {
        key: copy.deepcopy(value)
        for key, value in metadata.items()
        if rules and key in _known_metadata_fields(rules)
    }
    canonical_asset = {
        key: copy.deepcopy(value)
        for key, value in asset_manifest.items()
        if key in _ASSET_FIELDS
    }
    provided = confirmations if isinstance(confirmations, dict) else {}
    canonical_confirmations = {
        key: provided.get(key) is True for key in _CONFIRMATIONS
    }
    if (
        metadata.get("disclosed") is True
        and not canonical_confirmations["disclosure"]
    ):
        canonical_confirmations["disclosure"] = True

    identity = {
        "platform": target,
        "asset": canonical_asset,
        "metadata": canonical_meta,
        "confirmations": canonical_confirmations,
        "export_spec": spec,
    }
    package_id = _package_id(identity)
    release_payload = None
    if ready:
        release_payload = release_action_payload(
            {
                "target": target,
                "filename": canonical_asset["filename"],
            },
            base={
                "artifact_id": canonical_asset["artifact_id"],
                "package_id": package_id,
                "publish_state": "kernel-held",
            },
        )

    return {
        "package_id": package_id,
        "platform": target,
        "asset": canonical_asset,
        "export_spec": copy.deepcopy(spec) if spec else None,
        "metadata": canonical_meta,
        "confirmations": canonical_confirmations,
        "violations": violations,
        "warnings": _warnings(rules, meta, asset),
        "checklist": checklist,
        "ready": ready,
        "ready_for_approval": ready,
        "publish_state": "kernel-held",
        "generated": False,
        "release_payload": release_payload,
        "disclaimer": (
            "Package only — no upload or publish occurs here. A ready package "
            "still requires Action Kernel authorization."
        ),
    }
