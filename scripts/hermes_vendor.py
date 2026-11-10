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
``catalog --upstream <clone>``
    Re-vendor Hermes's skill catalog (Adopt lane slice 3): every skill folder under
    ``skills/`` and ``optional-skills/`` is classified, the instruction-only ones (a SKILL.md
    and plain data, nothing else) are copied byte-identical with a manifest row per file,
    and ``SKILLS_CATALOG.json`` indexes all of them (``upstream_only`` for a skill with code,
    ``excluded`` with a reason otherwise). Catalog files are never rewritten.
``pull --upstream <clone> <paths...>``
    Re-vendor the named upstream paths (rewrite, write, update the manifest). Refused for
    a symlink or a path resolving outside the clone, a file with local edits (``--force``
    overrides), a ``.py`` file that, rewritten, reaches beyond the allowlist (safe stdlib
    modules, the compat layer and vendored siblings only; ``os`` only as the compat
    ``os_env``; no relative import out of the tree; no network, process or import-machinery
    names), and a non-Python file that is not plain data.

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
    #: Upstream path prefixes the rule applies to; empty means every vendored file. A
    #: scoped rule is how one upstream import gets a different compat module in one
    #: adopted plugin (the governed ``urllib`` of the A2A client) and stays refused
    #: everywhere else.
    paths: tuple[str, ...] = ()

    def compiled(self) -> re.Pattern[str]:
        return re.compile(self.pattern, re.MULTILINE)

    def applies_to(self, path: str | None) -> bool:
        return not self.paths or (path is not None and path.startswith(self.paths))


# Line-anchored, order matters (the specific keyless_mcp rule runs before the general
# ``plugins.web.`` one, and the A2A-scoped ``urllib`` rule before the general refused one).
# No replacement matches any pattern (the import rules all produce
# ``from agents.`` / ``import agents.``; the one value rule produces a value its pattern does
# not match), so applying the rules twice changes nothing (idempotent). Each rule rewrites a
# line in place: line numbers are preserved, so upstream diffs stay readable.
#: The adopted A2A client package (slice 4); the only place the governed ``urllib`` exists.
A2A_PATH = "plugins/platforms/a2a/"

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
    Rule("exa-integration-tag",
         r'^(?P<i>[ \t]*)client\.headers\["x-exa-integration"\] = "hermes-agent"(?P<rest>[ \t]*(?:#.*)?)$',
         r'\g<i>client.headers["x-exa-integration"] = "nerva"\g<rest>',
         "tell Exa the caller is Nerva, not Hermes Agent"),
    # Slice 2 — model-provider profiles (plugins/model-providers/*) and their shared modules.
    Rule("providers-base", r"^(?P<i>[ \t]*)from providers\.base import ",
         r"\g<i>from agents.vendor.hermes.providers.base import ",
         "the vendored ProviderProfile base"),
    Rule("providers-registry", r"^(?P<i>[ \t]*)from providers import ",
         r"\g<i>from agents.vendor.hermes_compat.providers import ",
         "register_provider fills the compat registry; Nerva's bridge reads it"),
    Rule("reasoning-effort", r"^(?P<i>[ \t]*)from agent\.reasoning_effort import ",
         r"\g<i>from agents.vendor.hermes.agent.reasoning_effort import ",
         "the vendored effort vocabulary (pure)"),
    Rule("reasoning-effort-module", r"^(?P<i>[ \t]*)from agent import reasoning_effort\b",
         r"\g<i>from agents.vendor.hermes.agent import reasoning_effort",
         "the vendored effort vocabulary, imported as a module"),
    Rule("account-usage", r"^(?P<i>[ \t]*)from agent\.account_usage import ",
         r"\g<i>from agents.vendor.hermes_compat.account_usage import ",
         "a type name only; Nerva keeps its own usage accounting"),
    Rule("hermes-cli-leaf",
         r"^(?P<i>[ \t]*)from hermes_cli\.(?:version_info|auth|urllib_security|chat_catalog) import ",
         r"\g<i>from agents.vendor.hermes_compat.hermes_cli import ",
         "user agent, credential pool, catalog fetch: Nerva-owned or refused"),
    Rule("threading-locks", r"^(?P<i>[ \t]*)import threading(?P<rest>[ \t]*(?:#.*)?)$",
         r"\g<i>from agents.vendor.hermes_compat import locks as threading\g<rest>",
         "locks only; vendored code starts no thread"),
    # Slice 4 — the A2A client tools (plugins/platforms/a2a/{tools,protocol,security}.py).
    Rule("a2a-urllib",
         r"^(?P<i>[ \t]*)import urllib\.(?:request|error|parse)(?P<rest>[ \t]*(?:#.*)?)$",
         r"\g<i>from agents.vendor.hermes_compat import urllib\g<rest>",
         "the governed urllib: every urlopen goes through the compat httpx to the PluginHTTPClient "
         "bound for one A2A call, behind the owner's per-peer origin and credential guard",
         paths=(A2A_PATH,)),
    Rule("a2a-shared",
         r"^(?P<i>[ \t]*)from (?:gateway\.platforms\._shared|hermes_constants|hermes_cli\.config"
         r"|agent\.proxy_bypass|agent\.secret_scope|agent\.redact|pathlib) import ",
         r"\g<i>from agents.vendor.hermes_compat.a2a_shared import ",
         "peers, credential handles, home directory and redaction come from the Nerva A2A scope",
         paths=(A2A_PATH,)),
    Rule("a2a-futures", r"^(?P<i>[ \t]*)from concurrent\.futures import ",
         r"\g<i>from agents.vendor.hermes_compat.futures import ",
         "fan-out runs on a small shared Nerva pool that carries the call's egress binding",
         paths=(A2A_PATH,)),
    Rule("urllib-request", r"^(?P<i>[ \t]*)import urllib\.request(?P<rest>[ \t]*(?:#.*)?)$",
         r"\g<i>from agents.vendor.hermes_compat import urllib_refused as urllib\g<rest>",
         "a request object only; opening one is refused (catalog fetches are Nerva's)"),
)

# ── what a vendored file may contain (an allowlist, applied by pull, status and CI) ────

#: Standard-library modules a vendored file may import: no I/O, process, network or
#: interpreter-escape module is here. ``os`` only arrives as the compat ``os_env``.
SAFE_STDLIB = frozenset({
    "__future__", "abc", "asyncio", "base64", "collections", "collections.abc", "contextlib",
    "copy", "dataclasses", "datetime", "decimal", "difflib", "enum", "fractions", "functools",
    "hashlib", "html", "itertools", "json", "logging", "math", "numbers", "operator", "re",
    "statistics", "string", "textwrap", "time", "types", "typing", "unicodedata", "urllib.parse",
    "uuid", "warnings", "weakref",
    # slice 4 (A2A): pure computation
    "hmac", "ipaddress",
})
#: Compat modules a vendored file may import (``plugin_ctx`` is not one: a vendored file
#: never registers itself).
COMPAT_PACKAGE = "agents.vendor.hermes_compat"
COMPAT_MODULES = frozenset({
    "httpx", "os_env", "pm", "web_search_provider", "keyless_mcp", "interrupt", "web_tools",
    "sdk", "sdk.exa_py", "sdk.parallel",
    # slice 2 (model-provider profiles)
    "providers", "hermes_cli", "locks", "account_usage", "urllib_refused",
    # slice 4 (A2A client tools)
    "urllib", "a2a_shared", "futures",
})
#: Compat modules only some vendored paths may import: the governed ``urllib`` can open a
#: request (through the egress binding of one A2A call), so no other adopted file may
#: name it, even by hand.
#: The adopted A2A package as a module name: only files under it may import it.
A2A_PACKAGE = "agents.vendor.hermes.plugins.platforms.a2a"
#: Denied-name strings that are wire data in the A2A package (see ``unmapped_imports``).
WIRE_DATA_STRINGS = frozenset({"http"})
PATH_SCOPED_COMPAT: dict[str, tuple[str, ...]] = {
    "urllib": (A2A_PATH,), "a2a_shared": (A2A_PATH,), "futures": (A2A_PATH,),
}
VENDOR_PACKAGE = "agents.vendor.hermes"
#: Attribute / imported / string names that reach the network, a process or the import
#: machinery from an allowed module (``asyncio.open_connection``, ``getattr(x, "...")``).
DENIED_ATTRS = frozenset({
    "open_connection", "open_unix_connection", "start_server", "start_unix_server",
    "create_connection", "create_server", "create_datagram_endpoint", "create_unix_connection",
    "create_unix_server", "create_subprocess_exec", "create_subprocess_shell", "sock_connect",
    "sock_sendall", "sock_recv", "getaddrinfo", "subprocess", "import_module", "__import__",
    "__builtins__", "__globals__", "__subclasses__", "__code__", "__loader__", "__spec__",
    "modules", "streams", "urlopen", "urlretrieve", "build_opener", "install_opener",
    "OpenerDirector",
    # A module reached through another module's attribute (``logging.os.system``,
    # ``x.socket``, ``urllib.request.http.client``): never needed by vendored code.
    "os", "sys", "socket", "ssl", "http", "builtins", "importlib", "ctypes",
    "system", "popen", "spawnv", "execv", "Thread", "start_new_thread",
})
#: Attribute names refused on a module name unless that name is bound to a compat module
#: (``urllib`` is the compat ``urllib_refused`` after the ``urllib-request`` rule).
DENIED_SUBMODULES = {"urllib": frozenset({"request", "error", "response", "robotparser"})}
#: The one denied attribute a compat module makes safe: ``<name>.request.urlopen`` where
#: ``<name>`` is bound to this compat module (the governed ``urllib``).
GOVERNED_URLOPEN_MODULE = "urllib"
#: Builtins a vendored file may not call or read.
DENIED_NAMES = frozenset({"__import__", "exec", "eval", "compile", "open", "__builtins__",
                          "globals", "breakpoint", "input"})
#: Non-Python files a vendored tree may hold: data only.
DATA_SUFFIXES = frozenset({".yaml", ".yml", ".json", ".md", ".txt"})
_LOCAL_FILES = ("__init__.py", "NOTICE.md", "LICENSE", "MANIFEST.json")
#: Slice 3 — Hermes's skill catalog: vendored at its upstream paths under these folders,
#: byte-identical (no rewrite rule ever applies), data only, indexed by CATALOG_INDEX.
CATALOG_ROOTS = ("skills/", "optional-skills/")
CATALOG_INDEX = "SKILLS_CATALOG.json"
#: What a catalog file may be: plain data by suffix, or a LICENSE text.
CATALOG_SUFFIXES = DATA_SUFFIXES
CATALOG_NAMES = frozenset({"LICENSE"})
#: Nerva-written package markers for upstream packages whose own ``__init__.py`` is not
#: adopted (``providers/__init__.py`` is Hermes's plugin loader, ``agent/__init__.py``
#: preloads a JSON library). Each must be a docstring and nothing else (``status``).
_LOCAL_PACKAGE_MARKERS = ("agent/__init__.py", "providers/__init__.py",
                          # slice 4: upstream's a2a ``__init__`` is the gateway plugin loader
                          "plugins/platforms/__init__.py", "plugins/platforms/a2a/__init__.py")


def rewrite(text: str, path: str | None = None) -> tuple[str, list[str]]:
    """``(rewritten text, ids of the rules that changed something)``. *path* is the
    upstream path; a rule scoped to other paths (or any scoped rule, with no path) is
    skipped."""
    applied: list[str] = []
    for rule in REWRITE_RULES:
        if not rule.applies_to(path):
            continue
        new, count = rule.compiled().subn(rule.replacement, text)
        if count:
            applied.append(rule.id)
        text = new
    return text, applied


def _module_allowed(name: str) -> bool:
    if name in SAFE_STDLIB:
        return True
    if name == VENDOR_PACKAGE or name.startswith(VENDOR_PACKAGE + "."):
        return True
    if name.startswith(COMPAT_PACKAGE + "."):
        return name[len(COMPAT_PACKAGE) + 1:] in COMPAT_MODULES
    return False


def _relative_target(path: str, level: int, module: str | None) -> str | None:
    """The module a relative import names, or None when it leaves the file's own package
    (only ``from .x import y`` is accepted; upstream writes its imports absolute)."""
    if level != 1:
        return None
    parts = list(Path(path).parent.parts)
    return ".".join([VENDOR_PACKAGE, *parts] + ([module] if module else []))


def unmapped_imports(text: str, path: str = "x.py") -> list[str]:
    """What a rewritten ``.py`` file reaches beyond the allowlist (empty when it is clean)."""
    try:
        tree = ast.parse(text, filename=path)
    except SyntaxError as exc:
        return [f"unparseable: {exc.msg}"]
    found: list[str] = []
    compat_names = {alias.asname or alias.name: alias.name for node in ast.walk(tree)
                    if isinstance(node, ast.ImportFrom) and node.level == 0
                    and node.module == COMPAT_PACKAGE for alias in node.names}
    compat_bound = set(compat_names)

    def scoped_out(compat: str) -> bool:
        scope = PATH_SCOPED_COMPAT.get(compat)
        return scope is not None and not path.startswith(scope)

    def governed_urlopen(node: ast.Attribute) -> bool:
        base = node.value
        return (node.attr == "urlopen" and isinstance(base, ast.Attribute) and base.attr == "request"
                and isinstance(base.value, ast.Name)
                and compat_names.get(base.value.id) == GOVERNED_URLOPEN_MODULE)

    def scoped_module(module: str) -> bool:
        """A path-scoped compat module or the adopted A2A package, named outside its path."""
        if module.startswith(COMPAT_PACKAGE + "."):
            return scoped_out(module[len(COMPAT_PACKAGE) + 1:].split(".", 1)[0])
        return ((module == A2A_PACKAGE or module.startswith(A2A_PACKAGE + "."))
                and not path.startswith(A2A_PATH))

    # Under the A2A package only, the exact strings in WIRE_DATA_STRINGS are wire data where
    # they are a dict display's key or value (a card's ``{"type": "http"}``) or what a value
    # is compared with (``scheme in ("http", "https")``), not a name handed to ``getattr``.
    # Every other denied string, and every one outside the package, is still refused.
    dict_data: set[int] = set()
    if path.startswith(A2A_PATH):
        for node in ast.walk(tree):
            items: list = []
            if isinstance(node, ast.Dict):
                items = [*node.keys, *node.values]
            elif isinstance(node, ast.Compare):
                for side in node.comparators:
                    items += side.elts if isinstance(side, (ast.Tuple, ast.List, ast.Set)) else [side]
            dict_data.update(id(item) for item in items if isinstance(item, ast.Constant)
                             and item.value in WIRE_DATA_STRINGS)
    for node in ast.walk(tree):
        line = getattr(node, "lineno", 0)
        if isinstance(node, ast.Import):
            for alias in node.names:
                if not _module_allowed(alias.name):
                    found.append(f"line {line}: import {alias.name}")
                elif ("." in alias.name and alias.asname is None
                        and not _module_allowed(alias.name.split(".", 1)[0])):
                    # ``import urllib.parse`` binds ``urllib``, whose ``.request`` is then one
                    # attribute away: only ``from urllib.parse import …`` is allowed.
                    found.append(f"line {line}: import {alias.name} (binds {alias.name.split('.', 1)[0]}; "
                                 f"use from {alias.name} import …)")
                elif alias.name.startswith(COMPAT_PACKAGE) and "os_env" in alias.name:
                    found.append(f"line {line}: import {alias.name} (os only as `os_env as os`)")
                elif scoped_module(alias.name):
                    found.append(f"line {line}: import {alias.name} (path-scoped module)")
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                target = _relative_target(path, node.level, node.module)
                if target is None:
                    found.append(f"line {line}: relative import leaving its package")
                    continue
                module = target
            else:
                module = node.module or ""
            if module == COMPAT_PACKAGE:
                for alias in node.names:
                    if alias.name not in COMPAT_MODULES:
                        found.append(f"line {line}: from {module} import {alias.name}")
                    elif scoped_out(alias.name):
                        found.append(f"line {line}: from {module} import {alias.name} "
                                     f"(only under {', '.join(PATH_SCOPED_COMPAT[alias.name])})")
                    elif alias.name == "os_env" and alias.asname not in (None, "os"):
                        found.append(f"line {line}: os_env imported as {alias.asname}")
            elif not _module_allowed(module):
                found.append(f"line {line}: from {module or '.'} import ...")
            elif scoped_module(module):
                found.append(f"line {line}: from {module} import ... (path-scoped module)")
            for alias in node.names:
                if alias.name in DENIED_ATTRS or alias.name == "*":
                    found.append(f"line {line}: from {module} import {alias.name}")
                elif module.startswith(COMPAT_PACKAGE) and alias.name.startswith("_"):
                    found.append(f"line {line}: from {module} import {alias.name} (private)")
                elif node.level == 0 and scoped_module(f"{module}.{alias.name}"):
                    found.append(f"line {line}: from {module} import {alias.name} (path-scoped module)")
        elif (isinstance(node, ast.Attribute) and node.attr.startswith("_")
                and isinstance(node.value, ast.Name) and node.value.id in compat_bound):
            found.append(f"line {line}: {node.value.id}.{node.attr} (private compat name)")
        elif isinstance(node, ast.Attribute) and node.attr in DENIED_ATTRS:
            if not governed_urlopen(node):
                found.append(f"line {line}: .{node.attr}")
        elif (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
                and node.attr in DENIED_SUBMODULES.get(node.value.id, frozenset())
                and node.value.id not in compat_bound):
            found.append(f"line {line}: {node.value.id}.{node.attr}")
        elif isinstance(node, ast.Name) and node.id in DENIED_NAMES:
            found.append(f"line {line}: {node.id}")
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) \
                and node.value in DENIED_ATTRS and id(node) not in dict_data:
            found.append(f"line {line}: {node.value!r}")
    return found


def data_problems(data: bytes, path: str) -> list[str]:
    """Why a non-Python vendored file is not plain data (empty when it is)."""
    suffix = Path(path).suffix.lower()
    if suffix not in DATA_SUFFIXES:
        return [f"{suffix or 'no extension'} is not a data file type"]
    if b"\0" in data:
        return ["binary content"]
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return ["not UTF-8 text"]
    if suffix in {".yaml", ".yml"}:
        try:
            import yaml

            yaml.safe_load(text)
        except Exception as exc:  # any parse failure is a refusal
            return [f"not plain YAML: {type(exc).__name__}"]
    elif suffix == ".json":
        try:
            json.loads(text)
        except ValueError:
            return ["not JSON"]
    return []


def is_catalog_path(path: str) -> bool:
    return path.startswith(CATALOG_ROOTS)


def catalog_problems(data: bytes, path: str) -> list[str]:
    """Why a skill-catalog file is not plain data (empty when it is). Stricter than the
    general rule: no ``.py`` file at all, only the data suffixes and ``LICENSE``."""
    if Path(path).name in CATALOG_NAMES:
        if b"\0" in data:
            return ["binary content"]
        try:
            data.decode("utf-8")
        except UnicodeDecodeError:
            return ["not UTF-8 text"]
        return []
    if Path(path).suffix.lower() not in CATALOG_SUFFIXES:
        return [f"{Path(path).suffix or 'no extension'} is not a catalog data file type"]
    return data_problems(data, path)


def content_problems(data: bytes, path: str) -> list[str]:
    """Allowlist check for one vendored file, whatever its type."""
    if is_catalog_path(path):
        return catalog_problems(data, path)
    if path.endswith(".py"):
        try:
            return unmapped_imports(data.decode("utf-8"), path)
        except UnicodeDecodeError:
            return ["not UTF-8 text"]
    return data_problems(data, path)


def _docstring_only(data: bytes) -> bool:
    """True when a ``.py`` file is a module docstring and nothing else."""
    try:
        body = ast.parse(data.decode("utf-8")).body
    except (SyntaxError, UnicodeDecodeError):
        return False
    return all(isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
               and isinstance(node.value.value, str) for node in body) and len(body) <= 1


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def rules_record() -> list[dict]:
    return [{"id": r.id, "pattern": r.pattern, "replacement": r.replacement, "why": r.why,
             **({"paths": list(r.paths)} if r.paths else {})}
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


def _symlinked(root: Path, rel: str) -> bool:
    """True when *rel* or any directory on the way to it under *root* is a symlink."""
    current = root
    for part in Path(rel).parts:
        current = current / part
        if current.is_symlink():
            return True
    return False


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


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
        if _symlinked(vendor_root, entry["path"]):
            out.write(f"SYMLINK {entry['path']}\n")
            problems += 1
            continue
        if not target.exists():
            out.write(f"MISSING {entry['path']}\n")
            problems += 1
            continue
        data = target.read_bytes()
        if sha256(data) != entry["vendored_sha256"]:
            out.write(f"EDITED  {entry['path']}  (local edit: vendored bytes differ from MANIFEST)\n")
            problems += 1
            continue
        catalog = is_catalog_path(entry["path"])
        if catalog and (entry.get("rules_applied") or entry["upstream_sha256"] != entry["vendored_sha256"]):
            out.write(f"DRIFT   {entry['path']}  (a catalog file is vendored byte-identical, never rewritten)\n")
            problems += 1
            continue
        again = data.decode("utf-8") if catalog else rewrite(data.decode("utf-8"), entry["path"])[0]
        if again.encode("utf-8") != data:
            out.write(f"DRIFT   {entry['path']}  (rewrite is not a no-op on the vendored text)\n")
            problems += 1
            continue
        applied = list(entry.get("rules_applied", []))
        known = [r.id for r in REWRITE_RULES]
        if any(rule not in known for rule in applied) or \
                applied != [r for r in known if r in applied] or \
                (not applied) != (entry["upstream_sha256"] == entry["vendored_sha256"]):
            out.write(f"DRIFT   {entry['path']}  (rules_applied does not match the bytes)\n")
            problems += 1
            continue
        unsafe = content_problems(data, entry["path"])
        if unsafe:
            out.write(f"UNSAFE  {entry['path']}  ({'; '.join(unsafe)})\n")
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
            redone, redone_rules = ((raw.decode("utf-8"), []) if catalog
                                    else rewrite(raw.decode("utf-8"), entry["path"]))
            if redone.encode("utf-8") != data or redone_rules != applied:
                out.write(f"DRIFT   {entry['path']}  (rewritten upstream != vendored)\n")
                problems += 1
                continue
        out.write(f"ok      {entry['path']}\n")
    local = set(manifest.get("local_files", _LOCAL_FILES)) | set(_LOCAL_PACKAGE_MARKERS)
    for problem in catalog_index_problems(vendor_root, manifest):
        out.write(f"CATALOG {problem}\n")
        problems += 1
    for rel in sorted(r for r in local if r.endswith(".py")):
        target = vendor_root / rel
        if target.is_file() and not target.is_symlink() and not _docstring_only(target.read_bytes()):
            out.write(f"UNSAFE  {rel}  (a Nerva-written package marker holds more than a docstring)\n")
            problems += 1
    for path in sorted(vendor_root.rglob("*")):
        if "__pycache__" in path.parts:
            continue
        rel = path.relative_to(vendor_root).as_posix()
        if path.is_symlink():
            out.write(f"SYMLINK {rel}\n")
            problems += 1
            continue
        if not path.is_file():
            continue
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
        new_text = src.read_text(encoding="utf-8")
        if not is_catalog_path(rel):
            new_text, _ = rewrite(new_text, rel)
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
        for problem in content_problems(new_text.encode("utf-8"), rel):
            out.write(f"!!! {rel}: {problem} (outside the compat allowlist)\n")
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
        if is_catalog_path(rel):
            out.write(f"refused {rel}: a skill-catalog file; a skill is vendored whole by `catalog`\n")
            return 2
        src = upstream / rel
        if _symlinked(upstream, rel) or not _inside(src, upstream) or not src.is_file():
            out.write(f"refused {rel}: not a regular file inside the upstream clone\n")
            return 2
        raw = src.read_bytes()
        try:
            text, applied = rewrite(raw.decode("utf-8"), rel)
        except UnicodeDecodeError:
            out.write(f"refused {rel}: not UTF-8 text\n")
            return 2
        problems = content_problems(text.encode("utf-8"), rel)
        if problems:
            out.write(f"refused {rel}: outside the compat allowlist: " + "; ".join(problems) + "\n")
            return 2
        target = vendor_root / rel
        if _symlinked(vendor_root, rel) or not _inside(target, vendor_root):
            out.write(f"refused {rel}: the vendored path is a symlink\n")
            return 2
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


def catalog_index_problems(vendor_root: Path, manifest: dict) -> list[str]:
    """Where ``SKILLS_CATALOG.json`` and the manifest's catalog rows disagree: an
    installable skill must have every file in the manifest with the indexed sha256, and
    every catalog row must belong to one (no stray file of a skill that carries code)."""
    rows = {f["path"]: f for f in manifest.get("files", []) if is_catalog_path(f["path"])}
    index_path = vendor_root / CATALOG_INDEX
    if not index_path.exists():
        return [f"{CATALOG_INDEX} missing while catalog files are vendored"] if rows else []
    try:
        index = json.loads(index_path.read_text(encoding="utf-8"))
        skills = list(index["skills"])
    except (OSError, ValueError, KeyError, TypeError):
        return [f"{CATALOG_INDEX} cannot be read"]
    problems: list[str] = []
    if CATALOG_INDEX not in manifest.get("local_files", []):
        problems.append(f"{CATALOG_INDEX} is not listed in local_files")
    if index.get("commit") != manifest.get("upstream", {}).get("commit"):
        problems.append(f"{CATALOG_INDEX} names another commit than MANIFEST.json")
    owned: set[str] = set()
    for skill in skills:
        if skill.get("kind") != "instruction":
            continue
        for item in skill.get("files", []):
            rel = f"{skill.get('path')}/{item.get('path')}"
            owned.add(rel)
            row = rows.get(rel)
            if row is None:
                problems.append(f"{rel} is indexed as installable but not vendored")
            elif row["vendored_sha256"] != item.get("sha256"):
                problems.append(f"{rel} differs from its index sha256")
    problems += [f"{rel} is vendored but belongs to no installable skill" for rel in sorted(set(rows) - owned)]
    return problems


def cmd_catalog(vendor_root: Path, upstream: Path, *, commit: str, out) -> int:
    commit = commit or _clone_commit(upstream)
    if not commit:
        out.write("cannot read the clone's commit; pass --commit <sha>\n")
        return 2
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    from agents.core.skills import hermes_catalog

    index = hermes_catalog.build_index(upstream, commit)
    for skill in index["skills"]:
        if skill["kind"] != hermes_catalog.KIND_INSTRUCTION:
            continue
        for item in skill["files"]:
            rel = f"{skill['path']}/{item['path']}"
            if _symlinked(upstream, rel) or _symlinked(vendor_root, rel) \
                    or catalog_problems((upstream / rel).read_bytes(), rel):
                skill["kind"], skill["reason"] = hermes_catalog.KIND_EXCLUDED, "file_not_plain_data"
                break
    index["counts"] = {kind: sum(1 for s in index["skills"] if s["kind"] == kind)
                       for kind in (hermes_catalog.KIND_INSTRUCTION, hermes_catalog.KIND_UPSTREAM_ONLY,
                                    hermes_catalog.KIND_EXCLUDED)}
    manifest = load_manifest(vendor_root / "MANIFEST.json")
    entries = {f["path"]: f for f in manifest.get("files", []) if not is_catalog_path(f["path"])}
    old_catalog = {f["path"] for f in manifest.get("files", []) if is_catalog_path(f["path"])}
    staged: list[tuple[str, bytes]] = []
    for skill in index["skills"]:
        if skill["kind"] != hermes_catalog.KIND_INSTRUCTION:
            continue
        for item in skill["files"]:
            rel = f"{skill['path']}/{item['path']}"
            data = (upstream / rel).read_bytes()
            if sha256(data) != item["sha256"]:
                out.write(f"refused {rel}: changed while the catalog was read\n")
                return 2
            staged.append((rel, data))
    wanted = {rel for rel, _ in staged}
    for rel, data in staged:
        target = vendor_root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if not _inside(target.parent, vendor_root):
            out.write(f"refused {rel}: the vendored path leaves the tree\n")
            return 2
        target.write_bytes(data)
        entries[rel] = {"path": rel, "upstream_commit": commit, "upstream_sha256": sha256(data),
                        "vendored_sha256": sha256(data), "rules_applied": []}
    for rel in sorted(old_catalog - wanted):
        target = vendor_root / rel
        if target.is_file() and not target.is_symlink():
            target.unlink()
    for root in CATALOG_ROOTS:
        base = vendor_root / root.rstrip("/")
        if base.is_dir() and not base.is_symlink():
            for folder in sorted((p for p in base.rglob("*") if p.is_dir()), key=lambda p: -len(p.parts)):
                if not any(folder.iterdir()):
                    folder.rmdir()
            if not any(base.iterdir()):
                base.rmdir()
    manifest["files"] = list(entries.values())
    manifest["rewrite_rules"] = rules_record()
    manifest.setdefault("upstream", {}).update({"repo": UPSTREAM_REPO, "commit": commit, "license": "MIT"})
    manifest["local_files"] = sorted(set(manifest.get("local_files", _LOCAL_FILES)) | {CATALOG_INDEX})
    (vendor_root / CATALOG_INDEX).write_text(hermes_catalog.dump_index(index), encoding="utf-8")
    (vendor_root / "MANIFEST.json").write_text(dump_manifest(manifest), encoding="utf-8")
    counts = index["counts"]
    out.write(f"catalog @{commit[:8]}: {counts['instruction']} instruction-only vendored "
              f"({len(wanted)} files), {counts['upstream_only']} upstream-only (carry code), "
              f"{counts['excluded']} excluded\n")
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
    p_cat = sub.add_parser("catalog", help="re-vendor Hermes's instruction-only skills and index them all")
    p_cat.add_argument("--upstream", type=Path, required=True)
    p_cat.add_argument("--commit", default="")
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
        if ns.cmd == "catalog":
            return cmd_catalog(vendor_root, ns.upstream, commit=ns.commit, out=out)
        return cmd_pull(vendor_root, ns.upstream, ns.paths, commit=ns.commit,
                        force=ns.force, out=out)
    except ValueError as exc:
        out.write(f"refused: {exc}\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
