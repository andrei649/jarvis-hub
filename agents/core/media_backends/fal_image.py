"""Bounded FAL image payloads and result handling.

Payload construction adapts the pinned Hermes 59b2aeef catalog and its
``_build_payload`` whitelist behavior. Unsupported caller options fail before
approval instead of silently disappearing from a paid request.
"""

from __future__ import annotations

import io
from urllib.parse import urlsplit

from PIL import Image, UnidentifiedImageError

from .comfyui import validate_png
from .fal_catalog import DEFAULT_MODEL, FAL_MODELS

MAX_IMAGE = 16 * 1024 * 1024
MAX_RESPONSE = 256 * 1024
SIZE_ASPECT = {"1024x1024": "square", "1536x1024": "landscape", "1024x1536": "portrait"}
_SIZE_KEY = {"image_size_preset": "image_size", "gpt_literal": "image_size",
             "aspect_ratio": "aspect_ratio"}


def media_url(url):
    """Only FAL's HTTPS media domain and subdomains, with no userinfo or port."""
    if not isinstance(url, str) or len(url) > 2048 or any(c.isspace() for c in url):
        raise ValueError("invalid FAL media URL")
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower().rstrip(".")
        valid = (parts.scheme == "https" and host and
                 (host == "fal.media" or host.endswith(".fal.media")) and
                 parts.port in {None, 443} and not parts.username and not parts.password and
                 bool(parts.path) and not parts.fragment)
    except ValueError:
        valid = False
    if not valid:
        raise ValueError("invalid FAL media URL")
    return url


def normalize_request(prompt, options):
    if not isinstance(prompt, str) or not 1 <= len(prompt.strip()) <= 4000:
        raise ValueError("cloud image prompt required")
    if not isinstance(options, dict) or options.get("backend") != "fal" or set(options) - {
        "backend", "model", "size", "seed", "steps", "references",
    }:
        raise ValueError("unsupported FAL image option")
    model = options.get("model", DEFAULT_MODEL)
    size = options.get("size", "1536x1024")
    if (not isinstance(model, str) or model not in FAL_MODELS or
            not isinstance(size, str) or size not in SIZE_ASPECT):
        raise ValueError("unsupported FAL image model or size")
    meta = FAL_MODELS[model]
    refs = options.get("references", [])
    if not isinstance(refs, list) or len(refs) > 16 or any(not isinstance(r, str) for r in refs):
        raise ValueError("unsupported FAL image references")
    refs = [media_url(r) for r in refs]
    edit = bool(refs)
    if edit and (not meta.get("edit_endpoint") or len(refs) > meta["max_reference_images"]):
        raise ValueError("FAL model does not support this edit")
    supports = meta["edit_supports"] if edit else meta["supports"]
    body = {k: v for k, v in meta["defaults"].items() if k in supports}
    body["prompt"] = prompt.strip()
    size_key = _SIZE_KEY[meta["size_style"]]
    if size_key in supports:
        body[size_key] = meta["sizes"][SIZE_ASPECT[size]]
    if edit:
        image_key = meta.get("edit_image_param", "image_urls")
        body[image_key] = refs[0] if image_key == "image_url" else refs
    if "seed" in options:
        seed = options["seed"]
        if type(seed) is not int or not 0 <= seed < 2**63 or "seed" not in supports:
            raise ValueError("unsupported FAL image seed")
        body["seed"] = seed
    if "steps" in options:
        steps = options["steps"]
        if type(steps) is not int or not 1 <= steps <= 40 or "num_inference_steps" not in supports:
            raise ValueError("unsupported FAL image steps")
        body["num_inference_steps"] = steps
    result = {"model": model, "prompt": prompt.strip(), "size": size,
              "references": refs, "endpoint": meta["edit_endpoint"] if edit else model,
              "body": body}
    for key in ("seed", "steps"):
        if key in options:
            result[key] = options[key]
    return result


def result_url(value):
    if not isinstance(value, dict) or not isinstance(value.get("images"), list):
        raise ValueError("invalid FAL response")
    images = value["images"]
    if len(images) != 1 or not isinstance(images[0], dict):
        raise ValueError("invalid FAL response")
    return media_url(images[0].get("url"))


def decode_image(data, *, max_dimension=2048):
    """Decode provider raster, discard metadata, and return safe local PNG + dimensions."""
    if (type(max_dimension) is not int or max_dimension not in {2048, 4096}
            or not isinstance(data, bytes) or not 1 <= len(data) <= MAX_IMAGE):
        raise ValueError("invalid FAL image")
    try:
        with Image.open(io.BytesIO(data)) as source:
            if getattr(source, "is_animated", False) or not (0 < source.width <= max_dimension and 0 < source.height <= max_dimension):
                raise ValueError
            source.load()
            dimensions = source.size
            out = io.BytesIO()
            source.convert("RGBA").save(out, format="PNG")
        clean = out.getvalue()
        if len(clean) > MAX_IMAGE or validate_png(clean, max_dimension=max_dimension) != dimensions:
            raise ValueError
        return clean, dimensions
    except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError):
        raise ValueError("invalid FAL image") from None
