#!/usr/bin/env python3
"""Move the governed Hermes runtime to another upstream commit, reviewably.

``python scripts/hermes_runtime.py bump --commit <sha>`` (or this file directly):

1. fetches the archive of the *current* pin and refuses unless its SHA-256 and
   source identity still match ``runtime/hermes/upstream.lock.json``;
2. fetches the archive of the new commit, checks the commit recorded inside it,
   extracts it with the product extractor and computes every lock field the way
   ``agents.core.hermes_runtime.distribution`` later verifies them;
3. regenerates ``gateway-catalog.json`` from upstream's OpenRPC contract and prints
   what changed: methods, parameter schemas, server requests and notifications;
4. rewrites the lock, catalog, executable list, notice and the two code anchors.

It never classifies a method. New methods stay out of ``rpc-policy.json`` and the
policy keeps naming the previous commit, so the runtime refuses every call
("classification is incomplete") until a reviewer classifies the new methods,
re-checks the changed ones and sets the policy's ``source_sha``. Exit status 3
means that review is still required; 0 means the policy already covers the pin.

Archives come from codeload.github.com. Where that host is unreachable,
``--git-dir`` builds them with ``git archive | gzip -n`` from a local clone holding
both commits. That is accepted only if the rebuilt archive of the current pin is
byte-identical to the pinned codeload archive; the runtime's ``prepare`` checks the
new hash against codeload again before it extracts anything.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess  # nosec B404 - fixed git/gzip argv for an operator-run maintenance tool
import sys
import tempfile
import urllib.request
from collections.abc import Callable
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents.core.archive_safe import ArchiveLimits, ArchiveRejected, tar_listing  # noqa: E402
from agents.core.hermes_runtime import distribution  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
PROJECT = "NousResearch/hermes-agent"
CONTRACT = "apps/shared/src/gateway-contract.openrpc.json"
COMMIT_API = "https://api.github.com/repos/NousResearch/hermes-agent/git/commits/{commit}"
REVIEW_REQUIRED = 3
_SHA = re.compile(r"[0-9a-f]{40}")
_ANCHORS = (
    ("agents/core/hermes_runtime/distribution.py", 'PINNED_COMMIT = "{commit}"'),
    ("agents/core/hermes_runtime/worker.py", 'SOURCE_SHA = "{commit}"'),
    ("runtime/hermes/NOTICE.md", "Commit: {commit}"),
)


class BumpRefused(RuntimeError):
    """The bump stopped before writing anything."""


def _commit(value: str) -> str:
    if not isinstance(value, str) or not _SHA.fullmatch(value):
        raise BumpRefused("commit must be a full 40-character lowercase hex SHA")
    return value


# --- archive sources -------------------------------------------------------

def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def codeload_fetch(commit: str, destination: Path) -> Path:
    """Download upstream's codeload tarball with the runtime's own size cap."""
    url = distribution.ARCHIVE_URL.format(commit=_commit(commit))
    size = 0
    # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected
    with urllib.request.urlopen(url, timeout=120) as response, destination.open("wb") as file:  # nosec B310 - fixed https host
        for block in iter(lambda: response.read(1024 * 1024), b""):
            size += len(block)
            if size > distribution._MAX_ARCHIVE_BYTES:
                raise BumpRefused("Hermes archive too large")
            file.write(block)
    return destination


def codeload_tree(commit: str) -> str:
    # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected
    with urllib.request.urlopen(COMMIT_API.format(commit=_commit(commit)), timeout=30) as response:  # nosec B310 - fixed https host
        tree = json.loads(response.read(1024 * 1024))["tree"]["sha"]
    return _commit(tree)


def git_archive_fetcher(git_dir: Path) -> tuple[Callable[[str, Path], Path], Callable[[str], str]]:
    """Rebuild codeload's tarball format: ``git archive --format=tar | gzip -n``."""
    git, gzip = shutil.which("git"), shutil.which("gzip")
    if not git or not gzip:
        raise BumpRefused("--git-dir needs git and gzip on PATH")
    git_dir = Path(git_dir).resolve()

    def fetch(commit: str, destination: Path) -> Path:
        commit = _commit(commit)
        with destination.open("wb") as output:
            archive = subprocess.Popen(  # nosec B603 - fixed argv, validated SHA
                [git, f"--git-dir={git_dir}", "archive", "--format=tar",
                 f"--prefix=hermes-agent-{commit}/", commit], stdout=subprocess.PIPE)
            compressed = subprocess.run([gzip, "-n"], stdin=archive.stdout, stdout=output,  # nosec B603 - fixed argv
                                        check=False)
            archive.stdout.close()
            if archive.wait() or compressed.returncode:
                raise BumpRefused(f"git archive of {commit} failed")
        return destination

    def tree(commit: str) -> str:
        result = subprocess.run([git, f"--git-dir={git_dir}", "rev-parse", "--verify",  # nosec B603 - fixed argv
                                 f"{_commit(commit)}^{{tree}}"], capture_output=True, text=True, check=False)
        if result.returncode:
            raise BumpRefused(f"git cannot resolve the tree of {commit}")
        return _commit(result.stdout.strip())

    return fetch, tree


# --- archive identity ------------------------------------------------------

def archive_facts(archive: Path, commit: str) -> dict:
    """Read what the gzip'd tar says about itself before anything is extracted."""
    root = f"hermes-agent-{commit}"
    try:
        headers, members = tar_listing(archive, compression="gz", limits=ArchiveLimits(
            max_members=distribution._MAX_FILES, max_bytes=distribution._MAX_EXTRACTED_BYTES))
    except ArchiveRejected as exc:
        raise BumpRefused(f"Hermes archive refused: {exc}") from exc
    if headers.get("comment") != commit:
        raise BumpRefused("archive does not record the requested commit")
    executables = []
    for name, kind, mode in members:
        parts = name.split("/")
        if parts[0] != root:
            raise BumpRefused("archive has an unexpected root")
        if kind == "file" and mode & 0o111 and len(parts) > 1:
            executables.append("/".join(parts[1:]))
    return {"archive_root": root, "executables": sorted(executables)}


def _extract(archive: Path, workdir: Path, name: str, root: str, executables: list[str]) -> Path:
    target = workdir / name
    distribution._extract_archive(archive, target, root, executables)
    return target


# --- catalog ----------------------------------------------------------------

def _schemas(contract: dict) -> dict:
    return contract.get("components", {}).get("schemas", {})


def _top_schema(contract: dict, method: dict) -> dict:
    params = method.get("params") or []
    if len(params) != 1 or "schema" not in params[0]:
        raise BumpRefused(f"method {method.get('name')} does not take one params object")
    schema = params[0]["schema"]
    ref = schema.get("$ref")
    if ref is None:
        return schema
    if not ref.startswith("#/components/schemas/") or ref.rsplit("/", 1)[1] not in _schemas(contract):
        raise BumpRefused(f"method {method.get('name')} references an unknown schema")
    return _schemas(contract)[ref.rsplit("/", 1)[1]]


def build_catalog(contract_bytes: bytes, commit: str) -> dict:
    """The catalog format already in use: methods with their params schema, and
    upstream's server-request and notification declarations, verbatim."""
    contract = json.loads(contract_bytes)
    names = [method["name"] for method in contract["methods"]]
    if len(names) != len(set(names)):
        raise BumpRefused("contract declares a method twice")
    return {
        "source_sha": _commit(commit),
        "contract_sha256": hashlib.sha256(contract_bytes).hexdigest(),
        "methods": [{"name": method["name"], "summary": method.get("summary", ""),
                     "params": _top_schema(contract, method)} for method in contract["methods"]],
        "server_requests": contract["x-server-requests"],
        "notifications": contract["x-notifications"],
    }


def render_catalog(catalog: dict) -> str:
    return json.dumps(catalog, indent=2, ensure_ascii=False) + "\n"


# --- diff -------------------------------------------------------------------

def _resolve(value, schemas: dict, seen: tuple = ()):
    """Inline every component reference so nested schema changes are visible."""
    if isinstance(value, list):
        return [_resolve(item, schemas, seen) for item in value]
    if not isinstance(value, dict):
        return value
    ref = value.get("$ref")
    if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
        name = ref.rsplit("/", 1)[1]
        if name in seen:
            return {"$recursive": name}
        return _resolve(schemas.get(name, {"$missing": name}), schemas, seen + (name,))
    return {key: _resolve(item, schemas, seen) for key, item in value.items()}


def _entries(contract: dict, key: str) -> dict:
    schemas = _schemas(contract)
    return {entry["name"]: {"summary": entry.get("summary", ""),
                            "params": _resolve(entry.get("params"), schemas),
                            "result": _resolve(entry.get("result"), schemas)}
            for entry in contract.get(key, [])}


def _section(old: dict, new: dict) -> dict:
    shared = sorted(set(old) & set(new))
    return {
        "added": sorted(set(new) - set(old)),
        "removed": sorted(set(old) - set(new)),
        "params_changed": [name for name in shared if old[name]["params"] != new[name]["params"]],
        "result_changed": [name for name in shared if old[name]["result"] != new[name]["result"]],
        "summary_changed": [name for name in shared if old[name]["summary"] != new[name]["summary"]],
    }


def contract_diff(old_bytes: bytes, new_bytes: bytes) -> dict:
    old, new = json.loads(old_bytes), json.loads(new_bytes)
    return {key: _section(_entries(old, source), _entries(new, source))
            for key, source in (("methods", "methods"), ("server_requests", "x-server-requests"),
                                ("notifications", "x-notifications"))}


# --- bump --------------------------------------------------------------------

def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, text: str) -> None:
    temporary = path.with_name(f".{path.name}.bump")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def _rewrite_anchor(root: Path, relative: str, pattern: str, old: str, new: str) -> tuple[Path, str]:
    path = root / relative
    text = path.read_text(encoding="utf-8")
    before, after = pattern.format(commit=old), pattern.format(commit=new)
    if text.count(before) != 1:
        raise BumpRefused(f"{relative} does not name the current pin exactly once")
    return path, text.replace(before, after)


def bump(commit: str, *, fetch: Callable[[str, Path], Path], git_tree: Callable[[str], str],
         root: Path = REPO, write: bool = True) -> dict:
    """Compute and (unless ``write`` is false) apply a pin move. Raises BumpRefused
    before writing anything if any identity check fails."""
    commit = _commit(commit)
    runtime = root / "runtime/hermes"
    lock_path, catalog_path = runtime / "upstream.lock.json", runtime / "gateway-catalog.json"
    policy_path, executables_path = runtime / "rpc-policy.json", runtime / "executable-paths.json"
    current = _read_json(lock_path)
    try:
        current = distribution.load_pin(lock_path, commit=current.get("commit"))
    except ValueError as exc:
        raise BumpRefused(f"current lock is invalid: {exc}") from exc
    with tempfile.TemporaryDirectory(prefix="hermes-bump-") as temporary:
        workdir = Path(temporary)
        # 1. The current pin must still reproduce exactly; this also proves a
        #    non-codeload source builds byte-identical archives.
        old_archive = fetch(current["commit"], workdir / "old.tar.gz")
        if _sha256(old_archive) != current["archive_sha256"]:
            raise BumpRefused("archive of the current pin does not match its pinned SHA-256; "
                              "the archive source is not byte-identical to codeload")
        old_source = _extract(old_archive, workdir, "old", current["archive_root"],
                              _read_json(executables_path))
        try:
            distribution.verify_source(old_source, current)
        except ValueError as exc:
            raise BumpRefused(f"current pin no longer verifies: {exc}") from exc
        old_contract = (old_source / CONTRACT).read_bytes()
        if render_catalog(build_catalog(old_contract, current["commit"])) != catalog_path.read_text(encoding="utf-8"):
            raise BumpRefused("gateway-catalog.json is not the generated catalog of the current pin; "
                              "it was edited by hand")

        # 2. The new archive: identity, executable modes, every lock field.
        new_archive = fetch(commit, workdir / "new.tar.gz")
        if new_archive.stat().st_size > distribution._MAX_ARCHIVE_BYTES:
            raise BumpRefused("Hermes archive too large")
        facts = archive_facts(new_archive, commit)
        new_source = _extract(new_archive, workdir, "new", facts["archive_root"], facts["executables"])
        lock = {
            "project": PROJECT,
            "commit": commit,
            "tree_sha1": distribution._git_tree_sha1(new_source),
            "source_sha256": distribution._source_sha256(new_source),
            "git_tree_sha1": git_tree(commit),
            "archive_url": distribution.ARCHIVE_URL.format(commit=commit),
            "archive_sha256": _sha256(new_archive),
            "archive_root": facts["archive_root"],
            "license": current["license"],
        }
        distribution.verify_source(new_source, lock)
        if not (new_source / "LICENSE").is_file():
            raise BumpRefused("new source has no LICENSE")
        new_contract = (new_source / CONTRACT).read_bytes()

    catalog = build_catalog(new_contract, commit)
    diff = contract_diff(old_contract, new_contract)
    policy = _read_json(policy_path)
    names = {method["name"] for method in catalog["methods"]}
    dropped = sorted(set(policy["tiers"]) - names)
    policy["tiers"] = {name: tier for name, tier in sorted(policy["tiers"].items()) if name in names}
    unclassified = sorted(names - set(policy["tiers"]))
    review = {
        "unclassified_methods": unclassified,
        "recheck_methods": diff["methods"]["params_changed"],
        "dropped_policy_entries": dropped,
        "policy_source_sha": policy["source_sha"],
        "required": bool(unclassified) or policy["source_sha"] != commit,
    }
    report = {"from": current["commit"], "to": commit, "lock": lock,
              "counts": {"methods": len(catalog["methods"]),
                         "server_requests": len(catalog["server_requests"]),
                         "notifications": len(catalog["notifications"])},
              "diff": diff, "review": review}
    if write:
        anchors = [_rewrite_anchor(root, relative, pattern, current["commit"], commit)
                   for relative, pattern in _ANCHORS] if current["commit"] != commit else []
        _write(lock_path, json.dumps(lock, indent=2) + "\n")
        _write(catalog_path, render_catalog(catalog))
        _write(executables_path, json.dumps(facts["executables"], indent=2) + "\n")
        _write(policy_path, json.dumps(policy, indent=2) + "\n")
        for path, text in anchors:
            _write(path, text)
    return report


def format_report(report: dict) -> str:
    lines = [f"Hermes pin {report['from'][:12]} -> {report['to'][:12]}",
             "catalog: {methods} methods, {server_requests} server requests, "
             "{notifications} notifications".format(**report["counts"])]
    for section, changes in report["diff"].items():
        for kind, names in changes.items():
            if names:
                lines.append(f"{section} {kind} ({len(names)}): {', '.join(names)}")
    review = report["review"]
    if review["unclassified_methods"]:
        lines.append("UNCLASSIFIED (runtime refuses them until runtime/hermes/rpc-policy.json has a tier): "
                     + ", ".join(review["unclassified_methods"]))
    if review["recheck_methods"]:
        lines.append("RE-CHECK tier against the changed handler: " + ", ".join(review["recheck_methods"]))
    if review["dropped_policy_entries"]:
        lines.append("dropped from policy (removed upstream): " + ", ".join(review["dropped_policy_entries"]))
    if review["required"]:
        lines.append(f"REVIEW REQUIRED: classify, re-check, then set rpc-policy.json source_sha to {report['to']}. "
                     "Until then every Hermes RPC fails closed.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--commit", required=True, help="full upstream commit SHA to pin")
    parser.add_argument("--git-dir", type=Path,
                        help="local clone holding both commits; used instead of codeload.github.com")
    parser.add_argument("--git-tree", help="upstream tree SHA of --commit (skips the GitHub API lookup)")
    parser.add_argument("--dry-run", action="store_true", help="verify and print the diff without writing")
    parser.add_argument("--json", action="store_true", help="print the full report as JSON")
    args = parser.parse_args(argv)
    try:
        if args.git_dir:
            fetch, tree = git_archive_fetcher(args.git_dir)
        else:
            fetch, tree = codeload_fetch, codeload_tree
        if args.git_tree:
            given = _commit(args.git_tree)
            tree = lambda commit: given  # noqa: E731
        report = bump(args.commit, fetch=fetch, git_tree=tree, write=not args.dry_run)
    except (BumpRefused, ValueError, OSError) as exc:
        print(f"bump refused: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2) if args.json else format_report(report))
    return REVIEW_REQUIRED if report["review"]["required"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
