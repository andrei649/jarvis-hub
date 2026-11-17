#!/usr/bin/env python3
"""H264 — generate ``agents/core/env_registry.json``, the declared environment surface.

Every variable the hub reads, measured rather than remembered:

* the names: ``env_config.HUB_ENV_SUFFIXES`` (kept equal to the source by
  ``tests/test_rb2_env_alias_inventory.py``) plus every other name ``.env.example`` tells
  the owner to set (a provider key, ``PYTHON_DOTENV_DISABLED``);
* the type and default: read from the typed getter calls in ``agents/``, ``scripts/`` and
  ``serve.py`` (``env_flag("JARVIS_X", False)`` is a flag that defaults off); a name read
  without a typed getter is ``text`` (or ``path`` / ``credential`` from ``env_alias``);
* what it is for: the comment above the name in ``.env.example`` (its section heading and
  the first sentences), and whether that comment calls it REQUIRED for some setup.

Values are never read. ``--check`` exits 1 when the file on disk is not what this script
would write (``tests/test_h264_env_registry.py`` runs the same comparison).
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

OUT = REPO / "agents" / "core" / "env_registry.json"
GETTERS = {"env_flag": "flag", "env_str": "text", "env_list": "list", "env_int": "int",
           "env_float": "float", "env_json_object": "json", "env_int_map": "int_map"}
_HUB = re.compile(r"(?:JARVIS|NERVA)_([A-Z0-9_]+)\Z")
# ``NAME=value`` (commented out or not) with nothing after it but an inline comment: prose
# that merely mentions an assignment ("# NERVA_HARDENED=1 ignores the list.") is not one.
_NAME_LINE = re.compile(r"""^#?[ \t]*([A-Z][A-Z0-9_]+)=(?:'[^']*'|"[^"]*"|[^\s#'"]*)[ \t]*(?:#.*)?$""")
_INLINE_COMMENT = re.compile(r"^#?[ \t]*[A-Z][A-Z0-9_]+=[^\s'\"#]*[ \t]+#[ \t]*(\S.*)$")
_SECTION = re.compile(r"^#\s*[─━-]{2,}\s*(.+?)\s*[─━-]*\s*$")
PURPOSE_MAX = 240

#: ``<X>`` → a reviewed one-line purpose, for hub variables whose documentation is missing or
#: whose comment does not say what the variable does on its own line. Read against the
#: reader each names; a sentence here wins over one extracted from the docs.
PURPOSES = {
    "HOST": "Address the hub binds to (default 127.0.0.1, loopback; agents/web.py).",
    "PORT": "Port the hub listens on (default 8080; the CLI and the doctor use it to find the hub).",
    "HOME": "The hub's data root (settings, audit log, runtime state); keep it outside the git checkout.",
    "USER_HOME": "The owner's data folder (packaged installs); its .env is the second .env layer the hub loads.",
    "ALLOW_INSECURE_BIND": "Acknowledge a non-loopback bind the boot guard would refuse (agents/core/boot_guards.py); "
                           "loopback is always allowed.",
    "STRICT_MODELS": "Refuse a model outside an agent's approved_models (default on; 0 only logs the violation).",
    "STRICT_LOCAL": "Keep model calls on local backends: a cloud model or judge is refused while it is on.",
    "SAFE_MODE": "Safe mode (H275/H490): the hub starts with owner jobs and loosened settings left out.",
    "STRICT_EGRESS": "Strict egress (default on): outbound calls are limited to the egress allow-list; "
                     "NERVA_HARDENED forces it on.",
}


def _scan_sources(root: Path) -> dict[str, dict]:
    """``{<X>: {"type", "default", "sites"}}`` from the typed getter calls."""
    found: dict[str, dict] = {}
    files = [*sorted((root / "agents").rglob("*.py")), *sorted((root / "scripts").rglob("*.py")), root / "serve.py"]
    for path in files:
        if "vendor" in path.parts or not path.is_file():
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError, OSError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            func = node.func
            name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else ""
            if name not in GETTERS:
                continue
            first = node.args[0]
            if not (isinstance(first, ast.Constant) and isinstance(first.value, str)):
                continue
            match = _HUB.match(first.value)
            if not match:
                continue
            default_node = node.args[1] if len(node.args) > 1 else next(
                (kw.value for kw in node.keywords if kw.arg == "default"), None)
            if default_node is None:
                default = {"env_flag": False, "env_str": "", "env_list": [], "env_json_object": {},
                           "env_int_map": {}}.get(name)
            else:
                try:
                    default = ast.literal_eval(default_node)
                except (ValueError, SyntaxError, TypeError):
                    default = "(computed)"
            suffix = match.group(1)
            entry = found.setdefault(suffix, {"type": GETTERS[name], "default": default, "sites": 0,
                                              "varies": False})
            entry["sites"] += 1
            if (entry["type"], entry["default"]) != (GETTERS[name], default):
                entry["varies"] = True
    return found


def _purpose(lines: list[str]) -> str:
    text = " ".join(line.strip() for line in lines if line.strip())
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= PURPOSE_MAX:
        return text
    cut = text[:PURPOSE_MAX]
    stop = max(cut.rfind(". "), cut.rfind("; "))
    return (cut[:stop + 1] if stop > 80 else cut.rstrip() + "…").strip()


def _scan_example(root: Path) -> dict[str, dict]:
    """``{NAME as written: {"section", "purpose", "required_when"}}`` from ``.env.example``."""
    try:
        text = (root / ".env.example").read_text(encoding="utf-8")
    except OSError:
        return {}
    out: dict[str, dict] = {}
    section, comment, block_names = "", [], False
    for raw in text.splitlines():
        line = raw.rstrip()
        heading = _SECTION.match(line)
        if heading:
            section, comment, block_names = heading.group(1).strip(" ─━-"), [], False
            continue
        name = _NAME_LINE.match(line)
        if name:
            inline = _INLINE_COMMENT.match(line)
            # the paragraph nearest the name (a bare "#" line separates paragraphs)
            paragraphs = [[]]
            for text_line in comment:
                if text_line.strip():
                    paragraphs[-1].append(text_line)
                elif paragraphs[-1]:
                    paragraphs.append([])
            nearest = next((p for p in reversed(paragraphs) if p), [])
            purpose = _purpose([inline.group(1)]) if inline else _purpose(nearest)
            required = next((c.strip(" -#") for c in comment if "REQUIRED" in c), "")
            out.setdefault(name.group(1), {"section": section, "purpose": purpose,
                                           "required_when": _purpose([required]) if required else ""})
            block_names = True
            continue
        if not line.strip():
            comment, block_names = [], False
            continue
        if line.lstrip().startswith("#"):
            if block_names:                 # a new comment after a run of names starts a new block
                comment, block_names = [], False
            comment.append(line.lstrip()[1:])
    return out


_FLAG_HEADING = re.compile(r"^#{2,4}\s+(.*)$")
_BACKTICKED = re.compile(r"`((?:JARVIS|NERVA)_[A-Z0-9_]+)`")
_CODE_REF = re.compile(r"\(?`?[\w./-]+\.(?:py|tsx?|md|json|ya?ml):\d+(?:-\d+)?`?\)?")


def _clean_markdown(text: str) -> str:
    text = _CODE_REF.sub("", text)
    text = re.sub(r"\*\*|`", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"\s+([,.;:])", r"\1", text)
    return re.sub(r"\s+", " ", text).strip()


def _scan_flags(root: Path) -> dict[str, dict]:
    """``{<X>: {"purpose", "doc"}}`` from ``docs/FLAGS.md``: a heading that names variables
    gives each the first paragraph under it; a table row that starts with one gives it the
    row's second cell."""
    try:
        lines = (root / "docs" / "FLAGS.md").read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}
    out: dict[str, dict] = {}
    i = 0
    while i < len(lines):
        line = lines[i]
        heading = _FLAG_HEADING.match(line)
        if heading:
            names = [_HUB.match(n).group(1) for n in _BACKTICKED.findall(heading.group(1))]
            j, para = i + 1, []
            while j < len(lines) and not lines[j].strip():
                j += 1
            while True:
                para = []
                while j < len(lines) and lines[j].strip() and not _FLAG_HEADING.match(lines[j]):
                    para.append(lines[j])
                    j += 1
                if not (para and para[0].lstrip().startswith("**Default")):
                    break
                while j < len(lines) and not lines[j].strip():    # a defaults line: take the next paragraph
                    j += 1
            purpose = _purpose([_clean_markdown(" ".join(para))])
            for suffix in names:
                if purpose:
                    out.setdefault(suffix, {"purpose": purpose, "doc": "docs/FLAGS.md"})
        elif line.startswith("| `"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            first = _BACKTICKED.findall(cells[0]) if cells else []
            if len(first) == 1 and len(cells) > 1:
                purpose = _purpose([_clean_markdown(cells[1])])
                if purpose:
                    out.setdefault(_HUB.match(first[0]).group(1), {"purpose": purpose, "doc": "docs/FLAGS.md"})
        i += 1
    return out


def build(root: Path = REPO) -> dict:
    from agents.core import env_alias, env_config, env_provenance

    scanned = _scan_sources(root)
    example = _scan_example(root)
    flags = _scan_flags(root)
    entries: dict[str, dict] = {}

    def described(*names: str) -> dict:
        for candidate in names:
            if candidate in example:
                return example[candidate]
        return {"section": "", "purpose": "", "required_when": ""}

    for suffix in sorted(env_config.HUB_ENV_SUFFIXES):
        preferred, deprecated = env_config.PREFERRED_PREFIX + suffix, env_config.DEPRECATED_PREFIX + suffix
        info = scanned.get(suffix)
        kind = ("credential" if suffix in env_alias.CREDENTIALS else
                "path" if suffix in env_alias.PATH_TYPED else
                info["type"] if info else "text")
        default = info["default"] if info else None
        if kind == "credential":
            default = None                  # never a value, not even a shipped one
        doc = dict(described(preferred, deprecated), doc=".env.example")
        if not doc["purpose"]:
            documented = flags.get(suffix)
            doc.update(documented if documented else {"doc": ""})
        elif suffix in flags:
            doc["doc"] = ".env.example, docs/FLAGS.md"
        if suffix in PURPOSES:              # a reviewed sentence beats an extracted one
            doc.update(purpose=PURPOSES[suffix], doc=doc["doc"] or "scripts/gen_env_registry.py")
        entries[preferred] = {"aliases": [deprecated], "namespace": "hub", "type": kind,
                              "default": default, "default_varies": bool(info and info["varies"]),
                              **doc}
    for name in sorted(example):
        if _HUB.match(name):
            continue                         # a hub name: listed above under its preferred spelling
        doc = dict(example[name], doc=".env.example")
        secret = env_provenance.masked(name)          # the same name test the env views mask by
        entries[name] = {"aliases": [], "namespace": "other", "type": "credential" if secret else "text",
                         "default": None, "default_varies": False, **doc}
    families = [env_config.PREFERRED_PREFIX + family + "*" for family in env_config.HUB_ENV_FAMILIES]
    return {"schema": 1,
            "generated_by": "scripts/gen_env_registry.py",
            "families": families,
            "entries": entries}


def render(doc: dict) -> str:
    return json.dumps(doc, indent=1, ensure_ascii=False, sort_keys=False) + "\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--check", action="store_true", help="exit 1 when the committed file is stale")
    ns = parser.parse_args(argv)
    text = render(build())
    if ns.check:
        current = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        if current != text:
            print(f"{OUT.relative_to(REPO)} is stale: run python scripts/gen_env_registry.py", file=sys.stderr)
            return 1
        return 0
    OUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUT.relative_to(REPO)} ({len(json.loads(text)['entries'])} variables)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
