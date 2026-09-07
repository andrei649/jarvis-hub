"""capture.py — take a screenshot, or refuse by name.

Screen pixels are the most sensitive thing the operator can read: a screenshot may
contain a password manager, a bank page, a private message. So capture is its own
module with its own rules, rather than a helper inside each adapter:

* **The route is chosen per platform, never guessed.** X11 grabbers (mss, Pillow's
  ImageGrab) silently produce black frames on Wayland instead of failing, which is
  worse than an error — the caller gets an image and believes it. On Wayland only
  the portal or ``grim`` is accepted, and their absence is
  ``wayland_capture_unavailable``.
* **Nothing prompts.** A capture backend that would raise a permission dialog is
  not used; on macOS an absent Screen Recording grant is a named refusal, because
  Nerva never asks the OS for a permission on the owner's behalf.
* **Bytes are capped before they are returned**, not after they are encoded: a
  4K multi-monitor PNG can be tens of megabytes, and base64 grows it by a third.
* **A missing library is a refusal, not a crash**, using the host-probe vocabulary
  so the HUD renders the same sentence the probe would.

Everything is imported lazily inside the backend that needs it.
"""

from __future__ import annotations

import logging
import shutil
import subprocess  # nosec B404 - fixed argv, no shell; the Wayland grim capture path
from collections.abc import Callable
from typing import Any

from agents.core.desktop_drivers.base import MAX_SCREENSHOT_BYTES, DriverError, DriverUnavailable

logger = logging.getLogger("jarvis.desktop_drivers")

_GRIM_TIMEOUT_S = 10.0

# X11-only grabbers. Named here so the Wayland path can refuse them explicitly
# rather than "supporting" them into a black rectangle.
X11_ONLY_BACKENDS = ("mss", "PIL.ImageGrab")


def _mss_capture() -> bytes:
    """X11 / Windows / macOS: the mss grabber, whole virtual screen."""
    try:
        import mss  # type: ignore[import-not-found]
        import mss.tools  # type: ignore[import-not-found]
    except ImportError as exc:
        raise DriverUnavailable("desktop_dependency_unavailable") from exc
    with mss.mss() as sct:
        frame = sct.grab(sct.monitors[0])
        return mss.tools.to_png(frame.rgb, frame.size)


def _grim_capture() -> bytes:
    """Wayland: ``grim -`` writes a PNG to stdout. Fixed argv, no shell."""
    binary = shutil.which("grim")
    if not binary:
        raise DriverUnavailable("wayland_capture_unavailable")
    try:
        completed = subprocess.run(  # nosec B603 - fixed argv from shutil.which, no shell
            [binary, "-"],
            capture_output=True,
            timeout=_GRIM_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise DriverError("screenshot_failed") from exc
    if completed.returncode != 0 or not completed.stdout:
        # grim's stderr can name the output and the compositor; do not surface it.
        raise DriverError("screenshot_failed")
    return completed.stdout


def _macos_capture() -> bytes:
    """macOS: mss works once Screen Recording is granted, and only then.

    The grant is checked by the host probe, never requested here — asking the OS
    on the owner's behalf is exactly the prompt this module refuses to raise.
    """
    return _mss_capture()


def backend_for(platform: str) -> Callable[[], bytes]:
    """The capture callable for a detected session, or a refusal.

    Wayland deliberately does NOT fall back to an X11 grabber: under Xwayland
    those return a black frame rather than an error, and a black screenshot that
    looks like a screenshot is worse than no screenshot at all.
    """
    if platform == "linux-wayland":
        return _grim_capture
    if platform in {"linux-x11", "windows"}:
        return _mss_capture
    if platform == "macos":
        return _macos_capture
    raise DriverUnavailable("desktop_platform_unsupported")


def capture(platform: str, *, backend: Callable[[], bytes] | None = None) -> bytes:
    """Grab the screen for *platform*, bounded. Refuses rather than truncating.

    A truncated PNG is a corrupt PNG, so an oversized capture is refused with
    ``screenshot_too_large`` and the caller decides — cropping silently would hand
    a model a picture of something other than the screen it asked about.
    """
    take = backend or backend_for(platform)
    image = take()
    if not isinstance(image, (bytes, bytearray)):
        raise DriverError("screenshot_failed")
    if not image:
        raise DriverError("screenshot_failed")
    if len(image) > MAX_SCREENSHOT_BYTES:
        raise DriverError("screenshot_too_large")
    return bytes(image)


def available_backends(platform: str) -> dict[str, Any]:
    """What capture routes exist here — for the probe panel and the doctor."""
    have_mss = False
    try:
        import mss  # type: ignore[import-not-found]  # noqa: F401

        have_mss = True
    except ImportError:
        have_mss = False
    return {
        "platform": platform,
        "mss": have_mss,
        "grim": bool(shutil.which("grim")),
        # The one that will actually be used, or "" when none can be.
        "selected": (
            "grim" if platform == "linux-wayland" and shutil.which("grim")
            else "mss" if platform in {"linux-x11", "windows", "macos"} and have_mss
            else ""
        ),
        "x11_only_backends_refused_on_wayland": list(X11_ONLY_BACKENDS),
    }


__all__ = [
    "X11_ONLY_BACKENDS",
    "available_backends",
    "backend_for",
    "capture",
]
