#!/usr/bin/env python3
"""check_thirdparty_drift.py — flag vendored / doc-pinned third-party sources
that have drifted behind their latest upstream release.

Covers what Dependabot can't see: code we *vendor* into the repo (e.g. the
superpowers plugin under `.claude/plugins/`) and tools we *doc-pin* (e.g. the
codebase-memory-mcp binary). Package deps (pip/npm/github-actions) stay with
Dependabot — see `.github/dependabot.yml`.

Manifest: `.github/third-party-manifest.json`.
Every tracked source must declare a literal boolean ``auto_update``. ``false``
keeps drift reporting enabled while excluding the source from mutation.

Two checks:
  * consistency (offline, deterministic): the manifest's `pinned_version`
    matches the version recorded in the vendored file (`version_source`). Catches
    a re-vendor that forgot to update the manifest. Always fails the run on
    mismatch.
  * drift (network): `pinned_version` vs the latest upstream GitHub release/tag.
    Advisory by default; `--fail-on-drift` makes it exit non-zero.

The GitHub fetcher is injectable so the logic is unit-tested offline.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable, Optional

_REPO_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_MANIFEST = _REPO_ROOT / ".github" / "third-party-manifest.json"

Fetcher = Callable[[str], Optional[str]]


# ── version helpers ───────────────────────────────────────────────────────────

def _parse(v: Optional[str]) -> Optional[tuple[int, ...]]:
    if not v:
        return None
    core = v.strip().lstrip("vV").split("-")[0].split("+")[0]
    try:
        return tuple(int(p) for p in core.split("."))
    except ValueError:
        return None


def is_behind(pinned: Optional[str], latest: Optional[str]) -> bool:
    """True if *pinned* is older than *latest*. Falls back to string-inequality
    when either tag isn't semver-parseable (so non-semver drift still surfaces)."""
    p, l = _parse(pinned), _parse(latest)
    if p is None or l is None:
        return bool(latest) and (pinned or "").lstrip("vV") != (latest or "").lstrip("vV")
    n = max(len(p), len(l))
    p += (0,) * (n - len(p))
    l += (0,) * (n - len(l))
    return p < l


# ── sources ───────────────────────────────────────────────────────────────────

def read_source_version(version_source: dict, repo_root: Path) -> Optional[str]:
    """Extract the version recorded in a vendored file (JSON key or regex)."""
    path = repo_root / version_source["file"]
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8")
    if "json_key" in version_source:
        try:
            return str(json.loads(text).get(version_source["json_key"]))
        except json.JSONDecodeError:
            return None
    if "regex" in version_source:
        m = re.search(version_source["regex"], text)
        return m.group(1) if m else None
    return None


def fetch_latest_github(repo: str, token: Optional[str] = None) -> Optional[str]:
    """Latest release tag for owner/name, falling back to the newest tag."""
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "jarvis-drift-check"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    for url in (
        f"https://api.github.com/repos/{repo}/releases/latest",
        f"https://api.github.com/repos/{repo}/tags",
    ):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=15) as r:
                data = json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 404:  # no releases → try tags
                continue
            raise
        if isinstance(data, dict) and data.get("tag_name"):
            return data["tag_name"]
        if isinstance(data, list) and data:
            return data[0].get("name")
    return None


# ── core ────────────────────────────────────────────────────────────────────

def require_auto_update_policy(entry: dict) -> bool:
    """Return the required literal-boolean update policy for one source."""
    if "auto_update" not in entry:
        name = entry.get("name", "<unnamed>")
        raise ValueError(
            f"manifest source {name!r} must declare boolean auto_update"
        )
    policy = entry["auto_update"]
    if type(policy) is not bool:
        name = entry.get("name", "<unnamed>")
        raise ValueError(
            f"manifest source {name!r} must declare boolean auto_update"
        )
    return policy


def validate_auto_update_policies(manifest: dict) -> list[tuple[dict, bool]]:
    """Validate all tracked sources before any source-specific work begins."""
    return [
        (entry, require_auto_update_policy(entry))
        for entry in manifest.get("sources", [])
    ]


def run_checks(manifest: dict, fetch: Fetcher, repo_root: Path) -> list[dict]:
    sources = validate_auto_update_policies(manifest)
    results = []
    for e, auto_update in sources:
        pinned = e.get("pinned_version")
        row = {"name": e["name"], "repo": e.get("repo"), "pinned": pinned,
               "latest": None, "consistency": "n/a", "drift": "skipped",
               "auto_update": auto_update}

        vs = e.get("version_source")
        if vs:
            recorded = read_source_version(vs, repo_root)
            row["recorded"] = recorded
            row["consistency"] = "ok" if recorded == pinned else "MISMATCH"

        if e.get("track_drift") and e.get("repo"):
            try:
                latest = fetch(e["repo"])
                row["latest"] = latest
                row["drift"] = "DRIFT" if is_behind(pinned, latest) else "ok"
            except Exception as ex:  # network/API errors are non-fatal
                row["drift"] = f"error: {ex}"
        results.append(row)
    return results


def auto_update_candidates(results: list[dict]) -> list[str]:
    """Return drifted source names explicitly eligible for scheduled mutation."""
    return [
        row["name"]
        for row in results
        if row.get("drift") == "DRIFT" and row.get("auto_update") is True
    ]


def format_table(results: list[dict]) -> str:
    lines = [f"{'source':<22} {'pinned':<10} {'latest':<12} {'consistency':<12} "
             f"{'update':<8} drift",
             "-" * 79]
    for r in results:
        update_mode = "auto" if r["auto_update"] else "manual"
        lines.append(f"{r['name']:<22} {str(r['pinned']):<10} "
                     f"{str(r['latest'] or '-'):<12} {r['consistency']:<12} "
                     f"{update_mode:<8} {r['drift']}")
    return "\n".join(lines)


def summarize(results: list[dict]) -> tuple[bool, bool]:
    """Return (has_consistency_mismatch, has_drift)."""
    mismatch = any(r["consistency"] == "MISMATCH" for r in results)
    drift = any(r["drift"] == "DRIFT" for r in results)
    return mismatch, drift


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--manifest", default=str(_DEFAULT_MANIFEST))
    ap.add_argument("--consistency", action="store_true",
                    help="offline only: manifest vs vendored file version")
    ap.add_argument("--fail-on-drift", action="store_true",
                    help="exit non-zero if any source is behind upstream")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    repo_root = Path(args.manifest).resolve().parent.parent

    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if args.consistency:
        fetch: Fetcher = lambda repo: None  # noqa: E731 - no network in consistency mode
        manifest = {"sources": [{**s, "track_drift": False} for s in manifest.get("sources", [])]}
    else:
        fetch = lambda repo: fetch_latest_github(repo, token)  # noqa: E731

    results = run_checks(manifest, fetch, repo_root)
    print(json.dumps(results, indent=2) if args.json else format_table(results))

    mismatch, drift = summarize(results)
    if mismatch:
        print("\n✗ manifest is stale vs a vendored file (consistency MISMATCH).", file=sys.stderr)
        return 1
    if drift and args.fail_on_drift:
        print("\n✗ a third-party source is behind upstream (see DRIFT above).", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
