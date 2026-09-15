"""Fixed OpenAI image schema; provider content is never a path or an instruction."""

from __future__ import annotations

import base64
import binascii
import io

from PIL import Image

from .comfyui import ImageGenerationError, validate_png

ENDPOINT = "https://api.openai.com/v1/images/generations"
MODEL = "gpt-image-1.5"
MAX_IMAGE = 16 * 1024 * 1024
MAX_RESPONSE = 24 * 1024 * 1024
SIZES = {"1024x1024", "1536x1024", "1024x1536"}


def normalize_request(prompt, options):
    if not isinstance(prompt, str) or not 1 <= len(prompt.strip()) <= 4000:
        raise ValueError("cloud image prompt required")
    if not isinstance(options, dict) or set(options) - {"model", "size", "quality"}:
        raise ValueError("unsupported cloud image option")
    model = options.get("model", MODEL)
    size = options.get("size", "1024x1024")
    quality = options.get("quality", "low")
    if (
        not all(isinstance(value, str) for value in (model, size, quality))
        or model != MODEL
        or size not in SIZES
        or quality not in {"low", "medium", "high"}
    ):
        raise ValueError("unsupported cloud image option")
    return {
        "model": model,
        "prompt": prompt,
        "n": 1,
        "size": size,
        "quality": quality,
        "output_format": "png",
        "stream": False,
    }


def decode_result(value, size):
    try:
        rows = value["data"]
        if not isinstance(rows, list) or len(rows) != 1:
            raise ValueError
        encoded = rows[0]["b64_json"]
        if not isinstance(encoded, str) or len(encoded) > 4 * ((MAX_IMAGE + 2) // 3):
            raise ValueError
        data = base64.b64decode(encoded, validate=True)
        dimensions = validate_png(data)
        if dimensions != tuple(map(int, size.split("x"))):
            raise ValueError
        # Existing structural PNG validator bounds inflation and checks all pixels.
        # Re-encode only pixels, omitting untrusted ancillary text/profile chunks.
        with Image.open(io.BytesIO(data)) as source:
            source.load()
            clean = source.convert("RGBA")
            out = io.BytesIO()
            clean.save(out, format="PNG")
        result = out.getvalue()
        if len(result) > MAX_IMAGE:
            raise ValueError
        return result
    except (KeyError, TypeError, ValueError, OSError, ImageGenerationError, binascii.Error):
        raise ValueError("invalid cloud image result") from None
