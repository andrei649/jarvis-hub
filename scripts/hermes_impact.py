"""Map changed paths to recorded Hermes evidence and declared dependencies.

This selects review work, never changes a verdict or accepts an impact proposal.
Unmapped paths are explicit unknowns. No changed file contents are read here.
The caller supplies records already validated by hermes_status.
"""

from __future__ import annotations

import hashlib
import json
import subprocess  # nosec B404 -- fixed Git argv, no shell
from collections import defaultdict
from pathlib import Path


def _git(root: Path, args: list[str], runner) -> bytes:
    result = runner(["git", "-C", str(root), *args], capture_output=True,
                    check=False, timeout=20)
    if result.returncode:
        raise RuntimeError("cannot resolve base or inspect changed paths in the application repository")
    return result.stdout


def build_map(root: Path, rows: list[dict], data: dict, *, base: str = "HEAD",
              limit: int = 25, runner=subprocess.run) -> dict:
    """Return bounded review candidates plus complete aggregate/unknown counts."""
    if not 1 <= limit <= 697:
        raise ValueError("limit must be in 1..697")
    root = Path(root)
    sha = _git(root, ["rev-parse", "--verify", "--end-of-options", f"{base}^{{commit}}"], runner)
    sha_text = sha.decode("ascii").strip()
    changed = _git(root, ["diff", "--name-only", "--diff-filter=ACMRD", "--no-renames",
                          "-z", sha_text, "--"], runner)
    new = _git(root, ["ls-files", "--others", "--exclude-standard", "-z"], runner)
    paths = sorted({name.decode("utf-8") for name in (changed + b"\0" + new).split(b"\0") if name})

    index: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    by_id = {row["id"]: row for row in rows}
    for row in rows:
        for entry in row.get("evidence", []):
            index[entry["path"]][row["id"]].add("recorded_evidence")
    # Reviewed dependency manifests supplement the original source pins. They
    # are candidates even when a later change has made a receipt stale.
    current_reviews = {
        review["id"]: hashlib.sha256(json.dumps(
            review, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
        ).encode("utf-8")).hexdigest()
        for review in data.get("reviews", [])
    }
    for field in ("impact_receipts", "local_receipts", "acceptance"):
        for receipt in data.get(field, []):
            ident = receipt["id"]
            if ident not in by_id:
                continue
            # Superseded contract receipts remain history, not dependencies of
            # a replacement review. Keep stale fingerprints for current reviews
            # selectable so a changed dependency can be investigated.
            recorded_hash = receipt.get("previous_review_sha256", receipt.get("review_sha256"))
            if recorded_hash and ident in current_reviews and recorded_hash != current_reviews[ident]:
                continue
            for path in receipt.get("paths", []):
                index[path][ident].add("declared_dependency")

    selected: dict[str, dict] = {}
    unknown = []
    bookkeeping = []
    for path in paths:
        matches = index.get(path)
        if not matches:
            if path in {"docs/hermes/assessment.json", "HERMES_STATUS.md", "docs/HERMES_CAPABILITIES.md"}:
                bookkeeping.append(path)
            else:
                unknown.append(path)
            continue
        for ident, kinds in matches.items():
            row = by_id[ident]
            candidate = selected.setdefault(ident, {
                "id": ident, "recorded_status": row.get("recorded_status", row["status"]),
                "verification_status": row.get("freshness", "unknown"), "changes": [],
            })
            candidate["changes"].append({"path": path, "mapping": sorted(kinds)})
    affected = [selected[ident] for ident in sorted(selected)]
    return {
        "base": {"ref": base, "sha": sha_text}, "changed_path_count": len(paths),
        "affected_count": len(affected), "affected": affected[:limit],
        "has_more": len(affected) > limit, "unknown_count": len(unknown),
        "unknown_paths": unknown[:limit], "unknown_has_more": len(unknown) > limit,
        "bookkeeping_paths": bookkeeping, "credit_changed": False,
        "decision": "review_required",
        "next": "Inspect each affected contract with hermes_restamp impact/cite and its dependency paths. "
                "Unmapped paths need dependency review; no classification here restores credit.",
    }
