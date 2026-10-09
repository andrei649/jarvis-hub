"""Fixed OpenRouter image catalog and bounded native wire shapes.

The donor supports dynamic catalogs, arbitrary reference paths/URLs, and a
second model POST after some failures. This adapter admits only pinned models
and one approved attempt; the cloud worker owns credentials, artifact digests,
DNS-pinned egress and any admitted result download.
"""

from __future__ import annotations

import base64
import binascii
import ipaddress
import re
from urllib.parse import urlsplit

from .comfyui import ImageGenerationError, validate_png
from .fal_image import decode_image

BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "openai/gpt-5.4-image-2"
CHAT_MODELS = (DEFAULT_MODEL, "google/gemini-3-pro-image")
SIZES = {"1024x1024": "square", "1536x1024": "landscape", "1024x1536": "portrait"}
MAX_IMAGE = 16 * 1024 * 1024
MAX_RESPONSE = 24 * 1024 * 1024
MAX_INPUT_TOTAL = 64 * 1024 * 1024
_ID = re.compile(r"[a-f0-9]{32}\Z")
_QUALITY = ("auto", "low", "medium", "high")
_GEMINI_RATIOS = ("1:1", "1:4", "1:8", "2:3", "3:2", "3:4", "4:1", "4:3", "4:5", "5:4", "8:1", "9:16", "16:9", "21:9")
_MAI_RATIOS = ("1:1", "4:3", "3:4", "16:9", "9:16", "3:2", "2:3", "auto")
_KREA_RATIOS = ("1:1", "4:3", "3:2", "16:9", "4:5", "2:3", "9:16")
_PREFERENCES = {
    "square": ("1:1",),
    "landscape": ("16:9", "3:2", "4:3", "5:4", "21:9", "2:1", "19.5:9", "20:9", "4:1", "8:1"),
    "portrait": ("9:16", "2:3", "3:4", "4:5", "9:21", "1:2", "9:19.5", "9:20", "1:4", "1:8"),
}


def _model(ratios, max_refs, *, resolutions=(), quality=(), background=(), compression=False, seed=False):
    return {"ratios": tuple(ratios), "max_refs": max_refs, "resolutions": tuple(resolutions),
            "quality": tuple(quality), "background": tuple(background),
            "compression": compression, "seed": seed}


# Pinned Hermes 59b2aeef OpenRouter Image API catalog; no cold-start GET.
IMAGE_API_MODELS = {
    "google/gemini-3.1-flash-lite-image": _model(_GEMINI_RATIOS, 14, resolutions=("1K",)),
    "google/gemini-3.1-flash-image": _model(_GEMINI_RATIOS, 14, resolutions=("512", "1K", "2K", "4K")),
    "openai/gpt-image-2": _model(("1:1", "3:2", "2:3", "4:3", "3:4", "16:9", "9:16", "21:9", "auto"), 16,
                                   quality=_QUALITY, background=("auto", "opaque"), compression=True),
    "openai/gpt-image-1-mini": _model(("1:1", "3:2", "2:3", "auto"), 16,
                                        quality=_QUALITY, background=("auto", "transparent", "opaque"), compression=True),
    "microsoft/mai-image-2.5": _model(_MAI_RATIOS, 1),
    "microsoft/mai-image-2.5-pro": _model(_MAI_RATIOS, 1),
    "x-ai/grok-imagine-image-quality": _model(("1:1", "3:4", "4:3", "9:16", "16:9", "2:3", "3:2", "9:19.5",
                                                 "19.5:9", "9:20", "20:9", "1:2", "2:1", "auto"), 3,
                                                resolutions=("1K", "2K")),
    "krea/krea-2-medium": _model(_KREA_RATIOS, 1, resolutions=("1K",), seed=True),
    "krea/krea-2-medium-turbo": _model(_KREA_RATIOS, 1, resolutions=("1K",), seed=True),
    "qwen/qwen-image-3-pro": _model(("1:1", "1:2", "1:4", "2:1", "2:3", "3:2", "3:4", "4:1", "4:3",
                                      "4:5", "5:4", "9:16", "16:9"), 4,
                                     resolutions=("1K", "2K"), seed=True),
}
MODELS = (*CHAT_MODELS, *IMAGE_API_MODELS)


def model_capabilities():
    return {model: {"edit": True, "max_reference_images":
                    (3 if model in CHAT_MODELS else IMAGE_API_MODELS[model]["max_refs"]),
                    "reference_kind": "artifact_id"} for model in MODELS}


def normalize_request(prompt, options):
    """Canonical approval body; unsupported knobs and excess references refuse."""
    allowed = {"backend", "model", "size", "references", "aspect_ratio_exact", "resolution", "quality",
               "background", "output_format", "output_compression", "seed", "n"}
    if (not isinstance(prompt, str) or not 1 <= len(prompt.strip()) <= 4000 or
            not isinstance(options, dict) or options.get("backend") != "openrouter" or
            set(options) - allowed):
        raise ValueError("unsupported OpenRouter image request")
    model = options.get("model", DEFAULT_MODEL)
    size = options.get("size", "1024x1024")
    if not isinstance(model, str) or model not in MODELS or not isinstance(size, str) or size not in SIZES:
        raise ValueError("unsupported OpenRouter image model or size")
    surface = "chat" if model in CHAT_MODELS else "images"
    refs = options.get("references", [])
    cap = 3 if surface == "chat" else IMAGE_API_MODELS[model]["max_refs"]
    if (not isinstance(refs, list) or len(refs) > cap or len(set(map(str, refs))) != len(refs)
            or any(not isinstance(ref, str) or not _ID.fullmatch(ref) for ref in refs)):
        raise ValueError("unsupported OpenRouter image references")
    body = {"model": model, "prompt": prompt, "size": size, "surface": surface,
            "references": list(refs)}
    if surface == "chat":
        if set(options) & {"aspect_ratio_exact", "resolution", "quality", "background", "output_format",
                           "output_compression", "seed", "n"}:
            raise ValueError("unsupported OpenRouter chat image option")
        body["aspect_ratio"] = {"square": "1:1", "landscape": "16:9", "portrait": "9:16"}[SIZES[size]]
        return body
    meta = IMAGE_API_MODELS[model]
    exact = options.get("aspect_ratio_exact")
    if exact is not None:
        if not isinstance(exact, str) or exact not in meta["ratios"]:
            raise ValueError("unsupported OpenRouter image aspect ratio")
        body["aspect_ratio"] = exact
    else:
        body["aspect_ratio"] = next((r for r in _PREFERENCES[SIZES[size]] if r in meta["ratios"]), None)
        if body["aspect_ratio"] is None:
            raise ValueError("unsupported OpenRouter image aspect ratio")
    for key, permitted in (("resolution", meta["resolutions"]), ("quality", meta["quality"]),
                           ("background", meta["background"])):
        if key in options:
            value = options[key]
            if not isinstance(value, str) or value not in permitted:
                raise ValueError("unsupported OpenRouter image option")
            body[key] = value
    if "output_format" in options:
        # No pinned catalog row declares this knob. Do not silently discard it.
        raise ValueError("unsupported OpenRouter output format")
    if "output_compression" in options:
        value = options["output_compression"]
        if not meta["compression"] or type(value) is not int or not 0 <= value <= 100:
            raise ValueError("unsupported OpenRouter compression")
        body["output_compression"] = value
    if "seed" in options:
        value = options["seed"]
        if not meta["seed"] or type(value) is not int or not 0 <= value < 2**63:
            raise ValueError("unsupported OpenRouter seed")
        body["seed"] = value
    if "n" in options and (type(options["n"]) is not int or options["n"] != 1):
        raise ValueError("OpenRouter image approval permits one result")
    body["n"] = 1
    return body


def endpoint_for(body):
    _valid_body(body)
    model = body.get("model")
    expected = "chat" if model in CHAT_MODELS else "images" if model in IMAGE_API_MODELS else None
    if expected is None or body.get("surface") != expected:
        raise ValueError("invalid OpenRouter image surface")
    return BASE_URL + ("/chat/completions" if expected == "chat" else "/images")


def _valid_body(body):
    if not isinstance(body, dict):
        raise ValueError("invalid OpenRouter image request")
    options = {"backend": "openrouter", **{k: body[k] for k in
               ("model", "size", "references", "resolution", "quality", "background",
                "output_compression", "seed", "n") if k in body}}
    if body.get("surface") == "images" and "aspect_ratio" in body:
        options["aspect_ratio_exact"] = body["aspect_ratio"]
    if normalize_request(body.get("prompt"), options) != body:
        raise ValueError("invalid OpenRouter image request")


def wire_body(body, image_bytes):
    """Native JSON for the exact model; artifact ownership/digests remain worker-owned."""
    _valid_body(body)
    refs = body["references"]
    if not isinstance(image_bytes, (list, tuple)) or len(image_bytes) != len(refs):
        raise ValueError("OpenRouter image reference mismatch")
    total = 0
    urls = []
    for data in image_bytes:
        if not isinstance(data, bytes) or not data or len(data) > MAX_IMAGE:
            raise ValueError("invalid OpenRouter image reference")
        total += len(data)
        if total > MAX_INPUT_TOTAL:
            raise ValueError("OpenRouter image references too large")
        try:
            validate_png(data)
        except ImageGenerationError:
            raise ValueError("invalid OpenRouter image reference") from None
        urls.append("data:image/png;base64," + base64.b64encode(data).decode("ascii"))
    if body["surface"] == "chat":
        content = [{"type": "text", "text": body["prompt"]}]
        content.extend({"type": "image_url", "image_url": {"url": url}} for url in urls)
        return {"model": body["model"], "modalities": ["image", "text"],
                "messages": [{"role": "user", "content": content}],
                "image_config": {"aspect_ratio": body["aspect_ratio"]}}
    result = {k: body[k] for k in ("model", "prompt", "aspect_ratio", "resolution", "quality",
                                  "background", "output_compression", "seed", "n") if k in body}
    if urls:
        result["input_references"] = [{"type": "image_url", "image_url": {"url": url}} for url in urls]
    return result


def _candidate_url(url):
    """Only syntactic screening; the worker must admit host/DNS before GET."""
    if (not isinstance(url, str) or len(url) > 2048 or not url or
            any(ch.isspace() or ord(ch) < 32 or ch == "\\" for ch in url)):
        raise ValueError("untrusted OpenRouter image URL")
    try:
        part = urlsplit(url)
        host = (part.hostname or "").lower().rstrip(".")
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            raise ValueError
        if (part.scheme != "https" or not re.fullmatch(r"[a-z0-9.-]+", host) or "." not in host
                or host.startswith(".") or host.endswith(".") or ".." in host
                or part.port not in {None, 443} or part.username or part.password or
                not part.path or part.path == "/" or part.fragment):
            raise ValueError
    except ValueError:
        raise ValueError("untrusted OpenRouter image URL") from None
    return url


def _decoded_image(encoded):
    if not isinstance(encoded, str) or len(encoded) > 4 * ((MAX_IMAGE + 2) // 3):
        raise ValueError("invalid OpenRouter image data")
    try:
        raw = base64.b64decode(encoded, validate=True)
        data, _dimensions = decode_image(raw)
        return "bytes", data
    except (binascii.Error, ValueError):
        raise ValueError("invalid OpenRouter image data") from None


def _parse_ref(value):
    if not isinstance(value, str):
        raise ValueError("invalid OpenRouter image result")
    if value.startswith("data:"):
        head, sep, encoded = value.partition(",")
        if not sep or head not in {"data:image/png;base64", "data:image/jpeg;base64", "data:image/webp;base64"}:
            raise ValueError("invalid OpenRouter image data URL")
        return _decoded_image(encoded)
    return "url", _candidate_url(value)


def parse_response(value):
    """One result only: sanitized bytes or an exact OpenRouter-host URL for worker download."""
    if not isinstance(value, dict) or ("data" in value) == ("choices" in value):
        raise ValueError("invalid OpenRouter image response")
    if "data" in value:
        rows = value["data"]
        if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
            raise ValueError("OpenRouter image result count invalid")
        row = rows[0]
        b64, url = row.get("b64_json"), row.get("url")
        if (("b64_json" in row and b64 is not None and not isinstance(b64, str)) or
                ("url" in row and url is not None and not isinstance(url, str))):
            raise ValueError("invalid OpenRouter image response")
        if (isinstance(b64, str) and bool(b64)) == (isinstance(url, str) and bool(url)):
            raise ValueError("invalid OpenRouter image response")
        if b64:
            if row.get("media_type") not in {None, "image/png", "image/jpeg", "image/webp"}:
                raise ValueError("unsupported OpenRouter image media type")
            return _decoded_image(b64)
        return "url", _candidate_url(url)
    choices = value["choices"]
    if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
        raise ValueError("OpenRouter image result count invalid")
    message = choices[0].get("message")
    images = message.get("images") if isinstance(message, dict) else None
    if not isinstance(images, list) or len(images) != 1 or not isinstance(images[0], dict):
        raise ValueError("OpenRouter image result count invalid")
    part = images[0].get("image_url")
    return _parse_ref(part.get("url") if isinstance(part, dict) else None)


def auth_headers(key):
    if (not isinstance(key, str) or not 1 <= len(key) <= 4096 or
            any(ord(ch) < 33 or ord(ch) > 126 for ch in key)):
        raise ValueError("OpenRouter credential unavailable")
    return {"Authorization": "Bearer " + key, "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/andrei649/jarvis-hub", "X-Title": "Nerva"}
