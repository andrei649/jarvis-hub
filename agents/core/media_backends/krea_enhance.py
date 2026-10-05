"""Pure, opt-in Krea Enhance request contract adapted from Hermes 59b2aeef.

The caller owns the source artifact, authorization, transport, job polling, and
pixel admission. An Enhance request is a separate paid operation, never an
implicit second POST after image generation.
"""

from __future__ import annotations

from . import krea_image

_REQUIRED_OPTIONS = frozenset({"backend", "model", "size", "enhance_image_url"})
_OPTIONAL_OPTIONS = frozenset({"image_scaling_factor"})
_BODY_FIELDS = frozenset({"model", "prompt", "size", "operation", "image_url",
                          "image_scaling_factor"})
_SIZES = frozenset({"1024x1024", "1536x1024", "1024x1536"})


def normalize_request(prompt, options):
    """Bind one explicit generated-image URL to the fixed two-times Enhance call."""
    if not isinstance(prompt, str) or not 1 <= len(prompt.strip()) <= 4000:
        raise ValueError("Krea enhance prompt required")
    if (type(options) is not dict or not _REQUIRED_OPTIONS.issubset(options)
            or set(options) - _REQUIRED_OPTIONS - _OPTIONAL_OPTIONS
            or options["backend"] != "krea"
            or type(options["model"]) is not str or options["model"] not in krea_image.MODEL_IDS
            or type(options["size"]) is not str or options["size"] not in _SIZES):
        raise ValueError("unsupported Krea enhance option")
    factor = options.get("image_scaling_factor", 2)
    if type(factor) is not int or factor != 2:
        raise ValueError("unsupported Krea enhance factor")
    image_url = krea_image._https_url(options["enhance_image_url"])
    if len(image_url) > 1024:
        raise ValueError("Krea enhance source URL too long")
    return {"model": options["model"], "prompt": prompt.strip(),
            "size": options["size"], "operation": "enhance",
            "image_url": image_url, "image_scaling_factor": 2}


def _checked_body(body):
    if type(body) is not dict or set(body) != _BODY_FIELDS or body.get("operation") != "enhance":
        raise ValueError("invalid Krea enhance request")
    try:
        normalized = normalize_request(body["prompt"], {
            "backend": "krea", "model": body["model"], "size": body["size"],
            "enhance_image_url": body["image_url"],
            "image_scaling_factor": body["image_scaling_factor"],
        })
    except (KeyError, TypeError, ValueError):
        raise ValueError("invalid Krea enhance request") from None
    if body != normalized:
        raise ValueError("invalid Krea enhance request")
    return normalized


def endpoint_for(body):
    _checked_body(body)
    return krea_image.ENHANCE_ENDPOINT


def wire_body(body):
    """The donor's exact native JSON, with no approval metadata on the wire."""
    request = _checked_body(body)
    return {"image_url": request["image_url"],
            "image_scaling_factor": 2, "prompt": request["prompt"]}
