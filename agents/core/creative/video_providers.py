"""video_providers.py — the adopted Hermes video backends, seen from Nerva (G19, H516).

Hermes's ``VideoGenProvider`` ABC, its registry and three of its provider plugins (FAL, xAI
Grok Imagine, DeepInfra) are vendored under ``agents/vendor/hermes/`` and run as they are
behind the compat layer (``docs/hermes/ADOPT_LANE.md``, "Video generation"). This module is
the reviewed Nerva side of that seam:

* :data:`PROVIDERS` — the server-owned table: which upstream provider names Nerva runs, the
  egress identity each dials under (one RESTRICTED manifest per provider, its own hosts
  only), the one key name it may read, and its display facts. A vendored plugin that
  registers any other name is refused.
* :func:`registry` — imports the vendored plugins once and registers them through a ctx
  that offers only ``register_video_gen_provider``.
* :func:`normalize_request` — the arguments the owner approves, checked and clamped the way
  the provider will clamp them, so the approval card shows what will be sent.
* :func:`estimate` — the cost estimate on the card: a list price where Nerva has one
  (checked 2026-11-10), otherwise a stated ceiling for the provider's tier. It is an upper
  bound for the approval, recorded as the task's ``amount`` (the autonomy policy's money
  accounting); a price the provider reports after the run is recorded beside it.

The OpenRouter video plugin is not adopted: it resolves its key through Hermes's runtime
provider resolver (``hermes_cli.runtime_provider``) and uses ``requests`` directly.
"""

from __future__ import annotations

import importlib
import logging
import math
import re
import threading
from dataclasses import dataclass
from typing import Any

from agents.core.env_config import env_str

logger = logging.getLogger("jarvis.creative.video_providers")

ARTIFACT_ID = re.compile(r"[a-f0-9]{32}")
MAX_PROMPT = 2000
MAX_NEGATIVE = 1000
CHOICE_ENV = "JARVIS_VIDEO_PROVIDER"
ASPECT_RATIOS = ("16:9", "9:16", "1:1", "4:3", "3:4", "3:2", "2:3", "21:9")
RESOLUTIONS = ("480p", "540p", "720p", "768p", "1080p")


@dataclass(frozen=True)
class VideoProviderRow:
    name: str            # the upstream provider name (``VideoGenProvider.name``)
    display: str
    plugin: str          # Nerva egress identity (``plugin_gate.BUILTIN_PLUGINS``)
    key: str             # the one key name it may read
    host: str            # the API host the owner is told about
    media_hosts: tuple[str, ...]   # hosts whose media URLs it accepts as image inputs
    operations: tuple[str, ...] = ("generate",)


PROVIDERS: dict[str, VideoProviderRow] = {
    "fal": VideoProviderRow("fal", "FAL (video)", "cloud-video-fal", "FAL_KEY", "queue.fal.run",
                            ("fal.media",)),
    "xai": VideoProviderRow("xai", "xAI Grok Imagine (video)", "cloud-video-xai", "XAI_API_KEY",
                            "api.x.ai", ("imgen.x.ai", "vidgen.x.ai"),
                            ("generate", "edit", "extend")),
    "deepinfra": VideoProviderRow("deepinfra", "DeepInfra (video)", "cloud-video-deepinfra",
                                  "DEEPINFRA_API_KEY", "api.deepinfra.com", ()),
}

#: Vendored plugin packages (``agents.vendor.hermes.plugins.video_gen.<name>``).
ADOPTED_VIDEO_PLUGINS = ("fal", "xai", "deepinfra")


# ── the vendored registry ────────────────────────────────────────────────────────

_LOCK = threading.Lock()
_LOADED: list[Any] = []


class _VideoCtx:
    """The ``ctx`` a vendored video plugin's ``register(ctx)`` receives: one method."""

    def __init__(self, registry_module: Any) -> None:
        self._registry = registry_module
        self.registered: list[str] = []

    def register_video_gen_provider(self, provider: Any) -> None:
        name = str(getattr(provider, "name", "") or "")
        if name not in PROVIDERS:
            raise ValueError(f"video provider {name!r} has no reviewed row")
        self._registry.register_provider(provider)
        self.registered.append(name)


def registry() -> Any:
    """The vendored ``video_gen_registry`` module with the adopted plugins registered."""
    with _LOCK:
        if _LOADED:
            return _LOADED[0]
        module = importlib.import_module("agents.vendor.hermes.agent.video_gen_registry")
        ctx = _VideoCtx(module)
        for package in ADOPTED_VIDEO_PLUGINS:
            try:
                plugin = importlib.import_module(f"agents.vendor.hermes.plugins.video_gen.{package}")
                plugin.register(ctx)
            except Exception as exc:  # noqa: BLE001 — one plugin never breaks the others
                logger.warning("adopted Hermes video provider %s not loaded (type=%s)",
                               package, type(exc).__name__)
        from agents.vendor.hermes_compat.plugin_ctx import _quiet_vendor_loggers

        _quiet_vendor_loggers()
        _LOADED.append(module)
        return module


def provider(name: str) -> Any:
    if name not in PROVIDERS:
        return None
    return registry().get_provider(name)


def plugin_module(name: str) -> Any:
    return importlib.import_module(f"agents.vendor.hermes.plugins.video_gen.{name}")


def chosen() -> str:
    """The provider the owner chose with consent (Integrations panel or ``.env``), or ""."""
    value = str(env_str(CHOICE_ENV, "") or "").strip().lower()
    return value if value in PROVIDERS else ""


def key_set(name: str) -> bool:
    row = PROVIDERS.get(name)
    return bool(row and str(env_str(row.key, "") or "").strip())


class VideoRequestError(ValueError):
    """An argument Nerva will not send (the reason is a fixed code)."""


# ── pricing ──────────────────────────────────────────────────────────────────────
#
# Only verified list prices (checked 2026-11-10 on the fal.ai model pages, the
# docs.x.ai pricing page and deepinfra.com). A model, a modality or a resolution with no
# verified price is refused (``price_unverified``): a guess is never shown as a ceiling.
# The estimate is still an upper bound: an unknown audio default counts as audio on, a
# resolution the family drops counts at its dearest listed rate, an unset duration at the
# family's longest.

PRICE_SOURCE = "list price checked 2026-11-10 (fal.ai model pages, docs.x.ai/developers/pricing, deepinfra.com)"

#: FAL family -> verified modalities and USD/s per resolved resolution as
#: (audio off, audio on); ``None`` is the key for a family with no resolution setting.
FAL_PRICES: dict[str, dict] = {
    "pixverse-v6": {"modalities": ("text", "image"), "rates": {
        "360p": (0.025, 0.035), "540p": (0.035, 0.045), "720p": (0.045, 0.060), "1080p": (0.090, 0.115)}},
    "veo3.1": {"modalities": ("text", "image"), "rates": {
        "720p": (0.20, 0.40), "1080p": (0.20, 0.40), "4k": (0.40, 0.60)}},
    "kling-v3": {"modalities": ("text", "image"), "rates": {None: (0.084, 0.126)}},
    "kling-v3-pro": {"modalities": ("text",), "rates": {None: (0.112, 0.168)}},
    "kling-v3-4k": {"modalities": ("text",), "rates": {None: (0.42, 0.42)}},
    "seedance-2.0": {"modalities": ("text",), "rates": {"720p": (0.3034, 0.3034), "1080p": (0.682, 0.682)}},
    "seedance-2.0-mini": {"modalities": ("text",), "rates": {"480p": (0.0721, 0.0721), "720p": (0.1547, 0.1547)}},
    "wan-3.0": {"modalities": ("text", "image"), "rates": {
        "480p": (0.05, 0.05), "720p": (0.10, 0.10), "1080p": (0.20, 0.20)}},
    "wan-2.7": {"modalities": ("text",), "rates": {"720p": (0.10, 0.10), "1080p": (0.15, 0.15)}},
    "minimax-h3": {"modalities": ("text",), "rates": {"768P": (0.06, 0.06), "2K": (0.13, 0.13), "4K": (0.16, 0.16)}},
    "flux-3": {"modalities": ("text",), "rates": {"720p": (0.17, 0.17), "1080p": (0.29, 0.29)}},
    "happy-horse": {"modalities": ("text",), "rates": {"720p": (0.14, 0.14), "1080p": (0.18, 0.18)}},
}
#: xAI model -> USD/s per resolution (docs.x.ai).
XAI_PRICES: dict[str, dict[str, float]] = {
    "grok-imagine-video": {"480p": 0.05, "720p": 0.07},
    "grok-imagine-video-1.5": {"480p": 0.08, "720p": 0.14, "1080p": 0.25},
}
#: DeepInfra model -> USD/s, flat (deepinfra.com).
DEEPINFRA_PRICES: dict[str, float] = {"Wan-AI/Wan3.0-Video": 0.20, "Wan-AI/Wan2.6-T2V": 0.10}
#: Per input image (xAI lists $0.002–$0.01 an image; the dearer is used).
IMAGE_INPUT_USD = 0.01
#: xAI bills an input video by the second (edit and extend).
XAI_VIDEO_INPUT_USD_PER_SECOND = 0.01


def _unverified() -> VideoRequestError:
    return VideoRequestError("price_unverified")


def _per_second(body: dict) -> float:
    name, model = body["provider"], body["model"]
    if name == "xai":
        rates = XAI_PRICES.get(model)
        if not rates:
            raise _unverified()
        if body.get("operation", "generate") != "generate":
            return max(rates.values())          # the output resolution is xAI's choice
        rate = rates.get(body["resolution"])
        if rate is None:
            raise _unverified()
        return rate
    if name == "deepinfra":
        rate = DEEPINFRA_PRICES.get(model)
        if rate is None:
            raise _unverified()
        return rate
    family = plugin_module("fal").FAL_FAMILIES[model]
    prices = FAL_PRICES.get(model)
    modality = "image" if any(i.startswith("image:") for i in body.get("images", [])) else "text"
    if prices is None or modality not in prices["modalities"]:
        raise _unverified()
    rates = prices["rates"]
    if not family["resolutions"]:
        key = None
    else:
        resolved = (family.get("resolution_aliases") or {}).get(body["resolution"].lower(), body["resolution"])
        key = resolved if resolved in family["resolutions"] else "*"
    if key == "*":                               # dropped: the endpoint decides
        pair = max(rates.values(), key=lambda r: r[1])
    elif key in rates:
        pair = rates[key]
    else:
        raise _unverified()
    return pair[0] if body.get("audio") is False else pair[1]


def estimate(body: dict) -> dict:
    """``{"usd", "per_second", "seconds", "basis"}`` — an upper bound from verified prices.

    Raises :class:`VideoRequestError` ``price_unverified`` when Nerva has no verified price."""
    rate = _per_second(body)
    seconds = int(body["billed_seconds"])
    inputs = len(body.get("images", []))
    usd = rate * seconds + IMAGE_INPUT_USD * inputs
    if body.get("operation", "generate") != "generate":
        usd += XAI_VIDEO_INPUT_USD_PER_SECOND * int(body.get("source_seconds") or 0)
    usd = math.ceil(round(usd * 100, 6)) / 100
    return {"usd": usd, "per_second": rate, "seconds": seconds, "basis": PRICE_SOURCE}


# ── the request the owner approves ───────────────────────────────────────────────


def _image_ref(value: Any, row: VideoProviderRow) -> str:
    """An image input: a Nerva generated image (artifact id) or the provider's own media URL."""
    if isinstance(value, str) and ARTIFACT_ID.fullmatch(value):
        return value
    if isinstance(value, str) and value.startswith("https://") and len(value) <= 2048:
        from urllib.parse import urlsplit

        parts = urlsplit(value)
        host = (parts.hostname or "").lower()
        if (parts.port in (None, 443) and not parts.username and not parts.password
                and any(host == h or host.endswith("." + h) for h in row.media_hosts)):
            return value
    raise VideoRequestError("invalid_image_input")


def normalize_request(args: dict) -> dict:
    """Check and clamp the tool's arguments into the body an approval binds.

    ``provider`` defaults to the owner's consented choice. ``billed_seconds`` is the
    duration the provider will bill (its own clamp; its maximum when the endpoint chooses).
    """
    if not isinstance(args, dict):
        raise VideoRequestError("invalid_arguments")
    allowed = {"provider", "prompt", "model", "duration", "aspect_ratio", "resolution", "image",
               "reference_images", "negative_prompt", "seed", "audio", "operation", "source_task_id"}
    if set(args) - allowed:
        raise VideoRequestError("unsupported_video_option")
    name = args.get("provider") or chosen()
    row = PROVIDERS.get(name) if isinstance(name, str) else None
    if row is None:
        raise VideoRequestError("no_video_provider")
    operation = args.get("operation", "generate")
    if operation not in row.operations:
        raise VideoRequestError("unsupported_operation")
    prompt = args.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > MAX_PROMPT:
        raise VideoRequestError("invalid_prompt")
    prompt = prompt.strip()
    body: dict[str, Any] = {"provider": name, "operation": operation, "prompt": prompt}
    aspect = args.get("aspect_ratio", "16:9")
    resolution = args.get("resolution", "720p")
    if aspect not in ASPECT_RATIOS or resolution not in RESOLUTIONS:
        raise VideoRequestError("invalid_format")
    duration = args.get("duration")
    if duration is not None and (type(duration) is not int or not 1 <= duration <= 30):
        raise VideoRequestError("invalid_duration")
    seed = args.get("seed")
    if seed is not None and (type(seed) is not int or not 0 <= seed < 2**31):
        raise VideoRequestError("invalid_seed")
    audio = args.get("audio")
    if audio is not None and type(audio) is not bool:
        raise VideoRequestError("invalid_audio")
    negative = args.get("negative_prompt")
    if negative is not None and (not isinstance(negative, str) or len(negative) > MAX_NEGATIVE):
        raise VideoRequestError("invalid_negative_prompt")
    image = args.get("image")
    refs = args.get("reference_images")
    if refs is not None and (not isinstance(refs, list) or not refs or len(refs) > 7
                             or len(set(map(str, refs))) != len(refs)):
        raise VideoRequestError("invalid_reference_images")
    model = args.get("model")
    if model is not None and (not isinstance(model, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/:-]{0,127}", model)):
        raise VideoRequestError("invalid_model")

    if operation != "generate":
        # xAI edit / extend of a video Nerva generated with xAI (source_task_id).
        source = args.get("source_task_id")
        if type(source) is not int or not 1 <= source < 2**63:
            raise VideoRequestError("source_task_required")
        if image is not None or refs is not None or negative is not None or seed is not None or audio is not None:
            raise VideoRequestError("unsupported_video_option")
        xai = plugin_module("xai")
        if model is not None and model not in xai._MODELS:
            raise VideoRequestError("invalid_model")
        body["model"] = model or xai.DEFAULT_MODEL
        body["source_task_id"] = source
        seconds = (xai._clamp_duration(duration, max_seconds=10, default=xai.DEFAULT_EXTEND_DURATION)
                   if operation == "extend" else xai.DEFAULT_DURATION)
        body["duration"] = seconds
        body["billed_seconds"] = seconds
        body["images"] = []
        return body
    if args.get("source_task_id") is not None:
        raise VideoRequestError("unsupported_video_option")

    # Flat strings ("image:<ref>" / "reference:<ref>"): an approval payload has a nesting
    # bound. A ref is a generated image's id or the provider's own media URL.
    images = []
    if image is not None:
        images.append("image:" + _image_ref(image, row))
    for ref in refs or []:
        images.append("reference:" + _image_ref(ref, row))
    body.update(aspect_ratio=aspect, resolution=resolution)

    if name == "fal":
        fal = plugin_module("fal")
        family_id = model or fal.DEFAULT_MODEL
        family = fal.FAL_FAMILIES.get(family_id)
        if family is None:
            raise VideoRequestError("invalid_model")
        if refs is not None:
            raise VideoRequestError("unsupported_video_option")
        modality = "image" if image is not None else "text"
        if not family[f"{modality}_endpoint"]:
            raise VideoRequestError("modality_unsupported")
        resolved = (family.get("resolution_aliases") or {}).get(resolution.lower(), resolution)
        span = family["durations"]
        clamped = fal._clamp_duration(family, duration, resolved) if span and duration is not None else None
        billed = clamped if clamped is not None else (max(span) if span else 10)
        body.update(model=family_id, duration=duration, billed_seconds=int(billed))
        if negative is not None:
            body["negative_prompt"] = negative
        if seed is not None:
            body["seed"] = seed
        if audio is not None:
            body["audio"] = audio
    elif name == "xai":
        xai = plugin_module("xai")
        # Upstream's xAI generate takes no seed, negative prompt or audio toggle.
        if negative is not None or audio is not None or seed is not None:
            raise VideoRequestError("unsupported_video_option")
        if image is not None and refs is not None:
            raise VideoRequestError("conflicting_inputs")
        # Upstream falls back to its defaults for values it does not take; so does the card.
        if resolution not in xai.VALID_RESOLUTIONS:
            body["resolution"] = xai.DEFAULT_RESOLUTION
        if aspect not in xai.VALID_ASPECT_RATIOS:
            body["aspect_ratio"] = xai.DEFAULT_ASPECT_RATIO
        modality = "reference" if refs else ("image" if image is not None else "text")
        # Upstream: the configured model is not an agent override (explicit_model=False);
        # Nerva passes the model the owner approved and the plugin resolves it the same way.
        resolved = xai._resolve_model_for_modality(model, modality=modality, explicit_model=False)
        if refs and resolved != xai.DEFAULT_TEXT_TO_VIDEO_MODEL:
            resolved = xai.DEFAULT_TEXT_TO_VIDEO_MODEL
        seconds = xai._clamp_duration(duration, has_reference_images=bool(refs))
        body.update(model=resolved, duration=seconds, billed_seconds=seconds)
    else:  # deepinfra: no live catalog in Nerva, so the model is named
        if model is None:
            raise VideoRequestError("model_required")
        if refs is not None or audio is not None:
            raise VideoRequestError("unsupported_video_option")
        if duration is None:              # the endpoint's own default is not documented
            raise VideoRequestError("duration_required")
        seconds = min(duration, 10)
        body.update(model=model, duration=(min(duration, 10) if duration is not None else None),
                    billed_seconds=seconds)
        if negative is not None:
            body["negative_prompt"] = negative
        if seed is not None:
            body["seed"] = seed
    body["images"] = images
    estimate(body)                       # refuses a price Nerva has not verified
    return body


__all__ = ["ADOPTED_VIDEO_PLUGINS", "ASPECT_RATIOS", "CHOICE_ENV", "DEEPINFRA_PRICES", "FAL_PRICES",
           "PRICE_SOURCE", "PROVIDERS", "RESOLUTIONS", "XAI_PRICES", "VideoProviderRow", "VideoRequestError", "chosen",
           "estimate", "key_set", "normalize_request", "provider", "registry"]
