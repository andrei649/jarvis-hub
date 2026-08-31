"""No second, dead installer ships under agents/_system/ (DRA-48).

`agents/_system/install.sh` was a 49-line echo-only stub from the pre-rename
"Cabinet v0.1.0" era that announced the product as non-functional ("Installer
not yet active — core Python modules are still WIP") while the repo's real
installer sits at the root. Nothing imported or invoked it. It is deleted; these
guards keep it — and anything like it — from coming back.
"""
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

_INACTIVE_MARKERS = ("not yet active", "disabled until", "still wip")


def test_agents_system_holds_only_the_live_roster_file():
    names = sorted(p.name for p in (REPO / "agents/_system").iterdir() if p.is_file())
    assert names == ["agents.yaml"], (
        f"agents/_system/ should hold only the roster the code loads; found {names}"
    )


def test_no_shipped_shell_script_advertises_itself_as_inactive():
    tracked = subprocess.run(
        ["git", "ls-files", "*.sh"],
        cwd=REPO, capture_output=True, text=True, check=True,
    ).stdout.split()
    offenders = []
    for rel in tracked:
        path = REPO / rel
        if not path.exists():
            continue
        body = path.read_text(encoding="utf-8", errors="replace").lower()
        if any(marker in body for marker in _INACTIVE_MARKERS):
            offenders.append(rel)
    assert offenders == [], (
        f"shipped shell scripts announce themselves as non-functional: {offenders}"
    )
