"""desktop_drivers — the real host drivers behind the governed desktop operator.

`GovernedDesktop` owns the policy: approval, kernel mediation, injection
classification of what it observes. This package owns only *actuation* — the
platform-specific "how do I read this window and press this button" — and is
reached exclusively through `DesktopActionExecutor`, because every driver here
inherits ``requires_kernel = True``.

    from agents.core.desktop_drivers import driver_for_host

    choice = driver_for_host()
    if choice.ok:
        ...                     # choice.driver is ready
    else:
        ...                     # choice.reason / choice.hint say why not

The layout:

* ``base`` — the shared observe/act policy and every bound. Accessibility first,
  pixels last; a mutation re-snapshots and matches by exact name immediately
  before acting.
* ``platform`` — the factory. Chooses from the host probe's verdict, so the HUD
  and the driver can never disagree about what this machine can do, and never
  downgrades silently to a weaker route.
* ``capture`` — screenshots, per platform. Wayland refuses X11 grabbers outright
  because they return black frames rather than errors.
* ``macos`` / ``linux`` — the adapters. Windows already had one
  (``desktop_host.WindowsDesktopDriver``) and keeps it; the factory serves all
  three.

Importing this package imports no platform library: every adapter resolves its
dependencies inside the call that needs them, so a headless CI runner can import
everything and get clean refusals.
"""

from agents.core.desktop_drivers.base import (
    MAX_ELEMENTS,
    MAX_SCREENSHOT_BYTES,
    MAX_TYPE_CHARS,
    SUPPORTED_ACTIONS,
    AccessibilityDriver,
    DriverError,
    DriverUnavailable,
    UnavailableDriver,
    find_element,
    normalize_element,
)
from agents.core.desktop_drivers.capture import available_backends, backend_for, capture
from agents.core.desktop_drivers.platform import (
    DRIVER_PLATFORMS,
    DriverChoice,
    describe_host,
    driver_for_host,
)

__all__ = [
    "DRIVER_PLATFORMS",
    "MAX_ELEMENTS",
    "MAX_SCREENSHOT_BYTES",
    "MAX_TYPE_CHARS",
    "SUPPORTED_ACTIONS",
    "AccessibilityDriver",
    "DriverChoice",
    "DriverError",
    "DriverUnavailable",
    "UnavailableDriver",
    "available_backends",
    "backend_for",
    "capture",
    "describe_host",
    "driver_for_host",
    "find_element",
    "normalize_element",
]
