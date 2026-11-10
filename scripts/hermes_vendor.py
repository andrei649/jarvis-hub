#!/usr/bin/env python3
"""hermes_vendor.py — keep the Adopt lane's vendored Hermes files in step with upstream.

Nerva runs a few Hermes Agent (MIT, NousResearch/hermes-agent) source files as they are,
under ``agents/vendor/hermes/``. Each one is the upstream file with one mechanical change:
its imports of Hermes internals and of network libraries are rewritten to the compat layer
(``agents/vendor/hermes_compat/``), so every effect still crosses Nerva's controls. The
rules live here (:data:`REWRITE_RULES`) and are recorded in ``MANIFEST.json`` beside the
upstream and vendored sha256 of every file. Guide: ``docs/hermes/ADOPT_LANE.md``.

Commands (deterministic; nothing touches the network):

``status``
    Vendored files against the manifest: a changed hash is a local edit, a missing file
    or an unlisted ``.py`` under the vendor tree is drift. ``--upstream <clone>`` also
    checks that the clone's text, rewritten, is still exactly what is vendored.
``diff --upstream <clone> [paths...]``
    For each vendored file (or the named upstream paths), the unified diff from the
    vendored text to the clone's current text with the same rewrites applied: what an
    update would change, reviewed as a diff.
``pull --upstream <clone> <paths...>``
    Re-vendor the named upstream paths (rewrite, write, update the manifest). Refused for
    a file with local edits (``--force`` overrides) and for a file that, rewritten, still
    imports a Hermes internal or a network library the compat layer does not cover.

Exit status: 0 clean, 1 drift or differences found, 2 refused / usage error.
"""

from __future__ import annotations

import argparse
import ast
import difflib
import hashlib
import json
import re
import subprocess  # nosec B404 - read-only `git rev-parse` of a local clone
import sys
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
VENDOR_ROOT = REPO / "agents" / "vendor" / "hermes"
MANIFEST_PATH = VENDOR_ROOT / "MANIFEST.json"
UPSTREAM_REPO = "https://github.com/NousResearch/hermes-agent"


@dataclass(frozen=True)
class Rule:
    id: str
    pattern: str
    replacement: str
    why: str

    def compiled(self) -> re.Pattern[str]:
        return re.compile(self.pattern, re.MULTILINE)


# Line-anchored, order matters (the specific keyless_mcp rule runs before the general
# ``plugins.web.`` one). Every replacement starts ``from agents.`` / ``import agents.``, which
# no pattern matches, so applying the rules twice changes nothing (idempotent). Each rule
# rewrites a line in place: line numbers are preserved, so upstream diffs stay readable.
REWRITE_RULES: tuple[Rule, ...] = (
    Rule("httpx", r"^(?P<i>[ \t]*)import httpx(?P<rest>[ \t]*(?:#.*)?)$",
         r"\g<i>from agents.vendor.hermes_compat import httpx\g<rest>",
         "the compat httpx sends every request through Nerva's PluginHTTPClient"),
    Rule("os-env", r"^(?P<i>[ \t]*)import os(?P<rest>[ \t]*(?:#.*)?)$",
         r"\g<i>from agents.vendor.hermes_compat import os_env as os\g<rest>",
         "env reads go through an allowlist on agents.core.env_config"),
    Rule("web-search-provider", r"^(?P<i>[ \t]*)from agent\.web_search_provider import ",
         r"\g<i>from agents.vendor.hermes_compat.web_search_provider import ",
         "the WebSearchProvider base and the secret-scoped key lookup"),
    Rule("keyless-mcp", r"^(?P<i>[ \t]*)from plugins\.web\.keyless_mcp import ",
         r"\g<i>from agents.vendor.hermes_compat.keyless_mcp import ",
         "the anonymous keyless ring stays off in Nerva"),
    Rule("plugins-web", r"^(?P<i>[ \t]*)from plugins\.web\.",
         r"\g<i>from agents.vendor.hermes.plugins.web.",
         "vendored siblings live under agents.vendor.hermes"),
    Rule("interrupt", r"^(?P<i>[ \t]*)from tools\.interrupt import ",
         r"\g<i>from agents.vendor.hermes_compat.interrupt import ",
         "Hermes's interrupt flag (Nerva's e-stop acts at egress)"),
    Rule("web-tools-slots", r"^(?P<i>[ \t]*)import tools\.web_tools as ",
         r"\g<i>import agents.vendor.hermes_compat.web_tools as ",
         "the SDK client cache slots"),
    Rule("pm", r"^(?P<i>[ \t]*)import pm(?P<rest>[ \t]*(?:#.*)?)$",
         r"\g<i>from agents.vendor.hermes_compat import pm\g<rest>",
         "lazy installs are refused; only the compat SDK stand-ins are provided"),
    Rule("exa-sdk", r"^(?P<i>[ \t]*)from exa_py import ",
         r"\g<i>from agents.vendor.hermes_compat.sdk.exa_py import ",
         "the Exa SDK is a bare client; the stand-in dials through the compat httpx"),
    Rule("parallel-sdk", r"^(?P<i>[ \t]*)import parallel(?P<rest>[ \t]*(?:#.*)?)$",
         r"\g<i>from agents.vendor.hermes_compat.sdk import parallel\g<rest>",
         "the Parallel SDK is a bare client; the stand-in dials through the compat httpx"),
)

# A rewritten file may import only these (plus the standard library, minus networking).
_ALLOWED_PREFIXES = ("agents.vendor.hermes_compat", "agents.vendor.hermes.")
_HERMES_ROOTS = frozenset({
    "agent", "tools", "plugins", "hermes_cli", "hermes_state", "gateway", "pm", "acp",
    "cron", "environments", "hermes_constants", "model_tools", "toolsets", "utils",
})
_NETWORK_ROOTS = frozenset({
    "httpx", "httpcore", "requests", "aiohttp", "urllib3", "socket", "ssl", "http",
    "urllib", "websocket", "websockets", "grpc", "exa_py", "parallel", "openai",
    "anthropic", "mcp", "ftplib", "smtplib", "telnetlib", "asyncio.streams",
})
_LOCAL_FILES = ("__init__.py", "NOTICE.md", "LICENSE", "MANIFEST.json")


def rewrite(text: str) -> tuple[str, list[str]]:
    """``(rewritten text, ids of the rules that changed something)``."""
    applied: list[str] = []
    for rule in REWRITE_RULES:
        new, count = rule.compiled().subn(rule.replacement, text)
        if count:
            applied.append(rule.id)
        text = new
    return text, applied


def unmapped_imports(text: str, path: str = "<vendored>") -> list[str]:
    """Imports a rewritten file still makes of a Hermes internal or a network library."""
    if not path.endswith(".py"):
        return []
    try:
        tree = ast.parse(text, filename=path)
    except SyntaxError as exc:
        return [f"unparseable: {exc.msg}"]
    found: list[str] = []
    for node in ast.walk(tree):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names = [node.module]
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                and node.func.id == "__import__":
            names = ["__import__"]
        for name in names:
            if name.startswith(_ALLOWED_PREFIXES) or name == "agents.vendor.hermes_compat":
                continue
            root = name.split(".")[0]
            if root in _HERMES_ROOTS or root in _NETWORK_ROOTS or name in _NETWORK_ROOTS \
                    or name == "__import__" or root == "agents":
                found.append(f"line {node.lineno}: {name}")
    return found


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def rules_record() -> list[dict]:
    return [{"id": r.id, "pattern": r.pattern, "replacement": r.replacement, "why": r.why}
            for r in REWRITE_RULES]


def load_manifest(path: Path = MANIFEST_PATH) -> dict:
    if not path.exists():
        return {"upstream": {"repo": UPSTREAM_REPO, "commit": "", "license": "MIT"},
                "rewrite_rules": rules_record(), "files": [], "local_files": list(_LOCAL_FILES)}
    return json.loads(path.read_text(encoding="utf-8"))


def dump_manifest(manifest: dict) -> str:
    manifest = dict(manifest)
    manifest["files"] = sorted(manifest.get("files", []), key=lambda f: f["path"])
    manifest["local_files"] = sorted(set(manifest.get("local_files", _LOCAL_FILES)))
    return json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _safe_rel(path: str) -> str:
    rel = Path(path).as_posix().removeprefix("./")
    parts = Path(rel).parts
    if not rel or rel.startswith("/") or ".." in parts or Path(path).is_absolute():
        raise ValueError(f"not a relative upstream path: {path!r}")
    return rel


def _clone_commit(clone: Path) -> str:
    try:
        out = subprocess.run(  # nosec B603 B607 - fixed argv, read-only, local clone
            ["git", "-C", str(clone), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=20, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    sha = out.stdout.strip()
    return sha if re.fullmatch(r"[0-9a-f]{40}", sha) else ""


# ── commands ─────────────────────────────────────────────────────────────────

def cmd_status(vendor_root: Path, upstream: Path | None, out) -> int:
    manifest = load_manifest(vendor_root / "MANIFEST.json")
    problems = 0
    if manifest.get("rewrite_rules") != rules_record():
        out.write("DRIFT   rewrite rules in MANIFEST.json differ from scripts/hermes_vendor.py\n")
        problems += 1
    listed = {f["path"] for f in manifest.get("files", [])}
    for entry in sorted(manifest.get("files", []), key=lambda f: f["path"]):
        target = vendor_root / entry["path"]
        if not target.exists():
            out.write(f"MISSING {entry['path']}\n")
            problems += 1
            continue
        data = target.read_bytes()
        if sha256(data) != entry["vendored_sha256"]:
            out.write(f"EDITED  {entry['path']}  (local edit: vendored bytes differ from MANIFEST)\n")
            problems += 1
            continue
        again, _ = rewrite(data.decode("utf-8"))
        if again.encode("utf-8") != data:
            out.write(f"DRIFT   {entry['path']}  (rewrite is not a no-op on the vendored text)\n")
            problems += 1
            continue
        if upstream is not None:
            src = upstream / entry["path"]
            if not src.exists():
                out.write(f"GONE    {entry['path']}  (absent in the upstream clone)\n")
                problems += 1
                continue
            raw = src.read_bytes()
            if sha256(raw) != entry["upstream_sha256"]:
                out.write(f"BEHIND  {entry['path']}  (upstream changed since the pin)\n")
                problems += 1
                continue
            if rewrite(raw.decode("utf-8"))[0].encode("utf-8") != data:
                out.write(f"DRIFT   {entry['path']}  (rewritten upstream != vendored)\n")
                problems += 1
                continue
        out.write(f"ok      {entry['path']}\n")
    local = set(manifest.get("local_files", _LOCAL_FILES))
    for path in sorted(vendor_root.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        rel = path.relative_to(vendor_root).as_posix()
        if rel not in listed and rel not in local:
            out.write(f"EXTRA   {rel}  (not in MANIFEST.json)\n")
            problems += 1
    out.write(f"{len(listed)} vendored file(s), {problems} problem(s); pinned "
              f"{manifest.get('upstream', {}).get('commit', '') or 'unknown'}\n")
    return 1 if problems else 0


def cmd_diff(vendor_root: Path, upstream: Path, paths: list[str], out) -> int:
    manifest = load_manifest(vendor_root / "MANIFEST.json")
    entries = {f["path"]: f for f in manifest.get("files", [])}
    wanted = [_safe_rel(p) for p in paths] if paths else sorted(entries)
    changed = 0
    for rel in wanted:
        src = upstream / rel
        if not src.exists():
            out.write(f"--- {rel}: absent in the upstream clone\n")
            changed += 1
            continue
        new_text, _ = rewrite(src.read_text(encoding="utf-8"))
        target = vendor_root / rel
        old_text = target.read_text(encoding="utf-8") if target.exists() else ""
        if new_text == old_text:
            continue
        changed += 1
        out.writelines(difflib.unified_diff(
            old_text.splitlines(keepends=True), new_text.splitlines(keepends=True),
            fromfile=f"vendored/{rel}", tofile=f"upstream/{rel}",
        ))
        if not new_text.endswith("\n"):
            out.write("\n")
        for problem in unmapped_imports(new_text, rel):
            out.write(f"!!! {rel}: would import {problem} (not covered by the compat layer)\n")
    out.write(f"{changed} file(s) differ from upstream\n")
    return 1 if changed else 0


def cmd_pull(vendor_root: Path, upstream: Path, paths: list[str], *, commit: str,
             force: bool, out) -> int:
    if not paths:
        out.write("pull needs at least one upstream path\n")
        return 2
    manifest = load_manifest(vendor_root / "MANIFEST.json")
    commit = commit or _clone_commit(upstream)
    if not commit:
        out.write("cannot read the clone's commit; pass --commit <sha>\n")
        return 2
    entries = {f["path"]: f for f in manifest.get("files", [])}
    staged: list[tuple[str, bytes, dict]] = []
    for raw_path in paths:
        rel = _safe_rel(raw_path)
        src = upstream / rel
        if not src.is_file():
            out.write(f"refused {rel}: not a file in the upstream clone\n")
            return 2
        raw = src.read_bytes()
        text, applied = rewrite(raw.decode("utf-8"))
        problems = unmapped_imports(text, rel)
        if problems:
            out.write(f"refused {rel}: still imports " + "; ".join(problems) + "\n")
            return 2
        target = vendor_root / rel
        old = entries.get(rel)
        if old and target.exists() and sha256(target.read_bytes()) != old["vendored_sha256"] \
                and not force:
            out.write(f"refused {rel}: has local edits (use --force to overwrite)\n")
            return 2
        data = text.encode("utf-8")
        staged.append((rel, data, {
            "path": rel, "upstream_commit": commit, "upstream_sha256": sha256(raw),
            "vendored_sha256": sha256(data), "rules_applied": applied,
        }))
    for rel, data, entry in staged:
        target = vendor_root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        entries[rel] = entry
        out.write(f"vendored {rel}  ({', '.join(entry['rules_applied']) or 'no rewrite'})\n")
    manifest["files"] = list(entries.values())
    manifest["rewrite_rules"] = rules_record()
    manifest.setdefault("upstream", {}).update(
        {"repo": UPSTREAM_REPO, "commit": commit, "license": "MIT"})
    manifest.setdefault("local_files", list(_LOCAL_FILES))
    (vendor_root / "MANIFEST.json").write_text(dump_manifest(manifest), encoding="utf-8")
    return 0


def main(argv: list[str] | None = None, *, vendor_root: Path = VENDOR_ROOT, out=None) -> int:
    out = out or sys.stdout
    parser = argparse.ArgumentParser(prog="scripts/hermes_vendor.py",
                                     description="Sync the vendored Hermes files.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_status = sub.add_parser("status", help="vendored files vs MANIFEST.json")
    p_status.add_argument("--upstream", type=Path)
    p_diff = sub.add_parser("diff", help="upstream changes, rewritten, per vendored file")
    p_diff.add_argument("--upstream", type=Path, required=True)
    p_diff.add_argument("paths", nargs="*")
    p_pull = sub.add_parser("pull", help="re-vendor upstream paths and update MANIFEST.json")
    p_pull.add_argument("--upstream", type=Path, required=True)
    p_pull.add_argument("--commit", default="")
    p_pull.add_argument("--force", action="store_true")
    p_pull.add_argument("paths", nargs="+")
    try:
        ns = parser.parse_args(argv)
    except SystemExit as exc:
        return 2 if exc.code else 0
    try:
        if ns.cmd == "status":
            return cmd_status(vendor_root, ns.upstream, out)
        if not ns.upstream.is_dir():
            out.write(f"no upstream clone at {ns.upstream}\n")
            return 2
        if ns.cmd == "diff":
            return cmd_diff(vendor_root, ns.upstream, ns.paths, out)
        return cmd_pull(vendor_root, ns.upstream, ns.paths, commit=ns.commit,
                        force=ns.force, out=out)
    except ValueError as exc:
        out.write(f"refused: {exc}\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
