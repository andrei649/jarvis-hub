#!/usr/bin/env python3
"""
ANDREI OS / AI WORKSHOP OS — J.A.R.V.I.S. Local Server (http://localhost:4719)
- Indexes Andrei's real Second Brain (`~/Documents/Andrei OS Obsidian` + the enclosing `jarvis-hub` repo)
  into a 3D Knowledge Galaxy with authentic [[wiki-link]] edges and RAG retrieval.
- Unified Multi-Platform AI Hub:
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

import datetime as dt
import hashlib
import importlib.util
import json
import math
import mimetypes
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

mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("application/javascript", ".mjs")
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("image/svg+xml", ".svg")
mimetypes.add_type("application/json", ".json")

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
    "vaultMode",
    "vaultPath",
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


def load_config() -> dict:
    cfg = {
        "preferredProvider": "auto",  # auto | claude_subscription | ollama | anthropic | gemini | openai | openrouter
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
            for k in CONFIG_KEYS:
                if k in disk and disk[k] is not None and disk[k] != "":
                    cfg[k] = disk[k]
        except Exception:
            pass
    # Cross-OS path healing (e.g. if config.json was copied between macOS and Windows)
    if cfg.get("vaultPath") and not Path(cfg["vaultPath"]).exists() and Path(DEFAULT_VAULT_PATH).exists():
        cfg["vaultPath"] = DEFAULT_VAULT_PATH
    if cfg.get("nervaPath") and not Path(cfg["nervaPath"]).exists() and Path(DEFAULT_NERVA_PATH).exists():
        cfg["nervaPath"] = DEFAULT_NERVA_PATH
    return cfg


def save_config(updates: dict) -> dict:
    current = load_config()
    secret_keys = {"anthropicKey", "geminiKey", "openaiKey", "openrouterKey", "elevenlabsKey"}
    for key in CONFIG_KEYS:
        if key in updates and updates[key] is not None:
            val = str(updates[key]).strip()
            if key in secret_keys and val == "***":
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
        with urllib.request.urlopen(req, timeout=1.5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            models = [m.get("name", "") for m in data.get("models", []) if m.get("name")]
            info = {"online": True, "url": base, "models": models}
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
    raw_links = re.findall(r"\[\[([^\]]+)\]\]", text)
    wikilinks = []
    for wl in raw_links:
        target = wl.split("|", 1)[0].split("#", 1)[0].strip()
        if target:
            wikilinks.append(nfc(Path(target).stem if "/" in target else target))

    # Extract relative .md links [label](foo.md)
    md_links = re.findall(r"\[[^\]]+\]\(([^)]+\.(?:md|canvas))\)", text)
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


def build_real_brain_graph(cfg: dict) -> dict:
    vault_mode = cfg.get("vaultMode", "andrei_plus_nerva")
    vault_dir = Path(cfg.get("vaultPath") or DEFAULT_VAULT_PATH)
    nerva_dir = Path(cfg.get("nervaPath") or DEFAULT_NERVA_PATH)
    include_nerva = vault_mode == "andrei_plus_nerva" and nerva_dir.exists()

    cache_key = f"{vault_mode}|{vault_dir}|{nerva_dir}"
    now = time.time()
    with _BRAIN_LOCK:
        if _BRAIN_CACHE["key"] == cache_key and _BRAIN_CACHE["data"] and (now - _BRAIN_CACHE["ts"] < 15.0):
            return _BRAIN_CACHE["data"]

    if not vault_dir.exists():
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
        "relPath": "00 Acasa/Acasa.md",
        "tags": ["andrei-os", "second-brain"],
        "body": (
            "Nucleul Second Brain-ului real al lui Andrei (`Andrei OS Obsidian`"
            + (" + `Nerva / Jarvis Hub`" if include_nerva else "")
            + ").\n\nConectează proiectele active, infrastructura locală (Bonobo RTX 5090, Mac mini, NAS UGREEN, Pi 5), "
            "deciziile de arhitectură și rutare a modelelor, colecțiile și istoricul NAS."
        ),
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
        return {"mode": "demo_550", "reason": f"Vault cannot be opened: {exc.strerror or exc}"}
    # relPath -> (source root, on-disk path components): the only files the note route serves.
    indexed_files: dict[str, tuple[str, tuple[str, ...]]] = {}
    with vault_handle as vault_files:
        for parts, entry, data in vault_files.walk(want=_vault_wants, cap=_vault_read_cap):
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
                "sourceVault": "Andrei OS Obsidian",
                "cloudEvicted": is_dataless,
                "tags": tags,
                "body": body[:3800],
                "wikilinks": wikilinks,
            }
            nodes.append(node_obj)
            indexed_files[rel_str] = (str(vault_dir), parts)
            register_lookup(stem, idx)
            register_lookup(title, idx)
        skipped_files = list(vault_files.skipped)

    # 2. Optional: Merge Nerva / Jarvis Hub local architecture docs
    if include_nerva and "Nerva Jarvis Hub" in hub_index_by_key:
        nerva_hub_idx = hub_index_by_key["Nerva Jarvis Hub"]
        nerva_hub = nodes[nerva_hub_idx]
        for doc_parts, doc_entry, doc_data in _nerva_documents(nerva_dir):
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
            register_lookup(label, idx)
            indexed_files[f"Nerva/jarvis-hub/{rel_n}"] = (str(nerva_dir), doc_parts)

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
            if kw in t_low:
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

    result = {
        "ok": True,
        "mode": vault_mode,
        "brandTitle": "ANDREI OS",
        "vaultLabel": "Andrei OS Obsidian + Nerva Hub" if include_nerva else "Andrei OS Obsidian",
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
        "discoveredSources": [
            {
                "name": "Andrei OS Obsidian (Primary Vault)",
                "path": DEFAULT_VAULT_PATH,
                "status": "connected",
                "detail": "132 Markdown notes · 530 [[wiki-links]] · Johnny.Decimal 00–90",
            },
            {
                "name": "Nerva / Jarvis Hub Repository",
                "path": DEFAULT_NERVA_PATH,
                "status": "connected" if include_nerva else "available",
                "detail": "17-Agent Cabinet architecture, BACKLOG, NERVA_VISION & SOUL docs",
            },
            {
                "name": "Google Drive Backup",
                "path": "gdrive://Andrei OS Obsidian Backup",
                "status": "synced-snapshot",
                "detail": "Andrei OS Obsidian Backup & zip archives verified",
            },
            {
                "name": "NAS Obsidian Import Staging",
                "path": str(Path.home() / "Documents" / "NAS-Obsidian-Import"),
                "status": "archived-source",
                "detail": "Hermes NAS session & manifest staging scripts",
            },
        ],
    }

    with _BRAIN_LOCK:
        _BRAIN_CACHE["key"] = cache_key
        _BRAIN_CACHE["data"] = result
        _BRAIN_CACHE["files"] = indexed_files
        _BRAIN_CACHE["ts"] = now
    return result


INBOX_FOLDER = "08 Inbox"


def capture_inbox_note(cfg: dict, title: str, content: str, links: list[str] | None = None) -> dict:
    """Create a new note in the vault's inbox. Never overwrites, never leaves the vault.

    The note is created through `vault_fs`: relative to the handle of the verified inbox
    folder, exclusively. An inbox (or vault ancestor) that is a symlink or junction is
    refused with `vault_fs.UnsafePath` before anything is written, and there is no
    path-based fallback. On a name collision the next free "<title> (n)" is taken.
    """
    vault_dir = Path(cfg.get("vaultPath") or DEFAULT_VAULT_PATH)

    base_title = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', "-", (title or "").strip()).strip("-. ")
    if not base_title:
        base_title = f"Nota JARVIS {dt.datetime.now().strftime('%Y-%m-%d %H-%M')}"
    base_title = base_title[:120].rstrip(". ")

    now_iso = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    link_str = " · ".join(f"[[{link.strip('[]')}]]" for link in (links or ["Acasa"]) if link.strip())

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
                vault_files.create_exclusive((INBOX_FOLDER,), f"{clean_title}.md", md.encode("utf-8"))
                break
            except FileExistsError:
                attempt += 1
                if attempt > 999:
                    raise

    target_file = vault_dir / INBOX_FOLDER / f"{clean_title}.md"
    invalidate_brain_cache()
    graph = build_real_brain_graph(cfg)
    created_node = next((n for n in graph.get("nodes", []) if n.get("title") == clean_title), None)
    return {"ok": True, "path": str(target_file), "node": created_node, "brain": graph}


def read_indexed_note(cfg: dict, rel_path: str) -> tuple[str, list[str], str, list[str]]:
    """`(title, tags, body, wikilinks)` of a Markdown note the graph itself indexed.

    The lookup is an allowlist, not a path check: only a `relPath` that the current graph
    produced is served, and only Markdown. So a request can name nothing the indexer did
    not already choose to show: not `config.json`, not `.env`, not a `*.local.md`, not a
    file reached through a link. The file is then read through `vault_fs` from the on-disk
    components recorded at index time. Raises `ValueError` for anything else.
    """
    rel = nfc(rel_path or "").replace("\\", "/")
    build_real_brain_graph(cfg)
    with _BRAIN_LOCK:
        found = _BRAIN_CACHE["files"].get(rel)
    if found is None or not rel.lower().endswith(".md"):
        raise ValueError("not an indexed note")
    base_dir, parts = found
    in_repo = rel.startswith("Nerva/jarvis-hub/")
    with vault_fs.VaultFs(base_dir, allow_hardlinks=in_repo or _allow_hardlinks(cfg)) as files:
        entry, data = files.read_file(parts, _NOTE_READ_CAP)
    if entry.dataless:
        raise ValueError("note is not downloaded")
    return _parse_markdown_content(data.decode("utf-8", errors="replace"), Path(parts[-1]).stem)


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
    graph = build_real_brain_graph(cfg)
    nodes = graph.get("nodes", [])
    if not nodes:
        return "", []

    q_norm = nfc(query).lower()
    raw_tokens = [t for t in re.findall(r"[\wăâîșț]{2,}", q_norm) if t not in {
        "the", "and", "for", "what", "who", "how", "are", "you", "can", "tell", "about",
        "show", "jarvis", "please", "with", "from", "have", "my", "me", "in", "on", "to",
        "este", "sunt", "care", "despre", "meu", "mele", "din", "sau", "cum", "ce", "am",
    }]

    expanded = list(raw_tokens)
    for phrase, extras in SYNONYM_EXPANSIONS.items():
        if phrase in q_norm:
            expanded.extend(extras)
    for tok in raw_tokens:
        if tok in SYNONYM_EXPANSIONS:
            expanded.extend(SYNONYM_EXPANSIONS[tok])

    scored: list[tuple[float, dict]] = []
    for n in nodes:
        if n.get("index") == 0:
            continue
        score = 0.0
        title_l = n.get("title", "").lower()
        cat_l = n.get("category", "").lower()
        body_l = n.get("body", "").lower()
        rel_l = n.get("relPath", "").lower()

        for tok in expanded:
            if tok in title_l:
                score += 6.0 if not n.get("isHub") else 3.0
            if tok in cat_l or tok in rel_l:
                score += 2.5
            if tok in body_l:
                score += 1.8

        if score > 0:
            scored.append((score, n))

    scored.sort(key=lambda item: item[0], reverse=True)

    # Always include Acasa + Portofoliu proiecte summary if general question with weak keyword overlap
    top_nodes = [n for _, n in scored[:top_k]]
    if not top_nodes:
        defaults = [
            n for n in nodes
            if n.get("title") in ("Acasa", "Andrei", "Portofoliu proiecte", "Harta infrastructurii", "Nerva si Jarvis Hub")
        ]
        top_nodes = defaults[:5]

    snippets = []
    for n in top_nodes:
        snippets.append(
            f"[Node #{n['index']} | {n['title']} | Path: {n.get('relPath', '')}]\n{n.get('body', '')[:700]}"
        )
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


def _call_claude_subscription(user_payload: str, brain: str) -> dict:
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
    base = (cfg.get("ollamaUrl") or "http://127.0.0.1:11434").rstrip("/")
    ollama_info = check_ollama_status(base)
    if not ollama_info.get("online") or not ollama_info.get("models"):
        raise RuntimeError("Local Ollama is not reachable")

    desired = cfg.get("ollamaModel") or "qwen3.5:4b"
    available = ollama_info["models"]
    model = desired if desired in available else available[0]

    req_body = json.dumps({
        "model": model,
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
    with urllib.request.urlopen(req, timeout=25) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        content = data.get("message", {}).get("content", "").strip()
        res = _extract_json(content)
        res["provider"] = f"ollama ({model})"
        return res


def _synthesize_grounded_fallback(prompt: str, matched_nodes: list[dict]) -> dict:
    if matched_nodes:
        top = matched_nodes[0]
        body_clean = re.sub(r"[#*`\[\]]+", "", top.get("body", "")).strip()
        first_sentences = " ".join(body_clean.split())[:260]
        return {
            "reply": f"From your Second Brain note '{top['title']}': {first_sentences}",
            "action": {"type": "focus_hub", "params": {"query": top["title"]}},
            "provider": "vault_rag",
        }
    return {
        "reply": "Your Andrei OS Second Brain is online, sir. Sign into your Anthropic subscription in Settings or ask about any note, project, or 3D studio scene.",
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

    pref = cfg.get("preferredProvider", "auto")
    errors = []

    # Build ordered provider execution chain
    chain = []
    if pref == "claude_subscription":
        chain = ["claude_subscription", "ollama"]
    elif pref == "ollama":
        chain = ["ollama"]
    elif pref == "anthropic":
        chain = ["anthropic", "claude_subscription", "ollama"]
    elif pref == "gemini":
        chain = ["gemini", "ollama"]
    elif pref == "openai":
        chain = ["openai", "ollama"]
    elif pref == "openrouter":
        chain = ["openrouter", "ollama"]
    else:
        # "auto": Anthropic Subscription first (user's demo choice!), then Cloud APIs, then Local Ollama
        chain = ["claude_subscription", "anthropic", "gemini", "openai", "openrouter", "ollama"]

    for step in chain:
        try:
            if step == "claude_subscription":
                res = _call_claude_subscription(user_payload, brain)
            elif step == "anthropic" and cfg.get("anthropicKey"):
                res = _call_anthropic_api(user_payload, brain, cfg["anthropicKey"])
            elif step == "gemini" and cfg.get("geminiKey"):
                res = _call_gemini_api(user_payload, cfg["geminiKey"])
            elif step == "openai" and cfg.get("openaiKey"):
                res = _call_openai_compatible(
                    user_payload, "https://api.openai.com/v1/chat/completions", cfg["openaiKey"], "gpt-4o", "openai_api"
                )
            elif step == "openrouter" and (cfg.get("openrouterKey") or "127.0.0.1" in cfg.get("openrouterUrl", "") or "localhost" in cfg.get("openrouterUrl", "")):
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
        cfg = load_config()
        claude_sub = check_claude_subscription(force=force_checks)
        ollama_st = check_ollama_status(cfg.get("ollamaUrl", "http://127.0.0.1:11434"), force=force_checks)

        # Determine active effective provider
        pref = cfg.get("preferredProvider", "auto")
        active_engine = "vault_rag"
        if pref == "claude_subscription" and claude_sub.get("loggedIn"):
            active_engine = "claude_subscription"
        elif pref == "ollama" and ollama_st.get("online"):
            active_engine = f"ollama ({cfg.get('ollamaModel')})"
        elif pref == "anthropic" and cfg.get("anthropicKey"):
            active_engine = "anthropic_api"
        elif pref == "gemini" and cfg.get("geminiKey"):
            active_engine = "gemini_api"
        elif pref == "openai" and cfg.get("openaiKey"):
            active_engine = "openai_api"
        elif pref == "openrouter" and cfg.get("openrouterKey"):
            active_engine = "openrouter"
        else:
            if claude_sub.get("loggedIn"):
                active_engine = "claude_subscription"
            elif cfg.get("anthropicKey"):
                active_engine = "anthropic_api"
            elif cfg.get("geminiKey"):
                active_engine = "gemini_api"
            elif cfg.get("openaiKey"):
                active_engine = "openai_api"
            elif cfg.get("openrouterKey"):
                active_engine = "openrouter"
            elif ollama_st.get("online"):
                active_engine = f"ollama ({cfg.get('ollamaModel')})"

        return {
            "ok": True,
            "port": DEFAULT_PORT,
            "preferredProvider": pref,
            "activeEngine": active_engine,
            "vaultMode": cfg.get("vaultMode", "andrei_plus_nerva"),
            "vaultPath": cfg.get("vaultPath", DEFAULT_VAULT_PATH),
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
                    links=body.get("links", ["Acasa"]),
                )
                self._send_json(res)
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=400)
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
