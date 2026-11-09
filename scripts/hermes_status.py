#!/usr/bin/env python3
"""Reproducible code-equivalence status over the frozen 697-capability inventory.

The dated research ledger is immutable input, not a completion checklist.
Reviews are additive. Partial work, skips and changed evidence never count as done.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess  # nosec B404 -- fixed read-only Git argv, no shell
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
LEDGER = "docs/research/2026-09-07-hermes-absorption-ledger.json"
ASSESSMENT = "docs/hermes/assessment.json"
STATES = ("equivalent", "partial", "missing", "excluded", "needs_review")
DIMENSIONS = ("runtime", "platform", "provider")
LABELS = dict(zip(STATES, ("Echivalent", "Parțial", "Lipsă", "Exclus intenționat", "De reverificat"), strict=True))


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def file_digest(path: Path) -> str:
    """Bind UTF-8 source with universal newlines so Windows and Linux agree."""
    return hashlib.sha256(path.read_text(encoding="utf-8").encode("utf-8")).hexdigest()


def load(root: Path | None = None) -> tuple[dict, dict]:
    root = REPO if root is None else root
    return tuple(json.loads((root / path).read_text(encoding="utf-8"))
                 for path in (LEDGER, ASSESSMENT))


class GitTree:
    """Read one committed tree without changing this checkout or its index."""

    def __init__(self, root: Path, ref: str) -> None:
        result = subprocess.run(  # noqa: S603  # nosec B603, B607 -- fixed Git verb; ref follows --end-of-options
            ["git", "-C", str(root), "rev-parse", "--verify", "--end-of-options", f"{ref}^{{commit}}"],
            capture_output=True, check=False)
        _require(result.returncode == 0, f"unknown commit ref: {ref}")
        self.sha = result.stdout.decode("ascii").strip()
        self.root = root
        self._cache: dict[str, str | None] = {}

    def read_utf8(self, name: str) -> str | None:
        if name not in self._cache:
            result = subprocess.run(  # noqa: S603  # nosec B603, B607 -- fixed Git verb; object uses resolved commit SHA
                ["git", "-C", str(self.root), "show", f"{self.sha}:{name}"],
                capture_output=True, check=False)
            self._cache[name] = (result.stdout.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
                                 if result.returncode == 0 else None)
        return self._cache[name]

    def prefetch(self, names: set[str]) -> None:
        """Fetch all pinned blobs in two git calls, avoiding one process per evidence file."""
        listing = subprocess.run(  # noqa: S603  # nosec B603, B607 -- fixed read-only Git argv; resolved commit SHA
            ["git", "-C", str(self.root), "ls-tree", "-r", "-z", self.sha],
            capture_output=True, check=True).stdout
        blobs = {}
        for entry in listing.split(b"\0"):
            if not entry:
                continue
            meta, name = entry.split(b"\t", 1)
            mode, kind, sha = meta.split()
            path = name.decode("utf-8")
            if path in names and mode != b"120000" and kind == b"blob":
                blobs[path] = sha
        wanted = list(dict.fromkeys(blobs.values()))
        if wanted:
            output = subprocess.run(  # noqa: S603  # nosec B603, B607 -- fixed Git argv; object hashes enter stdin
                ["git", "-C", str(self.root), "cat-file", "--batch"],
                input=b"".join(sha + b"\n" for sha in wanted), capture_output=True, check=True).stdout
            contents: dict[bytes, str] = {}
            pos = 0
            for sha in wanted:
                end = output.index(b"\n", pos)
                header = output[pos:end].split()
                _require(len(header) == 3 and header[0] == sha and header[1] == b"blob",
                         "git blob batch mismatch")
                size = int(header[2])
                contents[sha] = output[end + 1:end + 1 + size].decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
                pos = end + size + 2
            for name, sha in blobs.items():
                self._cache[name] = contents[sha]
        for name in names - blobs.keys():
            self._cache[name] = None


def load_ref(root: Path, ref: str) -> tuple[dict, dict, GitTree]:
    tree = GitTree(root, ref)
    records = [tree.read_utf8(name) for name in (LEDGER, ASSESSMENT)]
    _require(all(record is not None for record in records), "commit lacks Hermes inventory or assessment")
    ledger, data = json.loads(records[0]), json.loads(records[1])
    paths = {entry["path"] for item in data["reviews"] for entry in item["evidence"]}
    paths.update(path for receipt in data.get("impact_receipts", []) for path in receipt["paths"])
    paths.update(path for receipt in data.get("acceptance", []) for path in receipt["paths"])
    tree.prefetch(paths)
    return ledger, data, tree


def worktree_provenance(root: Path) -> tuple[str, bool]:
    """Report HEAD and dirty state without reading arbitrary untracked file bytes."""
    def run(*args: str) -> bytes:
        result = subprocess.run(  # noqa: S603  # nosec B603, B607 -- fixed metadata-only Git argv; no shell
            ["git", "-C", str(root), *args], capture_output=True, check=False)
        _require(result.returncode == 0, f"git {args[0]} failed: {result.stderr.decode('utf-8', 'replace')}")
        return result.stdout

    return run("rev-parse", "--verify", "HEAD").decode("ascii").strip(), bool(run("status", "--porcelain", "-z"))


def _tracked_environment_example(root: Path, name: str, tree: GitTree | None) -> bool:
    """The root public template is source evidence; arbitrary env files are not."""
    if name != ".env.example":
        return False
    if tree is not None:
        return tree.read_utf8(name) is not None
    result = subprocess.run(  # noqa: S603  # nosec B603, B607 -- fixed metadata-only Git argv, no shell
        ["git", "-C", str(root), "ls-files", "--error-unmatch", "--", ".env.example"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    return result.returncode == 0


def manifest_fingerprint(root: Path, paths: list[str], *, tree: GitTree | None = None) -> str:
    """Hash only explicitly reviewed relative evidence/dependency paths."""
    _require(isinstance(paths, list) and len(paths) == len(set(paths)),
             "invalid reviewed path manifest")
    manifest = []
    for name in sorted(paths):
        _require(_text(name) and "\\" not in name and ":" not in name
                 and not PurePosixPath(name).is_absolute()
                 and all(part not in {"", ".", ".."} for part in name.split("/")),
                 "invalid reviewed path manifest")
        _require(not any(part in {".git", ".venv", "node_modules", "__pycache__"}
                         for part in name.split("/"))
                 and (not any(part.startswith(".env") for part in name.split("/"))
                      or _tracked_environment_example(root, name, tree))
                 and not any(part in {"runtime", "cache", "secrets", ".secrets", "private", "recovery"}
                             for part in name.split("/")),
                 "private/runtime path in reviewed manifest")
        if tree is None:
            path = root / name
            cursor = root
            linked = False
            for part in name.split("/"):
                cursor /= part
                linked = linked or cursor.is_symlink()
            if linked or not path.resolve().is_relative_to(root.resolve()):
                file_hash = "<symlink-or-escape>"
            elif path.is_file():
                try:
                    file_hash = file_digest(path)
                except UnicodeError:
                    file_hash = "<non-utf8>"
            else:
                file_hash = None
        else:
            content = tree.read_utf8(name)
            file_hash = hashlib.sha256(content.encode("utf-8")).hexdigest() if content is not None else None
        manifest.append({"path": name, "sha256": file_hash})
    return digest(manifest)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


CITATION = re.compile(r"([A-Za-z0-9_./-]+\.[A-Za-z0-9]{1,5}):(\d+)(?:-(\d+))?")


def _cited_lines(text: str, pinned: dict[str, list[str]]) -> list[str]:
    """Name the `path:line` pointers that miss the evidence the review pinned.

    The hashes pin a file's content, never the positions inside it: a review drafted
    against another checkout can publish numbers that fall past the end of the very
    file it hashed, or onto a blank line. Only paths this review pinned are checked —
    the rest name content nothing in the record froze, so nothing can verify them.
    """
    missed = []
    for match in CITATION.finditer(text):
        name, first = match.group(1), int(match.group(2))
        last = int(match.group(3) or first)
        found = [path for path in pinned if path == name or path.endswith("/" + name)]
        if len(found) != 1:
            continue
        lines = pinned[found[0]]
        if not (1 <= first <= last <= len(lines) and lines[first - 1].strip()):
            missed.append(match.group(0))
    return missed


def _evidence(root: Path, item: Any, tree: GitTree | None = None) -> tuple[str, bool]:
    _require(isinstance(item, dict) and set(item) == {"path", "sha256"}, "invalid evidence")
    name = item["path"]
    _require(_text(name) and "\\" not in name and ":" not in name
             and not PurePosixPath(name).is_absolute()
             and all(p not in {"", ".", ".."} for p in name.split("/")), "invalid evidence path")
    _require(isinstance(item["sha256"], str) and bool(re.fullmatch(r"[a-f0-9]{64}", item["sha256"])),
             "invalid evidence hash")
    path = (root / name).resolve() if tree is None else root / name
    if tree is None:
        _require(path.is_relative_to(root.resolve()), "evidence path leaves repository")
    if tree is None:
        matches = path.is_file() and file_digest(path) == item["sha256"]
    else:
        content = tree.read_utf8(name)
        matches = content is not None and hashlib.sha256(content.encode("utf-8")).hexdigest() == item["sha256"]
    return name, matches


def assess(ledger: dict, data: dict, root: Path | None = None, *, tree: GitTree | None = None) -> list[dict]:
    root = REPO if root is None else root
    _require(isinstance(data, dict), "invalid assessment schema")
    version = data.get("schema_version")
    _require(type(version) is int and version in {1, 2, 3}, "unsupported schema")
    fields = {
        "schema_version", "inventory_count", "inventory_sha256", "base_sha", "assessed_at", "reviews",
    }
    if version >= 2:
        fields.add("scope_reopenings")
    if version == 3:
        fields.update(("review_history", "impact_receipts", "acceptance", "local_receipts"))
    _require(set(data) == fields, "invalid assessment schema")
    caps = ledger.get("capabilities")
    _require(isinstance(caps, list) and type(data["inventory_count"]) is int
             and len(caps) == data["inventory_count"] and digest(ledger) == data["inventory_sha256"],
             "inventory changed: explicit identity migration and reassessment required")
    _require(isinstance(data["base_sha"], str) and bool(re.fullmatch(r"[a-f0-9]{40}", data["base_sha"])),
             "invalid inspected base")
    _require(isinstance(data["assessed_at"], str) and data["assessed_at"].endswith("Z"), "invalid timestamp")
    datetime.fromisoformat(data["assessed_at"].replace("Z", "+00:00"))
    _require(isinstance(data["reviews"], list), "reviews must be a list")
    rows = []
    for index, cap in enumerate(caps, 1):
        _require(isinstance(cap, dict) and _text(cap.get("name")) and _text(cap.get("cluster"))
                 and cap.get("decision") in {"keep", "skip", "copy", "update"}
                 and cap.get("nerva_state") in {"superior", "parity", "partial", "missing"}, "invalid inventory row")
        decision, old = cap["decision"], cap["nerva_state"]
        status = ("excluded" if decision == "skip" else
                  "equivalent" if decision == "keep" and old in {"parity", "superior"} else
                  "missing" if old == "missing" else "partial")
        rows.append({
            "id": f"H{index:03}", "name": cap["name"], "cluster": cap["cluster"].split(" (")[0],
            "decision": decision, "original_state": old, "status": status,
            "basis": "baseline_2026-09-07", "evidence": [],
            "summary": "Preluat din auditul 07.09; nereevaluat în această livrare.",
            "remaining": ("" if status in {"equivalent", "excluded"} else
                          "Reevaluare pe cod; cerințele și lipsurile sunt în rândul original."),
        })
    by_id = {row["id"]: row for row in rows}
    if version == 3:
        _require(isinstance(data["local_receipts"], list), "local receipts must be a list")
        for receipt in data["local_receipts"]:
            _require(isinstance(receipt, dict) and set(receipt) == {
                "id", "review_sha256", "head_sha", "paths", "untracked", "worktree_uncommitted",
                "source_fingerprint", "recorded_at",
            } and receipt["id"] in by_id and re.fullmatch(r"[a-f0-9]{64}", receipt["review_sha256"])
                and re.fullmatch(r"[a-f0-9]{40}", receipt["head_sha"])
                and re.fullmatch(r"[a-f0-9]{64}", receipt["source_fingerprint"])
                and isinstance(receipt["paths"], list) and bool(receipt["paths"])
                and isinstance(receipt["untracked"], list)
                and set(receipt["untracked"]).issubset(receipt["paths"])
                and receipt["worktree_uncommitted"] is True
                and _text(receipt["recorded_at"]) and receipt["recorded_at"].endswith("Z"),
                "invalid local receipt")
            datetime.fromisoformat(receipt["recorded_at"].replace("Z", "+00:00"))
        _require(isinstance(data["review_history"], list), "review history must be a list")
        for history in data["review_history"]:
            _require(isinstance(history, dict) and set(history) == {"review", "superseded_at", "replacement_sha256"},
                     "invalid review history")
            _require(isinstance(history["review"], dict) and
                     set(history["review"]) == {"id", "row_sha256", "status", "summary", "remaining", "evidence"}
                     and history["review"]["id"] in by_id, "invalid historical review")
            _require(_text(history["superseded_at"]) and history["superseded_at"].endswith("Z")
                     and re.fullmatch(r"[a-f0-9]{64}", history["replacement_sha256"]),
                     "invalid review history receipt")
            datetime.fromisoformat(history["superseded_at"].replace("Z", "+00:00"))
        _require(isinstance(data["impact_receipts"], list), "impact receipts must be a list")
        for receipt in data["impact_receipts"]:
            _require(isinstance(receipt, dict) and set(receipt) == {
                "id", "previous_review_sha256", "source_fingerprint", "paths", "head_sha", "worktree_uncommitted",
                "classification", "reason", "checks", "accepted_at",
            } and receipt["id"] in by_id and receipt["classification"] in {"moved", "unrelated"}
                and _text(receipt["reason"]) and isinstance(receipt["checks"], list)
                and bool(receipt["checks"]) and all(_text(check) for check in receipt["checks"])
                and type(receipt["worktree_uncommitted"]) is bool
                and isinstance(receipt["paths"], list) and bool(receipt["paths"])
                and all(isinstance(receipt[key], str) and re.fullmatch(rf"[a-f0-9]{{{n}}}", receipt[key])
                        for key, n in (
                    ("previous_review_sha256", 64), ("source_fingerprint", 64), ("head_sha", 40)))
                and _text(receipt["accepted_at"]) and receipt["accepted_at"].endswith("Z"),
                "invalid impact receipt")
            datetime.fromisoformat(receipt["accepted_at"].replace("Z", "+00:00"))
        _require(isinstance(data["acceptance"], list), "acceptance must be a list")
        for entry in data["acceptance"]:
            _require(isinstance(entry, dict) and set(entry) == {
                "id", "dimension", "state", "evidence", "checks", "environment", "artifact", "paths",
                "head_sha", "source_fingerprint", "worktree_uncommitted", "checked_at",
            } and entry["id"] in by_id and entry["dimension"] in DIMENSIONS
                and entry["state"] in {"required_pending", "verified", "blocked"}
                and isinstance(entry["evidence"], list) and all(_text(note) for note in entry["evidence"])
                and isinstance(entry["checks"], list) and all(_text(check) for check in entry["checks"])
                and isinstance(entry["environment"], str)
                and isinstance(entry["paths"], list)
                and re.fullmatch(r"[a-f0-9]{40}", entry["head_sha"])
                and re.fullmatch(r"[a-f0-9]{64}", entry["source_fingerprint"])
                and type(entry["worktree_uncommitted"]) is bool
                and _text(entry["checked_at"]) and entry["checked_at"].endswith("Z"),
                "invalid acceptance record")
            datetime.fromisoformat(entry["checked_at"].replace("Z", "+00:00"))
            artifact = entry["artifact"]
            _require(artifact is None or (isinstance(artifact, dict) and set(artifact) == {"path", "sha256"}
                     and _text(artifact["path"]) and re.fullmatch(r"[a-f0-9]{64}", artifact["sha256"])),
                     "invalid acceptance artifact")
            if entry["state"] == "verified":
                _require(bool(entry["evidence"]) and bool(entry["checks"]) and _text(entry["environment"])
                         and bool(entry["paths"]),
                         "verified acceptance needs evidence, executed checks and environment")
    reopenings = data.get("scope_reopenings", [])
    _require(isinstance(reopenings, list), "scope reopenings must be a list")
    reopened = set()
    for item in reopenings:
        _require(isinstance(item, dict) and set(item) == {
            "id", "row_sha256", "decided_at", "reason",
        }, "invalid scope reopening fields")
        ident = item["id"]
        _require(isinstance(ident, str) and ident in by_id, "unknown scope reopening id")
        _require(ident not in reopened, "duplicate scope reopening")
        row = by_id[ident]
        _require(row["decision"] == "skip", "only originally excluded rows can be reopened")
        _require(item["row_sha256"] == digest(caps[int(ident[1:]) - 1]),
                 "scope reopening identity mismatch")
        stamp = item["decided_at"]
        _require(_text(stamp) and "T" in stamp and stamp.endswith("Z"),
                 "invalid scope reopening timestamp")
        datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        _require(_text(item["reason"]), "scope reopening needs a reason")
        reopened.add(ident)
        row.update(status="needs_review", basis="scope_reopened",
                   summary=item["reason"],
                   remaining="Readmis în obiectivul de paritate completă; necesită evaluare pe cod și teste. "
                             "Vechiul verdict de excludere nu dovedește implementarea.")
    seen = set()
    fields = {"id", "row_sha256", "status", "summary", "remaining", "evidence"}
    for item in data["reviews"]:
        _require(isinstance(item, dict) and set(item) == fields, "invalid review fields")
        ident = item["id"]
        _require(isinstance(ident, str) and ident in by_id, "unknown review id")
        _require(ident not in seen, "duplicate review id")
        seen.add(ident)
        row = by_id[ident]
        _require(item["row_sha256"] == digest(caps[int(ident[1:]) - 1]), "review identity mismatch")
        _require(row["decision"] != "skip" or ident in reopened,
                 "excluded scope cannot be silently changed")
        _require(item["status"] in {"equivalent", "partial", "missing"}
                 and _text(item["summary"]) and isinstance(item["remaining"], str), "invalid review status/text")
        _require((item["status"] == "equivalent") == (item["remaining"] == ""),
                 "equivalent cannot have remaining work; unfinished rows must name it")
        _require(isinstance(item["evidence"], list) and bool(item["evidence"]), "review needs evidence")
        checked = [_evidence(root, entry, tree) for entry in item["evidence"]]
        names = [name for name, _ in checked]
        _require(len(set(names)) == len(names), "duplicate evidence")
        if item["status"] == "equivalent":
            code = any(name.startswith(("agents/", "frontend/src/", "mobile/src/", "desktop/"))
                       and "/test/" not in name for name in names)
            tests = any(name.startswith("tests/") or "/test/" in name for name in names)
            _require(code and tests, "equivalence needs source and tests")
        current = all(match for _, match in checked)
        if current:
            missed = _cited_lines(
                f"{item['summary']}\n{item['remaining']}",
                {name: (tree.read_utf8(name) if tree else (root / name).read_text(encoding="utf-8")).splitlines()
                 for name in names})
            _require(not missed, f"{ident}: citation does not resolve in pinned evidence: {', '.join(missed)}")
        receipts = [receipt for receipt in data.get("impact_receipts", []) if receipt["id"] == ident]
        accepted_impact = False
        if receipts:
            latest = receipts[-1]
            if latest["previous_review_sha256"] == digest(item):
                # Explicit dependency review remains binding even if a cited
                # file is later restored to its original recorded hash.
                scope_current = latest["source_fingerprint"] == manifest_fingerprint(
                    root, latest["paths"], tree=tree)
                accepted_impact = not current and scope_current
                current = current and scope_current
        missing = any(tree.read_utf8(name) is None if tree else not (root / name).is_file()
                      for name in names)
        row.update(status=item["status"] if current or accepted_impact else "needs_review",
                   basis="reviewed" if current else "impact_accepted" if accepted_impact else "stale_evidence",
                   evidence=item["evidence"], recorded_status=item["status"],
                   recorded_remaining=item["remaining"],
                   freshness="current" if current else "missing" if missing else "changed",
                   impact="accepted" if accepted_impact else "pending" if not current else "none",
                   summary=item["summary"], remaining=item["remaining"],
                   citation_note=("Citările din reviewul înregistrat sunt istorice; verifică relocările curente."
                                  if accepted_impact else ""),
                   verification_note=("" if current or accepted_impact else
                                      "Dovada s-a schimbat sau lipsește; reevaluează înainte de a număra rândul ca terminat."))
    for row in rows:
        row.setdefault("recorded_status", row["status"])
        row.setdefault("recorded_remaining", row["remaining"])
        row.setdefault("verification_note", "")
        row.setdefault("citation_note", "")
        row.setdefault("freshness", "unrecorded")
        row.setdefault("impact", "none")
        row["acceptance"] = dict.fromkeys(DIMENSIONS, "unrecorded")
        row["acceptance_freshness"] = dict.fromkeys(DIMENSIONS, "unrecorded")
        row["acceptance_scopes"] = {dimension: [] for dimension in DIMENSIONS}
        row["local_receipts"] = [receipt for receipt in data.get("local_receipts", [])
                                 if receipt["id"] == row["id"]]
    latest_scopes = {}
    for entry in data.get("acceptance", []):
        latest_scopes[(entry["id"], entry["dimension"], entry["environment"])] = entry
    for entry in latest_scopes.values():
        row = by_id[entry["id"]]
        fingerprint = manifest_fingerprint(root, entry["paths"], tree=tree)
        artifact = entry["artifact"]
        artifact_current = True
        if artifact is not None:
            path = Path(artifact["path"])
            artifact_current = (tree is None and path.is_file() and not path.is_symlink()
                                and hashlib.sha256(path.read_bytes()).hexdigest() == artifact["sha256"])
        freshness = "current" if entry["source_fingerprint"] == fingerprint and artifact_current else "stale"
        row["acceptance_scopes"][entry["dimension"]].append({
            "environment": entry["environment"], "state": entry["state"],
            "freshness": freshness, "checked_at": entry["checked_at"],
        })
    for row in rows:
        for dimension in DIMENSIONS:
            scopes = sorted(row["acceptance_scopes"][dimension], key=lambda item: item["environment"])
            row["acceptance_scopes"][dimension] = scopes
            if not scopes:
                continue
            states = {scope["state"] for scope in scopes}
            row["acceptance"][dimension] = ("blocked" if "blocked" in states else
                                             "required_pending" if "required_pending" in states else "verified")
            row["acceptance_freshness"][dimension] = (
                "stale" if any(scope["freshness"] == "stale" for scope in scopes) else "current")
    return rows


def metrics(rows: list[dict]) -> dict:
    counts = dict.fromkeys(STATES, 0)
    counts.update(Counter(row["status"] for row in rows))
    total = len(rows)
    accepted = total - counts["excluded"]
    result = {
        "total": total, "accepted": accepted, "counts": counts,
        "all_percent": round(100 * counts["equivalent"] / total, 1) if total else 0.0,
        "accepted_percent": round(100 * counts["equivalent"] / accepted, 1) if accepted else 0.0,
        "reviewed": sum(row["basis"] in {"reviewed", "impact_accepted"} for row in rows),
        "reviewed_equivalent": sum(row["basis"] in {"reviewed", "impact_accepted"}
                                   and row["status"] == "equivalent" for row in rows),
        "inherited_equivalent": sum(row["basis"] == "baseline_2026-09-07" and row["status"] == "equivalent" for row in rows),
    }
    result["recorded_counts"] = dict(Counter(row["recorded_status"] for row in rows))
    result["freshness_counts"] = dict(Counter(row["freshness"] for row in rows))
    result["impact_counts"] = dict(Counter(row["impact"] for row in rows))
    result["acceptance_counts"] = {
        dimension: dict(Counter(row["acceptance"][dimension] for row in rows)) for dimension in DIMENSIONS}
    result["acceptance_freshness_counts"] = {
        dimension: dict(Counter(row["acceptance_freshness"][dimension] for row in rows))
        for dimension in DIMENSIONS}
    result["required_pending_scope_counts"] = {
        dimension: sum(scope["state"] == "required_pending" for row in rows
                       for scope in row["acceptance_scopes"][dimension])
        for dimension in DIMENSIONS}
    return result


def _md(value: str) -> str:
    value = " ".join(value.split())
    return re.sub(r"([\\`*\[\]|<>])", r"\\\1", value)


def reports(rows: list[dict], data: dict) -> dict[str, str]:
    result = metrics(rows)
    done = result["counts"]["equivalent"]
    out = [
        "# Sprint curent: echivalarea celor 697 de capabilități Hermes", "",
        f"**{done} / {result['total']} = {result['all_percent']}% echivalente complet în evaluarea documentată.**", "",
        f"Din acestea, **{result['reviewed_equivalent']}** au fost reevaluate pe cod în această livrare; "
        f"**{result['inherited_equivalent']}** păstrează verdictul auditului din 7 septembrie.", "",
        "**Acesta este un status inițial conservator, nu o reauditare completă a celor 697.** "
        "Verdictele moștenite și cele actualizate sunt vizibile pentru fiecare rând. "
        "Procentul de 88% discutat anterior privea altă listă și nu se aplică aici.", "",
        "[Toate cele 697 de rânduri](docs/HERMES_CAPABILITIES.md) · "
        "[Sprint, livrări și următorii pași](docs/HERMES_SPRINT.md) · "
        "[Planul tehnic](docs/HERMES_ABSORPTION.md)", "",
        "| Stare cod | Rânduri | Din 697 |", "|---|---:|---:|",
    ]
    for state in STATES:
        count = result["counts"][state]
        out.append(f"| {LABELS[state]} | {count} | {100 * count / result['total']:.1f}% |")
    out.extend([
        "", "## Axe separate de contabilizare", "",
        "**Verdict pe cod înregistrat** (review sau audit moștenit): " +
        ", ".join(f"{state} {count}" for state, count in result["recorded_counts"].items()) + ". "
        "Acesta nu este creditul conservator de mai sus.",
        "**Prospețimea dovezii:** " +
        ", ".join(f"{state} {count}" for state, count in result["freshness_counts"].items()) + ".",
        "**Impactul schimbării:** " +
        ", ".join(f"{state} {count}" for state, count in result["impact_counts"].items()) + ". "
        "Un hash schimbat cere analiză; nu dovedește singur regresia funcțională.",
        "**Acceptare runtime/platform/provider:** " + "; ".join(
            f"{dimension}: " + ", ".join(f"{state} {count}" for state, count in counts.items())
            for dimension, counts in result["acceptance_counts"].items()) + ". "
        "«unrecorded» nu înseamnă că toate rândurile cer servicii externe.",
        "**Prospețimea acceptării:** " + "; ".join(
            f"{dimension}: " + ", ".join(f"{state} {count}" for state, count in counts.items())
            for dimension, counts in result["acceptance_freshness_counts"].items()) + ".",
        "**Scope-uri declarate încă în așteptare:** " + ", ".join(
            f"{dimension} {count}" for dimension, count in result["required_pending_scope_counts"].items()) + ".",
    ])
    out.extend([
        "", f"**Ținta acceptată în produs:** {result['accepted']} rânduri; progres "
        f"{done}/{result['accepted']} = **{result['accepted_percent']}%**. "
        f"Excluderi active: {result['counts']['excluded']}. "
        f"Readmise explicit din vechiul audit: {len(data.get('scope_reopenings', []))}; "
        "readmiterea nu acordă credit de implementare.", "",
        f"**Acoperirea reevaluării curente:** {result['reviewed']}/{result['total']} rânduri. "
        "Restul păstrează auditul inițial sau așteaptă evaluarea după readmitere. "
        "Existența unui fișier sau a unui PR nu închide automat un rând.", "",
        "**Regulă de calcul:** fiecare rând are greutate egală; parțial = zero credit de finalizare. "
        "Un rând compus rămâne parțial cât timp are cerințe acceptate neimplementate. "
        "Un `update` rămâne parțial chiar dacă vechiul audit îl numea superior/parity, până când lipsurile sunt reconciliate. "
        "Acest procent măsoară codul documentat, nu efortul rămas, calitatea UX sau probele pe servicii reale.", "",
        "## Pe domenii", "", "| Domeniu | Total | Echiv. | Parțial | Lipsă | Exclus | Reverificare |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ])
    for cluster in dict.fromkeys(row["cluster"] for row in rows):
        group = [row for row in rows if row["cluster"] == cluster]
        counts = metrics(group)["counts"]
        out.append(f"| {_md(cluster)} | {len(group)} | " + " | ".join(str(counts[s]) for s in STATES) + " |")
    out.extend([
        "", "## Actualizare", "",
        f"Evaluare: `{data['assessed_at']}`. Cod inspectat: `{data['base_sha']}`. "
        f"Inventar înghețat: SHA-256 `{data['inventory_sha256']}`.", "",
        "Sursa editabilă este [assessment.json](docs/hermes/assessment.json). "
        "Actualizează numai rândurile inspectate, cu motiv, lipsuri și hash-uri ale codului/testelor. "
        "Dacă dovezile se schimbă sau dispar, rândul trece la «De reverificat» până la analiza de impact. "
        "O acceptare explicită a impactului, legată de revizie și verificări, poate păstra verdictul; "
        "simpla schimbare de hash nu dovedește regresia. "
        "Data reauditării moștenite nu este rescrisă.", "",
        "```text", "python scripts/hermes_status.py summary", "python scripts/hermes_status.py list --state partial --limit 20",
        "python scripts/hermes_status.py show H515", "python scripts/hermes_status.py write",
        "python scripts/hermes_status.py check", "```", "",
        "Pagina și inventarul afișat sunt generate din aceleași date; testele verifică derivarea, "
        "identitatea tuturor celor 697 de rânduri și lipsa derivării unor procente din PR-uri sau din bifele HA.", "",
    ])
    detail = ["# Cele 697 de capabilități Hermes — status cod", "",
              "[Statusul sprintului](../HERMES_STATUS.md) · [Reguli și livrări](HERMES_SPRINT.md)", "",
              "ID-urile H001–H697 sunt poziții în inventarul înghețat, validate prin hash. "
              "Folosește căutarea paginii pentru nume/ID sau comanda `show` pentru cerința originală completă. "
              "«Audit 07.09» înseamnă moștenit, nu verificat din nou. Dovezile legate sunt fișiere inspectate; "
              "simpla lor existență nu dovedește întregul flux și nu afirmă că testele au fost rulate în această livrare.", ""]
    for cluster in dict.fromkeys(row["cluster"] for row in rows):
        detail.extend([f"## {_md(cluster)}", "", "| ID | Capabilitate | Decizie inițială | Stare cod | Verdict înregistrat | Dovadă | Impact | Acceptare R/P/Pr | Bază | Observație / restanță |",
                       "|---|---|---|---|---|---|---|---|---|---|"])
        for row in (r for r in rows if r["cluster"] == cluster):
            basis = {"baseline_2026-09-07": "Audit 07.09", "reviewed": "Reevaluat",
                     "impact_accepted": "Impact verificat",
                     "scope_reopened": "Readmis; neevaluat"}.get(row["basis"], "Dovadă schimbată")
            note = " ".join(filter(None, (row["remaining"] or row["summary"], row["verification_note"],
                                          row["citation_note"])))
            links = " ".join(f"[d{i + 1}](../{e['path']})" for i, e in enumerate(row["evidence"][:3]))
            acceptance = row["acceptance"]
            freshness = row["acceptance_freshness"]
            acceptance_text = "/".join(f"{acceptance[dimension]}"
                                       f"{'(stale)' if freshness[dimension] == 'stale' else ''}"
                                       for dimension in DIMENSIONS)
            detail.append(f"| <a id=\"{row['id'].lower()}\"></a>{row['id']} | {_md(row['name'])} | {row['decision']} | "
                          f"{LABELS[row['status']]} | {row['recorded_status']} | {row['freshness']} | "
                          f"{row['impact']} | {acceptance_text} | {basis} | {_md(note)} {links} |")
        detail.append("")
    return {"HERMES_STATUS.md": "\n".join(out), "docs/HERMES_CAPABILITIES.md": "\n".join(detail)}


def show_payload(ledger: dict, data: dict, rows: list[dict], ident: str,
                 *, recorded: bool = False) -> dict | None:
    """Return one current row and frozen capability, optionally with its stored review.

    The recorded review is diagnostic history. It does not replace the current
    assessment, whose evidence drift and remaining-work verdict came from assess().
    """
    row = next((item for item in rows if item["id"] == ident.upper()), None)
    if row is None:
        return None
    payload = {"assessment": row, "original": ledger["capabilities"][int(row["id"][1:]) - 1]}
    if recorded:
        payload["recorded_review"] = next(
            (item for item in data["reviews"] if item["id"] == row["id"]), None
        )
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="command", required=True)
    summary = subs.add_parser("summary")
    summary.add_argument("--json", action="store_true")
    summary.add_argument("--ref", help="read inventory, assessment and evidence from this committed ref")
    listing = subs.add_parser("list")
    listing.add_argument("--state", choices=STATES)
    listing.add_argument("--recorded-status", choices=STATES)
    listing.add_argument("--freshness", choices=("unrecorded", "current", "changed", "missing"))
    listing.add_argument("--impact", choices=("none", "pending", "accepted"))
    listing.add_argument("--acceptance", choices=("runtime", "platform", "provider"),
                         help="dimension to filter with --acceptance-state")
    listing.add_argument("--acceptance-state", choices=("unrecorded", "required_pending", "verified", "blocked"))
    listing.add_argument("--acceptance-freshness", choices=("unrecorded", "current", "stale"))
    listing.add_argument("--cluster")
    listing.add_argument("--limit", type=int, default=20)
    show = subs.add_parser("show")
    show.add_argument("id")
    show.add_argument("--recorded", action="store_true",
                      help="also show the stored historical review; current assessment is unchanged")
    mapping = subs.add_parser("impact-map", help="read-only changed-path to capability map")
    mapping.add_argument("--base", default="HEAD", help="compare this committed ref with the working tree")
    mapping.add_argument("--limit", type=int, default=25)
    mapping.add_argument("--json", action="store_true")
    subs.add_parser("write")
    subs.add_parser("check")
    ns = parser.parse_args(argv)
    try:
        if ns.command == "summary" and ns.ref:
            ledger, data, tree = load_ref(REPO, ns.ref)
            rows = assess(ledger, data, REPO, tree=tree)
        else:
            ledger, data = load()
            rows = assess(ledger, data, REPO) if ns.command == "summary" else assess(ledger, data)
        if ns.command == "impact-map":
            _require(0 < ns.limit <= 697, "limit must be 1..697")
            from scripts.hermes_impact import build_map

            result = build_map(REPO, rows, data, base=ns.base, limit=ns.limit)
            print(json.dumps(result, ensure_ascii=False, indent=2) if ns.json else
                  json.dumps(result, ensure_ascii=False))
        elif ns.command == "summary":
            result = metrics(rows)
            if ns.ref:
                result["source"] = {"kind": "committed_ref", "ref": ns.ref, "sha": tree.sha}
            else:
                head, uncommitted = worktree_provenance(REPO)
                result["source"] = {"kind": "working_tree", "head_sha": head,
                                    "worktree_uncommitted": uncommitted,
                                    "assessment_sha256": hashlib.sha256((REPO / ASSESSMENT).read_bytes()).hexdigest()}
            if ns.json:
                print(json.dumps(result, ensure_ascii=False))
            else:
                print(f"{result['counts']['equivalent']}/{result['total']} = {result['all_percent']}% documented code equivalence")
                print(f"Accepted scope: {result['accepted']}; current reviews: {result['reviewed']}; inherited equivalent: {result['inherited_equivalent']}")
                print(json.dumps(result["counts"], ensure_ascii=False))
                print("Recorded implementation verdicts: " + json.dumps(result["recorded_counts"], ensure_ascii=False))
                print("Evidence freshness: " + json.dumps(result["freshness_counts"], ensure_ascii=False))
                print("Impact: " + json.dumps(result["impact_counts"], ensure_ascii=False))
                print("Acceptance: " + json.dumps(result["acceptance_counts"], ensure_ascii=False))
                print("Acceptance freshness: " + json.dumps(result["acceptance_freshness_counts"], ensure_ascii=False))
                print("Source: " + json.dumps(result["source"], ensure_ascii=False))
        elif ns.command == "list":
            _require(0 < ns.limit <= 697, "limit must be 1..697")
            _require(bool(ns.acceptance) == bool(ns.acceptance_state),
                     "--acceptance and --acceptance-state must be used together")
            _require(not ns.acceptance_freshness or ns.acceptance,
                     "--acceptance-freshness needs --acceptance")
            selected = [r for r in rows if (not ns.state or r["status"] == ns.state)
                        and (not ns.recorded_status or r["recorded_status"] == ns.recorded_status)
                        and (not ns.freshness or r["freshness"] == ns.freshness)
                        and (not ns.impact or r["impact"] == ns.impact)
                        and (not ns.acceptance or r["acceptance"][ns.acceptance] == ns.acceptance_state)
                        and (not ns.acceptance_freshness or
                             r["acceptance_freshness"][ns.acceptance] == ns.acceptance_freshness)
                        and (not ns.cluster or ns.cluster.lower() in r["cluster"].lower())]
            for row in selected[:ns.limit]:
                print(f"{row['id']} {row['status']:<12} recorded={row['recorded_status']} "
                      f"freshness={row['freshness']} impact={row['impact']} {row['name'][:100]}")
            print(f"{min(ns.limit, len(selected))} of {len(selected)} rows")
        elif ns.command == "show":
            payload = show_payload(ledger, data, rows, ns.id, recorded=ns.recorded)
            if payload is None:
                print(f"not found: {ns.id}", file=sys.stderr)
                return 1
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            drift = []
            for name, content in reports(rows, data).items():
                path = REPO / name
                if ns.command == "write":
                    path.write_text(content, encoding="utf-8", newline="\n")
                elif not path.is_file() or path.read_text(encoding="utf-8") != content:
                    drift.append(name)
            if drift:
                print("stale reports: " + ", ".join(drift), file=sys.stderr)
                return 1
            print("Hermes 697 reports " + ("written" if ns.command == "write" else "in sync"))
        return 0
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print(f"Hermes status error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if callable(getattr(stream, "reconfigure", None)):
            stream.reconfigure(encoding="utf-8")
    raise SystemExit(main())
