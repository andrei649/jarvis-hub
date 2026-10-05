"""Pinned native Codex images request shape and paired owner OAuth credential.

Nerva deliberately has no implicit Hermes/Nous credential import. An owner must
enable the distinct plugin and explicitly configure this credential source.
"""

from __future__ import annotations

import base64
import json
import os
import time
import uuid
from dataclasses import dataclass

from .openai_image import IMAGE2_TIERS, SIZES

BASE_URL = "https://chatgpt.com/backend-api/codex"
DEFAULT_MODEL = "gpt-image-2-medium"


@dataclass(frozen=True)
class CodexCredential:
    access_token: str
    base_url: str
    account_id: str
    residency: str | None

    @property
    def headers(self):
        result = {
            "Authorization": f"Bearer {self.access_token}",
            "User-Agent": "Nerva/1.0",
            "originator": "nerva",
            "ChatGPT-Account-ID": self.account_id,
            "x-codex-image-turn-id": str(uuid.uuid4()),
        }
        if self.residency:
            result["x-openai-internal-codex-residency"] = self.residency
        return result


def configured_source():
    """Explicit owner setting; no discovery of existing user credential files."""
    if os.environ.get("NERVA_CODEX_IMAGE_OAUTH_ENABLED") != "1":
        return None
    return {
        "access_token": os.environ.get("NERVA_CODEX_IMAGE_OAUTH_TOKEN"),
        "base_url": os.environ.get("NERVA_CODEX_IMAGE_OAUTH_BASE_URL"),
    }


def resolve_credential(source=configured_source):
    pair = source()
    if not isinstance(pair, dict) or set(pair) != {"access_token", "base_url"}:
        raise ValueError("Codex OAuth credential unavailable")
    token, base = pair["access_token"], pair["base_url"]
    if not isinstance(token, str) or len(token) > 16_384 or not isinstance(base, str):
        raise ValueError("Codex OAuth credential invalid")
    # Native images are only entrusted to the official Codex endpoint. A URL
    # from a model, a credential pool or an arbitrary custom proxy never receives
    # this token, including when another egress policy is relaxed.
    if base != BASE_URL or len(token.split(".")) != 3:
        raise ValueError("Codex OAuth endpoint or token invalid")
    try:
        part = token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
        auth = claims["https://api.openai.com/auth"]
        account = auth["chatgpt_account_id"]
        expiry = claims["exp"]
        if (not isinstance(account, str) or not account or len(account) > 256 or
                not isinstance(expiry, int) or expiry <= time.time() + 60):
            raise ValueError
        residency = auth.get("chatgpt_data_residency") or auth.get("chatgpt_compute_residency")
        if residency is not None and (not isinstance(residency, str) or len(residency) > 64):
            raise ValueError
    except (KeyError, ValueError, TypeError, UnicodeError, json.JSONDecodeError):
        raise ValueError("Codex OAuth token invalid or expired") from None
    return CodexCredential(token, base, account, residency)


def normalize_request(prompt, options):
    if not isinstance(prompt, str) or not 1 <= len(prompt.strip()) <= 4000:
        raise ValueError("cloud image prompt required")
    if not isinstance(options, dict) or set(options) - {"model", "size", "references"}:
        raise ValueError("unsupported Codex image option")
    model = options.get("model", DEFAULT_MODEL)
    size = options.get("size", "1024x1024")
    refs = options.get("references", [])
    if model not in IMAGE2_TIERS or size not in SIZES or not isinstance(refs, list) or len(refs) > 16:
        raise ValueError("unsupported Codex image option")
    if any(not isinstance(ref, str) or len(ref) != 32 or
           any(ch not in "0123456789abcdef" for ch in ref) for ref in refs):
        raise ValueError("unsupported Codex image reference")
    return {"prompt": prompt, "model": model, "size": size, "references": refs}


def endpoint_for(body):
    return BASE_URL + ("/images/edits" if body["references"] else "/images/generations")


def wire_body(body, images=()):
    result = {
        "prompt": body["prompt"], "model": "gpt-image-2", "n": 1,
        "quality": IMAGE2_TIERS[body["model"]], "size": body["size"],
        "background": "opaque",
    }
    if images:
        result["images"] = [{"image_url": "data:image/png;base64," +
                             base64.b64encode(data).decode("ascii")} for data in images]
    return result
