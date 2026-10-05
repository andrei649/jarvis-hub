"""Fixed xAI Imagine image request and result contract, without transport.

The worker owns the paired XAI_API_KEY, approval, artifact ownership/digests,
DNS-pinned result admission and local PNG publication. This module performs no
catalog GET, automatic model fallback, paid POST or result download.
"""

from __future__ import annotations

import base64
import binascii
import ipaddress
import re
from urllib.parse import urlsplit

from .comfyui import ImageGenerationError, validate_png
from .fal_image import decode_image

BASE_URL = "https://api.x.ai/v1"
DEFAULT_MODEL = "grok-imagine-image"
MODEL_CATALOG = {
    "grok-imagine-image": {"display": "Grok Imagine Image", "max_refs": 3, "quality": False},
    "grok-imagine-image-2.0": {"display": "Grok Imagine Image 2.0", "max_refs": 5, "quality": True},
    "grok-imagine-image-quality": {"display": "Grok Imagine Image (Quality)", "max_refs": 3,
                                   "quality": False},
}
SIZES = {"1024x1024": "1:1", "1536x1024": "16:9", "1024x1536": "9:16"}
RESOLUTIONS = ("1k", "2k")
QUALITIES = ("auto", "low", "medium")
MAX_IMAGE = 16 * 1024 * 1024
MAX_RESPONSE = 24 * 1024 * 1024
MAX_INPUT_TOTAL = 64 * 1024 * 1024
_ID = re.compile(r"[a-f0-9]{32}\Z")


def model_capabilities():
    return {model: {"edit": True, "max_reference_images": meta["max_refs"],
                    "reference_kind": "artifact_id"} for model, meta in MODEL_CATALOG.items()}


def normalize_request(prompt, options):
    """Canonical one-result body; every selected model and source survives intact."""
    allowed = {"backend", "model", "size", "references", "resolution", "quality", "n"}
    if (not isinstance(prompt, str) or not 1 <= len(prompt.strip()) <= 4000 or
            not isinstance(options, dict) or options.get("backend") != "xai" or set(options) - allowed):
        raise ValueError("unsupported xAI image request")
    model = options.get("model", DEFAULT_MODEL)
    size = options.get("size", "1024x1024")
    if not isinstance(model, str) or model not in MODEL_CATALOG or not isinstance(size, str) or size not in SIZES:
        raise ValueError("unsupported xAI image model or size")
    refs = options.get("references", [])
    if (not isinstance(refs, list) or len(refs) > MODEL_CATALOG[model]["max_refs"] or
            any(not isinstance(ref, str) or _ID.fullmatch(ref) is None for ref in refs) or
            len(set(refs)) != len(refs)):
        raise ValueError("unsupported xAI image references")
    edit = bool(refs)
    if edit and ("resolution" in options or "n" in options):
        raise ValueError("unsupported xAI edit option")
    body = {"model": model, "prompt": prompt, "size": size,
            "surface": "edit" if edit else "generation", "references": list(refs),
            "aspect_ratio": SIZES[size]}
    if not edit:
        resolution = options.get("resolution", "1k")
        if not isinstance(resolution, str) or resolution not in RESOLUTIONS:
            raise ValueError("unsupported xAI image resolution")
        body["resolution"] = resolution
        if "n" in options and (type(options["n"]) is not int or options["n"] != 1):
            raise ValueError("xAI image approval permits one result")
        body["n"] = 1
    if "quality" in options:
        quality = options["quality"]
        if (not MODEL_CATALOG[model]["quality"] or not isinstance(quality, str) or
                quality not in QUALITIES):
            raise ValueError("unsupported xAI image quality")
        body["quality"] = quality
    return body


def _checked_body(body):
    if not isinstance(body, dict):
        raise ValueError("invalid xAI image request")
    options = {"backend": "xai", **{key: body[key] for key in
               ("model", "size", "references", "resolution", "quality", "n") if key in body}}
    try:
        if normalize_request(body.get("prompt"), options) != body:
            raise ValueError
    except ValueError:
        raise ValueError("invalid xAI image request") from None
    return body


def endpoint_for(body):
    request = _checked_body(body)
    return BASE_URL + ("/images/edits" if request["surface"] == "edit" else "/images/generations")


def wire_body(body, image_bytes):
    """Build xAI's JSON image/image[] fields from owned, validated PNG bytes."""
    request = _checked_body(body)
    refs = request["references"]
    if not isinstance(image_bytes, (list, tuple)) or len(image_bytes) != len(refs):
        raise ValueError("xAI image reference mismatch")
    image_fields = []
    total = 0
    for data in image_bytes:
        if not isinstance(data, bytes) or not data or len(data) > MAX_IMAGE:
            raise ValueError("invalid xAI image reference")
        total += len(data)
        if total > MAX_INPUT_TOTAL:
            raise ValueError("xAI image references too large")
        try:
            validate_png(data)
        except ImageGenerationError:
            raise ValueError("invalid xAI image reference") from None
        image_fields.append({"type": "image_url",
                             "url": "data:image/png;base64," + base64.b64encode(data).decode("ascii")})
    wire = {"model": request["model"], "prompt": request["prompt"],
            "aspect_ratio": request["aspect_ratio"], "response_format": "b64_json"}
    if request["surface"] == "generation":
        wire["resolution"] = request["resolution"]
        wire["n"] = 1
    else:
        wire["image" if len(image_fields) == 1 else "images"] = (
            image_fields[0] if len(image_fields) == 1 else image_fields)
    if "quality" in request:
        wire["quality"] = request["quality"]
    return wire


def _candidate_url(value):
    """A syntax-screened HTTPS candidate, never download authority by itself."""
    if (not isinstance(value, str) or not 1 <= len(value) <= 2048 or
            any(ch.isspace() or ord(ch) < 32 or ch == "\\" for ch in value)):
        raise ValueError("untrusted xAI image URL")
    try:
        part = urlsplit(value)
        host = (part.hostname or "").lower().rstrip(".")
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            raise ValueError
        if (part.scheme != "https" or not re.fullmatch(r"[a-z0-9.-]+", host) or "." not in host
                or host.startswith(".") or host.endswith(".") or ".." in host
                or part.port not in {None, 443} or part.username or part.password
                or not part.path or part.path == "/" or part.fragment):
            raise ValueError
    except ValueError:
        raise ValueError("untrusted xAI image URL") from None
    return value


def parse_response(value):
    """Exactly one raster result: clean PNG bytes or an untrusted URL candidate."""
    if not isinstance(value, dict) or not isinstance(value.get("data"), list) or len(value["data"]) != 1:
        raise ValueError("invalid xAI image response")
    row = value["data"][0]
    if not isinstance(row, dict):
        raise ValueError("invalid xAI image response")
    mime = row.get("mime_type")
    if mime not in {None, "image/png", "image/jpeg", "image/jpg", "image/webp"}:
        raise ValueError("unsupported xAI image media type")
    encoded, url = row.get("b64_json"), row.get("url")
    if (("b64_json" in row and encoded is not None and not isinstance(encoded, str)) or
            ("url" in row and url is not None and not isinstance(url, str))):
        raise ValueError("invalid xAI image response")
    if (isinstance(encoded, str) and bool(encoded)) == (isinstance(url, str) and bool(url)):
        raise ValueError("invalid xAI image response")
    if encoded:
        if not isinstance(encoded, str) or len(encoded) > 4 * ((MAX_IMAGE + 2) // 3):
            raise ValueError("invalid xAI image data")
        try:
            raw = base64.b64decode(encoded, validate=True)
            clean, _dimensions = decode_image(raw)
            return "bytes", clean
        except (binascii.Error, ValueError):
            raise ValueError("invalid xAI image data") from None
    return "url", _candidate_url(url)


def auth_headers(key):
    if (not isinstance(key, str) or not 1 <= len(key) <= 4096 or
            any(ord(ch) < 33 or ord(ch) > 126 for ch in key)):
        raise ValueError("xAI credential unavailable")
    return {"Authorization": "Bearer " + key, "Content-Type": "application/json",
            "User-Agent": "Nerva-H515-Image/1"}
