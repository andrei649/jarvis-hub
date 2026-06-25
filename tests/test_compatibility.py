"""H23.14 — versioning/compatibility contract is real and self-consistent.

These turn the docs into a *gate* (not just prose), so the version drift CDX-5
flagged can't silently come back: the supported-versions matrices in
COMPATIBILITY.md and SECURITY.md must reference the current major.minor derived
from the single-sourced `agents.__version__`. Bump the version and forget to
update the docs → CI fails here. Also asserts the deploy service templates (H23.15)
exist and are wired to the H23.11 operability knobs.
"""
import re
import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents import __version__

_SEMVER = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")


def _read(rel):
    return (repo_root / rel).read_text(encoding="utf-8")


def _major_minor():
    return ".".join(__version__.split(".")[:2])


# ── version single-source (CDX-4) ─────────────────────────────────────────────

def test_version_is_valid_semver():
    assert _SEMVER.match(__version__), f"__version__ {__version__!r} is not semver"


def test_app_reports_the_single_sourced_version():
    from agents import web
    assert web.app.version == __version__  # no stale hard-coded "0.5.0-beta"


# ── COMPATIBILITY.md (H23.14) ─────────────────────────────────────────────────

def test_compatibility_doc_exists_and_tracks_version():
    doc = _read("docs/COMPATIBILITY.md")
    mm = _major_minor()
    assert f"{mm}.x" in doc, (
        f"docs/COMPATIBILITY.md must reference the current line {mm}.x "
        f"(version is {__version__}); update the supported-versions table on a bump."
    )


def test_compatibility_doc_states_python_floor():
    # The platform matrix must keep the real Python floor (numpy>=2.5 → 3.12+).
    assert "3.12" in _read("docs/COMPATIBILITY.md")


def test_compatibility_doc_covers_the_contract():
    doc = _read("docs/COMPATIBILITY.md").lower()
    for term in ("semantic versioning", "deprecat", "platform"):
        assert term in doc, f"COMPATIBILITY.md missing the '{term}' section"


# ── SECURITY.md is real, not the GitHub placeholder (H23.14 / H23.19) ─────────

def test_security_md_is_not_the_github_placeholder():
    sec = _read("SECURITY.md")
    assert "Use this section to tell people" not in sec, "SECURITY.md is still the template"
    assert "5.1.x" not in sec, "SECURITY.md still has placeholder version rows"


def test_security_md_supported_line_tracks_version():
    assert f"{_major_minor()}.x" in _read("SECURITY.md")


# ── deploy service templates (H23.15) ─────────────────────────────────────────

def test_systemd_unit_present_and_wired():
    unit = _read("deploy/systemd/jarvis-hub.service")
    assert "ExecStart=" in unit and "serve.py" in unit
    assert "JARVIS_SHUTDOWN_TIMEOUT" in unit          # ties to H23.11 graceful stop
    assert "KillSignal=SIGTERM" in unit
    assert "[Install]" in unit


def test_windows_service_script_present():
    ps1 = _read("deploy/windows/install-service.ps1")
    assert "serve.py" in ps1
    assert "JARVIS_SHUTDOWN_TIMEOUT" in ps1
