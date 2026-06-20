#!/usr/bin/env python3
"""update_thirdparty.py — auto-update variant of the third-party drift check.

Where `check_thirdparty_drift.py` only *detects* that a vendored / doc-pinned
source is behind upstream and files a tracking issue, this script *acts*: for a
single manifest entry (by ``--name``) it re-vendors the source from upstream and
bumps ``pinned_version`` in `.github/third-party-manifest.json` to the latest
release. The workflow `.github/workflows/thirdparty-autoupdate.yml` then opens a
PR for review.

Two kinds of source (mirrors the manifest's ``kind``):

  * **vendored** (e.g. superpowers): shallow-clone the upstream repo, replace the
    vendored dir, strip ``.git``, refresh the mirrored license file if the entry
    records one (``license``), and bump the pin + ``version_source`` file so the
    consistency check stays green.
  * **doc-pinned** (e.g. codebase-memory-mcp): no tree to re-vendor — just bump
    the pin, and rewrite a plain version string in the doc if one is present.

The clone/replace step goes through an **injectable runner** (``VendorRunner``)
so the core logic — which entry, what new version, the manifest rewrite — is
unit-testable OFFLINE without network or git. The default runner shells out to
``git``; tests pass a fake.

Latest-version fetch and version compare are reused from
`check_thirdparty_drift.py` (imported, not duplicated).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Callable, Optional

# Reuse the drift checker's helpers (latest-version fetch + version compare)
# instead of duplicating them. `scripts/` is on sys.path when run as a script;
# add it explicitly so this resolves in both cases without importing twice.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_thirdparty_drift as drift  # noqa: E402

_REPO_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_MANIFEST = _REPO_ROOT / ".github" / "third-party-manifest.json"


# ── injectable vendor runner ──────────────────────────────────────────────────

# A VendorRunner clones `repo` (at `version`, or default branch) into `dest`,
# leaving a clean working tree with NO `.git`. The real one shells out to git;
# tests inject a fake so the rewrite logic runs offline.
VendorRunner = Callable[[str, str, Path], None]


def git_vendor_runner(repo: str, version: str, dest: Path) -> None:
    """Default runner: shallow-clone ``owner/name`` into *dest*, strip ``.git``.

    Tries the tag matching *version* (with and without a ``v`` prefix); falls
    back to the default branch so a missing/odd tag still re-vendors.
    """
    url = f"https://github.com/{repo}"
    candidates = [version, f"v{version}", version.lstrip("vV")] if version else []
    # de-dupe while preserving order
    seen: set[str] = set()
    refs = [c for c in candidates if c and not (c in seen or seen.add(c))]

    with tempfile.TemporaryDirectory() as tmp:
        clone_dir = Path(tmp) / "clone"
        cloned = False
        for ref in refs:
            try:
                subprocess.run(
                    ["git", "clone", "--depth", "1", "--branch", ref, url, str(clone_dir)],
                    check=True, capture_output=True, text=True,
                )
                cloned = True
                break
            except subprocess.CalledProcessError:
                if clone_dir.exists():
                    shutil.rmtree(clone_dir)
        if not cloned:
            subprocess.run(
                ["git", "clone", "--depth", "1", url, str(clone_dir)],
                check=True, capture_output=True, text=True,
            )
        shutil.rmtree(clone_dir / ".git", ignore_errors=True)
        if dest.exists():
            shutil.rmtree(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(clone_dir), str(dest))


# ── manifest helpers ──────────────────────────────────────────────────────────

def find_entry(manifest: dict, name: str) -> Optional[dict]:
    for e in manifest.get("sources", []):
        if e.get("name") == name:
            return e
    return None


def _write_manifest(path: Path, manifest: dict) -> None:
    # Match the committed file's 2-space indent + trailing newline.
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def _set_version_source_file(entry: dict, repo_root: Path, new_version: str) -> bool:
    """Rewrite the version recorded inside the vendored ``version_source`` file
    so the offline consistency check matches the new pin. Returns True if the
    file was changed."""
    vs = entry.get("version_source")
    if not vs:
        return False
    path = repo_root / vs["file"]
    if not path.exists():
        return False
    text = path.read_text(encoding="utf-8")
    if "json_key" in vs:
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return False
        if str(data.get(vs["json_key"])) == new_version:
            return False
        data[vs["json_key"]] = new_version
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        return True
    if "regex" in vs:
        m = re.search(vs["regex"], text)
        if not m or m.group(1) == new_version:
            return False
        start, end = m.start(1), m.end(1)
        path.write_text(text[:start] + new_version + text[end:], encoding="utf-8")
        return True
    return False


def _refresh_license(entry: dict, repo_root: Path) -> bool:
    """Copy the vendored upstream LICENSE to the mirrored path the manifest
    records (``license``). No-op if the entry records no license. Returns True
    if a file was written."""
    mirror_rel = entry.get("license")
    if not mirror_rel:
        return False
    vendored_dir = repo_root / entry["path"]
    src = None
    for cand in ("LICENSE", "LICENSE.txt", "LICENSE.md", "COPYING"):
        p = vendored_dir / cand
        if p.exists():
            src = p
            break
    if src is None:
        return False
    dest = repo_root / mirror_rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dest)
    return True


def _bump_doc_version(entry: dict, repo_root: Path, old: str, new: str) -> bool:
    """For a doc-pinned source: if the update_doc contains a plain version
    string equal to the old pin, rewrite it to the new pin. Returns True if the
    doc was changed. Best-effort — the manifest pin is the source of truth."""
    doc_rel = entry.get("update_doc")
    if not doc_rel or not old:
        return False
    path = repo_root / doc_rel
    if not path.exists():
        return False
    text = path.read_text(encoding="utf-8")
    # Replace the exact version token only on word boundaries, so "0.8.1" does
    # not clobber "10.8.10" etc.
    pattern = re.compile(r"(?<![\w.])" + re.escape(old) + r"(?![\w.])")
    if not pattern.search(text):
        return False
    new_text = pattern.sub(new, text)
    if new_text == text:
        return False
    path.write_text(new_text, encoding="utf-8")
    return True


# ── core ──────────────────────────────────────────────────────────────────────

def update_entry(
    manifest: dict,
    name: str,
    new_version: str,
    repo_root: Path,
    runner: VendorRunner,
    manifest_path: Optional[Path] = None,
) -> dict:
    """Re-vendor (if vendored) and bump the pin for one manifest entry.

    Pure-ish core: the only side effects are filesystem writes under *repo_root*
    and the one network/git call delegated to *runner*. Returns a summary dict.
    Raises KeyError if *name* isn't in the manifest.
    """
    entry = find_entry(manifest, name)
    if entry is None:
        raise KeyError(f"no manifest entry named {name!r}")

    old_version = entry.get("pinned_version")
    summary = {
        "name": name,
        "old_version": old_version,
        "new_version": new_version,
        "vendored": False,
        "license_refreshed": False,
        "version_source_updated": False,
        "doc_updated": False,
        "manifest_updated": False,
        "changed": False,
    }

    # No-op when already current.
    if not drift.is_behind(old_version, new_version):
        return summary

    is_vendored = str(entry.get("kind", "")).startswith("vendored")

    if is_vendored:
        dest = repo_root / entry["path"]
        runner(entry["repo"], new_version, dest)
        summary["vendored"] = True
        summary["license_refreshed"] = _refresh_license(entry, repo_root)
        # The re-vendor may already carry the right version_source value; only
        # rewrite if it doesn't, so the consistency check matches the new pin.
        summary["version_source_updated"] = _set_version_source_file(
            entry, repo_root, new_version
        )
    else:
        summary["doc_updated"] = _bump_doc_version(
            entry, repo_root, old_version, new_version
        )

    # Bump the pin in-place and persist the manifest.
    entry["pinned_version"] = new_version
    summary["manifest_updated"] = True
    if manifest_path is not None:
        _write_manifest(manifest_path, manifest)

    summary["changed"] = True
    return summary


# ── CLI ───────────────────────────────────────────────────────────────────────

def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--name", required=True, help="manifest entry name to update")
    ap.add_argument("--manifest", default=str(_DEFAULT_MANIFEST))
    ap.add_argument(
        "--version",
        help="target version (default: latest upstream GitHub release/tag)",
    )
    ap.add_argument("--json", action="store_true", help="emit the summary as JSON")
    args = ap.parse_args(argv)

    manifest_path = Path(args.manifest)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    repo_root = manifest_path.resolve().parent.parent

    entry = find_entry(manifest, args.name)
    if entry is None:
        print(f"✗ no manifest entry named {args.name!r}", file=sys.stderr)
        return 2

    new_version = args.version
    if not new_version:
        token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        latest = drift.fetch_latest_github(entry["repo"], token)
        if not latest:
            print(f"✗ could not determine latest version for {entry['repo']}", file=sys.stderr)
            return 2
        new_version = latest.lstrip("vV")

    summary = update_entry(
        manifest, args.name, new_version, repo_root,
        runner=git_vendor_runner, manifest_path=manifest_path,
    )

    if args.json:
        print(json.dumps(summary, indent=2))
    elif summary["changed"]:
        print(
            f"✓ {args.name}: {summary['old_version']} → {summary['new_version']}"
            f" (vendored={summary['vendored']}, license={summary['license_refreshed']},"
            f" doc={summary['doc_updated']})"
        )
    else:
        print(f"= {args.name}: already at {summary['old_version']}, nothing to do")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
