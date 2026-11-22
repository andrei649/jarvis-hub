#!/usr/bin/env python3
"""
ANDREI OS / AI WORKSHOP OS — J.A.R.V.I.S. Local Server (http://localhost:4719)
- Indexes Andrei's real Second Brain (`~/Documents/Andrei OS Obsidian` + the enclosing `jarvis-hub` repo)
  into a 3D Knowledge Galaxy with authentic [[wiki-link]] edges and RAG retrieval.
- Unified Multi-Platform AI Hub:
  Standalone chat defaults to local Ollama and offline vault synthesis. Cloud
  dispatch (including CLI subscriptions and remote models) requires explicit consent.
  1. Anthropic Subscription via official Claude Code CLI (`claude -p`)
  2. Anthropic Console API
  3. Google Gemini API
  4. OpenAI / ChatGPT API
  5. OpenRouter / Custom OpenAI-Compatible (LM Studio / Bonobo RTX 5090)
  6. Local Ollama (`qwen3.5:4b` / `qwen3.5:0.8b`)
  7. Grounded Second Brain RAG Synthesizer fallback
- Serves 3D Robot Workshop, 2D-to-3D Architectural Studio + Miniature, and Computer Use HUD.
"""

from __future__ import annotations

import ast
import datetime as dt
import hashlib
import importlib.util
import ipaddress
import json
import math
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
PUBLIC_DIR = ROOT_DIR / "public"
CONFIG_PATH = ROOT_DIR / "config.json"
DEFAULT_PORT = int(os.environ.get("JARVIS_PORT", "4719"))


def _load_sibling(name: str):
    """Import a module that sits next to this file, without touching `sys.path`.

    The hub loads this file by path too, so a plain `import vault_fs` would depend on
    who started the process.
    """
    qualified = f"jarvis_os_{name}"
    if qualified in sys.modules:
        return sys.modules[qualified]
    spec = importlib.util.spec_from_file_location(qualified, ROOT_DIR / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[qualified] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(qualified, None)
        raise
    return module


# Every read and create under a vault goes through this: handle-relative, no link followed.
vault_fs = _load_sibling("vault_fs")
vault_search = _load_sibling("vault_search")
vault_projects = _load_sibling("vault_projects")
workshop_projects = _load_sibling("workshop_projects")


def _detect_default_vault_path() -> str:
    candidates = [
        ROOT_DIR / "vault" / "Andrei OS Obsidian",
        Path.home() / "Documents" / "Andrei OS Obsidian",
        ROOT_DIR.parent / "Andrei OS Obsidian",
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return str(candidates[1])


def _find_enclosing_hub_root() -> Path | None:
    """Walk up from this app to the jarvis-hub checkout that contains it.

    Works for a normal clone, a renamed clone and a git worktree: the root is
    the first ancestor that has a `.git` entry (directory, or the pointer file a
    worktree uses) next to the hub's own marker docs.
    """
    for parent in ROOT_DIR.parents:
        if not (parent / ".git").exists():
            continue
        if (parent / "NERVA.md").is_file() and (parent / "agents").is_dir():
            return parent
    return None


def _detect_default_nerva_path() -> str:
    enclosing = _find_enclosing_hub_root()
    if enclosing is not None:
        return str(enclosing)
    candidates = [
        Path.home() / "Documents" / "Nerva" / "jarvis-hub",
        Path.home() / "Documents" / "GitHub" / "jarvis-hub",
        ROOT_DIR / "jarvis-hub",
        ROOT_DIR.parent / "Nerva" / "jarvis-hub",
        Path.home() / "jarvis-hub",
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return str(candidates[0])


DEFAULT_VAULT_PATH = _detect_default_vault_path()
DEFAULT_NERVA_PATH = _detect_default_nerva_path()

# Content types for the static files this server serves. Kept on the handler, not
# registered with `mimetypes`: the hub loads this module too, and a process-wide
# registration would change the types the hub serves for its own assets.
STATIC_TYPES = {
    ".js": "text/javascript",
    ".mjs": "text/javascript",
    ".css": "text/css",
    ".svg": "image/svg+xml",
    ".json": "application/json",
}

_extra_bins = [
    str(Path.home() / ".local" / "bin"),
    str(Path.home() / ".local" / "share" / "node-v22" / "bin"),
]
if os.name == "nt":
    appdata = os.environ.get("APPDATA", "")
    localapp = os.environ.get("LOCALAPPDATA", "")
    if appdata:
        _extra_bins.append(str(Path(appdata) / "npm"))
    if localapp:
        _extra_bins.append(str(Path(localapp) / "Programs" / "claude"))
else:
    _extra_bins.extend(["/opt/homebrew/bin", "/usr/local/bin"])
_extra_bins.append(os.environ.get("PATH", ""))
EXTENDED_PATH = os.pathsep.join([p for p in _extra_bins if p])


def nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text or "")


def find_claude_bin() -> str:
    found = shutil.which("claude", path=EXTENDED_PATH)
    if found:
        return found
    candidates = [
        Path.home() / ".local" / "share" / "node-v22" / "bin" / "claude",
        Path.home() / ".local" / "bin" / "claude",
        Path.home() / ".local" / "bin" / "claude.exe",
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return ""


# ==============================================================================
# CONFIGURATION MANAGEMENT
# ==============================================================================
CONFIG_KEYS = (
    "preferredProvider",
    "cloudConsent",
    "allowHardLinks",
    "vaultMode",
    "vaultPath",
    "vaultInclude",
    "vaultExclude",
    "vaultInbox",
    "projectIndex",
    "projectIndexPath",
    "projectRegisterDir",
    "projectIndexSchema",
    "nervaPath",
    "ollamaUrl",
    "ollamaModel",
    "anthropicKey",
    "geminiKey",
    "openaiKey",
    "openrouterKey",
    "openrouterUrl",
    "openrouterModel",
    "elevenlabsKey",
    "elevenlabsVoiceId",
)

PROVIDERS = {"auto", "ollama", "claude_subscription", "anthropic", "gemini", "openai", "openrouter"}
SECRET_KEYS = {"anthropicKey", "geminiKey", "openaiKey", "openrouterKey", "elevenlabsKey"}
BOOLEAN_KEYS = {"cloudConsent", "allowHardLinks", "projectIndex"}


def _normalize_routing(cfg: dict) -> dict:
    """Legacy selection/credentials never constitute consent; malformed values fail closed."""
    cfg = dict(cfg)
    pref = cfg.get("preferredProvider")
    cfg["preferredProvider"] = pref if isinstance(pref, str) and pref in PROVIDERS else "ollama"
    cfg["cloudConsent"] = cfg.get("cloudConsent") is True
    return cfg


def _is_loopback_url(url) -> bool:
    """Parse the authority, never trust a loopback-looking substring of a remote URL."""
    if not isinstance(url, str):
        return False
    try:
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme not in {"http", "https"} or parsed.username or parsed.password:
            return False
        if parsed.query or parsed.fragment or not parsed.port and parsed.netloc.endswith(":"):
            return False
        host = parsed.hostname
        return host == "localhost" or ipaddress.ip_address(host).is_loopback
    except (ValueError, TypeError):
        return False


def _provider_chain(cfg: dict) -> list[str]:
    cfg = _normalize_routing(cfg)
    pref = cfg["preferredProvider"]
    if pref == "auto":
        chain = ["ollama", "claude_subscription", "anthropic", "gemini", "openai", "openrouter"]
    elif pref == "anthropic":
        chain = ["anthropic", "claude_subscription", "ollama"]
    elif pref == "ollama":
        chain = ["ollama"]
    else:
        chain = [pref, "ollama"]
    # Also used by status so the advertised engine respects the dispatch policy.
    return [step for step in chain if _dispatch_allowed(step, cfg)] or []


def _dispatch_allowed(provider: str, cfg: dict) -> bool:
    if cfg.get("cloudConsent") is True:
        return True
    return provider == "ollama" and _is_loopback_url(cfg.get("ollamaUrl", "http://127.0.0.1:11434"))


def _live_dispatch_allowed(provider: str, cfg: dict) -> bool:
    if provider == "ollama" and _is_loopback_url(cfg.get("ollamaUrl", "http://127.0.0.1:11434")):
        return True
    # Revocation stops subsequent fallback dispatches in an already-running turn.
    # New consent never upgrades a request that started without it.
    return cfg.get("cloudConsent") is True and load_config()["cloudConsent"] is True


def _model_opener():
    """Model requests never inherit proxies or follow redirects to another authority."""
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None

    return urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())


def _local_ollama_model(model: dict) -> bool:
    """Positive local artifact metadata; loopback alone does not mean local inference."""
    if not isinstance(model, dict):
        return False
    name, details = model.get("name"), model.get("details")
    return bool(
        isinstance(name, str) and name and "cloud" not in name.lower()
        and model.get("remote_host", "") in ("", None) and model.get("remote_model", "") in ("", None)
        and type(model.get("size")) is int and model["size"] > 0
        and isinstance(details, dict) and isinstance(details.get("format"), str) and details["format"]
    )


def _select_ollama_model(info: dict, cfg: dict) -> str | None:
    available = info.get("models", []) if _live_dispatch_allowed("ollama_cloud", cfg) else info.get("localModels", [])
    desired = cfg.get("ollamaModel") or "qwen3.5:4b"
    return desired if desired in available else next(iter(available), None)


def load_config() -> dict:
    cfg = {
        "preferredProvider": "ollama",
        "cloudConsent": False,
        "allowHardLinks": False,
        "vaultMode": "andrei_plus_nerva",  # andrei_plus_nerva | andrei_os | demo_550
        "vaultPath": DEFAULT_VAULT_PATH,
        "nervaPath": DEFAULT_NERVA_PATH,
        "ollamaUrl": os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434"),
        "ollamaModel": "qwen3.5:4b",
        "anthropicKey": os.environ.get("ANTHROPIC_API_KEY", ""),
        "geminiKey": os.environ.get("GEMINI_API_KEY", ""),
        "openaiKey": os.environ.get("OPENAI_API_KEY", ""),
        "openrouterKey": os.environ.get("OPENROUTER_API_KEY", ""),
        "openrouterUrl": "https://openrouter.ai/api/v1/chat/completions",
        "openrouterModel": "anthropic/claude-sonnet-4",
        "elevenlabsKey": os.environ.get("ELEVENLABS_API_KEY", ""),
        "elevenlabsVoiceId": os.environ.get("ELEVENLABS_VOICE_ID", "onwK4e9ZLuTAKqWW03F9"),
    }
    if CONFIG_PATH.exists():
        try:
            disk = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if not isinstance(disk, dict):
                disk = {}
            for k in CONFIG_KEYS:
                if k in BOOLEAN_KEYS:
                    cfg[k] = disk.get(k) is True
                elif k in ("vaultInclude", "vaultExclude", "vaultInbox") and k in disk:
                    # Keep malformed scope values so the reader or capture refuses them.
                    cfg[k] = disk[k]
                elif k in disk and isinstance(disk[k], str) and disk[k] != "":
                    cfg[k] = disk[k]
        except Exception:
            pass
    # The selected personal vault can be offline. Never substitute another vault.
    if cfg.get("nervaPath") and not Path(cfg["nervaPath"]).exists() and Path(DEFAULT_NERVA_PATH).exists():
        cfg["nervaPath"] = DEFAULT_NERVA_PATH
    return _normalize_routing(cfg)


def save_config(updates: dict) -> dict:
    if not isinstance(updates, dict):
        raise ValueError("Settings must be a JSON object")
    for key in BOOLEAN_KEYS:
        if key in updates and type(updates[key]) is not bool:
            raise ValueError(f"{key} must be a JSON boolean")
    if "preferredProvider" in updates and (
        not isinstance(updates["preferredProvider"], str) or updates["preferredProvider"] not in PROVIDERS
    ):
        raise ValueError("Unknown preferredProvider")
    current = load_config()
    for key in CONFIG_KEYS:
        if key in updates and updates[key] is not None:
            if key in BOOLEAN_KEYS:
                current[key] = updates[key]
                continue
            if not isinstance(updates[key], str):
                raise ValueError(f"{key} must be a string")
            val = str(updates[key]).strip()
            # Empty inputs can result from incomplete status hydration. Clearing a key
            # requires editing the private config; ordinary settings saves retain it.
            if key in SECRET_KEYS and val in {"", "***"}:
                continue
            current[key] = val
    CONFIG_PATH.write_text(json.dumps(current, indent=2), encoding="utf-8")
    invalidate_brain_cache()
    return current


# ==============================================================================
# LIVE RUNTIME STATUS CHECKS (CLAUDE SUBSCRIPTION CLI & OLLAMA)
# ==============================================================================
_STATUS_CACHE = {"claude": (0.0, {}), "ollama": (0.0, {})}
_STATUS_LOCK = threading.Lock()


def check_claude_subscription(force: bool = False) -> dict:
    now = time.time()
    with _STATUS_LOCK:
        ts, cached = _STATUS_CACHE["claude"]
        if not force and (now - ts) < 6.0 and cached:
            return cached

    claude_bin = find_claude_bin()
    if not claude_bin:
        info = {"installed": False, "loggedIn": False, "authMethod": "none", "bin": ""}
    else:
        try:
            env = os.environ.copy()
            env["PATH"] = EXTENDED_PATH
            use_shell = os.name == "nt" and claude_bin.lower().endswith((".cmd", ".bat"))
            proc = subprocess.run(
                [claude_bin, "auth", "status"],
                capture_output=True,
                text=True,
                timeout=4.5,
                env=env,
                shell=use_shell,
            )
            out = (proc.stdout or "") + "\n" + (proc.stderr or "")
            s = out.find("{")
            e = out.rfind("}")
            if s != -1 and e != -1:
                parsed = json.loads(out[s : e + 1])
                info = {
                    "installed": True,
                    "loggedIn": bool(parsed.get("loggedIn")),
                    "authMethod": parsed.get("authMethod", "none"),
                    "subscriptionType": parsed.get("subscriptionType") or parsed.get("plan") or "Claude Subscription",
                    "email": parsed.get("email") or "",
                    "bin": claude_bin,
                }
            else:
                info = {"installed": True, "loggedIn": False, "authMethod": "none", "bin": claude_bin}
        except Exception as exc:
            info = {"installed": True, "loggedIn": False, "error": str(exc), "bin": claude_bin}

    with _STATUS_LOCK:
        _STATUS_CACHE["claude"] = (now, info)
    return info


def check_ollama_status(ollama_url: str, force: bool = False) -> dict:
    now = time.time()
    with _STATUS_LOCK:
        ts, cached = _STATUS_CACHE["ollama"]
        if not force and (now - ts) < 8.0 and cached:
            return cached

    base = (ollama_url or "http://127.0.0.1:11434").rstrip("/")
    try:
        req = urllib.request.Request(f"{base}/api/tags", method="GET")
        with _model_opener().open(req, timeout=1.5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            entries = data.get("models", [])
            models = [m["name"] for m in entries if isinstance(m, dict) and isinstance(m.get("name"), str) and m["name"]]
            local = [m["name"] for m in entries if _local_ollama_model(m)]
            info = {"online": True, "url": base, "models": models, "localModels": local}
    except Exception:
        info = {"online": False, "url": base, "models": []}

    with _STATUS_LOCK:
        _STATUS_CACHE["ollama"] = (now, info)
    return info


# ==============================================================================
# REAL SECOND BRAIN VAULT INDEXER (ANDREI OS OBSIDIAN + NERVA JARVIS HUB)
# ==============================================================================
_BRAIN_CACHE = {"key": None, "data": None, "ts": 0.0, "files": {}}
_BRAIN_LOCK = threading.Lock()


def invalidate_brain_cache():
    with _BRAIN_LOCK:
        _BRAIN_CACHE["key"] = None
        _BRAIN_CACHE["data"] = None
        _BRAIN_CACHE["files"] = {}


HUB_DEFINITIONS = [
    {
        "key": "00 Acasa",
        "title": "00 Acasa",
        "category": "Acasa & Index",
        "color": "#10b981",
        "pos3d": [0, 14, 18],
        "pos2d": [0, 18],
    },
    {
        "key": "01 Personal",
        "title": "01 Personal",
        "category": "Personal",
        "color": "#f43f5e",
        "pos3d": [-34, 18, 16],
        "pos2d": [-44, 24],
    },
    {
        "key": "02 Proiecte",
        "title": "02 Proiecte",
        "category": "Proiecte",
        "color": "#eab308",
        "pos3d": [32, 16, 20],
        "pos2d": [42, 22],
    },
    {
        "key": "03 Infrastructura",
        "title": "03 Infrastructura",
        "category": "Infrastructura",
        "color": "#06b6d4",
        "pos3d": [44, -10, -14],
        "pos2d": [56, -16],
    },
    {
        "key": "04 Sisteme si decizii",
        "title": "04 Sisteme & Decizii",
        "category": "Sisteme & Decizii",
        "color": "#a855f7",
        "pos3d": [-26, -18, 28],
        "pos2d": [-34, -26],
    },
    {
        "key": "05 Colectii",
        "title": "05 Colectii & Jocuri",
        "category": "Colectii",
        "color": "#ec4899",
        "pos3d": [-50, -6, -18],
        "pos2d": [-64, -10],
    },
    {
        "key": "06 Surse & Jurnal",
        "title": "06-08 Surse & Inbox",
        "category": "Jurnal & Inbox",
        "color": "#fb923c",
        "pos3d": [10, 38, -20],
        "pos2d": [14, 48],
    },
    {
        "key": "10 NAS Idei",
        "title": "10 NAS · Idei & Colectii",
        "category": "NAS Idei",
        "color": "#38bdf8",
        "pos3d": [16, -34, 22],
        "pos2d": [22, -46],
    },
    {
        "key": "10 NAS Istoric",
        "title": "10 NAS · Istoric Sesiuni",
        "category": "NAS Istoric",
        "color": "#6366f1",
        "pos3d": [-14, 34, -34],
        "pos2d": [-20, -56],
    },
    {
        "key": "11 Catalog fisiere NAS",
        "title": "11 Catalog Fisiere NAS",
        "category": "Catalog NAS",
        "color": "#64748b",
        "pos3d": [-48, -32, -8],
        "pos2d": [-62, 46],
    },
    {
        "key": "90 Atasamente",
        "title": "90 Atasamente & Harti",
        "category": "Atasamente",
        "color": "#14b8a6",
        "pos3d": [52, 28, -10],
        "pos2d": [66, 38],
    },
    {
        "key": "Nerva Jarvis Hub",
        "title": "Nerva · Jarvis Hub",
        "category": "Nerva Cabinet",
        "color": "#c084fc",
        "pos3d": [56, -24, 26],
        "pos2d": [72, -36],
    },
]


def _classify_vault_hub(rel_parts: tuple[str, ...]) -> str:
    if not rel_parts:
        return "00 Acasa"
    top = nfc(rel_parts[0])
    if top == "00 Acasa":
        return "00 Acasa"
    if top == "01 Personal":
        return "01 Personal"
    if top == "02 Proiecte":
        return "02 Proiecte"
    if top == "03 Infrastructura":
        return "03 Infrastructura"
    if top == "04 Sisteme si decizii":
        return "04 Sisteme si decizii"
    if top == "05 Colectii":
        return "05 Colectii"
    if top in ("06 Surse", "07 Jurnal", "08 Inbox"):
        return "06 Surse & Jurnal"
    if top == "10 NAS":
        sub = nfc(rel_parts[1]) if len(rel_parts) > 1 else ""
        if sub == "Istoric":
            return "10 NAS Istoric"
        return "10 NAS Idei"
    if top == "11 Catalog fisiere NAS":
        return "11 Catalog fisiere NAS"
    if top == "90 Atasamente":
        return "90 Atasamente"
    return "00 Acasa"


def _outside_code_fences(text: str) -> str:
    if "```" not in text and "~~~" not in text:
        return text
    fence = ""
    lines = []
    for line in text.splitlines():
        mark = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line)
        if fence:
            if mark and mark[1].startswith(fence) and not mark[2].strip(" \t"):
                fence = ""
        elif mark and (mark[1][0] == "~" or "`" not in mark[2]):
            fence = mark[1]
            lines.append("")
        else:
            lines.append(line)
    return "\n".join(lines)


def _parse_markdown_content(raw_text: str, fallback_title: str) -> tuple[str, list[str], str, list[str]]:
    text = nfc(raw_text)
    title = fallback_title
    tags: list[str] = []
    body = text

    # Strip YAML frontmatter and harvest title/tags
    if text.startswith("---"):
        end_fm = text.find("\n---", 3)
        if end_fm != -1:
            fm_block = text[3:end_fm]
            body = text[end_fm + 4 :].strip()
            m_title = re.search(r'^title:\s*["\']?(.+?)["\']?\s*$', fm_block, flags=re.MULTILINE)
            if m_title:
                title = m_title.group(1).strip()
            m_tags = re.search(r"^tags:\s*\[([^\]]*)\]", fm_block, flags=re.MULTILINE)
            if m_tags:
                tags = [t.strip().strip("\"'") for t in m_tags.group(1).split(",") if t.strip()]

    # Extract [[WikiLinks]]
    link_text = _outside_code_fences(text)
    raw_links = re.findall(r"\[\[([^\]]+)\]\]", link_text)
    wikilinks = []
    for wl in raw_links:
        target = wl.split("|", 1)[0].split("#", 1)[0].strip()
        if target:
            wikilinks.append(nfc(Path(target).stem if "/" in target else target))

    # Extract relative .md links [label](foo.md)
    md_links = re.findall(r"\[[^\]]+\]\(([^)]+\.(?:md|canvas))\)", link_text)
    for ml in md_links:
        if not ml.startswith(("http://", "https://")):
            decoded = urllib.parse.unquote(ml)
            wikilinks.append(nfc(Path(decoded).stem))

    return title, tags, body, wikilinks


def _det_offset(seed_key: str, min_r: float = 6.5, max_r: float = 21.0) -> tuple[list[float], float]:
    digest = hashlib.sha256(seed_key.encode("utf-8")).digest()
    u1 = int.from_bytes(digest[0:4], "big") / 4294967295.0
    u2 = int.from_bytes(digest[4:8], "big") / 4294967295.0
    u3 = int.from_bytes(digest[8:12], "big") / 4294967295.0
    theta = u1 * math.pi * 2.0
    phi = math.acos(2.0 * u2 - 1.0)
    dist = min_r + (u3 ** 0.72) * (max_r - min_r)
    ox = round(math.sin(phi) * math.cos(theta) * dist, 2)
    oy = round(math.sin(phi) * math.sin(theta) * dist * 0.85, 2)
    oz = round(math.cos(phi) * dist, 2)
    return [ox, oy, oz], theta


_VAULT_EXTENSIONS = (".md", ".canvas", ".html", ".csv", ".json", ".txt")
_VAULT_MANIFESTS = ("vault-manifest.json", "nas-import-manifest.json", "validation.json")
_NOTE_READ_CAP = 350_000
_NERVA_READ_CAP = 220_000


def _vault_wants(name: str) -> bool:
    return name not in _VAULT_MANIFESTS and Path(name).suffix.lower() in _VAULT_EXTENSIONS


def _vault_read_cap(name: str) -> int:
    # Only Markdown is read into the graph; every other type is listed by name and size.
    return _NOTE_READ_CAP if name.lower().endswith(".md") else 0


_NATIVE_UNSAFE = re.compile(r'[<>:"/\\|?*^#%\x00-\x1f\x7f]')


def _native_note_source(vault_name: str, parts: tuple[str, ...], readable: bool) -> dict | None:
    values = (vault_name, *parts)
    if any(not value or value.startswith(".") or value != value.strip() or value.endswith(".")
           or _NATIVE_UNSAFE.search(value) for value in values):
        return None
    try:
        vault_fs.check_name(vault_name)
        for part in parts:
            vault_fs.check_name(part)
    except OSError:
        return None
    return {"vault": vault_name, "file": "/".join(parts), "readable": readable}


def _folder_policy(cfg=None) -> tuple[tuple[tuple[str, ...], ...], tuple[tuple[str, ...], ...]]:
    """Folder lists are semicolon-separated, vault-relative paths; invalid policy refuses all."""
    def parse(key: str, preferred: str, legacy: str) -> tuple[tuple[str, ...], ...]:
        raw = (cfg or {}).get(key, os.environ.get(preferred, os.environ.get(legacy, "")))
        if not isinstance(raw, str):
            raise ValueError("invalid vault scope")
        paths = []
        for item in raw.split(";"):
            item = item.strip().replace("\\", "/")
            if not item:
                if raw.strip():
                    raise ValueError("empty vault folder")
                continue
            if item.startswith("/") or re.match(r"^[A-Za-z]:", item):
                raise ValueError("absolute vault folder")
            parts = tuple(unicodedata.normalize("NFC", p).casefold() for p in item.split("/"))
            if any(p in ("", ".", "..") for p in parts):
                raise ValueError("unsafe vault folder")
            paths.append(parts)
        return tuple(paths)
    return (parse("vaultInclude", "NERVA_OS_VAULT_INCLUDE", "JARVIS_OS_VAULT_INCLUDE"),
            parse("vaultExclude", "NERVA_OS_VAULT_EXCLUDE", "JARVIS_OS_VAULT_EXCLUDE"))


def _vault_path_allowed(parts: tuple[str, ...], includes, excludes, *, directory: bool) -> bool:
    norm = tuple(unicodedata.normalize("NFC", p).casefold() for p in parts)
    if any(norm[:len(p)] == p for p in excludes):
        return False
    if not includes:
        return True
    return any(norm[:len(p)] == p or (directory and p[:len(norm)] == norm) for p in includes)


def _markdown_is_visible(data: bytes, size: int) -> bool:
    """Accept plain notes and simple public YAML headers; refuse undecidable headers."""
    if size >= _NOTE_READ_CAP or len(data) < size:
        return False
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return False
    lines = text.splitlines()
    first = next((i for i, line in enumerate(lines) if line.strip()), None)
    if first is None or not lines[first].strip().startswith("---"):
        return True
    if lines[first].strip() != "---":
        return False
    closing = next((i for i in range(first + 1, len(lines)) if lines[i].strip() in ("---", "...")), None)
    if closing is None or closing - first > 256 or sum(len(line) for line in lines[first + 1:closing]) > 16_384:
        return False
    header = [line.strip() for line in lines[first + 1:closing] if line.strip() and not line.lstrip().startswith("#")]
    if not header:
        return True
    pairs = []
    if len(header) == 1 and header[0].startswith("{"):
        try:
            expression = ast.parse(header[0], mode="eval").body
            if not isinstance(expression, ast.Dict):
                return False
            pairs = [(ast.literal_eval(key), ast.literal_eval(expression.values[index]))
                     for index, key in enumerate(expression.keys)]
        except (SyntaxError, ValueError, TypeError, MemoryError, RecursionError):
            return False
    else:
        for line in header:
            if line.startswith(("-", "?", "[", "{")) or ":" not in line:
                return False
            key, value = (part.strip() for part in line.split(":", 1))
            if key.startswith(("'", '"')):
                try:
                    key = ast.literal_eval(key)
                except (SyntaxError, ValueError):
                    return False
            value = value.split(" #", 1)[0].strip()
            if value.startswith(("'", '"')):
                try:
                    value = ast.literal_eval(value)
                except (SyntaxError, ValueError):
                    return False
            elif value.startswith("[") and value.endswith("]"):
                pass  # ordinary inline tags; privacy below rejects non-scalars
            elif not re.fullmatch(r"[\w .,/:+@-]*", value, flags=re.UNICODE):
                return False
            pairs.append((key, value))
    for key, value in pairs:
        if not isinstance(key, str):
            return False
        if isinstance(value, (dict, tuple, set)) or (isinstance(value, list) and
                                                    (key.casefold().strip() != "tags" or
                                                     any(not isinstance(tag, str) for tag in value))):
            return False
        if unicodedata.normalize("NFKC", key).casefold().strip() == "privacy":
            if not isinstance(value, str):
                return False
            label = re.sub(r"[\s_\u2010-\u2015-]+", "-", unicodedata.normalize("NFKC", value).casefold().strip())
            if label != "public":
                return False
    return True


def _allow_hardlinks(cfg: dict) -> bool:
    """Whether vault files with more than one hard link are indexed. Off unless asked.

    A hard link inside the vault can be a second name for a file outside it, so they are
    skipped by default and counted in the graph's `skipped`. Folders synced by a client
    that hard-links files while uploading them (Google Drive) need this on.
    """
    if str(cfg.get("allowHardLinks", "")).strip().lower() in ("1", "true", "yes", "on"):
        return True
    for name in ("NERVA_OS_ALLOW_HARDLINKS", "JARVIS_OS_ALLOW_HARDLINKS"):
        if os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on"):
            return True
    return False


def _is_public_doc(name: str) -> bool:
    """A repo document fit for the graph. `*.local.md` are owner-specific (gitignored
    personal souls and identities) and never leave the disk through this app."""
    low = name.lower()
    return low.endswith(".md") and not low.startswith(".") and not low.endswith(".local.md")


def _nerva_documents(nerva_dir: Path) -> list:
    """`(parts, entry, data)` for the hub repo's root docs and the first agent docs.

    Read through `vault_fs`, so a symlinked doc or folder is skipped, not followed. Hard
    links are allowed here: this is the checkout the app itself runs from, and whoever can
    link files into it can already change its code.
    """
    docs: list = []
    try:
        repo = vault_fs.VaultFs(nerva_dir, allow_hardlinks=True)
    except OSError:
        return docs
    with repo:
        wanted = [(name,) for name in repo.list_names() if _is_public_doc(name)]
        agent_docs = []
        try:
            agent_dirs = repo.list_names(("agents",))
        except OSError:
            agent_dirs = []
        for sub in agent_dirs:
            if sub.startswith("."):
                continue
            try:
                names = repo.list_names(("agents", sub))
            except OSError:
                continue  # a file, a link, or unreadable
            agent_docs.extend(("agents", sub, name) for name in names if _is_public_doc(name))
        wanted.extend(agent_docs[:20])
        for parts in wanted:
            try:
                entry, data = repo.read_file(parts, _NERVA_READ_CAP)
            except OSError:
                continue
            docs.append((parts, entry, data))
    return docs


#: Where an indexed file came from. Decides which root it is read from and which link
#: policy applies. Recorded by the indexer; never derived from a request's path.
SOURCE_VAULT = "vault"
SOURCE_REPO = "repo"


def _source_roots(cfg: dict) -> tuple[str, Path, Path]:
    vault_mode = cfg.get("vaultMode", "andrei_plus_nerva")
    vault_dir = Path(cfg.get("vaultPath") or DEFAULT_VAULT_PATH)
    nerva_dir = Path(cfg.get("nervaPath") or DEFAULT_NERVA_PATH)
    return vault_mode, vault_dir, nerva_dir


def _cache_key(cfg: dict) -> str:
    """Identity of the exact sources and policy a graph was built from.

    The configured paths and what they resolve to right now, plus the hard-link policy:
    a graph (and its file index) built for one vault, one repo or one policy is never
    reused for another, including when a path string is re-pointed at a different folder.
    """
    vault_mode, vault_dir, nerva_dir = _source_roots(cfg)
    return "|".join((vault_mode, str(vault_dir), os.path.realpath(vault_dir), str(nerva_dir),
                     os.path.realpath(nerva_dir), "links" if _allow_hardlinks(cfg) else "nolinks",
                     repr(_folder_policy(cfg)), repr(vault_projects.settings(cfg)),
                     str(cfg.get("projectIndex", ""))))


def build_real_brain_graph(cfg: dict, *, on_body=None) -> dict:
    vault_mode, vault_dir, nerva_dir = _source_roots(cfg)
    include_nerva = vault_mode == "andrei_plus_nerva" and nerva_dir.exists()

    try:
        includes, excludes = _folder_policy(cfg)
        project_index_path, project_register_dir, project_schema = vault_projects.settings(cfg)
        cache_key = _cache_key(cfg)
    except ValueError:
        invalidate_brain_cache()
        return {"ok": False, "mode": vault_mode, "reason": "invalid vault folder policy", "nodes": []}
    now = time.time()

    if not vault_dir.exists():
        # No graph for this configuration: drop whatever an earlier one left behind, so
        # nothing indexed for another vault stays readable.
        invalidate_brain_cache()
        return {"mode": "demo_550", "reason": f"Vault directory not found: {vault_dir}"}

    nodes: list[dict] = []
    hub_defs_active = [h for h in HUB_DEFINITIONS if h["key"] != "Nerva Jarvis Hub" or include_nerva]

    # 0. Central Core Router Node
    core_node = {
        "index": 0,
        "id": "andrei-os-core",
        "title": "Andrei OS Core",
        "category": "Core",
        "color": "#22c55e",
        "isHub": True,
        "isTopHub": False,
        "hubLabel": "Andrei OS",
        "radius": 3.2,
        "base3d": [0.0, 0.0, 0.0],
        "base2d": [0.0, 0.0],
        "relPath": "",
        "tags": ["andrei-os", "second-brain"],
        "body": f"Obsidian · {vault_dir.name}",
        "wikilinks": [],
    }
    nodes.append(core_node)

    hub_index_by_key: dict[str, int] = {}
    for h in hub_defs_active:
        idx = len(nodes)
        hub_index_by_key[h["key"]] = idx
        nodes.append({
            "index": idx,
            "id": f"hub-{h['key'].lower().replace(' ', '-')}",
            "title": h["title"],
            "category": h["category"],
            "color": h["color"],
            "isHub": True,
            "isTopHub": True,
            "hubLabel": h["title"],
            "radius": 2.45,
            "base3d": list(h["pos3d"]),
            "base2d": list(h["pos2d"]),
            "relPath": h["key"],
            "tags": ["hub"],
            "body": f"Cluster principal din Second Brain: **{h['title']}**.\nSelectează oricare notă conectată pentru a-i citi conținutul complet din vault.",
            "wikilinks": [],
        })

    # Lookup map from normalized stem/title -> node index
    title_to_idx: dict[str, int] = {}

    def register_lookup(name: str, idx: int):
        clean = nfc(name).strip().lower()
        if clean:
            title_to_idx.setdefault(clean, idx)

    # 1. Walk Andrei OS Obsidian
    # Through vault_fs: a symlink, junction or hard-linked file inside the vault is
    # skipped rather than followed, so nothing outside the vault can enter the graph
    # (and from there the model's grounding).
    try:
        vault_handle = vault_fs.VaultFs(vault_dir, allow_hardlinks=_allow_hardlinks(cfg))
    except OSError as exc:
        invalidate_brain_cache()
        return {"mode": "demo_550", "reason": f"Vault cannot be opened: {exc.strerror or exc}"}
    # relPath -> (source, root, on-disk path components): the only files the note route
    # serves. The source is recorded here, by the indexer that opened the file.
    indexed_files: dict[str, tuple[str, str, tuple[str, ...]]] = {}
    ambiguous_files: set[str] = set()
    project_note_files: dict[int, str] = {}
    project_index_enabled = cfg.get("projectIndex", os.environ.get(
        "NERVA_OS_PROJECT_INDEX", os.environ.get("JARVIS_OS_PROJECT_INDEX", "")) == "1") is True
    project_source = None
    with vault_handle as vault_files:
        for parts, entry, data in vault_files.walk(
            want=_vault_wants, cap=_vault_read_cap,
            allow_dir=lambda p: _vault_path_allowed(p, includes, excludes, directory=True),
            allow_file=lambda p: _vault_path_allowed(p, includes, excludes, directory=False),
        ):
            fn = parts[-1]
            ext = Path(fn).suffix.lower()
            rel_str = nfc("/".join(parts))
            stem = nfc(Path(fn).stem)
            hub_key = _classify_vault_hub(parts)
            if ext == ".canvas" and hub_key != "90 Atasamente":
                # Keep .canvas visual maps in their semantic hub with slightly larger radius
                pass
            parent_idx = hub_index_by_key.get(hub_key, 1)
            parent_hub = nodes[parent_idx]

            is_dataless = entry.dataless
            size = entry.size
            if ext == ".md" and (is_dataless or not _markdown_is_visible(data, size)):
                continue

            title = stem
            tags: list[str] = []
            wikilinks: list[str] = []
            if ext == ".md" and not is_dataless and size < 350_000:
                try:
                    raw = data.decode("utf-8", errors="replace")
                    title, tags, body, wikilinks = _parse_markdown_content(raw, stem)
                except Exception:
                    body = f"Notă din `{rel_str}` ({size} bytes)."
            elif ext == ".canvas" and not is_dataless and size < 200_000:
                body = f"Hartă vizuală Obsidian Canvas (`{rel_str}`, {size} bytes)."
                tags = ["canvas"]
            else:
                status_note = "stocată în iCloud Drive (click pentru hidratare live)" if is_dataless else f"atașament local ({size:,} bytes)"
                body = f"Fișier indexat din `{rel_str}` — {status_note}."

            offset3d, theta = _det_offset(rel_str)
            dist2d = math.hypot(offset3d[0], offset3d[2]) * 1.15
            idx = len(nodes)
            node_obj = {
                "index": idx,
                "id": f"vault-{idx}",
                "title": title,
                "stem": stem,
                "category": parent_hub["category"],
                "color": parent_hub["color"],
                "parentHubIndex": parent_idx,
                "offset3d": offset3d,
                "base3d": [
                    round(parent_hub["base3d"][0] + offset3d[0], 2),
                    round(parent_hub["base3d"][1] + offset3d[1], 2),
                    round(parent_hub["base3d"][2] + offset3d[2], 2),
                ],
                "base2d": [
                    round(parent_hub["base2d"][0] + math.cos(theta) * dist2d, 2),
                    round(parent_hub["base2d"][1] + math.sin(theta) * dist2d, 2),
                ],
                "radius": 1.35 if ext == ".canvas" else (1.12 if hub_key in ("00 Acasa", "02 Proiecte", "03 Infrastructura", "04 Sisteme si decizii") else 0.86),
                "relPath": rel_str,
                "sourceVault": vault_dir.name,
                "cloudEvicted": is_dataless,
                "tags": tags,
                "body": body[:3800],
                "wikilinks": wikilinks,
            }
            if ext == ".md" and "```nerva-workshop" in body:
                node_obj["workshopProject"] = True
            nodes.append(node_obj)
            if rel_str in indexed_files:
                indexed_files.pop(rel_str)
                ambiguous_files.add(rel_str)
            elif rel_str not in ambiguous_files:
                indexed_files[rel_str] = (SOURCE_VAULT, str(vault_dir), parts)
            if ext == ".md":
                source = _native_note_source(vault_dir.name, parts, True)
                if source is not None:
                    node_obj["obsidianSource"] = source
                if on_body is not None:
                    on_body(node_obj, body)
            register_lookup(stem, idx)
            register_lookup(title, idx)
            if project_index_enabled and rel_str == project_index_path:
                # A register row grants access to its summary. Its filename can
                # supply a native link without admitting the note body to the index.
                records = []
                try:
                    meta, payload = vault_files.read_file(parts, vault_projects.MAX_BYTES + 1)
                    if meta.dataless or len(payload) != meta.size:
                        raise ValueError("incomplete project index")
                    records = vault_projects.project_records(payload, index_path=project_index_path,
                                                            schema=project_schema)
                    detail = f"{len(records)} project summaries indexed"
                    status = "connected"
                except (ValueError, OSError):
                    status, detail = "unavailable", "Project index could not be read"
                project_source = {"name": "Project register", "path": rel_str, "status": status, "detail": detail}
                node_obj.update(title="Project register", body=detail)
                for record in records:
                    note_file = record.pop("noteFile")
                    offset, _ = _det_offset(record["projectId"], 3.0, 10.0)
                    child = {**node_obj, **record, "index": len(nodes), "id": record["projectId"],
                             "stem": record["title"], "parentHubIndex": idx, "offset3d": offset,
                             "base3d": [round(coord + offset[axis], 2) for axis, coord in enumerate(node_obj["base3d"])],
                             "base2d": [node_obj["base2d"][0] + offset[0], node_obj["base2d"][1] + offset[2]]}
                    nodes.append(child)
                    project_note_files[child["index"]] = note_file
                    register_lookup(record["projectId"], child["index"])
        for node in nodes:
            if node.get("relPath") in ambiguous_files:
                node.pop("obsidianSource", None)
        if project_note_files and _vault_path_allowed(tuple(project_register_dir.split("/")), (), excludes, directory=True):
            try:
                register_dir = vault_files.open_dir(tuple(project_register_dir.split("/")))
            except OSError:
                register_dir = None
            if register_dir is not None:
                try:
                    for index, note_file in project_note_files.items():
                        parts = (*project_register_dir.split("/"), note_file)
                        if not _vault_path_allowed(parts, (), excludes, directory=False):
                            continue
                        source = _native_note_source(vault_dir.name, parts, False)
                        if source is None:
                            continue
                        try:
                            entry, _ = vault_files.read_in(register_dir, note_file, 0)
                        except (OSError, ValueError):
                            continue
                        if entry.dataless:
                            continue
                        found = indexed_files.get(nfc("/".join(parts)))
                        source["readable"] = bool(found and found[0] == SOURCE_VAULT and found[2] == parts)
                        nodes[index]["obsidianSource"] = source
                finally:
                    vault_files.close_dir(register_dir)
        skipped_files = list(vault_files.skipped)

    # 2. Optional: Merge Nerva / Jarvis Hub local architecture docs
    if include_nerva and "Nerva Jarvis Hub" in hub_index_by_key:
        nerva_hub_idx = hub_index_by_key["Nerva Jarvis Hub"]
        nerva_hub = nodes[nerva_hub_idx]
        for doc_parts, doc_entry, doc_data in _nerva_documents(nerva_dir):
            if doc_entry.dataless or not _markdown_is_visible(doc_data, doc_entry.size):
                continue
            is_dl = doc_entry.dataless
            rel_n = nfc("/".join(doc_parts))
            doc_stem = Path(doc_parts[-1]).stem
            label = f"Nerva · {doc_stem}" if len(doc_parts) == 1 else f"Agent · {doc_parts[-2]} ({doc_stem})"

            if not is_dl and doc_entry.size < _NERVA_READ_CAP:
                try:
                    raw = doc_data.decode("utf-8", errors="replace")
                    _, tags, body, wls = _parse_markdown_content(raw, label)
                except Exception:
                    tags, body, wls = ["nerva"], f"Document Nerva `{rel_n}`", []
            else:
                tags, body, wls = ["nerva"], f"Document Nerva `{rel_n}` ({doc_entry.size:,} bytes).", []

            offset3d, theta = _det_offset(f"nerva:{rel_n}", 6.0, 18.0)
            dist2d = math.hypot(offset3d[0], offset3d[2]) * 1.15
            idx = len(nodes)
            nodes.append({
                "index": idx,
                "id": f"nerva-{idx}",
                "title": label,
                "stem": label,
                "category": "Nerva Cabinet",
                "color": nerva_hub["color"],
                "parentHubIndex": nerva_hub_idx,
                "offset3d": offset3d,
                "base3d": [
                    round(nerva_hub["base3d"][0] + offset3d[0], 2),
                    round(nerva_hub["base3d"][1] + offset3d[1], 2),
                    round(nerva_hub["base3d"][2] + offset3d[2], 2),
                ],
                "base2d": [
                    round(nerva_hub["base2d"][0] + math.cos(theta) * dist2d, 2),
                    round(nerva_hub["base2d"][1] + math.sin(theta) * dist2d, 2),
                ],
                "radius": 1.05 if doc_parts[-1] in ("README.md", "NERVA_VISION.md", "HERMES_STATUS.md", "SOUL.md") else 0.82,
                "relPath": f"Nerva/jarvis-hub/{rel_n}",
                "sourceVault": "Nerva Jarvis Hub",
                "cloudEvicted": is_dl,
                "tags": tags or ["nerva", "jarvis-hub"],
                "body": body[:3800],
                "wikilinks": wls + ["Nerva si Jarvis Hub", "Hermes personal OS"],
            })
            if on_body is not None:
                on_body(nodes[-1], body)
            register_lookup(label, idx)
            # A vault note at this path keeps its policy; normalized aliases in either
            # source never gain an allowlist entry by falling back to the repo.
            key = f"Nerva/jarvis-hub/{rel_n}"
            if key not in ambiguous_files:
                found = indexed_files.get(key)
                if found is None:
                    indexed_files[key] = (SOURCE_REPO, str(nerva_dir), doc_parts)
                elif found[0] == SOURCE_REPO:
                    indexed_files.pop(key)
                    ambiguous_files.add(key)

    # 3. Build Real Edges (Core <-> Hubs, Note <-> Parent Hub, Authentic [[WikiLinks]], Semantic Entity Mentions)
    edge_set: set[str] = set()
    edges: list[list[int]] = []
    degree = [0] * len(nodes)

    def add_edge(a: int, b: int):
        if a == b or a < 0 or b < 0 or a >= len(nodes) or b >= len(nodes):
            return
        u, v = (a, b) if a < b else (b, a)
        key = f"{u}:{v}"
        if key in edge_set:
            return
        edge_set.add(key)
        edges.append([u, v])
        degree[u] += 1
        degree[v] += 1

    hub_indices = list(hub_index_by_key.values())
    for pos_i, h_idx in enumerate(hub_indices):
        add_edge(0, h_idx)
        if pos_i + 1 < len(hub_indices):
            add_edge(h_idx, hub_indices[pos_i + 1])
    if len(hub_indices) > 2:
        add_edge(hub_indices[0], hub_indices[-1])

    # Connect notes to their parent hub + resolve [[wikilinks]]
    canonical_keywords = {
        "bonobo": "bonobo",
        "jarvis": "nerva si jarvis hub",
        "nerva": "nerva si jarvis hub",
        "hermes": "hermes personal os",
        "digitaholic": "digitaholic si venit 50k",
        "ipod": "atelier ipod si muzica",
        "macbook 2010": "macbook 2010",
        "ing": "interviu ing",
        "jocuri": "biblioteca de jocuri",
        "ugreen": "nas ugreen",
        "home assistant": "retea si home assistant",
    }

    for n in nodes:
        idx = n["index"]
        p_idx = n.get("parentHubIndex")
        if p_idx is not None:
            add_edge(idx, p_idx)

        for wl in n.get("wikilinks", []):
            target_idx = title_to_idx.get(wl.lower())
            if target_idx is not None:
                add_edge(idx, target_idx)

        # Entity bridge from title keywords
        t_low = n["title"].lower()
        for kw, target_name in canonical_keywords.items():
            if re.search(r"(?<!\w)" + re.escape(kw) + r"(?!\w)", t_low):
                t_idx = title_to_idx.get(target_name)
                if t_idx is not None:
                    add_edge(idx, t_idx)

    # Bridge Nerva hub directly to `02 Proiecte/Nerva si Jarvis Hub`
    if include_nerva and "Nerva Jarvis Hub" in hub_index_by_key:
        nerva_note_idx = title_to_idx.get("nerva si jarvis hub")
        if nerva_note_idx is not None:
            add_edge(hub_index_by_key["Nerva Jarvis Hub"], nerva_note_idx)

    # Update hub displayCount and sort Top Hubs
    top_hubs = []
    for h in hub_defs_active:
        h_idx = hub_index_by_key[h["key"]]
        cnt = degree[h_idx]
        nodes[h_idx]["displayCount"] = cnt
        top_hubs.append({
            "id": nodes[h_idx]["id"],
            "nodeIndex": h_idx,
            "title": h["title"],
            "displayCount": cnt,
            "color": h["color"],
        })
    top_hubs.sort(key=lambda x: x["displayCount"], reverse=True)

    # Category summary for top-right Filter panel
    cat_counts: dict[str, dict] = {}
    for n in nodes:
        cat = n["category"]
        if cat not in cat_counts:
            cat_counts[cat] = {"id": cat, "count": 0, "color": n["color"]}
        cat_counts[cat]["count"] += 1
    categories = sorted(cat_counts.values(), key=lambda c: c["count"], reverse=True)

    # Strip internal `wikilinks` array from client payload to keep JSON ultra-compact
    public_nodes = [{k: v for k, v in n.items() if k != "wikilinks"} for n in nodes]
    markdown_count = sum(source == SOURCE_VAULT and path.lower().endswith(".md")
                         for path, (source, _, _) in indexed_files.items())
    sources = [{"name": vault_dir.name, "path": str(vault_dir), "status": "connected",
                "detail": f"{markdown_count} Markdown notes indexed"}]
    if project_index_enabled:
        sources.append(project_source or {"name": "Project register", "path": project_index_path,
                                         "status": "unavailable", "detail": "Project index outside the visible vault or absent"})
    if include_nerva:
        count = sum(n.get("sourceVault") == "Nerva Jarvis Hub" for n in nodes)
        sources.append({"name": "Nerva / Jarvis Hub", "path": str(nerva_dir), "status": "connected",
                        "detail": f"{count} repository documents indexed"})

    result = {
        "ok": True,
        "mode": vault_mode,
        "brandTitle": "ANDREI OS",
        "vaultLabel": vault_dir.name + (" + Nerva Hub" if include_nerva else ""),
        "vaultPath": str(vault_dir),
        "nervaPath": str(nerva_dir),
        # Vault entries left out because they are links (never followed): a count and the
        # reasons, so an incomplete graph is explained rather than silent.
        "skipped": {
            "count": len(skipped_files),
            "reasons": {reason: sum(1 for _p, r in skipped_files if r == reason)
                        for reason in sorted({r for _p, r in skipped_files})},
        },
        "nodes": public_nodes,
        "edges": edges,
        "categories": categories,
        "topHubs": top_hubs[:10],
        "discoveredSources": sources,
    }

    with _BRAIN_LOCK:
        _BRAIN_CACHE["key"] = cache_key
        _BRAIN_CACHE["data"] = result
        _BRAIN_CACHE["files"] = indexed_files
        _BRAIN_CACHE["ts"] = now
    return result


INBOX_FOLDER = "08 Inbox"


def configured_inbox(cfg: dict) -> str:
    folder = cfg.get("vaultInbox", os.environ.get("NERVA_OS_VAULT_INBOX", os.environ.get("JARVIS_OS_VAULT_INBOX", INBOX_FOLDER)))
    return folder.strip().replace("\\", "/") if isinstance(folder, str) else ""


class ChatNoteConflict(ValueError):
    """A request ID was reused or its previously saved note changed."""
    code = "conflict"


class ChatNoteTitleConflict(ChatNoteConflict):
    code = "title_conflict"


class ChatNoteChanged(ChatNoteConflict):
    code = "note_changed"


def _chat_note_scope(cfg: dict, files, folder: int | None) -> tuple[dict, tuple[str, ...]]:
    inbox = configured_inbox(cfg)
    parts = tuple(inbox.split("/"))
    if any(not part or part.startswith(".") for part in parts):
        raise vault_fs.UnsafePath("invalid inbox folder")
    for part in parts:
        vault_fs.check_name(part)
    try:
        includes, excludes = _folder_policy(cfg)
    except ValueError as exc:
        raise vault_fs.UnsafePath("invalid vault folder policy") from exc
    if not _vault_path_allowed((*parts, "chat-note.md"), includes, excludes, directory=False):
        raise vault_fs.UnsafePath("inbox outside the allowed folders")
    root = Path(cfg["vaultPath"]).resolve(strict=True)
    identity = files.root_identity() if inbox == INBOX_FOLDER else files.folder_identity(folder)
    binding = json.dumps((str(root), identity, inbox,
                          cfg.get("vaultInclude", ""), cfg.get("vaultExclude", "")),
                         ensure_ascii=False, separators=(",", ":"))
    target_id = "v1-" + hashlib.sha256(binding.encode("utf-8")).hexdigest()
    return {"id": target_id, "vault": root.name, "inbox": inbox}, parts


def chat_note_target(cfg: dict) -> dict | None:
    """The current, physically bound and writable vault inbox, if one exists."""
    try:
        with vault_fs.VaultFs(cfg["vaultPath"]) as files:
            inbox = tuple(configured_inbox(cfg).split("/"))
            try:
                folder = files.open_dir(inbox)
            except FileNotFoundError:
                if configured_inbox(cfg) != INBOX_FOLDER:
                    raise
                folder = None
            try:
                target, _ = _chat_note_scope(cfg, files, folder)
                return target
            finally:
                if folder is not None:
                    files.close_dir(folder)
    except (OSError, ValueError):
        return None


def _chat_note_name(title: str, request_id: str | None = None) -> str:
    # The old UUID suffix remains available only for replaying v1 receipts.
    clean = re.sub(r'[<>:"/\\|?*^#%\x00-\x1f\x7f]', "-", unicodedata.normalize("NFC", title)).strip(" .-")
    result, utf8, utf16 = "", 0, 0
    limit = 200 if request_id else 240
    for char in clean:
        size8, size16 = len(char.encode("utf-8")), len(char.encode("utf-16-le")) // 2
        if utf8 + size8 > limit or utf16 + size16 > limit:
            break
        result += char
        utf8 += size8
        utf16 += size16
    result = result.rstrip(" .-") or "Note"
    if request_id:
        return f"{result} - {request_id}.md"
    if result.casefold().endswith(".md"):
        result = result[:-3].rstrip(" .-") or "Note"
    stem, dot, rest = result.partition(".")
    if re.fullmatch(r"(?:CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³])", stem, re.I):
        result = stem + "-Note" + dot + rest
    return result + ".md"


def save_chat_note(cfg: dict, target_id: str, request_id: str, title: str, content: str) -> dict:
    """Persist exactly the reviewed body; a UUID identifies one immutable save intent."""
    data = content.encode("utf-8")
    marker = f".chat-note-{request_id}.json"
    name = _chat_note_name(title)
    digest = hashlib.sha256(data).hexdigest()
    receipt = json.dumps({"version": 2, "title": title, "sha256": digest, "file": name},
                         ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    with vault_fs.VaultFs(cfg["vaultPath"]) as files:
        inbox = tuple(configured_inbox(cfg).split("/"))
        default_inbox = configured_inbox(cfg) == INBOX_FOLDER
        try:
            folder = files.open_dir(inbox)
        except FileNotFoundError:
            if not default_inbox:
                raise
            folder = None
        try:
            target, parts = _chat_note_scope(cfg, files, folder)
            if target_id != target["id"]:
                raise ChatNoteConflict("capture target changed")
            includes, excludes = _folder_policy(cfg)
            if not _vault_path_allowed((*parts, name), includes, excludes, directory=False):
                raise vault_fs.UnsafePath("note outside the allowed folders")
            if folder is None:
                folder = files.open_dir(inbox, create=True)
            marker_preexisting = False
            try:
                files.publish_in(folder, marker, receipt)
            except FileExistsError:
                marker_preexisting = True
                entry, existing = files.read_in(folder, marker, 2048)
                if entry.size > 2048 or len(existing) != entry.size:
                    raise ChatNoteConflict("request ID already used") from None
                try:
                    previous = json.loads(existing)
                except (ValueError, UnicodeDecodeError):
                    raise ChatNoteConflict("request ID already used") from None
                if (not isinstance(previous, dict) or previous.get("title") != title
                        or previous.get("sha256") != digest):
                    raise ChatNoteConflict("request ID already used") from None
                if previous.get("version") == 2 and previous.get("file") == name:
                    pass
                elif set(previous) == {"title", "sha256"}:
                    name = _chat_note_name(title, request_id)
                else:
                    raise ChatNoteConflict("request ID already used") from None
            try:
                files.publish_in(folder, name, data)
            except FileExistsError:
                try:
                    entry, existing = files.read_in(folder, name, len(data) + 1)
                except vault_fs.UnsafePath:
                    # A concurrent publisher can still hold its temporary link to this title.
                    if marker_preexisting:
                        raise
                    raise ChatNoteTitleConflict("title already exists") from None
                if entry.size != len(data) or existing != data:
                    if marker_preexisting:
                        raise ChatNoteChanged("saved note changed") from None
                    raise ChatNoteTitleConflict("title already exists") from None
        finally:
            if folder is not None:
                files.close_dir(folder)
    invalidate_brain_cache()
    rel = nfc("/".join((*parts, name)))
    return {"ok": True, "relPath": rel,
            "source": _native_note_source(target["vault"], (*parts, name), True)}


def capture_inbox_note(cfg: dict, title: str, content: str, links: list[str] | None = None,
                       *, reindex: bool = True) -> dict:
    """Create a new note in the vault's inbox. Never overwrites, never leaves the vault.

    The note is created through `vault_fs`: relative to the handle of the verified inbox
    folder, exclusively. An inbox (or vault ancestor) that is a symlink or junction is
    refused with `vault_fs.UnsafePath` before anything is written, and there is no
    path-based fallback. On a name collision the next free "<title> (n)" is taken.
    """
    vault_dir = Path(cfg.get("vaultPath") or DEFAULT_VAULT_PATH)
    inbox = configured_inbox(cfg)
    parts = tuple(inbox.split("/"))
    if any(not part or part.startswith(".") or ":" in part for part in parts):
        raise vault_fs.UnsafePath("invalid inbox folder")
    try:
        includes, excludes = _folder_policy(cfg)
    except ValueError as exc:
        raise vault_fs.UnsafePath("invalid vault folder policy") from exc
    if not _vault_path_allowed((*parts, "capture.md"), includes, excludes, directory=False):
        raise vault_fs.UnsafePath("inbox outside the allowed folders")

    base_title = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', "-", (title or "").strip()).strip("-. ")
    if not base_title:
        base_title = f"Nota JARVIS {dt.datetime.now().strftime('%Y-%m-%d %H-%M')}"
    base_title = base_title[:120].rstrip(". ")

    now_iso = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    default_links = ["Acasa"] if inbox == INBOX_FOLDER else []
    link_str = " · ".join(f"[[{link.strip('[]')}]]" for link in (links or default_links) if link.strip())

    with vault_fs.VaultFs(vault_dir) as vault_files:
        attempt = 1
        while True:
            clean_title = base_title if attempt == 1 else f"{base_title} ({attempt})"
            md = (
                f"---\n"
                f'title: "{clean_title}"\n'
                f'created: "{now_iso}"\n'
                f'status: "inbox"\n'
                f'source: "JARVIS AI Workshop OS"\n'
                f"tags: [andrei-os, inbox]\n"
                f"---\n\n"
                f"# {clean_title}\n\n"
                f"{(content or '').strip()}\n\n"
                f"{link_str}\n"
            )
            try:
                file_name = f"{clean_title}.md"
                if not _vault_path_allowed((*parts, file_name), includes, excludes, directory=False):
                    raise vault_fs.UnsafePath("note outside the allowed folders")
                vault_files.create_exclusive(parts, file_name, md.encode("utf-8"), create_dirs=inbox == INBOX_FOLDER)
                break
            except FileExistsError:
                attempt += 1
                if attempt > 999:
                    raise

    target_file = vault_dir.joinpath(*parts, file_name)
    rel = nfc("/".join((*parts, file_name)))
    if not reindex:
        invalidate_brain_cache()
        return {"ok": True, "path": str(target_file), "relPath": rel}
    invalidate_brain_cache()
    graph = build_real_brain_graph(cfg)
    created_node = next((n for n in graph.get("nodes", []) if n.get("relPath") == rel), None)
    return {"ok": True, "path": str(target_file), "node": created_node, "brain": graph}


def read_indexed_note(cfg: dict, rel_path: str, *, target_id: str | None = None) -> tuple[str, list[str], str, list[str]]:
    """`(title, tags, body, wikilinks)` of a Markdown note the graph itself indexed.

    The lookup is an allowlist, not a path check: only a `relPath` that the current graph
    produced is served, and only Markdown. So a request can name nothing the indexer did
    not already choose to show: not `config.json`, not `.env`, not a `*.local.md`, not a
    file reached through a link. The file is then read through `vault_fs` from the on-disk
    components recorded at index time. Raises `ValueError` for anything else.
    """
    rel = nfc(rel_path or "").replace("\\", "/")
    try:
        cache_key = _cache_key(cfg)
    except ValueError:
        raise ValueError("not an indexed note") from None
    with _BRAIN_LOCK:
        found = _BRAIN_CACHE["files"].get(rel) if _BRAIN_CACHE["key"] == cache_key else None
    if found is None:
        build_real_brain_graph(cfg)
        with _BRAIN_LOCK:
            found = _BRAIN_CACHE["files"].get(rel) if _BRAIN_CACHE["key"] == cache_key else None
    if found is None or not rel.lower().endswith(".md"):
        raise ValueError("not an indexed note")
    return _read_indexed_note_found(cfg, found, target_id=target_id)


def _read_indexed_note_found(cfg: dict, found, *, target_id: str | None = None) -> tuple[str, list[str], str, list[str]]:
    source, base_dir, parts = found
    _mode, vault_dir, nerva_dir = _source_roots(cfg)
    # The trust domain is what the indexer recorded for this file, never the shape of the
    # requested path: a vault note stored under "Nerva/jarvis-hub/" is still a vault note.
    if source == SOURCE_REPO:
        expected_root, allow_links = nerva_dir, True
    elif source == SOURCE_VAULT:
        expected_root, allow_links = vault_dir, _allow_hardlinks(cfg)
        includes, excludes = _folder_policy(cfg)
        if not _vault_path_allowed(parts, includes, excludes, directory=False):
            raise ValueError("not an indexed note")
    else:
        raise ValueError("not an indexed note")
    if base_dir != str(expected_root):
        raise ValueError("not an indexed note")
    with vault_fs.VaultFs(expected_root, allow_hardlinks=allow_links) as files:
        if target_id is None:
            entry, data = files.read_file(parts, _NOTE_READ_CAP)
        else:
            inbox = tuple(configured_inbox(cfg).split("/"))
            if source != SOURCE_VAULT or parts[:-1] != inbox:
                raise ValueError("not in the saved inbox")
            folder = files.open_dir(inbox)
            try:
                # Bind the check and the file read to the same open folder.
                target, _ = _chat_note_scope(cfg, files, folder)
                if target["id"] != target_id:
                    raise ValueError("vault destination changed")
                entry, data = files.read_in(folder, parts[-1], _NOTE_READ_CAP)
            finally:
                files.close_dir(folder)
    if entry.dataless or not _markdown_is_visible(data, entry.size):
        raise ValueError("not an indexed note")
    return _parse_markdown_content(data.decode("utf-8-sig"), Path(parts[-1]).stem)


# ==============================================================================
# SECOND BRAIN RAG RETRIEVAL + MULTI-PLATFORM AI ROUTER
# ==============================================================================
SYNONYM_EXPANSIONS = {
    "project": ["proiecte", "portofoliu", "nerva", "digitaholic", "vizibil", "hermes"],
    "projects": ["proiecte", "portofoliu", "nerva", "digitaholic", "vizibil", "hermes"],
    "hardware": ["infrastructura", "bonobo", "mac", "nas", "ugreen", "raspberry", "5090"],
    "pc": ["bonobo", "infrastructura", "5090", "gaming"],
    "server": ["infrastructura", "nas", "ugreen", "bonobo", "mac mini"],
    "games": ["jocuri", "colectii", "biblioteca", "catalog"],
    "game": ["jocuri", "colectii", "biblioteca"],
    "memory": ["memorie", "sincronizare", "vault", "acasa", "brain"],
    "brain": ["acasa", "memorie", "biblioteca brain", "andrei"],
    "who am i": ["andrei", "personal", "preferinte", "cariera"],
    "about me": ["andrei", "personal", "preferinte", "portofoliu"],
    "models": ["rutarea modelelor", "claude", "hermes", "bonobo"],
    "finance": ["finante", "venit 50k", "digitaholic"],
    "family": ["familie", "beads and blush"],
}


def retrieve_vault_context(query: str, cfg: dict, top_k: int = 6) -> tuple[str, list[dict]]:
    if cfg.get("vaultMode") == "demo_550":
        return "", []
    terms, related = vault_search.query_terms(query, SYNONYM_EXPANSIONS)
    if top_k <= 0 or not (terms or related):
        return "", []
    scored = []

    def score_body(node, body):
        literal, expanded = vault_search.score(node, terms, related, body=body)
        if literal or expanded:
            scored.append((literal, expanded, node.get("relPath", ""), node["index"]))

    graph = build_real_brain_graph(cfg, on_body=score_body)
    nodes = graph.get("nodes", [])
    if not nodes:
        return "", []
    for node in nodes:
        if node.get("projectId"):
            score_body(node, node.get("body", ""))
    scored.sort(key=lambda item: (-item[0], -item[1], item[2]))
    by_index = {node["index"]: node for node in nodes}

    try:
        key = _cache_key(cfg)
    except ValueError:
        return "", []
    with _BRAIN_LOCK:
        files = dict(_BRAIN_CACHE["files"]) if _BRAIN_CACHE["key"] == key else {}
    top_nodes = []
    snippets = []
    for _literal, _expanded, _path, index in scored:
        if len(top_nodes) >= top_k:
            break
        node = by_index[index]
        if node.get("projectId"):
            # The graph was built for this request from the current validated register.
            body = node.get("body", "")
            fresh_node = node
        else:
            found = files.get(node.get("relPath", ""))
            if found is None:
                continue
            if node.get("id", "").startswith("nerva-") != (found[0] == SOURCE_REPO):
                continue
            try:
                title, tags, body, _links = _read_indexed_note_found(cfg, found)
            except (OSError, ValueError):
                continue
            fresh_node = {**node, "title": node["title"] if found[0] == SOURCE_REPO else title,
                          "tags": tags, "body": body[:3800]}
            if not any(vault_search.score(fresh_node, terms, related, body=body)):
                continue
        excerpt = vault_search.passage(body, query, SYNONYM_EXPANSIONS)
        top_nodes.append({**fresh_node, "excerpt": excerpt})
        short = excerpt if len(excerpt) <= 700 else vault_search.passage(body, query, SYNONYM_EXPANSIONS, limit=700)
        snippets.append(f"[Node #{index} | {fresh_node['title']} | Path: {node.get('relPath', '')}]\n"
                        + short)
    return "\n\n---\n\n".join(snippets), top_nodes


SYSTEM_PROMPT = """You are J.A.R.V.I.S., Andrei's refined, direct, pragmatic AI co-pilot and butler inside ANDREI OS / AI WORKSHOP OS.
Language & style rules:
- Match the user's language naturally: reply in English if the user asks in English, or in Romanian if the user asks in Romanian.
- Be concise, accurate, and grounded (1 to 3 crisp sentences suitable for spoken TTS). Never invent facts not in the Second Brain context; state clearly if something is marked unverified in the vault.
- When answering a question grounded in a Second Brain note or cluster, set action.type to "focus_hub" with {"query": "<Exact Note or Hub Title>"} so the 3D Knowledge Galaxy camera flies directly to that note!
- If the user asks to save/capture/write a new note into their Second Brain Inbox, set action.type to "capture_note" with {"title": "...", "content": "..."}.

Respond STRICTLY as a single valid JSON object matching this exact schema (no markdown fences, no extra prose):
{
  "reply": "Spoken response to the user",
  "action": {
    "type": "none | switch_brain | focus_hub | search_brain | capture_note | open_robot | robot_edit | robot_explode | robot_assemble | open_house | house_edit | house_miniature | house_3d | open_computer_use | run_ads_campaign | close_overlay | galaxy_mode",
    "params": {}
  }
}

Action parameter reference:
- focus_hub: {"query": "exact title of relevant note or hub"}
- search_brain: {"query": "search keyword"}
- capture_note: {"title": "Short note title", "content": "Markdown body"}
- switch_brain: {"brain": "fable-5.2" | "opus-5.5"}
- open_robot: {}
- robot_edit: {"housingColor": "#c81e2b"|"silver"|"#10b981"|"#f59e0b"|"#3b82f6", "ringColor": "#10b981"|"#ef4444"|"#06b6d4"|"#a855f7"}
- robot_explode: {}
- robot_assemble: {}
- open_house: {}
- house_edit: {"centerDoorRemoveStairs": bool, "addGarageCars": bool, "enlargeLivingRoom": number, "enlargeKitchen": number, "addPoolPalmsAndFlowers": bool, "toggleRoof": bool, "showLabels": bool, "explodedHouse": bool}
- house_miniature: {}
- house_3d: {}
- open_computer_use: {}
- run_ads_campaign: {"campaignName": string, "dailyBudget": number, "objective": "Leads"|"Sales"}
- close_overlay: {}
- galaxy_mode: {"flat": bool}
"""


def _extract_json(text: str) -> dict:
    cleaned = re.sub(r"<think>[\s\S]*?</think>", "", text or "").strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        cleaned = "\n".join(ln for ln in lines if not ln.strip().startswith("```")).strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            obj = json.loads(cleaned[start : end + 1])
            if isinstance(obj, dict) and "reply" in obj:
                obj.setdefault("action", {"type": "none", "params": {}})
                return obj
        except Exception:
            pass
    return {"reply": cleaned or "Right away, sir.", "action": {"type": "none", "params": {}}}


def _call_claude_subscription(user_payload: str, brain: str, cfg: dict) -> dict:
    claude_info = check_claude_subscription()
    if not claude_info.get("loggedIn") or not claude_info.get("bin"):
        raise RuntimeError("Claude subscription CLI is not signed in yet")

    model_alias = "fable" if brain == "fable-5.2" else "sonnet"
    env = os.environ.copy()
    env["PATH"] = EXTENDED_PATH
    cmd = [
        claude_info["bin"],
        "-p",
        "--model",
        model_alias,
        "--fallback-model",
        "opus,sonnet",
        "--no-session-persistence",
        "--tools",
        "",
        "--system-prompt",
        SYSTEM_PROMPT,
        user_payload,
    ]
    use_shell = os.name == "nt" and claude_info["bin"].lower().endswith((".cmd", ".bat"))
    if not _live_dispatch_allowed("claude_subscription", cfg):
        raise RuntimeError("Cloud chat consent was revoked")
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=28, env=env, shell=use_shell)
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or "claude CLI error").strip())
    res = _extract_json(proc.stdout.strip())
    res["provider"] = f"claude_subscription ({model_alias})"
    return res


def _call_anthropic_api(user_payload: str, brain: str, api_key: str) -> dict:
    model = "claude-opus-4-20250514" if brain == "fable-5.2" else "claude-sonnet-4-20250514"
    req_body = json.dumps({
        "model": model,
        "max_tokens": 550,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": user_payload}],
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=req_body,
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=22) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        res = _extract_json(data["content"][0]["text"].strip())
        res["provider"] = "anthropic_api"
        return res


def _call_gemini_api(user_payload: str, api_key: str) -> dict:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
    req_body = json.dumps({
        "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [{"role": "user", "parts": [{"text": user_payload}]}],
        "generationConfig": {"responseMimeType": "application/json", "maxOutputTokens": 550},
    }).encode("utf-8")
    req = urllib.request.Request(url, data=req_body, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=22) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
        res = _extract_json(text)
        res["provider"] = "gemini_api"
        return res


def _call_openai_compatible(user_payload: str, url: str, api_key: str, model: str, label: str) -> dict:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req_body = json.dumps({
        "model": model,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_payload},
        ],
        "max_tokens": 550,
    }).encode("utf-8")
    req = urllib.request.Request(url, data=req_body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=22) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        text = data["choices"][0]["message"]["content"].strip()
        res = _extract_json(text)
        res["provider"] = label
        return res


def _call_ollama(user_payload: str, cfg: dict) -> dict:
    if not _live_dispatch_allowed("ollama", cfg):
        raise RuntimeError("Remote Ollama requires cloud consent in Settings")
    base = (cfg.get("ollamaUrl") or "http://127.0.0.1:11434").rstrip("/")
    # Refresh before sending a private prompt: cached names can have become cloud aliases.
    ollama_info = check_ollama_status(base, force=True)
    if not ollama_info.get("online") or not ollama_info.get("models"):
        raise RuntimeError("Local Ollama is not reachable")

    model = _select_ollama_model(ollama_info, cfg)
    if not model:
        raise RuntimeError("No verified local Ollama model; cloud models require consent")
    cloud_allowed = _live_dispatch_allowed("ollama_cloud", cfg)
    # Supported Ollama versions resolve this selector atomically and refuse remote
    # aliases. Older servers may reject it; never retry with an unrestricted name.
    tagged_model = model if ":" in model.rsplit("/", 1)[-1] else f"{model}:latest"
    wire_model = model if cloud_allowed else f"{tagged_model}:local"

    req_body = json.dumps({
        "model": wire_model,
        "stream": False,
        "think": False,
        "format": "json",
        "options": {"temperature": 0.35, "num_predict": 380},
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_payload},
        ],
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{base}/api/chat",
        data=req_body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    if not _live_dispatch_allowed("ollama", cfg) or (
        cloud_allowed and not _live_dispatch_allowed("ollama_cloud", cfg)
    ):
        raise RuntimeError("Cloud chat consent was revoked")
    with _model_opener().open(req, timeout=25) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        content = data.get("message", {}).get("content", "").strip()
        res = _extract_json(content)
        label = "ollama" if model in ollama_info.get("localModels", []) else "ollama_cloud"
        res["provider"] = f"{label} ({model})"
        return res


def _synthesize_grounded_fallback(prompt: str, matched_nodes: list[dict]) -> dict:
    if matched_nodes:
        top = matched_nodes[0]
        body_clean = re.sub(r"[#*`\[\]]+", "", top.get("excerpt", top.get("body", ""))).strip()
        first_sentences = " ".join(body_clean.split())[:260]
        return {
            "reply": f"From your Second Brain note '{top['title']}': {first_sentences}",
            "action": {"type": "focus_hub", "params": {"query": top["title"]}},
            "provider": "vault_rag",
        }
    return {
        "reply": "Your Second Brain is online. Start local Ollama or ask about a note. Cloud chat requires explicit consent in Settings.",
        "action": {"type": "none", "params": {}},
        "provider": "vault_rag",
    }


def _detect_prompt_language(prompt: str) -> str:
    q = nfc(prompt).lower()
    if re.search(r"[ăâîșț]", q):
        return "Romanian"
    ro_words = {"ce", "care", "cum", "despre", "sunt", "este", "am", "proiectele", "spune", "arata", "noteaza"}
    tokens = set(re.findall(r"[a-zăâîșț]+", q))
    if len(tokens & ro_words) >= 2:
        return "Romanian"
    return "English"


def call_llm(prompt: str, brain: str, context: dict, cfg: dict) -> dict:
    cfg = _normalize_routing(cfg)
    rag_text, matched_nodes = retrieve_vault_context(prompt, cfg, top_k=6)
    target_lang = _detect_prompt_language(prompt)
    user_payload = (
        f"Active Brain Persona: {brain}\n"
        f"Current UI View: {json.dumps(context)}\n"
        f"Required Reply Language: {target_lang} (translate facts from Romanian notes into {target_lang} naturally).\n\n"
        f"=== RELEVANT SECOND BRAIN NOTES (ANDREI OS) ===\n{rag_text or 'Demo mode active.'}\n"
        f"===============================================\n\n"
        f"User Request: {prompt}"
    )

    errors = []
    for step in _provider_chain(cfg):
        # Check at every dispatch, including fallback. A key, login or legacy
        # provider selection is availability evidence only, never permission.
        if not _live_dispatch_allowed(step, cfg):
            continue
        try:
            if step == "claude_subscription":
                res = _call_claude_subscription(user_payload, brain, cfg)
            elif step == "anthropic" and cfg.get("anthropicKey"):
                res = _call_anthropic_api(user_payload, brain, cfg["anthropicKey"])
            elif step == "gemini" and cfg.get("geminiKey"):
                res = _call_gemini_api(user_payload, cfg["geminiKey"])
            elif step == "openai" and cfg.get("openaiKey"):
                res = _call_openai_compatible(
                    user_payload, "https://api.openai.com/v1/chat/completions", cfg["openaiKey"], "gpt-4o", "openai_api"
                )
            elif step == "openrouter" and (cfg.get("openrouterKey") or _is_loopback_url(cfg.get("openrouterUrl"))):
                res = _call_openai_compatible(
                    user_payload,
                    cfg.get("openrouterUrl", "https://openrouter.ai/api/v1/chat/completions"),
                    cfg.get("openrouterKey", ""),
                    cfg.get("openrouterModel", "anthropic/claude-sonnet-4"),
                    "openrouter_custom",
                )
            elif step == "ollama":
                res = _call_ollama(user_payload, cfg)
            else:
                continue

            # If action is capture_note, persist it immediately!
            act = res.get("action") or {}
            if act.get("type") == "capture_note":
                p = act.get("params") or {}
                cap = capture_inbox_note(cfg, p.get("title", ""), p.get("content", prompt))
                res["capturedNote"] = cap.get("node")
            # If LLM answered from a specific note without picking a UI action, gently focus top note in galaxy view
            elif (
                (not act.get("type") or act.get("type") == "none")
                and context.get("activeView") == "galaxy"
                and matched_nodes
                and len(prompt.split()) >= 3
            ):
                # Only auto-focus when the top note had a strong match
                top_title = matched_nodes[0].get("title", "")
                if top_title and any(w in top_title.lower() for w in re.findall(r"[\wăâîșț]{3,}", nfc(prompt).lower())):
                    res["action"] = {"type": "focus_hub", "params": {"query": top_title}}

            return res
        except Exception as exc:
            errors.append(f"{step}: {exc}")

    fallback = _synthesize_grounded_fallback(prompt, matched_nodes)
    fallback["debugErrors"] = errors
    return fallback


# ==============================================================================
# HTTP REQUEST HANDLER
# ==============================================================================
class JarvisRequestHandler(SimpleHTTPRequestHandler):
    extensions_map = {**SimpleHTTPRequestHandler.extensions_map, **STATIC_TYPES}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(PUBLIC_DIR), **kwargs)

    def log_message(self, fmt, *args):
        sys.stdout.write(f"[JARVIS 4719] {self.address_string()} - {fmt % args}\n")
        sys.stdout.flush()

    def end_headers(self):
        # No CORS headers on purpose: this API serves personal notes and writes
        # settings, and only the page this server itself serves may call it.
        self.send_header("Cache-Control", "no-store, max-age=0")
        super().end_headers()

    def _local_authorities(self) -> set:
        port = self.server.server_address[1]
        return {f"{host}:{port}" for host in ("localhost", "127.0.0.1", "[::1]")}

    def _request_is_same_origin(self) -> bool:
        """True only for requests from the page this server serves.

        Binding to loopback does not authenticate the browser: any website can make
        the owner's browser call 127.0.0.1. Two checks close that:
        - `Host` must name this loopback server, which defeats DNS rebinding (a
          foreign hostname resolved to 127.0.0.1 still sends its own name);
        - `Origin`, which browsers attach to every cross-origin request and to every
          POST, must be this server's own origin when present. Non-browser clients
          (curl, scripts) send none and are allowed.
        """
        allowed = self._local_authorities()
        if (self.headers.get("Host") or "").strip().lower() not in allowed:
            return False
        origin = (self.headers.get("Origin") or "").strip().lower()
        if not origin:
            return True
        return origin in {f"http://{authority}" for authority in allowed}

    def _refuse_cross_origin(self) -> bool:
        if self._request_is_same_origin():
            return False
        self._send_json({"ok": False, "error": "cross-origin request refused"}, status=403)
        return True

    def do_OPTIONS(self):
        # A CORS preflight is only ever sent for a cross-origin call; none is allowed.
        self.send_response(204 if self._request_is_same_origin() else 403)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _send_json(self, payload: dict, status: int = 200):
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8"))

    def _build_status_payload(self, force_checks: bool = False) -> dict:
        cfg = _normalize_routing(load_config())
        claude_sub = check_claude_subscription(force=force_checks)
        ollama_st = (check_ollama_status(cfg.get("ollamaUrl", "http://127.0.0.1:11434"), force=force_checks)
                     if _dispatch_allowed("ollama", cfg) else {"online": False, "models": []})

        # Advertise only engines this configuration is allowed to dispatch to.
        pref = cfg["preferredProvider"]
        available = {
            "claude_subscription": bool(claude_sub.get("loggedIn")),
            "ollama": bool(ollama_st.get("online") and _select_ollama_model(ollama_st, cfg)),
            "anthropic": bool(cfg.get("anthropicKey")),
            "gemini": bool(cfg.get("geminiKey")),
            "openai": bool(cfg.get("openaiKey")),
            "openrouter": bool(cfg.get("openrouterKey") or _is_loopback_url(cfg.get("openrouterUrl"))),
        }
        model = _select_ollama_model(ollama_st, cfg)
        ollama_label = "ollama" if model in ollama_st.get("localModels", []) else "ollama_cloud"
        labels = {"ollama": f"{ollama_label} ({model})",
                  "anthropic": "anthropic_api", "gemini": "gemini_api", "openai": "openai_api"}
        active_engine = next((labels.get(step, step) for step in _provider_chain(cfg)
                              if available.get(step)), "vault_rag")

        return {
            "ok": True,
            "port": DEFAULT_PORT,
            "preferredProvider": pref,
            "cloudConsent": cfg["cloudConsent"],
            "activeEngine": active_engine,
            "vaultMode": cfg.get("vaultMode", "andrei_plus_nerva"),
            "vaultPath": cfg.get("vaultPath", DEFAULT_VAULT_PATH),
            "inboxFolder": configured_inbox(cfg),
            "nervaPath": cfg.get("nervaPath", DEFAULT_NERVA_PATH),
            "ollamaUrl": cfg.get("ollamaUrl", "http://127.0.0.1:11434"),
            "ollamaModel": cfg.get("ollamaModel", "qwen3.5:4b"),
            "openrouterUrl": cfg.get("openrouterUrl", "https://openrouter.ai/api/v1/chat/completions"),
            "openrouterModel": cfg.get("openrouterModel", "anthropic/claude-sonnet-4"),
            "elevenlabsVoiceId": cfg.get("elevenlabsVoiceId", "onwK4e9ZLuTAKqWW03F9"),
            "claudeSubscription": claude_sub,
            "ollama": ollama_st,
            "providers": {
                "claude_subscription": bool(claude_sub.get("loggedIn")),
                "ollama": bool(ollama_st.get("online")),
                "anthropic": bool(cfg.get("anthropicKey")),
                "gemini": bool(cfg.get("geminiKey")),
                "openai": bool(cfg.get("openaiKey")),
                "openrouter": bool(cfg.get("openrouterKey")),
                "elevenlabs": bool(cfg.get("elevenlabsKey")),
            },
        }

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        qs = urllib.parse.parse_qs(parsed.query)

        if path.startswith("/api/") and self._refuse_cross_origin():
            return

        if path == "/api/status":
            force = qs.get("refresh", ["0"])[0] == "1"
            self._send_json(self._build_status_payload(force_checks=force))
            return

        if path == "/api/brain":
            cfg = load_config()
            if qs.get("reindex", ["0"])[0] == "1":
                invalidate_brain_cache()
            if cfg.get("vaultMode") == "demo_550":
                self._send_json({"ok": True, "mode": "demo_550", "brandTitle": "AI WORKSHOP OS"})
            else:
                self._send_json(build_real_brain_graph(cfg))
            return

        if path == "/api/brain/note":
            cfg = load_config()
            rel = qs.get("relPath", [""])[0]
            try:
                title, tags, body, wls = read_indexed_note(cfg, rel)
            except (OSError, ValueError):
                # A static message: the reason can carry filesystem paths.
                self._send_json({"ok": False, "error": "note not found"}, status=404)
                return
            self._send_json({"ok": True, "title": title, "tags": tags, "body": body[:6000], "wikilinks": wls})
            return

        if path in ("/api/workshop/projects", "/api/workshop/project"):
            cfg = load_config()
            try:
                if path.endswith("/projects"):
                    self._send_json({"ok": True, "projects": workshop_projects.list_projects(sys.modules[__name__], cfg)})
                else:
                    result = workshop_projects.get_project(sys.modules[__name__], cfg, qs.get("path", [""])[0])
                    self._send_json({"ok": True, **result})
            except FileNotFoundError:
                self._send_json({"ok": False, "error": "workshop project not found"}, status=404)
            except (OSError, ValueError):
                self._send_json({"ok": False, "error": "workshop project unavailable or corrupt"}, status=422)
            return

        super().do_GET()

    def do_POST(self):
        if self._refuse_cross_origin():
            return

        if self.path == "/api/config":
            try:
                body = self._read_json()
                save_config(body)
                self._send_json(self._build_status_payload(force_checks=True))
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=400)
            return

        if self.path == "/api/claude/login":
            claude_bin = find_claude_bin()
            if not claude_bin:
                self._send_json({"ok": False, "error": "Claude CLI binary not found."}, status=404)
                return
            try:
                env = os.environ.copy()
                env["PATH"] = EXTENDED_PATH
                use_shell = os.name == "nt" and claude_bin.lower().endswith((".cmd", ".bat"))
                subprocess.Popen(
                    [claude_bin, "auth", "login", "--claudeai"],
                    env=env,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                    shell=use_shell,
                )
                self._send_json({
                    "ok": True,
                    "message": "Anthropic Subscription OAuth opened in your default browser. Complete sign-in there, then click Refresh Status.",
                })
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=500)
            return

        if self.path == "/api/brain/capture":
            try:
                body = self._read_json()
                cfg = load_config()
                res = capture_inbox_note(
                    cfg,
                    title=body.get("title", ""),
                    content=body.get("content", ""),
                    links=body.get("links"),
                )
                self._send_json(res)
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=400)
            return

        if self.path == "/api/workshop/projects":
            try:
                if int(self.headers.get("Content-Length", "0")) > 20_000:
                    self._send_json({"ok": False, "error": "workshop project too large"}, status=413)
                    return
                body = self._read_json()
                if type(body) is not dict or set(body) != {"title", "project"}:
                    raise workshop_projects.InvalidProject("invalid project request")
                result = workshop_projects.save_project(sys.modules[__name__], load_config(),
                                                       body["title"], body["project"])
                self._send_json({"ok": True, **result})
            except workshop_projects.SavedProjectUnavailable as exc:
                self._send_json({"ok": False, "error": "project saved but could not be reopened", "path": exc.path},
                                status=500)
            except (OSError, ValueError, TypeError):
                self._send_json({"ok": False, "error": "invalid or unavailable workshop project"}, status=422)
            return

        if self.path == "/api/chat":
            try:
                body = self._read_json()
                cfg = load_config()
                result = call_llm(
                    prompt=body.get("prompt", ""),
                    brain=body.get("brain", "opus-5.5"),
                    context=body.get("context", {}),
                    cfg=cfg,
                )
                self._send_json(result)
            except Exception as exc:
                self._send_json({"mode": "local", "fallbackReason": str(exc)})
            return

        if self.path == "/api/tts":
            cfg = load_config()
            if not cfg.get("elevenlabsKey"):
                self._send_json({"mode": "browser_speech"}, status=200)
                return
            try:
                body = self._read_json()
                text = body.get("text", "").strip()
                voice_id = cfg.get("elevenlabsVoiceId") or "onwK4e9ZLuTAKqWW03F9"
                url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
                payload = json.dumps({
                    "text": text,
                    "model_id": "eleven_turbo_v2_5",
                    "voice_settings": {"stability": 0.55, "similarity_boost": 0.8},
                }).encode("utf-8")
                req = urllib.request.Request(
                    url,
                    data=payload,
                    headers={
                        "Content-Type": "application/json",
                        "xi-api-key": cfg["elevenlabsKey"],
                        "Accept": "audio/mpeg",
                    },
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=15) as resp:
                    audio_bytes = resp.read()
                self.send_response(200)
                self.send_header("Content-Type", "audio/mpeg")
                self.send_header("Content-Length", str(len(audio_bytes)))
                self.end_headers()
                self.wfile.write(audio_bytes)
            except Exception as exc:
                self._send_json({"mode": "browser_speech", "error": str(exc)}, status=200)
            return

        self._send_json({"error": "Not found"}, status=404)


class ReusableThreadingHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True


def main():
    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    server = ReusableThreadingHTTPServer(("127.0.0.1", DEFAULT_PORT), JarvisRequestHandler)
    print(f"\n  ANDREI OS / AI WORKSHOP OS — J.A.R.V.I.S. Online at http://localhost:{DEFAULT_PORT}\n", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down J.A.R.V.I.S. server...")
        server.server_close()


if __name__ == "__main__":
    main()
