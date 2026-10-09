"""Pure DeepInfra text-to-image adapter from pinned Hermes 59b2aeef.

The donor discovers ``image-gen`` tagged models dynamically. A caller must
obtain and retain a trusted catalog snapshot before approval; this module does
not fetch it, hold credentials, make requests, or publish provider media.
"""

from __future__ import annotations

import base64
import binascii
import ipaddress
import json
import math
import re
from urllib.parse import urlsplit

from .fal_image import MAX_IMAGE, decode_image

BASE_URL = "https://api.deepinfra.com/v1/openai"
CATALOG_ENDPOINT = BASE_URL + "/models?filter=true&sort_by=hermes"
IMAGE_ENDPOINT = BASE_URL + "/images/generations"
SIZES = {"landscape": "1536x1024", "square": "1024x1024", "portrait": "1024x1536"}
MAX_CATALOG_BYTES = 512 * 1024
MAX_MODELS = 512
MAX_RESPONSE = 24 * 1024 * 1024
_SEGMENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")


def _model_id(value):
    if not isinstance(value, str) or not 3 <= len(value) <= 256:
        return False
    parts = value.split("/")
    return 2 <= len(parts) <= 4 and all(
        part not in {".", ".."} and ".." not in part and _SEGMENT.fullmatch(part)
        for part in parts
    )


def catalog_from_response(value):
    """Filter a bounded trusted DeepInfra models response using donor tag rules."""
    try:
        if len(json.dumps(value, ensure_ascii=False).encode("utf-8")) > MAX_CATALOG_BYTES:
            raise ValueError
    except (TypeError, ValueError, OverflowError, RecursionError):
        raise ValueError("invalid DeepInfra image catalog") from None
    if not isinstance(value, dict) or not isinstance(value.get("data"), list) or len(value["data"]) > MAX_MODELS:
        raise ValueError("invalid DeepInfra image catalog")
    result = {}
    for item in value["data"]:
        if not isinstance(item, dict):
            continue
        model = item.get("id")
        metadata = item.get("metadata")
        if not _model_id(model) or not isinstance(metadata, dict):
            continue
        tags = metadata.get("tags")
        if not isinstance(tags, list) or "image-gen" not in tags:
            continue
        if model in result:
            raise ValueError("duplicate DeepInfra image model")
        row = {}
        for key in ("default_width", "default_height", "default_iterations"):
            dimension = metadata.get(key)
            if type(dimension) is int and 0 < dimension <= 4096:
                row[key] = dimension
        description = metadata.get("description")
        if isinstance(description, str):
            row["description"] = description[:512]
        pricing = metadata.get("pricing")
        price = pricing.get("per_image_unit") if isinstance(pricing, dict) else None
        if type(price) in {int, float} and math.isfinite(price) and 0 <= price <= 1000:
            row["price_per_image"] = float(price)
        result[model] = row
    return result


def model_capabilities(catalog):
    if not isinstance(catalog, dict) or len(catalog) > MAX_MODELS:
        raise ValueError("invalid DeepInfra image catalog")
    result = {}
    for model, row in catalog.items():
        if not _model_id(model) or not isinstance(row, dict):
            raise ValueError("invalid DeepInfra image catalog")
        caps = {"modalities": ["text"], "max_reference_images": 0, "edit": False}
        for key in ("default_width", "default_height", "default_iterations"):
            if key in row:
                value = row[key]
                if type(value) is not int or not 0 < value <= 4096:
                    raise ValueError("invalid DeepInfra image catalog")
                caps[key] = value
        result[model] = caps
    return result


def normalize_request(prompt, options, *, catalog):
    """Bind donor model, prompt, and aspect size into one approved POST body."""
    if not isinstance(prompt, str) or not 1 <= len(prompt.strip()) <= 4000:
        raise ValueError("DeepInfra image prompt required")
    if not isinstance(options, dict) or options.get("backend") != "deepinfra" or set(options) - {
        "backend", "model", "size", "aspect_ratio", "references", "n",
    }:
        raise ValueError("unsupported DeepInfra image option")
    models = model_capabilities(catalog)
    model = options.get("model", next(iter(models), None))
    if not isinstance(model, str) or model not in models:
        raise ValueError("unsupported DeepInfra image model")
    refs = options.get("references", [])
    if not isinstance(refs, list) or refs:
        raise ValueError("DeepInfra image references unsupported")
    if "n" in options and (type(options["n"]) is not int or options["n"] != 1):
        raise ValueError("DeepInfra approves one image")
    aspect = options.get("aspect_ratio", "landscape")
    if not isinstance(aspect, str) or aspect not in SIZES:
        raise ValueError("unsupported DeepInfra aspect ratio")
    size = options.get("size", SIZES[aspect])
    if not isinstance(size, str) or size not in SIZES.values() or (
        "aspect_ratio" in options and size != SIZES[aspect]
    ):
        raise ValueError("unsupported DeepInfra image size")
    return {"model": model, "prompt": prompt.strip(), "size": size, "n": 1}


def _valid_body(body):
    if not isinstance(body, dict) or set(body) != {"model", "prompt", "size", "n"}:
        raise ValueError("invalid DeepInfra image request")
    if (not _model_id(body["model"]) or not isinstance(body["prompt"], str) or
            not 1 <= len(body["prompt"].strip()) <= 4000 or body["prompt"] != body["prompt"].strip() or
            body["size"] not in SIZES.values() or type(body["n"]) is not int or body["n"] != 1):
        raise ValueError("invalid DeepInfra image request")


def endpoint_for(body):
    _valid_body(body)
    return IMAGE_ENDPOINT


def wire_body(body):
    _valid_body(body)
    return dict(body)


def _https_candidate(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 2048 or any(ch.isspace() for ch in value):
        raise ValueError("invalid DeepInfra image URL")
    try:
        parsed = urlsplit(value)
        host = (parsed.hostname or "").lower().rstrip(".")
        if not (parsed.scheme == "https" and host and "." in host and
                parsed.port in {None, 443} and parsed.username is None and
                parsed.password is None and parsed.path and not parsed.fragment and
                not host.endswith((".local", ".internal", ".localhost"))):
            raise ValueError
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            raise ValueError
    except ValueError:
        raise ValueError("invalid DeepInfra image URL") from None
    return value


def parse_response(value):
    """Return one verified raster byte string or an untrusted URL candidate."""
    if not isinstance(value, dict) or not isinstance(value.get("data"), list) or len(value["data"]) != 1:
        raise ValueError("invalid DeepInfra image response")
    item = value["data"][0]
    if not isinstance(item, dict):
        raise ValueError("invalid DeepInfra image response")
    encoded, url = item.get("b64_json"), item.get("url")
    if isinstance(encoded, str) and encoded and not url:
        if len(encoded) > ((MAX_IMAGE + 2) // 3) * 4:
            raise ValueError("DeepInfra image too large")
        try:
            data = base64.b64decode(encoded, validate=True)
            decode_image(data)
        except (ValueError, binascii.Error):
            raise ValueError("invalid DeepInfra image response") from None
        return "bytes", data
    if isinstance(url, str) and url and not encoded:
        return "url", _https_candidate(url)
    raise ValueError("invalid DeepInfra image response")


def auth_headers(key):
    if (not isinstance(key, str) or not 1 <= len(key) <= 4096 or
            any(ord(ch) < 33 or ord(ch) > 126 for ch in key)):
        raise ValueError("invalid DeepInfra credential")
    return {"Authorization": "Bearer " + key}
