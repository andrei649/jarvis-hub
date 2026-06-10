"""One-shot migration for the SOUL templating change (2026-06-10).

The repo now ships *generic* SOUL.md templates; personalized souls live in
``agents/<id>/SOUL.local.md`` (gitignored) and override the template at load
time. Run this ONCE on the deployed machine after pulling the templating
commit: it restores the pre-templating personalized souls from git history
into SOUL.local.md, so the running instance keeps its personality.

    python scripts/restore_personal_souls.py [--sha <commit>] [--force]

Only writes an overlay where the historical soul differs from the current
template; never overwrites an existing SOUL.local.md unless --force.
"""

import argparse
import subprocess
from pathlib import Path

# Last commit whose SOUL.md files were the personalized originals.
DEFAULT_SHA = "9c3ee48cb09c24de784f68ee35fb7087b9470df0"

REPO = Path(__file__).resolve().parent.parent


def git_show(sha: str, path: str) -> str | None:
    try:
        out = subprocess.run(
            ["git", "show", f"{sha}:{path}"],
            cwd=REPO, capture_output=True, text=True, timeout=30,
        )
        return out.stdout if out.returncode == 0 else None
    except Exception:
        return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sha", default=DEFAULT_SHA, help="commit to restore souls from")
    ap.add_argument("--force", action="store_true", help="overwrite existing SOUL.local.md")
    args = ap.parse_args()

    restored, skipped = [], []
    for soul in sorted(
        list((REPO / "agents").glob("*/SOUL.md"))
        + list((REPO / "agents").glob("*/HEARTBEAT.md"))
    ):
        agent_dir = soul.parent
        rel = soul.relative_to(REPO).as_posix()
        historical = git_show(args.sha, rel)
        if historical is None:
            continue  # agent didn't exist at that commit
        if historical == soul.read_text(encoding="utf-8"):
            continue  # template identical to history — no personalization to save
        local = agent_dir / (soul.stem + ".local.md")
        if local.exists() and not args.force:
            skipped.append(f"{agent_dir.name}/{soul.stem}")
            continue
        local.write_text(historical, encoding="utf-8")
        restored.append(f"{agent_dir.name}/{soul.stem}")

    print(f"Restored {len(restored)} personalized soul/heartbeat file(s): {', '.join(restored) or '—'}")
    if skipped:
        print(f"Skipped (SOUL.local.md already exists; use --force): {', '.join(skipped)}")
    print("Restart the server so agents reload their souls.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
