"""The desktop driver factory, the shared driver policy, and screen capture.

Three things are being pinned, and they are the ones that would let a real host
driver do something the owner did not agree to:

  · the factory NEVER silently downgrades. A host that cannot be driven gets a
    named refusal from the host-probe vocabulary — never a driver that quietly
    does less than it claims;
  · the shared policy in `base` is where every bound lives, so an adapter cannot
    widen a limit by forgetting to check, and `requires_kernel` cannot be omitted;
  · Wayland capture refuses X11 grabbers outright, because under Xwayland they
    return a black frame rather than an error, and a black screenshot that looks
    like a screenshot is worse than no screenshot at all.

Hermetic on a headless runner: every platform library is injected, and the real
probe is used only to prove the honest refusal on this very box.
"""

from __future__ import annotations

import pytest

from agents.core.desktop_drivers import (
    MAX_SCREENSHOT_BYTES,
    AccessibilityDriver,
    DriverError,
    DriverUnavailable,
    available_backends,
    capture,
    describe_host,
    driver_for_host,
    find_element,
    normalize_element,
)
from agents.core.desktop_drivers.capture import backend_for
from agents.core.host_probe import REFUSAL_REASONS, HostProbe

pytestmark = pytest.mark.asyncio


def _probe(platform="linux-x11", refusals=(), **over):
    base = {
        "platform": platform,
        "deps": {"pywinauto": False, "uiautomation": False, "pyobjc": False,
                 "gi_atspi": True, "libei": False, "playwright": False, "mss": True},
        "permissions": {"accessibility_trusted": True},
        "refusals": tuple(refusals),
    }
    base.update(over)
    return HostProbe(**base)


class _Fake(AccessibilityDriver):
    """A driver whose seams the test owns, so the shared policy is what runs."""

    platform = "test"

    def __init__(self, elements=(), *, screenshot=b"PNG", **kw):
        super().__init__(**kw)
        self.clicks: list = []
        self.typed: list = []
        self._rows = list(elements)
        self._png = screenshot

    def _elements(self):
        return [(dict(row), row.get("name")) for row in self._rows]

    def _click(self, handle):
        self.clicks.append(handle)

    def _type(self, handle, text):
        self.typed.append((handle, text))

    def _screenshot(self):
        return self._png


def _rows(*names):
    return [{"name": n, "role": "button", "value": "", "text": "", "enabled": True}
            for n in names]


# ── the factory never downgrades silently ────────────────────────────────────

def test_this_headless_runner_is_refused_by_name_not_given_a_pretend_driver():
    """The real probe on this box. A driver here would be a lie about a machine
    with no display."""
    choice = driver_for_host()
    assert choice.ok is False
    assert choice.driver is None
    assert choice.reason == "desktop_platform_unsupported"
    assert choice.hint  # the probe's own sentence, for the owner to act on


def test_every_refusal_the_factory_emits_is_host_probe_vocabulary():
    """A reason the HUD cannot render is a reason nobody can act on."""
    for refusal in (
        "atspi_unavailable",
        "accessibility_permission_missing",
        "wayland_input_unavailable",
        "wayland_capture_unavailable",
        "desktop_dependency_unavailable",
    ):
        choice = driver_for_host(_probe(refusals=(refusal,)))
        assert choice.ok is False
        assert choice.reason in REFUSAL_REASONS
        assert choice.reason == refusal


def test_the_most_fundamental_refusal_is_the_one_reported():
    """Two blockers, one sentence: the owner reads the thing to fix first."""
    choice = driver_for_host(
        _probe(refusals=("desktop_dependency_unavailable", "atspi_unavailable"))
    )
    assert choice.reason == "atspi_unavailable"


def test_a_missing_vision_model_does_not_veto_an_accessibility_driver():
    """`local_vlm_not_proven_local` disables the visual FALLBACK, not the driver.
    Refusing the whole session for it would strand a perfectly good a11y route."""
    choice = driver_for_host(
        _probe(refusals=("local_vlm_not_proven_local",)),
        factories={"linux-x11": lambda: _Fake()},
    )
    assert choice.ok is True
    assert describe_host(_probe(refusals=("local_vlm_not_proven_local",)))[
        "visual_fallback"] is False


def test_a_clean_host_gets_the_adapter_for_its_platform():
    built = []
    choice = driver_for_host(
        _probe(platform="macos"),
        factories={"macos": lambda: built.append("macos") or _Fake()},
    )
    assert choice.ok is True and built == ["macos"]
    assert choice.platform == "macos"


def test_an_adapter_that_cannot_construct_is_a_refusal_not_a_crash():
    def _boom():
        raise DriverUnavailable("accessibility_permission_missing")

    choice = driver_for_host(_probe(platform="macos"), factories={"macos": _boom})
    assert choice.ok is False
    assert choice.reason == "accessibility_permission_missing"


def test_an_unexpected_adapter_error_still_refuses_by_name():
    def _boom():
        raise RuntimeError("something in pyobjc")

    choice = driver_for_host(_probe(platform="macos"), factories={"macos": _boom})
    assert choice.reason == "desktop_dependency_unavailable"


def test_an_unknown_refusal_word_cannot_be_constructed():
    """The vocabulary is closed on purpose — an ad-hoc reason has no hint and no
    HUD row, so it reaches the owner as noise."""
    with pytest.raises(ValueError):
        DriverUnavailable("something_went_wrong")


# ── the shared policy is where the bounds live ───────────────────────────────

def test_every_driver_requires_the_kernel_by_inheritance():
    """Set on the base class so a new adapter cannot omit it and thereby take the
    legacy direct path that skips kernel mediation."""
    assert AccessibilityDriver.requires_kernel is True
    assert _Fake().requires_kernel is True

    from agents.core.desktop_drivers.linux import LinuxDesktopDriver
    from agents.core.desktop_drivers.macos import MacDesktopDriver

    assert MacDesktopDriver.requires_kernel is True
    assert LinuxDesktopDriver.requires_kernel is True


async def test_an_unsupported_action_is_refused_before_any_host_call():
    driver = _Fake(_rows("Save"))
    result = await driver.perform("format_the_disk", {})
    assert result == {"ok": False, "reason": "unsupported_action",
                      "action": "format_the_disk"}
    assert driver.clicks == []


async def test_observe_answers_from_the_tree_and_never_takes_a_screenshot():
    """Pixels are the most sensitive thing here, so they are never incidental."""
    taken = []

    class _Watched(_Fake):
        def _screenshot(self):
            taken.append(1)
            return b"PNG"

    result = await _Watched(_rows("Save", "Cancel")).perform("observe", {})
    assert result["ok"] is True and result["source"] == "accessibility"
    assert [e["name"] for e in result["elements"]] == ["Save", "Cancel"]
    assert taken == []


async def test_a_mutation_matches_by_exact_name_only():
    """A substring match is fine for "where is Save"; for "click Save" on a screen
    that also holds "Save and delete" it is dangerous."""
    driver = _Fake(_rows("Save and delete"))
    assert (await driver.perform("click", {"name": "Save"}))["reason"] == "element_not_found"
    assert driver.clicks == []
    assert (await driver.perform("click", {"name": "Save and delete"}))["ok"] is True


async def test_a_mutation_re_snapshots_immediately_before_acting():
    """A handle from an earlier turn may now point at a different control."""
    driver = _Fake(_rows("Save"))
    snapshots = []

    original = driver._elements
    driver._elements = lambda: snapshots.append(1) or original()
    await driver.perform("click", {"name": "Save"})
    assert snapshots == [1]


async def test_a_disabled_element_is_not_clicked():
    driver = _Fake([{"name": "Save", "role": "button", "value": "", "text": "",
                     "enabled": False}])
    assert (await driver.perform("click", {"name": "Save"}))["reason"] == "element_disabled"
    assert driver.clicks == []


async def test_typed_text_is_capped_by_the_base_not_the_adapter(caplog):
    driver = _Fake(_rows("Field"), max_type_chars=10)
    result = await driver.perform("type", {"name": "Field", "text": "x" * 11})
    assert result["reason"] == "text_too_large"
    assert driver.typed == []


async def test_a_mutation_without_a_name_is_refused():
    driver = _Fake(_rows("Save"))
    assert (await driver.perform("click", {}))["reason"] == "named_element_required"
    assert (await driver.perform("type", {"name": "Save"}))["reason"] == "text_required"


async def test_an_oversized_screenshot_is_refused_rather_than_truncated():
    """A truncated PNG is a corrupt PNG. Cropping silently would hand a model a
    picture of something other than the screen it asked about."""
    driver = _Fake(screenshot=b"x" * (MAX_SCREENSHOT_BYTES + 1))
    assert (await driver.perform("screenshot", {}))["reason"] == "screenshot_too_large"


async def test_a_host_exception_never_reaches_the_caller_as_text():
    """Host errors carry window titles and paths."""
    class _Leaky(_Fake):
        def _elements(self):
            raise RuntimeError("failed reading /home/andrei/Documents/passwords.kdbx")

    result = await _Leaky().perform("observe", {})
    assert result == {"ok": False, "reason": "driver_error", "action": "observe"}
    assert "passwords" not in str(result)


async def test_element_text_is_bounded_before_a_model_ever_sees_it():
    row = normalize_element({"name": "x" * 5_000, "role": "button"}, 0)
    assert len(row["name"]) == 200


# ── the visual fallback is a fallback, and only if it is local ───────────────

async def test_locate_uses_the_tree_first_and_the_locator_never(caplog):
    calls = []

    class _Locator:
        proven_local = True

        def locate(self, query, image):
            calls.append(query)
            return {"ok": True, "point": [1, 2]}

    driver = _Fake(_rows("Save"), locator=_Locator())
    result = await driver.perform("locate", {"query": "Save"})
    assert result["source"] == "accessibility"
    assert calls == []


async def test_the_visual_fallback_runs_only_after_the_tree_fails():
    class _Locator:
        proven_local = True

        def locate(self, query, image):
            return {"ok": True, "point": [10, 20], "confidence": 0.9}

    driver = _Fake(_rows("Save"), locator=_Locator())
    result = await driver.perform("locate", {"query": "Publish"})
    assert result["source"] == "visual"
    assert result["point"] == [10, 20]


async def test_a_locator_that_cannot_prove_it_is_local_is_refused_by_name():
    """A cloud vision model here would ship the owner's screen off the box."""
    class _Cloud:
        proven_local = False

        def locate(self, query, image):  # pragma: no cover - must never run
            raise AssertionError("a non-local locator must never be called")

    driver = _Fake(_rows("Save"), locator=_Cloud())
    result = await driver.perform("locate", {"query": "Publish"})
    assert result["reason"] == "local_vlm_not_proven_local"


async def test_a_locator_returning_junk_is_refused_rather_than_clicked_on():
    class _Junk:
        proven_local = True

        def locate(self, query, image):
            return {"ok": True, "point": "somewhere near the top"}

    driver = _Fake(_rows("Save"), locator=_Junk())
    assert (await driver.perform("locate", {"query": "Publish"}))[
        "reason"] == "invalid_locator_result"


# ── capture ──────────────────────────────────────────────────────────────────

def test_wayland_refuses_x11_grabbers_outright():
    """Under Xwayland they return a black frame instead of an error — an image
    the caller believes."""
    assert backend_for("linux-wayland").__name__ == "_grim_capture"
    assert backend_for("linux-x11").__name__ == "_mss_capture"
    assert "mss" in available_backends("linux-wayland")["x11_only_backends_refused_on_wayland"]


def test_capture_on_a_platform_with_no_route_refuses_by_name():
    with pytest.raises(DriverUnavailable) as exc:
        backend_for("headless")
    assert exc.value.reason == "desktop_platform_unsupported"


def test_capture_refuses_an_empty_frame_rather_than_returning_it():
    with pytest.raises(DriverError) as exc:
        capture("linux-x11", backend=lambda: b"")
    assert exc.value.reason == "screenshot_failed"


def test_capture_refuses_a_non_image_result():
    with pytest.raises(DriverError):
        capture("linux-x11", backend=lambda: {"png": "later"})


def test_capture_caps_bytes_before_returning_them():
    with pytest.raises(DriverError) as exc:
        capture("linux-x11", backend=lambda: b"x" * (MAX_SCREENSHOT_BYTES + 1))
    assert exc.value.reason == "screenshot_too_large"


def test_available_backends_reports_what_would_actually_be_used():
    report = available_backends("linux-wayland")
    assert report["platform"] == "linux-wayland"
    # this runner has neither, and the honest answer is "none", not a guess
    assert report["selected"] in {"", "grim"}


# ── matching ─────────────────────────────────────────────────────────────────

def test_find_element_prefers_an_exact_name_over_a_substring():
    snapshot = [
        ({"name": "Save and delete", "role": "", "value": "", "text": ""}, "A"),
        ({"name": "Save", "role": "", "value": "", "text": ""}, "B"),
    ]
    assert find_element(snapshot, "Save", exact=False)[1] == "B"
    assert find_element(snapshot, "Save", exact=True)[1] == "B"


def test_find_element_falls_back_to_role_and_text_only_when_inexact():
    snapshot = [({"name": "", "role": "button", "value": "Publish now", "text": ""}, "A")]
    assert find_element(snapshot, "publish", exact=False)[1] == "A"
    assert find_element(snapshot, "publish", exact=True) is None


def test_an_empty_query_matches_nothing():
    snapshot = [({"name": "Save", "role": "", "value": "", "text": ""}, "A")]
    assert find_element(snapshot, "   ", exact=False) is None
