#!/usr/bin/env python3
"""reconcile_drift_alert.py — close the third-party drift alert once it is fixed.

`.github/workflows/thirdparty-drift.yml` opens (and refreshes) a tracking issue
when a vendored / doc-pinned source falls behind upstream, but nothing ever
closes it, so a resolved alert stays open and stops being read.

Two guards make that safe:

* **Positive evidence only.** Closing happens on
  `check_thirdparty_drift.drift_resolved()` — every tracked source checked and
  `ok` — never on "the run found no DRIFT lines", which is also what a crash, an
  empty manifest or a GitHub API outage look like.
* **Only this workflow's own issues.** An issue is closable only when its title,
  hidden marker, footer and bot authorship all match what the workflow writes. A
  hand-filed or hand-edited issue is never touched.

The GitHub calls are injected, so every decision here is unit-tested offline.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from check_thirdparty_drift import drift_resolved  # noqa: E402

# These three must stay byte-identical to the strings the workflow writes;
# tests/test_thirdparty_drift_reconcile.py asserts they appear in the YAML.
ALERT_TITLE = "Third-party version drift detected"
AUTO_MARKER = "<!-- thirdparty-drift -->"
AUTO_FOOTER = "_Auto-managed by `.github/workflows/thirdparty-drift.yml`._"

_BOT_LOGIN = "github-actions[bot]"

CommentFn = Callable[[int, str], None]
CloseFn = Callable[[int], None]


def is_auto_managed(issue: dict) -> bool:
    """True only for an open issue this workflow itself created and still owns."""
    if not isinstance(issue, dict) or issue.get("pull_request") is not None:
        return False
    body = issue.get("body")
    if not isinstance(body, str):
        return False
    login = (issue.get("user") or {}).get("login")
    return (
        issue.get("title") == ALERT_TITLE
        and AUTO_MARKER in body
        and AUTO_FOOTER in body
        and login == _BOT_LOGIN
    )


def select_closable(issues: list[dict], resolved: bool) -> list[dict]:
    """The subset of OPEN issues this run may close (empty unless resolved)."""
    if not resolved:
        return []
    return [issue for issue in issues if is_auto_managed(issue)]


def _closing_comment(table: str, run_url: str) -> str:
    lines = [
        "Drift resolved — every tracked third-party source matches upstream"
        f" as of run {run_url or '(local run)'}.",
        "",
        "```",
        (table or "").strip() or "(no table captured)",
        "```",
        "",
        AUTO_FOOTER,
    ]
    return "\n".join(lines)


def reconcile(
    results: list[dict],
    issues: list[dict],
    comment_fn: CommentFn,
    close_fn: CloseFn,
    *,
    table: str = "",
    run_url: str = "",
) -> list[int]:
    """Comment then close every auto-managed alert, once drift is truly resolved.

    Returns the issue numbers closed. Commenting first leaves the audit trail on
    the issue even if the close call fails.
    """
    closable = select_closable(issues, drift_resolved(results))
    closed: list[int] = []
    body = _closing_comment(table, run_url)
    for issue in closable:
        number = int(issue["number"])
        comment_fn(number, body)
        close_fn(number)
        closed.append(number)
    return closed


# ── GitHub client (only used from the workflow) ───────────────────────────────

def _api(path: str, token: str, *, method: str = "GET", payload: dict | None = None):
    request = urllib.request.Request(
        f"https://api.github.com{path}",
        method=method,
        data=json.dumps(payload).encode("utf-8") if payload is not None else None,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "nerva-thirdparty-drift",
            "X-GitHub-Api-Version": "2022-11-28",
            **({"Content-Type": "application/json"} if payload is not None else {}),
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        raw = response.read().decode("utf-8")
    return json.loads(raw) if raw else None


def list_open_issues(repo: str, token: str) -> list[dict]:
    issues: list[dict] = []
    page = 1
    while page <= 10:
        batch = _api(f"/repos/{repo}/issues?state=open&per_page=100&page={page}", token)
        if not batch:
            break
        issues.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    return issues


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--drift-json", default="drift.json")
    parser.add_argument("--drift-table", default="drift.txt")
    parser.add_argument("--dry-run", action="store_true",
                        help="print the plan; make no GitHub writes")
    args = parser.parse_args(argv)

    try:
        results = json.loads(Path(args.drift_json).read_text(encoding="utf-8"))
    except Exception as exc:
        # A missing or malformed drift.json is exactly the "no evidence" case.
        print(f"cannot read {args.drift_json}: {exc} — leaving any alert open", file=sys.stderr)
        return 0
    if not isinstance(results, list):
        print(f"{args.drift_json} is not a result list — leaving any alert open", file=sys.stderr)
        return 0

    try:
        table = Path(args.drift_table).read_text(encoding="utf-8")
    except OSError:
        table = ""

    if not drift_resolved(results):
        print("drift is not resolved — nothing to close")
        return 0

    repo = os.environ.get("GITHUB_REPOSITORY", "")
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or ""
    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    run_url = f"{server}/{repo}/actions/runs/{run_id}" if repo and run_id else ""

    if args.dry_run or not (repo and token):
        issues = [] if (args.dry_run and not (repo and token)) else list_open_issues(repo, token)
        planned = [int(i["number"]) for i in select_closable(issues, True)]
        print(f"dry-run: would close {planned or 'nothing'}")
        return 0

    try:
        issues = list_open_issues(repo, token)
    except urllib.error.URLError as exc:
        print(f"cannot list issues: {exc}", file=sys.stderr)
        return 0

    def comment_fn(number: int, body: str) -> None:
        _api(f"/repos/{repo}/issues/{number}/comments", token,
             method="POST", payload={"body": body})

    def close_fn(number: int) -> None:
        _api(f"/repos/{repo}/issues/{number}", token,
             method="PATCH", payload={"state": "closed", "state_reason": "completed"})

    closed = reconcile(results, issues, comment_fn, close_fn, table=table, run_url=run_url)
    print(f"closed: {closed or 'nothing'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
