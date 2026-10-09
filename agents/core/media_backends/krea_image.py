"""Krea 2 image/job contract adapted from pinned Hermes 59b2aeef.

This module has no transport or credential side effects. Result URLs are only
untrusted candidates: the worker must establish an approved CDN policy, pin DNS,
download, validate pixels, and publish locally before reporting success. The
donor's ``krea.cdn`` URLs occur in test fixtures and prove no real CDN origin.
"""

from __future__ import annotations

import ipaddress
import math
import re
from urllib.parse import urlsplit

BASE_URL = "https://api.krea.ai"
ENHANCE_ENDPOINT = BASE_URL + "/generate/enhance/krea/enhance"
DEFAULT_MODEL = "krea-2-medium"
MODEL_CATALOG = {
    "krea-2-medium": {
        "display": "Krea 2 Medium", "speed": "~15-25s",
        "strengths": "Illustration, anime, painting, expressive styles. Faster + cheaper.",
        "price": "$0.030 (text) / $0.035 (style refs) / $0.040 (moodboards)",
        "path": "medium", "upscale": False,
    },
    "krea-2-large": {
        "display": "Krea 2 Large", "speed": "~25-60s",
        "strengths": "Photorealism, raw textured looks (motion blur, grain), expressive styles.",
        "price": "$0.060 (text) / $0.065 (style refs) / $0.070 (moodboards)",
        "path": "large", "upscale": False,
    },
    "krea-2-medium-turbo": {
        "display": "Krea 2 Medium Turbo", "speed": "~8-15s",
        "strengths": "Fastest Krea 2 — medium quality at lower latency / cost.",
        "price": "$0.015 (text) / $0.0175 (style refs)",
        "path": "medium-turbo", "upscale": False,
    },
}
MODEL_IDS = frozenset(MODEL_CATALOG)
_SIZE_TO_ASPECT = {"1536x1024": "16:9", "1024x1024": "1:1", "1024x1536": "9:16"}
_ABSTRACT_TO_SIZE = {"landscape": "1536x1024", "square": "1024x1024",
                     "portrait": "1024x1536"}
_CREATIVITY = frozenset({"raw", "low", "medium", "high"})
MAX_STYLE_REFERENCES = 10
DEFAULT_STYLE_STRENGTH = 0.6
_JOB_ID = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")


def model_capabilities(model):
    if not isinstance(model, str) or model not in MODEL_CATALOG:
        raise ValueError("unsupported Krea model")
    return {
        "modalities": ["text", "style_guided_generation"],
        "max_style_references": MAX_STYLE_REFERENCES,
        "supports_enhance": True,
        "enhance_default": False,
    }


def _https_url(value):
    """Bound a URL's syntax; this does not certify its DNS or download authority."""
    if not isinstance(value, str) or not 1 <= len(value) <= 2048 or any(ch.isspace() for ch in value):
        raise ValueError("invalid Krea image URL")
    try:
        parsed = urlsplit(value)
        host = (parsed.hostname or "").lower().rstrip(".")
        if not (parsed.scheme == "https" and host and "." in host and
                parsed.port in {None, 443} and parsed.username is None and
                parsed.password is None and parsed.path and not parsed.fragment and
                not host.endswith((".local", ".internal")) and not host.endswith(".localhost")):
            raise ValueError
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            raise ValueError
    except ValueError:
        raise ValueError("invalid Krea image URL") from None
    return value


def _style_references(raw):
    if not isinstance(raw, list) or not 1 <= len(raw) <= MAX_STYLE_REFERENCES:
        raise ValueError("unsupported Krea style references")
    refs = []
    seen = set()
    for item in raw:
        if isinstance(item, str):
            url, strength = _https_url(item), DEFAULT_STYLE_STRENGTH
        elif isinstance(item, dict) and set(item) == {"url", "strength"}:
            url = _https_url(item["url"])
            strength = item["strength"]
            if (type(strength) not in {int, float} or not math.isfinite(strength) or
                    not -2 <= strength <= 2):
                raise ValueError("unsupported Krea style strength")
            strength = float(strength)
        else:
            raise ValueError("unsupported Krea style reference")
        if url in seen:
            raise ValueError("duplicate Krea style reference")
        seen.add(url)
        refs.append({"url": url, "strength": strength})
    return refs


def normalize_request(prompt, options):
    """Return exact generation inputs; no implicit enhance or generic image editing."""
    if not isinstance(prompt, str) or not 1 <= len(prompt.strip()) <= 4000:
        raise ValueError("Krea image prompt required")
    if not isinstance(options, dict) or options.get("backend") != "krea" or set(options) - {
        "backend", "model", "size", "aspect_ratio", "creativity", "seed", "image_style_references",
    }:
        raise ValueError("unsupported Krea image option")
    model = options.get("model", DEFAULT_MODEL)
    size = options.get("size", "1536x1024")
    abstract = options.get("aspect_ratio")
    if abstract is not None:
        if not isinstance(abstract, str) or abstract not in _ABSTRACT_TO_SIZE:
            raise ValueError("unsupported Krea aspect ratio")
        derived = _ABSTRACT_TO_SIZE[abstract]
        if "size" in options and size != derived:
            raise ValueError("conflicting Krea image size and aspect ratio")
        size = derived
    if (not isinstance(model, str) or model not in MODEL_CATALOG or
            not isinstance(size, str) or size not in _SIZE_TO_ASPECT):
        raise ValueError("unsupported Krea image model or size")
    creativity = options.get("creativity", "medium")
    if not isinstance(creativity, str) or creativity not in _CREATIVITY:
        raise ValueError("unsupported Krea creativity")
    result = {"model": model, "prompt": prompt.strip(), "size": size,
              "creativity": creativity, "modality": "text"}
    if "seed" in options:
        seed = options["seed"]
        if type(seed) is not int or not 0 <= seed < 2**63:
            raise ValueError("unsupported Krea seed")
        result["seed"] = seed
    if "image_style_references" in options:
        result["image_style_references"] = _style_references(options["image_style_references"])
        result["modality"] = "style_guided_generation"
    return result


def _checked_body(body):
    if not isinstance(body, dict):
        raise ValueError("invalid Krea image request")
    try:
        normalized = normalize_request(body["prompt"], {
            "backend": "krea", **{key: body[key] for key in
             ("model", "size", "creativity", "seed", "image_style_references") if key in body},
        })
    except (KeyError, TypeError, ValueError):
        raise ValueError("invalid Krea image request") from None
    if body != normalized:
        raise ValueError("invalid Krea image request")
    return normalized


def endpoint_for(body):
    request = _checked_body(body)
    return BASE_URL + "/generate/image/krea/krea-2/" + MODEL_CATALOG[request["model"]]["path"]


def wire_body(body):
    """Build donor's submit JSON from exact normalized inputs."""
    request = _checked_body(body)
    wire = {"prompt": request["prompt"], "aspect_ratio": _SIZE_TO_ASPECT[request["size"]],
            "resolution": "1K", "creativity": request["creativity"]}
    for key in ("seed", "image_style_references"):
        if key in request:
            wire[key] = request[key]
    return wire


def parse_job_id(value):
    if not isinstance(value, dict) or not isinstance(value.get("job_id"), str):
        raise ValueError("invalid Krea job response")
    job_id = value["job_id"]
    if _JOB_ID.fullmatch(job_id) is None:
        raise ValueError("invalid Krea job id")
    return job_id


def poll_endpoint(job_id):
    return BASE_URL + "/jobs/" + parse_job_id({"job_id": job_id})


def parse_job_status(value):
    """Normalize polling state; a completed URL remains untrusted candidate data."""
    if not isinstance(value, dict) or not isinstance(value.get("status"), str) or not value["status"]:
        raise ValueError("invalid Krea job status")
    status = value["status"]
    if len(status) > 64:
        raise ValueError("invalid Krea job status")
    result = value.get("result")
    if status in {"failed", "cancelled"}:
        if isinstance(result, dict) and (result.get("urls") or result.get("url")):
            raise ValueError("conflicting Krea job result")
        return {"state": status, "url": None}
    completed = status == "completed" or (
        isinstance(value.get("completed_at"), str) and bool(value["completed_at"].strip())
    )
    if not completed:
        if isinstance(result, dict) and (result.get("urls") or result.get("url")):
            raise ValueError("premature Krea job result")
        return {"state": "pending", "url": None}
    if not isinstance(result, dict):
        raise ValueError("Krea completed result missing")
    urls = result.get("urls")
    if urls is not None and (not isinstance(urls, list) or len(urls) > 1):
        raise ValueError("unsupported Krea result count")
    listed = urls[0] if urls else None
    single = result.get("url")
    if listed and single and listed != single:
        raise ValueError("conflicting Krea result URLs")
    candidate = listed or single
    if candidate is None:
        raise ValueError("Krea completed result URL missing")
    return {"state": "completed", "url": _https_url(candidate)}


def normalize_enhance_request(prompt, image_url):
    """Separate optional paid POST body; the caller must govern it independently."""
    if not isinstance(prompt, str) or not 1 <= len(prompt.strip()) <= 4000:
        raise ValueError("Krea enhance prompt required")
    return {"image_url": _https_url(image_url), "image_scaling_factor": 2,
            "prompt": prompt.strip()}
