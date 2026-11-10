"""catalog.py — the MCP server catalog (G9 / H549).

Hermes ships a directory of reviewed MCP server manifests (``optional-mcps/<name>/manifest.yaml``,
pin ``9c0560f8``). Nerva adopts them as **data**: ``scripts/hermes_vendor.py mcp-catalog``
copies each file byte-identical under ``agents/vendor/hermes/optional-mcps/`` with a
``MANIFEST.json`` row. This module reads them back, re-checks every file against its row
(``upstream_sha256 == vendored_sha256 ==`` the bytes on disk), validates the manifest with
Nerva's own reader (the schema follows Hermes's ``hermes_cli/mcp_catalog.py``, which is a
reference, not adopted) and turns an entry into an **install plan**: exactly the server
configuration the admin add path would write, plus the names of the secrets the owner must
type. Nothing here writes configuration or starts a process.

* **What runs is shown first.** :func:`build_plan` returns the command line (stdio) or the
  endpoint (HTTP), the static environment, the secret names, the trust tier and the tool
  filter. :func:`plan_digest` is a sha256 over that plan; the install route refuses unless
  the owner's confirmation carries the same digest, so what was shown is what is written.
* **Secrets never sit in the server config.** A secret the manifest declares is stored in the
  hub's encrypted secret store as ``mcp.secret.<server>.<NAME>`` (:func:`store_secrets`) and
  read back only when the server is spawned (stdio env) or connected (an HTTP header
  template). The config keeps the names.
* **Deep links are inert.** :func:`parse_link_config` reads a vendor's ``config=`` payload
  (Cursor/Hermes shape, at most 32 KB), never trusts its environment values (each becomes a
  secret the owner types) and refuses headers; the plan is marked ``origin: "link"`` and
  goes through the same confirmation.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import logging
import re
import shlex
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

logger = logging.getLogger("jarvis.mcp.catalog")

VENDOR_ROOT = Path(__file__).resolve().parents[2] / "vendor" / "hermes"
CATALOG_DIR = "optional-mcps"
MANIFEST_VERSION = 1
#: A deep link's ``config`` (base64) is refused above this many characters (Hermes: 32 KB).
MAX_LINK_CONFIG = 32 * 1024
#: Secret-store name prefixes (``security/secret_broker.py`` treats them as internal).
SECRET_PREFIX = "mcp.secret."  # nosec B105 - a secret-store name prefix, not a secret

NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
_ENV_REF_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
_MANIFEST_OAUTH_KEYS = frozenset({"client_id", "client_secret", "redirect_host", "redirect_port", "scope"})
#: Environment names a link or a manifest may never set on a spawned server: they change what
#: the interpreter loads or where it looks for code, so they are code, not configuration.
_REFUSED_ENV = frozenset({
    "PATH", "LD_PRELOAD", "LD_LIBRARY_PATH", "DYLD_INSERT_LIBRARIES", "DYLD_LIBRARY_PATH",
    "PYTHONPATH", "PYTHONSTARTUP", "PYTHONHOME", "NODE_OPTIONS", "NODE_PATH", "BASH_ENV", "ENV",
    "PERL5OPT", "RUBYOPT", "JAVA_TOOL_OPTIONS", "HOME",
})

STATUS_OK = "ok"
STATUS_FUTURE = "future_manifest"
STATUS_INVALID = "invalid"
STATUS_UNSUPPORTED = "unsupported"
STATUS_TAMPERED = "tampered"


class CatalogError(Exception):
    """A manifest, a link or a plan that cannot be used, with a stable ``reason``."""

    def __init__(self, reason: str, message: str = "") -> None:
        super().__init__(message or reason)
        self.reason = reason
        self.message = message or reason


@dataclass
class SecretSpec:
    name: str
    prompt: str
    required: bool = True
    secret: bool = True
    default: str = ""


@dataclass
class Entry:
    name: str
    path: str
    status: str = STATUS_OK
    problem: str = ""
    description: str = ""
    source: str = ""
    connector_slug: str | None = None
    transport: str = ""
    url: str | None = None
    #: The declared non-secret input the URL is typed into at install (``url: "${NAME}"``).
    url_input: str | None = None
    command: str | None = None
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    auth: str = "none"
    inputs: list[SecretSpec] = field(default_factory=list)
    oauth: dict[str, Any] = field(default_factory=dict)
    tools_allow: list[str] | None = None
    tools_deny: list[str] | None = None
    keywords: list[str] = field(default_factory=list)
    hosts: list[str] = field(default_factory=list)
    post_install: str = ""
    sha256: str = ""

    def summary(self) -> dict:
        return {
            "name": self.name, "status": self.status, "problem": self.problem,
            "description": self.description, "source": self.source,
            "transport": self.transport, "url": self.url,
            "command": _command_line(self.command, self.args) if self.command else None,
            "auth": self.auth,
            "secrets": [{"name": s.name, "prompt": s.prompt, "required": s.required, "secret": s.secret}
                        for s in self.inputs],
            "keywords": list(self.keywords), "hosts": list(self.hosts),
            "post_install": self.post_install, "path": self.path, "sha256": self.sha256,
        }


def _command_line(command: str | None, args: list[str]) -> str:
    return shlex.join([str(command or ""), *[str(a) for a in args]])


# ── reading the vendored catalog ─────────────────────────────────────────────

_cache_lock = threading.Lock()
_cache: dict[str, Any] = {"key": None, "entries": None, "commit": ""}


def _manifest_rows(root: Path) -> tuple[str, dict[str, dict]]:
    try:
        manifest = json.loads((root / "MANIFEST.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CatalogError("catalog_unavailable", "MANIFEST.json cannot be read") from exc
    rows = {f["path"]: f for f in manifest.get("files", [])
            if isinstance(f, dict) and str(f.get("path", "")).startswith(CATALOG_DIR + "/")}
    return str(manifest.get("upstream", {}).get("commit", "")), rows


def load_catalog(root: Path | None = None) -> tuple[str, list[Entry]]:
    """``(commit, entries)``: every vendored manifest, verified against ``MANIFEST.json``.

    A file whose bytes differ from its row (or that has no row) is listed as
    ``tampered`` and can never be installed; a manifest Nerva cannot read is ``invalid``;
    a newer ``manifest_version`` is ``future_manifest``; a manifest that needs a bootstrap
    step (``install:`` git clone + commands) is ``unsupported``."""
    base = Path(root or VENDOR_ROOT)
    try:
        stamp = (base / "MANIFEST.json").stat().st_mtime_ns
    except OSError as exc:
        raise CatalogError("catalog_unavailable", "MANIFEST.json is missing") from exc
    key = (str(base), stamp)
    with _cache_lock:
        if _cache["key"] == key and root is None:
            return _cache["commit"], list(_cache["entries"])
    commit, rows = _manifest_rows(base)
    entries: list[Entry] = []
    folder = base / CATALOG_DIR
    seen: set[str] = set()
    if folder.is_dir() and not folder.is_symlink():
        for sub in sorted(folder.iterdir()):
            rel = f"{CATALOG_DIR}/{sub.name}/manifest.yaml"
            seen.add(rel)
            entries.append(_read_entry(base, rel, rows.get(rel)))
    for rel in sorted(set(rows) - seen):
        entries.append(Entry(name=rel.split("/")[1], path=rel, status=STATUS_TAMPERED,
                             problem="listed in MANIFEST.json but missing"))
    if root is None:
        with _cache_lock:
            _cache.update(key=key, entries=list(entries), commit=commit)
    return commit, entries


def _read_entry(base: Path, rel: str, row: dict | None) -> Entry:
    folder_name = rel.split("/")[1]
    target = base / rel
    if target.is_symlink() or target.parent.is_symlink() or not target.is_file():
        return Entry(name=folder_name, path=rel, status=STATUS_TAMPERED, problem="not a plain file")
    data = target.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if row is None:
        return Entry(name=folder_name, path=rel, status=STATUS_TAMPERED, problem="not in MANIFEST.json")
    if row.get("rules_applied") or not (digest == row.get("vendored_sha256") == row.get("upstream_sha256")):
        return Entry(name=folder_name, path=rel, status=STATUS_TAMPERED,
                     problem="the bytes differ from MANIFEST.json")
    try:
        entry = parse_manifest(data, rel)
    except CatalogError as exc:
        status = STATUS_FUTURE if exc.reason == STATUS_FUTURE else (
            STATUS_UNSUPPORTED if exc.reason == STATUS_UNSUPPORTED else STATUS_INVALID)
        return Entry(name=folder_name, path=rel, status=status, problem=exc.message, sha256=digest)
    if entry.name != folder_name:
        return Entry(name=folder_name, path=rel, status=STATUS_INVALID,
                     problem=f"declares name {entry.name!r} in folder {folder_name!r}", sha256=digest)
    entry.sha256 = digest
    return entry


def find(name: str, root: Path | None = None) -> tuple[str, Entry]:
    commit, entries = load_catalog(root)
    for entry in entries:
        if entry.name == name:
            return commit, entry
    raise CatalogError("not_in_catalog", f"no catalog entry named {name!r}")


def search(entries: list[Entry], query: str = "") -> list[Entry]:
    q = (query or "").strip().lower()
    if not q:
        return list(entries)
    out = []
    for e in entries:
        hay = " ".join([e.name, e.description, e.source, *e.keywords, *e.hosts, e.url or ""]).lower()
        if all(word in hay for word in q.split()):
            out.append(e)
    return out


# ── the manifest reader (Nerva's; schema follows Hermes's mcp_catalog.py) ────

def _str_list(value: Any, where: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(v, str) and v.strip() for v in value):
        raise CatalogError(STATUS_INVALID, f"{where} must be a list of non-empty strings")
    return [v.strip() for v in value]


def _mapping(value: Any, where: str) -> dict:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise CatalogError(STATUS_INVALID, f"{where} must be a mapping")
    return value


def _env_spec(raw: Any) -> SecretSpec:
    if not isinstance(raw, dict):
        raise CatalogError(STATUS_INVALID, "auth.env entries must be mappings")
    name = str(raw.get("name") or "")
    if not ENV_NAME_RE.match(name) or name.upper() in _REFUSED_ENV:
        raise CatalogError(STATUS_INVALID, f"auth.env name {name!r} is not allowed")
    return SecretSpec(name=name, prompt=str(raw.get("prompt") or name)[:200],
                      required=bool(raw.get("required", True)), secret=bool(raw.get("secret", True)),
                      default=str(raw.get("default") or ""))


def api_key_name(server: str) -> str:
    """Hermes's naming contract for an HTTP server's API key (``MCP_<NAME>_API_KEY``)."""
    return "MCP_" + re.sub(r"[^A-Za-z0-9]", "_", server).upper() + "_API_KEY"


def parse_manifest(data: bytes, rel: str = "manifest.yaml") -> Entry:
    import yaml

    try:
        raw = yaml.safe_load(data.decode("utf-8-sig")) or {}
    except Exception as exc:  # any parse failure is a refusal
        raise CatalogError(STATUS_INVALID, f"not plain YAML ({type(exc).__name__})") from exc
    if not isinstance(raw, dict):
        raise CatalogError(STATUS_INVALID, "a manifest must be a mapping")
    version = raw.get("manifest_version")
    if isinstance(version, int) and not isinstance(version, bool) and version > MANIFEST_VERSION:
        raise CatalogError(STATUS_FUTURE, f"manifest_version {version} is newer than this Nerva reads")
    if version != MANIFEST_VERSION:
        raise CatalogError(STATUS_INVALID, f"manifest_version {version!r} is not supported")
    name = str(raw.get("name") or "")
    if not NAME_RE.match(name):
        raise CatalogError(STATUS_INVALID, "missing or invalid name")
    if raw.get("install") is not None:
        raise CatalogError(STATUS_UNSUPPORTED,
                           "needs a bootstrap step (git clone and commands); Nerva does not run those")
    transport = _mapping(raw.get("transport"), "transport")
    t_type = transport.get("type")
    entry = Entry(name=name, path=rel, description=" ".join(str(raw.get("description") or "").split())[:400],
                  source=str(raw.get("source") or ""),
                  post_install=str(raw.get("post_install") or "").strip()[:2000])
    slug = raw.get("connector_slug")
    if slug is not None and (not isinstance(slug, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", slug)):
        raise CatalogError(STATUS_INVALID, "connector_slug must be a slug")
    entry.connector_slug = slug
    if t_type == "http":
        url = str(transport.get("url") or "")
        from agents.core.mcp.http_transport import validate_mcp_url

        typed = re.fullmatch(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", url.strip())
        if typed:
            entry.url_input = typed.group(1)
            url = ""
        else:
            problem = validate_mcp_url(url)
            if problem:
                raise CatalogError(STATUS_INVALID, f"transport.url: {problem}")
        entry.transport, entry.url = "streamable-http", url or None
    elif t_type == "stdio":
        command = transport.get("command")
        args = transport.get("args") or []
        if not isinstance(command, str) or not command.strip():
            raise CatalogError(STATUS_INVALID, "stdio transport requires a command")
        if not isinstance(args, list) or not all(isinstance(a, (str, int, float)) for a in args):
            raise CatalogError(STATUS_INVALID, "transport.args must be a list of strings")
        if any("${INSTALL_DIR}" in str(a) for a in [command, *args]):
            raise CatalogError(STATUS_UNSUPPORTED, "uses ${INSTALL_DIR}; Nerva does not run bootstrap steps")
        entry.transport, entry.command, entry.args = "stdio", command.strip(), [str(a) for a in args]
        env = _mapping(transport.get("env"), "transport.env")
        for key, value in env.items():
            if not isinstance(key, str) or not ENV_NAME_RE.match(key) or key.upper() in _REFUSED_ENV \
                    or not isinstance(value, str):
                raise CatalogError(STATUS_INVALID, f"transport.env {key!r} is not allowed")
        entry.env = dict(env)
    else:
        raise CatalogError(STATUS_INVALID, "transport.type must be 'stdio' or 'http'")
    auth = _mapping(raw.get("auth") or {"type": "none"}, "auth")
    a_type = auth.get("type") or "none"
    if a_type not in ("none", "oauth", "api_key"):
        raise CatalogError(STATUS_INVALID, "auth.type must be none, oauth or api_key")
    entry.auth = a_type
    env_list = auth.get("env") or []
    if not isinstance(env_list, list):
        raise CatalogError(STATUS_INVALID, "auth.env must be a list")
    entry.inputs = [_env_spec(e) for e in env_list]
    if a_type == "oauth" and auth.get("provider"):
        raise CatalogError(STATUS_UNSUPPORTED, "a third-party OAuth provider is not supported")
    if entry.transport == "streamable-http" and a_type == "api_key" \
            and api_key_name(name) not in {s.name for s in entry.inputs}:
        raise CatalogError(STATUS_INVALID, f"http + api_key must declare {api_key_name(name)} in auth.env")
    oauth = _mapping(auth.get("oauth"), "auth.oauth")
    if oauth and a_type != "oauth":
        raise CatalogError(STATUS_INVALID, "auth.oauth is only valid with auth.type oauth")
    unknown = sorted(set(oauth) - _MANIFEST_OAUTH_KEYS)
    if unknown or not all(isinstance(v, (str, int)) and not isinstance(v, bool) for v in oauth.values()):
        raise CatalogError(STATUS_INVALID, f"auth.oauth allows {sorted(_MANIFEST_OAUTH_KEYS)} only")
    declared = {s.name for s in entry.inputs}
    if entry.url_input and entry.url_input not in {s.name for s in entry.inputs if not s.secret}:
        raise CatalogError(STATUS_INVALID, "transport.url names something that is not a declared non-secret input")
    refs = {r for v in oauth.values() if isinstance(v, str) for r in _ENV_REF_RE.findall(v)}
    if refs - declared:
        raise CatalogError(STATUS_INVALID, f"auth.oauth references undeclared names {sorted(refs - declared)}")
    entry.oauth = dict(oauth)
    tools = _mapping(raw.get("tools"), "tools")
    enabled, excluded = tools.get("default_enabled"), tools.get("default_excluded")
    if enabled is not None and excluded is not None:
        raise CatalogError(STATUS_INVALID, "tools.default_enabled and default_excluded are exclusive")
    entry.tools_allow = _str_list(enabled, "tools.default_enabled") if enabled is not None else None
    entry.tools_deny = _str_list(excluded, "tools.default_excluded") if excluded is not None else None
    suggest = _mapping(raw.get("suggest"), "suggest")
    entry.keywords = [k.lower() for k in _str_list(suggest.get("keywords"), "suggest.keywords")]
    entry.hosts = [h.lower().lstrip(".") for h in _str_list(suggest.get("hosts"), "suggest.hosts")]
    return entry


# ── deep links ───────────────────────────────────────────────────────────────

def parse_link_config(name: str, config_b64: str) -> Entry:
    """A vendor's ``config=`` payload (``nerva`` link or Cursor/Hermes shape) as an entry.

    * at most :data:`MAX_LINK_CONFIG` characters of base64, a JSON object;
    * ``command`` (+ ``args``) for stdio or ``url`` for HTTP, nothing else runs;
    * ``env`` values are dropped: each name becomes a secret the owner types, so a link
      can never plant a value; names that steer an interpreter are refused;
    * ``headers`` are refused (a link must not carry a credential)."""
    if not NAME_RE.match(name or ""):
        raise CatalogError("invalid_name", "a link needs a name of letters, digits, - and _")
    raw = (config_b64 or "").strip()
    if not raw:
        raise CatalogError("invalid_link", "the link has no config")
    if len(raw) > MAX_LINK_CONFIG:
        raise CatalogError("link_too_large", f"the link's config is over {MAX_LINK_CONFIG} characters")
    try:
        padded = raw + "=" * (-len(raw) % 4)
        decoded = base64.b64decode(padded.replace("-", "+").replace("_", "/"), validate=True)
        cfg = json.loads(decoded.decode("utf-8"))
    except (binascii.Error, ValueError, UnicodeDecodeError) as exc:
        raise CatalogError("invalid_link", "the link's config is not base64 JSON") from exc
    if not isinstance(cfg, dict):
        raise CatalogError("invalid_link", "the link's config must be a JSON object")
    if cfg.get("headers"):
        raise CatalogError("link_headers_refused", "a link may not carry headers; sign in or type a key instead")
    entry = Entry(name=name, path="link", description="Added from a link; not in the reviewed catalog.")
    if cfg.get("url"):
        from agents.core.mcp.http_transport import validate_mcp_url

        problem = validate_mcp_url(cfg.get("url"))
        if problem:
            raise CatalogError("invalid_link", f"url: {problem}")
        entry.transport, entry.url = "streamable-http", str(cfg["url"]).strip()
    elif cfg.get("command"):
        command, args = cfg.get("command"), cfg.get("args") or []
        if not isinstance(command, str) or not isinstance(args, list) \
                or not all(isinstance(a, (str, int, float)) for a in args):
            raise CatalogError("invalid_link", "command must be a string and args a list")
        entry.transport, entry.command, entry.args = "stdio", command.strip(), [str(a) for a in args]
    else:
        raise CatalogError("invalid_link", "the link names neither a command nor a url")
    env = cfg.get("env") or {}
    if not isinstance(env, dict):
        raise CatalogError("invalid_link", "env must be an object")
    for key in env:
        if not isinstance(key, str) or not ENV_NAME_RE.match(key) or key.upper() in _REFUSED_ENV:
            raise CatalogError("invalid_link", f"env name {key!r} is not allowed")
        entry.inputs.append(SecretSpec(name=key, prompt=key, required=True, secret=True))
    if entry.transport == "streamable-http" and entry.inputs:
        raise CatalogError("invalid_link", "an HTTP link cannot declare env")
    return entry


# ── install plan ─────────────────────────────────────────────────────────────

def build_plan(entry: Entry, *, server_name: str | None = None, origin: str = "catalog",
               commit: str = "", values: dict | None = None) -> dict:
    """The exact configuration an install would write, and what the owner must type.

    *values* are the owner's **non-secret** inputs (a typed server URL, a plain setting):
    they are part of what runs, so they are in the plan and its digest. Secret values never
    are; only their names."""
    if entry.status != STATUS_OK:
        raise CatalogError("not_installable", f"{entry.name}: {entry.status} ({entry.problem})")
    name = server_name or entry.name
    if not NAME_RE.match(name):
        raise CatalogError("invalid_name", "a server name is letters, digits, - and _ (at most 64)")
    values = dict(values or {})
    plain: dict[str, str] = {}
    for spec in entry.inputs:
        if spec.secret:
            continue
        raw = values.get(spec.name)
        if raw is not None and not isinstance(raw, str):
            raise CatalogError("invalid_input", f"{spec.name} must be text")
        value = (raw or "").strip() or spec.default
        if any(ch in value for ch in "\r\n\x00"):
            raise CatalogError("invalid_input", f"{spec.name} holds a line break")
        plain[spec.name] = value
    url = entry.url
    needs = [s.name for s in entry.inputs if not s.secret and s.required and not plain.get(s.name)]
    if entry.url_input:
        url = plain.get(entry.url_input) or None
        if url:
            from agents.core.mcp.http_transport import validate_mcp_url

            problem = validate_mcp_url(url)
            if problem:
                raise CatalogError("invalid_input", f"{entry.url_input}: {problem}")
    env = dict(entry.env)
    if entry.transport == "stdio":
        env.update({k: v for k, v in plain.items() if v})
    secret_env = [s.name for s in entry.inputs if s.secret] if entry.transport == "stdio" else []
    secret_headers: dict[str, str] = {}
    if entry.transport == "streamable-http" and entry.auth == "api_key":
        secret_headers = {"Authorization": "Bearer ${" + api_key_name(entry.name) + "}"}
    command = _command_line(entry.command, entry.args) if entry.command else None
    host = urlsplit(url).hostname if url else None
    plan = {
        "name": name,
        "origin": origin,
        "catalog_name": entry.name if origin == "catalog" else None,
        "commit": commit if origin == "catalog" else None,
        "manifest_sha256": entry.sha256 or None,
        "transport": entry.transport,
        "command": command,
        "url": url,
        "host": host,
        "env": dict(sorted(env.items())),
        "inputs": [{"name": s.name, "prompt": s.prompt, "required": s.required, "default": s.default,
                    "value": plain.get(s.name, "")} for s in entry.inputs if not s.secret],
        "secrets": [{"name": s.name, "prompt": s.prompt, "required": s.required,
                     "has_default": bool(s.default)} for s in entry.inputs if s.secret],
        "needs": needs,
        "secret_env": secret_env,
        "secret_headers": secret_headers,
        "auth": entry.auth,
        "oauth": {k: entry.oauth[k] for k in sorted(entry.oauth)},
        "trust": "read-only",
        "tools_allow": entry.tools_allow,
        "tools_deny": entry.tools_deny,
        "post_install": entry.post_install,
        "starts": "only when you press connect",
    }
    plan["will_run"] = (f"spawn on this hub: {command}" if command
                        else f"connect over HTTPS to {url}" if (url or "").startswith("https")
                        else f"connect to {url}" if url
                        else f"connect to the URL you type for {entry.url_input}")
    plan["digest"] = plan_digest(plan)
    return plan


def plan_digest(plan: dict) -> str:
    body = {k: v for k, v in plan.items() if k != "digest"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def resolve_plan(*, catalog_name: str | None = None, link_name: str | None = None,
                 link_config: str | None = None, server_name: str | None = None,
                 values: dict | None = None, root: Path | None = None) -> tuple[dict, Entry]:
    if link_config is not None:
        entry = parse_link_config(link_name or server_name or "", link_config)
        return build_plan(entry, server_name=server_name or entry.name, origin="link", values=values), entry
    commit, entry = find(catalog_name or "", root)
    return build_plan(entry, server_name=server_name, origin="catalog", commit=commit, values=values), entry


def validate_inputs(entry: Entry, values: dict | None) -> dict[str, str]:
    """The owner's typed **secret** values, checked against the entry's declared secret names.
    Unknown names are refused; a required name with no value and no default is refused."""
    values = dict(values or {})
    specs = {s.name: s for s in entry.inputs if s.secret}
    unknown = sorted(set(values) - set(specs))
    if unknown:
        raise CatalogError("unknown_secret", f"not a declared secret of this server: {unknown}")
    out: dict[str, str] = {}
    for spec in specs.values():
        value = values.get(spec.name)
        if value is not None and not isinstance(value, str):
            raise CatalogError("invalid_secret", f"{spec.name} must be text")
        value = (value or "").strip() or spec.default
        if any(ch in value for ch in "\r\n\x00"):
            raise CatalogError("invalid_secret", f"{spec.name} holds a line break")
        if not value:
            if spec.required:
                raise CatalogError("missing_secret", f"{spec.name} is required ({spec.prompt})")
            continue
        out[spec.name] = value
    return out


# ── server secrets (encrypted store; names only in the config) ───────────────

_STORES: dict[str, Any] = {}


def _store():
    """The hub's encrypted secret store (the file the secret broker and the Integrations panel
    use), one instance per path: opening one derives its key, and the store re-reads its file
    when another writer changed it."""
    from agents.core.paths import data_path
    from agents.core.secrets import SecretStore

    path = str(data_path("security", "secrets.enc"))
    with _cache_lock:
        store = _STORES.get(path)
        if store is None:
            store = _STORES[path] = SecretStore(path=path)
        return store


def secret_name(server: str, var: str) -> str:
    return f"{SECRET_PREFIX}{server}.{var}"


def store_secrets(server: str, values: dict[str, str]) -> list[str]:
    store = _store()
    for var, value in values.items():
        store.set(secret_name(server, var), value)
    return sorted(values)


def read_secret(server: str, var: str) -> str | None:
    try:
        return _store().get(secret_name(server, var))
    except Exception:
        logger.warning("MCP server secret unreadable (server=%s name=%s)", server, var)
        return None


def delete_secrets(server: str) -> int:
    store = _store()
    prefix = f"{SECRET_PREFIX}{server}."
    removed = 0
    for name in list(store.names()):
        if name.startswith(prefix) and store.delete(name):
            removed += 1
    return removed


def secret_env_values(server: str, names: list[str]) -> dict[str, str]:
    """The stored values of *names* for a spawn; a missing one is left out (the server then
    fails as it would without the variable, and the admin list says which is unset)."""
    out = {}
    for var in names or []:
        value = read_secret(server, var)
        if value:
            out[var] = value
    return out


def render_secret_headers(server: str, templates: dict[str, str]) -> dict[str, str] | None:
    """Header templates (``Bearer ${NAME}``) filled from the store; None when one is unset."""
    out = {}
    for header, template in (templates or {}).items():
        missing = False

        def fill(match: re.Match) -> str:
            nonlocal missing
            value = read_secret(server, match.group(1))
            if not value:
                missing = True
                return ""
            return value

        rendered = _ENV_REF_RE.sub(fill, str(template))
        if missing:
            return None
        out[str(header)] = rendered
    return out
