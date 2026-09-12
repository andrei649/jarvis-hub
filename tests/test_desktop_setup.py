"""The path from "I installed Nerva" to "it can drive this machine".

The desktop operator has been built for a while — governed drivers for Windows,
macOS and X11/Wayland, an injection classifier, a visual-grounding fallback —
and the inventory row H044 says what was missing: not the capability, the
permission-grant UX. These pin that path, and in particular the two places it
would be tempting to lie: an unestablished fact must never render as readiness,
and "open the settings pane" must never become a launch-anything seam.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

from agents.core.desktop_setup import (
    BLOCKED,
    NOT_APPLICABLE,
    READY,
    UNKNOWN,
    Opener,
    SetupPlan,
    Step,
    open_settings,
    openers_for,
    plan,
    render,
)
from agents.core.host_probe import DEP_NAMES, HostProbe


def probe(platform, *, deps=(), permissions=None, refusals=(), binaries=None):
    return HostProbe(
        platform=platform,
        deps={name: name in deps for name in DEP_NAMES},
        permissions=dict(permissions or {}),
        refusals=tuple(refusals),
        binaries=dict(binaries or {}),
    )


MAC_READY = {"accessibility_trusted": True, "screen_capture": True, "process_elevated": False}


# ── the order is the information ────────────────────────────────────────────


def test_the_steps_come_in_the_order_the_owner_can_act_on_them():
    report = plan(probe("macos", deps=("pyobjc",), permissions=MAC_READY))
    assert [s.key for s in report.steps] == [
        "display", "dependencies", "accessibility", "screen_recording", "elevation",
    ]


def test_a_host_with_no_display_reports_that_and_stops_there():
    report = plan(probe("headless"))
    assert [s.key for s in report.steps] == ["display"]
    assert report.blocking.state == BLOCKED
    assert report.ready is False
    # No point listing libraries and permissions for a machine with no desktop.
    assert report.step("dependencies") is None


def test_an_unknown_platform_is_refused_rather_than_guessed():
    report = plan(probe("linux-wayland"))  # no deps, no portal
    assert report.ready is False
    assert plan(probe("headless")).blocking.hint


# ── an unestablished fact is never readiness ────────────────────────────────


def test_a_permission_the_probe_could_not_establish_reads_unknown_not_granted():
    report = plan(probe("macos", deps=("pyobjc",), permissions={
        "accessibility_trusted": True, "screen_capture": None, "process_elevated": False,
    }))
    screen = report.step("screen_recording")
    assert screen.state == UNKNOWN
    assert screen.state != READY
    assert report.ready is False, "unknown must not be reported as ready"
    assert report.blocking.key == "screen_recording"


def test_every_permission_granted_and_unelevated_is_the_only_ready_macos():
    report = plan(probe("macos", deps=("pyobjc",), permissions=MAC_READY))
    assert report.ready is True
    assert report.blocking is None
    assert report.unresolved == ()


def test_a_denied_permission_is_blocked_and_carries_its_hint_and_pane():
    report = plan(probe("macos", deps=("pyobjc",), permissions={
        "accessibility_trusted": False, "screen_capture": True, "process_elevated": False,
    }))
    step = report.step("accessibility")
    assert step.state == BLOCKED
    assert "Privacy & Security" in step.hint
    assert step.opener is not None


def test_elevation_is_tri_state_too():
    unelevated = plan(probe("macos", deps=("pyobjc",), permissions=MAC_READY))
    assert unelevated.step("elevation").state == READY

    elevated = plan(probe("macos", deps=("pyobjc",), permissions={
        **MAC_READY, "process_elevated": True,
    }))
    assert elevated.step("elevation").state == BLOCKED
    assert elevated.ready is False

    unknown = plan(probe("macos", deps=("pyobjc",), permissions={
        "accessibility_trusted": True, "screen_capture": True,
    }))
    assert unknown.step("elevation").state == UNKNOWN
    assert unknown.ready is False


# ── per-platform dependency truth ───────────────────────────────────────────


@pytest.mark.parametrize("installed", [("pywinauto",), ("uiautomation",),
                                       ("pywinauto", "uiautomation")])
def test_windows_is_satisfied_by_either_adapter(installed):
    report = plan(probe("windows", deps=installed, permissions={"process_elevated": False}))
    assert report.step("dependencies").state == READY
    assert report.ready is True


def test_windows_with_neither_adapter_names_what_is_missing():
    report = plan(probe("windows", permissions={"process_elevated": False}))
    step = report.step("dependencies")
    assert step.state == BLOCKED
    assert "pywinauto" in step.detail and "uiautomation" in step.detail


def test_a_platform_with_no_owner_grant_says_so_instead_of_inventing_one():
    report = plan(probe("linux-x11", deps=("gi_atspi",), permissions={"process_elevated": False}))
    assert report.step("os_permission").state == NOT_APPLICABLE
    assert report.ready is True


# ── Wayland reads the probe's own verdict, not a second weaker copy ─────────


def test_wayland_takes_the_probe_refusals_as_the_established_fact():
    blocked = plan(probe(
        "linux-wayland", deps=("gi_atspi", "libei"),
        permissions={"process_elevated": False},
        refusals=("wayland_input_unavailable", "wayland_capture_unavailable"),
    ))
    assert blocked.step("wayland_input").state == BLOCKED
    assert blocked.step("wayland_capture").state == BLOCKED

    clear = plan(probe(
        "linux-wayland", deps=("gi_atspi", "libei"),
        permissions={"process_elevated": False, "portal_remote_desktop_version": 2},
    ))
    assert clear.step("wayland_input").state == READY
    assert clear.step("wayland_capture").state == READY


def test_an_x11_only_grabber_is_not_a_wayland_capture_route():
    # mss is X11-only — the repo's own refusal hint says so. Installing it must
    # not flip Wayland capture to ready when the probe refused it.
    report = plan(probe(
        "linux-wayland", deps=("gi_atspi", "libei", "mss"),
        permissions={"process_elevated": False},
        refusals=("wayland_capture_unavailable",),
    ))
    assert report.step("wayland_capture").state == BLOCKED


# ── opening a pane is not granting, and not a launch-anything seam ──────────


class _Spawn:
    def __init__(self, raises=None):
        self.calls: list[list[str]] = []
        self._raises = raises

    def __call__(self, argv):
        self.calls.append(list(argv))
        if self._raises is not None:
            raise self._raises


def _mac_plan():
    return plan(probe("macos", deps=("pyobjc",), permissions={
        "accessibility_trusted": False, "screen_capture": False, "process_elevated": False,
    }))


def test_opening_the_pane_runs_exactly_the_fixed_argv_and_claims_nothing_more():
    spawn = _Spawn()
    step = _mac_plan().step("accessibility")
    result = open_settings(step, spawn=spawn)
    assert result["ok"] is True
    assert spawn.calls == [[
        "open",
        "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility",
    ]]
    # It must not report the permission as granted — it was not.
    assert "granted" not in result.get("note", "")
    assert result.get("granted") is None


def test_a_step_with_no_pane_refuses_by_name_and_never_spawns():
    spawn = _Spawn()
    step = plan(probe("headless")).step("display")
    assert open_settings(step, spawn=spawn)["reason"] == "no_opener_for_step"
    assert spawn.calls == []


def test_an_opener_that_is_not_the_tables_own_is_refused_even_when_it_looks_identical():
    """The identity check is the seam: a value-equal forgery must not execute."""
    spawn = _Spawn()
    real = openers_for(["macos.accessibility"])["macos.accessibility"]
    twin = Opener(argv=tuple(real.argv), label=real.label)
    assert twin == real, "the forgery is equal by value; only identity separates them"
    forged = Step("accessibility", "Accessibility", BLOCKED, "x", opener=twin)
    assert open_settings(forged, spawn=spawn)["reason"] == "opener_not_in_table"
    assert spawn.calls == []


def test_an_attacker_supplied_argv_can_never_ride_this_seam():
    spawn = _Spawn()
    evil = Step("accessibility", "Accessibility", BLOCKED, "x",
                opener=Opener(argv=("curl", "http://evil/x"), label="totally fine"))
    assert open_settings(evil, spawn=spawn)["reason"] == "opener_not_in_table"
    assert spawn.calls == []


@pytest.mark.parametrize("error,reason", [
    (FileNotFoundError(), "opener_not_found"),
    (OSError(), "opener_failed"),
])
def test_a_failing_pane_launch_is_a_named_reason_not_an_exception(error, reason):
    step = _mac_plan().step("accessibility")
    assert open_settings(step, spawn=_Spawn(raises=error))["reason"] == reason


def test_open_settings_refuses_anything_that_is_not_a_step():
    with pytest.raises(TypeError):
        open_settings({"key": "accessibility"}, spawn=_Spawn())


# ── what the owner reads ────────────────────────────────────────────────────


def test_the_render_leads_with_the_one_thing_to_do_next():
    text = render(_mac_plan())
    assert "not ready" in text
    assert "next: Accessibility permission" in text
    assert "nerva desktop grant accessibility" in text
    assert "Privacy & Security" in text


def test_a_ready_host_has_no_next_step_to_show():
    text = render(plan(probe("macos", deps=("pyobjc",), permissions=MAC_READY)))
    assert "ready" in text
    assert "next:" not in text


def test_the_plan_serializes_without_leaking_argv():
    payload = plan(probe("macos", deps=("pyobjc",), permissions=MAC_READY)).to_dict()
    assert payload["ready"] is True
    assert payload["platform"] == "macos"
    # The pane is named for a human; the argv stays inside the module.
    assert "x-apple.systempreferences" not in str(payload)


@pytest.mark.parametrize("bad", [None, {"platform": "macos"}, "macos"])
def test_plan_and_render_refuse_the_wrong_shape(bad):
    with pytest.raises(TypeError):
        plan(bad)
    with pytest.raises(TypeError):
        render(bad)


def test_a_step_must_carry_a_key_a_title_and_a_known_state():
    with pytest.raises(ValueError):
        Step("", "Title", READY, "")
    with pytest.raises(ValueError):
        Step("key", "", READY, "")
    with pytest.raises(ValueError):
        Step("key", "Title", "probably", "")


def test_the_plan_view_is_a_copy_not_the_table():
    first = openers_for()
    first["macos.accessibility"] = Opener(argv=("rm", "-rf", "/"), label="x")
    assert openers_for()["macos.accessibility"].argv[0] == "open"


# ── the command a person actually types ─────────────────────────────────────


def _run(argv):
    import io

    from agents.cli.nerva import Context, main

    out, err = io.StringIO(), io.StringIO()
    code = main(argv, context=Context(out=out, err=err, environ={}))
    return code, out.getvalue(), err.getvalue()


def test_nerva_desktop_status_reports_this_host():
    code, out, _ = _run(["desktop", "status"])
    assert "desktop operator on" in out
    # This test host is headless, so the honest answer is "not ready" and a
    # non-zero exit — a script can branch on it.
    assert code != 0
    assert "not ready" in out


def test_nerva_desktop_status_json_is_machine_readable():
    import json

    code, out, _ = _run(["desktop", "status", "--json"])
    payload = json.loads(out)
    assert payload["platform"]
    assert isinstance(payload["steps"], list)
    assert payload["ready"] is False
    assert code != 0


def test_granting_an_unknown_step_lists_the_steps_this_host_has():
    code, _, err = _run(["desktop", "grant", "not-a-step"])
    assert code == 2
    assert "no step named" in err
    assert "display" in err


def test_granting_a_step_with_no_pane_says_so():
    code, _, err = _run(["desktop", "grant", "display"])
    assert code != 0
    assert "no_opener_for_step" in err


def test_the_module_can_actually_be_run_as_a_command():
    """`python -m agents.cli.nerva` used to import, run nothing and exit 0."""
    proc = subprocess.run(
        [sys.executable, "-m", "agents.cli.nerva", "desktop", "status"],
        capture_output=True, text=True, timeout=120,
    )
    assert "desktop operator on" in proc.stdout, proc.stderr[-400:]
    assert proc.returncode != 0


def test_a_bare_invocation_prints_usage_rather_than_nothing():
    proc = subprocess.run(
        [sys.executable, "-m", "agents.cli.nerva"],
        capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode != 0
    assert "usage:" in (proc.stdout + proc.stderr).lower()


def test_the_setup_plan_type_is_exported_for_callers():
    assert isinstance(plan(probe("headless")), SetupPlan)
