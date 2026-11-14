"""CLI chrome theming & terminal colour skins (`nerva skin` / `/skin`, H052 + H591).

Provides built-in terminal skins and validated user-authored YAML skins under
``<data_root>/skins/*.yaml`` covering:
- 22 semantic `#RRGGBB` colour slots (rendered as 24-bit ANSI truecolour unless ``NO_COLOR``
  is set or ``TERM=dumb``);
- spinner faces, thinking verbs, cadence and completion symbol;
- CLI/REPL branding (product name, tagline, prompt symbol, speaker labels, divider);
- tool call chrome (`tool_prefix` and per-tool `tool_emojis`);
- startup ASCII/Unicode banner (`banner_logo` and `banner_hero`).

Security invariants:
- User skin files are loaded strictly with ``yaml.safe_load`` from regular, non-symlink
  files capped at 64 KiB inside ``data_path("skins")``.
- Every string in a skin is checked against control/escape injection (no raw ESC ``\\x1b``,
  OSC/CSI sequences, NULs, or bidi overrides), so a user or imported YAML skin cannot
  smuggle terminal escape sequences outside the vetted ``#RRGGBB`` colour slots.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from agents.core.env_config import env_str
from agents.core.paths import data_path

DEFAULT_SKIN_NAME = "nerva-obsidian"
MAX_SKIN_BYTES = 64 * 1024

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,47}$")
_HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
# Reject C0/C1 controls (except \n and \t in multiline logos) and bidi override chars.
_FORBIDDEN_INLINE_RE = re.compile(
    r"[\x00-\x1f\x7f-\x9f\u202a-\u202e\u2066-\u2069]"
)
_FORBIDDEN_MULTILINE_RE = re.compile(
    r"[\x00-\x08\x0b-\x1f\x7f-\x9f\u202a-\u202e\u2066-\u2069]"
)

COLOR_KEYS: tuple[str, ...] = (
    "primary",
    "secondary",
    "accent",
    "muted",
    "surface",
    "border",
    "banner_border",
    "banner_title",
    "banner_accent",
    "banner_dim",
    "banner_text",
    "ui_accent",
    "ui_label",
    "ui_ok",
    "ui_warn",
    "ui_error",
    "prompt",
    "response_border",
    "assistant_name",
    "user_name",
    "tool_prefix",
    "spinner",
)

SPINNER_KEYS: tuple[str, ...] = ("faces", "verbs", "interval_ms", "done_symbol")
BRANDING_KEYS: tuple[str, ...] = (
    "product_name",
    "tagline",
    "prompt_symbol",
    "assistant_label",
    "user_label",
    "divider_char",
)
TOP_LEVEL_KEYS: frozenset[str] = frozenset(
    {
        "name",
        "description",
        "colors",
        "spinner",
        "branding",
        "tool_prefix",
        "tool_emojis",
        "banner_logo",
        "banner_hero",
    }
)


class SkinValidationError(ValueError):
    """Raised when a skin dictionary or YAML file fails schema or safety checks."""

    def __init__(self, message: str, *, problems: tuple[str, ...] = ()) -> None:
        self.problems = problems or (message,)
        super().__init__(message if not problems else f"{message}: {'; '.join(problems)}")


@dataclass(frozen=True)
class Skin:
    """Immutable validated CLI skin definition."""

    name: str
    description: str
    colors: Mapping[str, str]
    spinner: Mapping[str, Any]
    branding: Mapping[str, str]
    tool_prefix: str
    tool_emojis: Mapping[str, str]
    banner_logo: str
    banner_hero: str
    source: str = "builtin"
    path: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "source": self.source,
            **({"path": self.path} if self.path else {}),
            "colors": dict(self.colors),
            "spinner": {
                "faces": list(self.spinner["faces"]),
                "verbs": list(self.spinner["verbs"]),
                "interval_ms": int(self.spinner["interval_ms"]),
                "done_symbol": str(self.spinner["done_symbol"]),
            },
            "branding": dict(self.branding),
            "tool_prefix": self.tool_prefix,
            "tool_emojis": dict(self.tool_emojis),
            "banner_logo": self.banner_logo,
            "banner_hero": self.banner_hero,
        }


_BASE_TOOL_EMOJIS: dict[str, str] = {
    "default": "•",
    "terminal_run": "⌘",
    "execute_code": "λ",
    "file_read": "📄",
    "file_write": "✎",
    "file_search": "⌕",
    "web_search": "🌐",
    "delegate_task": "⑂",
    "memory": "◈",
    "skill_view": "✦",
}

_DEFAULT_LOGO = (
    "╭──────────────────────────────────────╮\n"
    "│  ███╗   ██╗███████╗██████╗ ██╗   ██╗ │\n"
    "│  ████╗  ██║██╔════╝██╔══██╗██║   ██║ │\n"
    "│  ██╔██╗ ██║█████╗  ██████╔╝██║   ██║ │\n"
    "│  ██║╚██╗██║██╔══╝  ██╔══██╗╚██╗ ██╔╝ │\n"
    "│  ██║ ╚████║███████╗██║  ██║ ╚████╔╝  │\n"
    "│  ╚═╝  ╚═══╝╚══════╝╚═╝  ╚═╝  ╚═══╝   │\n"
    "╰──────────────────────────────────────╯"
)


def _palette(
    *,
    primary: str,
    secondary: str,
    accent: str,
    muted: str,
    surface: str,
    border: str,
    ok: str = "#22c55e",
    warn: str = "#f59e0b",
    error: str = "#ef4444",
) -> dict[str, str]:
    return {
        "primary": primary,
        "secondary": secondary,
        "accent": accent,
        "muted": muted,
        "surface": surface,
        "border": border,
        "banner_border": border,
        "banner_title": primary,
        "banner_accent": accent,
        "banner_dim": muted,
        "banner_text": secondary,
        "ui_accent": accent,
        "ui_label": secondary,
        "ui_ok": ok,
        "ui_warn": warn,
        "ui_error": error,
        "prompt": accent,
        "response_border": border,
        "assistant_name": primary,
        "user_name": secondary,
        "tool_prefix": accent,
        "spinner": accent,
    }


_BUILTIN_SPECS: tuple[dict[str, Any], ...] = (
    {
        "name": "nerva-obsidian",
        "description": "Default Nerva obsidian & electric cyan operator chrome.",
        "colors": _palette(
            primary="#e2e8f0",
            secondary="#94a3b8",
            accent="#38bdf8",
            muted="#64748b",
            surface="#0f172a",
            border="#1e293b",
        ),
        "spinner": {
            "faces": ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"],
            "verbs": ["routing", "grounding", "verifying", "synthesizing"],
            "interval_ms": 80,
            "done_symbol": "✓",
        },
        "branding": {
            "product_name": "Nerva",
            "tagline": "Local-first governed autonomy",
            "prompt_symbol": "nerva ❯",
            "assistant_label": "nerva",
            "user_label": "you",
            "divider_char": "─",
        },
        "tool_prefix": "⟡",
        "tool_emojis": dict(_BASE_TOOL_EMOJIS),
        "banner_logo": _DEFAULT_LOGO,
        "banner_hero": "Local-first multi-agent hub · governed tool surface",
    },
    {
        "name": "hermes-classic",
        "description": "Classic Hermes bronze, gold wing accents and caduceus spinner.",
        "colors": _palette(
            primary="#fef3c7",
            secondary="#fcd34d",
            accent="#f59e0b",
            muted="#a16207",
            surface="#1c1917",
            border="#78350f",
        ),
        "spinner": {
            "faces": ["🪽", "✦", "✧", "✦"],
            "verbs": ["consulting", "deliberating", "dispatching", "composing"],
            "interval_ms": 120,
            "done_symbol": "✦",
        },
        "branding": {
            "product_name": "Nerva · Hermes Classic",
            "tagline": "Swift terminal chrome with governed execution",
            "prompt_symbol": "⚕ ❯",
            "assistant_label": "hermes",
            "user_label": "operator",
            "divider_char": "═",
        },
        "tool_prefix": "⚡",
        "tool_emojis": {**_BASE_TOOL_EMOJIS, "delegate_task": "🪽", "terminal_run": "⚡"},
        "banner_logo": _DEFAULT_LOGO,
        "banner_hero": "Classic gold terminal chrome · governed Nerva runtime",
    },
    {
        "name": "solar-dawn",
        "description": "Warm daylight amber and parchment palette for bright terminals.",
        "colors": _palette(
            primary="#1e293b",
            secondary="#475569",
            accent="#d97706",
            muted="#94a3b8",
            surface="#fefce8",
            border="#fde68a",
        ),
        "spinner": {
            "faces": ["◐", "◓", "◑", "◒"],
            "verbs": ["reading", "planning", "checking", "answering"],
            "interval_ms": 100,
            "done_symbol": "●",
        },
        "branding": {
            "product_name": "Nerva · Solar Dawn",
            "tagline": "Daylight-balanced operator workspace",
            "prompt_symbol": "☀ ❯",
            "assistant_label": "nerva",
            "user_label": "you",
            "divider_char": "─",
        },
        "tool_prefix": "◈",
        "tool_emojis": dict(_BASE_TOOL_EMOJIS),
        "banner_logo": _DEFAULT_LOGO,
        "banner_hero": "Daylight palette · crisp contrast without glare",
    },
    {
        "name": "cyber-cyan",
        "description": "High-contrast neon cyan and violet grid aesthetic.",
        "colors": _palette(
            primary="#ecfeff",
            secondary="#a5f3fc",
            accent="#06b6d4",
            muted="#0e7490",
            surface="#083344",
            border="#155e75",
        ),
        "spinner": {
            "faces": ["◢", "◣", "◤", "◥"],
            "verbs": ["scanning", "compiling", "probing", "resolving"],
            "interval_ms": 70,
            "done_symbol": "◆",
        },
        "branding": {
            "product_name": "Nerva · Cyber Cyan",
            "tagline": "High-contrast operator telemetry",
            "prompt_symbol": "◈❯",
            "assistant_label": "core",
            "user_label": "op",
            "divider_char": "━",
        },
        "tool_prefix": "▸",
        "tool_emojis": dict(_BASE_TOOL_EMOJIS),
        "banner_logo": _DEFAULT_LOGO,
        "banner_hero": "Neon telemetry skin · zero-trust execution",
    },
    {
        "name": "amber-terminal",
        "description": "Retro phosphor CRT amber monochrome terminal.",
        "colors": _palette(
            primary="#ffb000",
            secondary="#cc8800",
            accent="#ffcc33",
            muted="#805500",
            surface="#120c00",
            border="#664400",
            ok="#ffcc33",
            warn="#ff9900",
            error="#ff5500",
        ),
        "spinner": {
            "faces": ["|", "/", "-", "\\"],
            "verbs": ["working", "computing", "fetching", "printing"],
            "interval_ms": 90,
            "done_symbol": "+",
        },
        "branding": {
            "product_name": "NERVA VT-220",
            "tagline": "Amber phosphor operator console",
            "prompt_symbol": "READY>",
            "assistant_label": "SYS",
            "user_label": "USR",
            "divider_char": "-",
        },
        "tool_prefix": ">>",
        "tool_emojis": dict.fromkeys(_BASE_TOOL_EMOJIS, "*"),
        "banner_logo": _DEFAULT_LOGO,
        "banner_hero": "P3 AMBER PHOSPHOR TERMINAL · LOCAL FIRST",
    },
    {
        "name": "forest-moss",
        "description": "Calm botanical emerald, pine and sage palette.",
        "colors": _palette(
            primary="#ecfdf5",
            secondary="#a7f3d0",
            accent="#10b981",
            muted="#047857",
            surface="#022c22",
            border="#065f46",
        ),
        "spinner": {
            "faces": ["🌱", "🌿", "🍃", "🌿"],
            "verbs": ["cultivating", "gathering", "tending", "distilling"],
            "interval_ms": 130,
            "done_symbol": "✓",
        },
        "branding": {
            "product_name": "Nerva · Forest Moss",
            "tagline": "Quiet local workspace",
            "prompt_symbol": "🌿 ❯",
            "assistant_label": "nerva",
            "user_label": "you",
            "divider_char": "─",
        },
        "tool_prefix": "✦",
        "tool_emojis": dict(_BASE_TOOL_EMOJIS),
        "banner_logo": _DEFAULT_LOGO,
        "banner_hero": "Botanical emerald chrome · calm deep-work sessions",
    },
    {
        "name": "crimson-forge",
        "description": "Deep forge ember, ruby accent and brushed steel.",
        "colors": _palette(
            primary="#ffe4e6",
            secondary="#fda4af",
            accent="#f43f5e",
            muted="#9f1239",
            surface="#1f0910",
            border="#881337",
        ),
        "spinner": {
            "faces": ["⬖", "⬘", "⬗", "⬙"],
            "verbs": ["forging", "tempering", "inspecting", "sealing"],
            "interval_ms": 85,
            "done_symbol": "❖",
        },
        "branding": {
            "product_name": "Nerva · Crimson Forge",
            "tagline": "Tempered engineering chrome",
            "prompt_symbol": "❖ ❯",
            "assistant_label": "forge",
            "user_label": "builder",
            "divider_char": "━",
        },
        "tool_prefix": "⚒",
        "tool_emojis": dict(_BASE_TOOL_EMOJIS),
        "banner_logo": _DEFAULT_LOGO,
        "banner_hero": "Tempered steel & ember · deterministic builds",
    },
    {
        "name": "mono-ink",
        "description": "Distraction-free grayscale e-ink aesthetic.",
        "colors": _palette(
            primary="#f8fafc",
            secondary="#cbd5e1",
            accent="#e2e8f0",
            muted="#64748b",
            surface="#09090b",
            border="#3f3f46",
            ok="#d4d4d8",
            warn="#a1a1aa",
            error="#f4f4f5",
        ),
        "spinner": {
            "faces": [".  ", ".. ", "...", " ..", "  .", "···"],
            "verbs": ["thinking", "reading", "writing", "checking"],
            "interval_ms": 110,
            "done_symbol": "ok",
        },
        "branding": {
            "product_name": "Nerva · Mono Ink",
            "tagline": "Minimal monochrome interface",
            "prompt_symbol": ">",
            "assistant_label": "nerva",
            "user_label": "you",
            "divider_char": "-",
        },
        "tool_prefix": "·",
        "tool_emojis": dict.fromkeys(_BASE_TOOL_EMOJIS, "-"),
        "banner_logo": _DEFAULT_LOGO,
        "banner_hero": "Monochrome ink · zero visual noise",
    },
    {
        "name": "nordic-frost",
        "description": "Glacier ice blue and cool arctic slate.",
        "colors": _palette(
            primary="#e5e9f0",
            secondary="#d8dee9",
            accent="#88c0d0",
            muted="#4c566a",
            surface="#2e3440",
            border="#434c5e",
            ok="#a3be8c",
            warn="#ebcb8b",
            error="#bf616a",
        ),
        "spinner": {
            "faces": ["❄", "❅", "❆", "❅"],
            "verbs": ["crystallizing", "tracing", "indexing", "answering"],
            "interval_ms": 115,
            "done_symbol": "✓",
        },
        "branding": {
            "product_name": "Nerva · Nordic Frost",
            "tagline": "Arctic slate terminal theme",
            "prompt_symbol": "❄ ❯",
            "assistant_label": "nerva",
            "user_label": "you",
            "divider_char": "─",
        },
        "tool_prefix": "❄",
        "tool_emojis": dict(_BASE_TOOL_EMOJIS),
        "banner_logo": _DEFAULT_LOGO,
        "banner_hero": "Arctic slate & frost · crisp long-session readability",
    },
)


def _check_inline_text(
    value: Any, field_name: str, *, max_len: int, allow_empty: bool = False
) -> str | None:
    if not isinstance(value, str):
        return f"{field_name} must be a string"
    if not allow_empty and not value.strip():
        return f"{field_name} must be non-empty"
    if len(value) > max_len:
        return f"{field_name} exceeds max length ({max_len})"
    if _FORBIDDEN_INLINE_RE.search(value):
        return f"{field_name} contains forbidden control or escape characters"
    return None


def validate_skin_dict(
    raw: Any,
    *,
    expected_name: str | None = None,
    allow_partial: bool = True,
    source: str = "user",
    path: str = "",
) -> Skin:
    """Validate *raw* against the CLI skin schema and return an immutable :class:`Skin`.

    When ``allow_partial=True`` (the rule for user YAML skins), omitted sections or keys
    inherit from ``nerva-obsidian`` while every supplied key is strictly validated.
    """
    if not isinstance(raw, Mapping):
        raise SkinValidationError("skin document must be a YAML/JSON mapping")

    problems: list[str] = []
    unknown_top = sorted(set(raw.keys()) - TOP_LEVEL_KEYS)
    if unknown_top:
        problems.append(f"unknown top-level keys: {', '.join(unknown_top)}")

    name = raw.get("name", expected_name or "")
    if not isinstance(name, str) or not _NAME_RE.fullmatch(name):
        problems.append("name must match ^[a-z0-9][a-z0-9_-]{0,47}$")
    elif expected_name and name != expected_name:
        problems.append(f"name {name!r} does not match file stem {expected_name!r}")

    base = _BUILTIN_SPECS[0]
    description = raw.get("description", base["description"] if allow_partial else "")
    err = _check_inline_text(description, "description", max_len=240)
    if err:
        problems.append(err)

    # Colors
    colors_in = raw.get("colors", {} if allow_partial else None)
    merged_colors = dict(base["colors"])
    if not isinstance(colors_in, Mapping):
        problems.append("colors must be a mapping")
    else:
        unknown_colors = sorted(set(colors_in.keys()) - set(COLOR_KEYS))
        if unknown_colors:
            problems.append(f"unknown color keys: {', '.join(unknown_colors)}")
        if not allow_partial:
            missing_colors = sorted(set(COLOR_KEYS) - set(colors_in.keys()))
            if missing_colors:
                problems.append(f"missing color keys: {', '.join(missing_colors)}")
        for k, v in colors_in.items():
            if k not in COLOR_KEYS:
                continue
            if not isinstance(v, str) or not _HEX_COLOR_RE.fullmatch(v):
                problems.append(f"colors.{k} must be a #RRGGBB hex string")
            else:
                merged_colors[k] = v.lower()

    # Spinner
    spinner_in = raw.get("spinner", {} if allow_partial else None)
    merged_spinner: dict[str, Any] = {
        "faces": tuple(base["spinner"]["faces"]),
        "verbs": tuple(base["spinner"]["verbs"]),
        "interval_ms": int(base["spinner"]["interval_ms"]),
        "done_symbol": str(base["spinner"]["done_symbol"]),
    }
    if not isinstance(spinner_in, Mapping):
        problems.append("spinner must be a mapping")
    else:
        unknown_sp = sorted(set(spinner_in.keys()) - set(SPINNER_KEYS))
        if unknown_sp:
            problems.append(f"unknown spinner keys: {', '.join(unknown_sp)}")
        if not allow_partial:
            missing_sp = sorted(set(SPINNER_KEYS) - set(spinner_in.keys()))
            if missing_sp:
                problems.append(f"missing spinner keys: {', '.join(missing_sp)}")
        if "faces" in spinner_in:
            faces = spinner_in["faces"]
            if (
                not isinstance(faces, (list, tuple))
                or not (1 <= len(faces) <= 24)
                or any(_check_inline_text(f, "spinner.faces[]", max_len=16, allow_empty=False) for f in faces)
            ):
                problems.append("spinner.faces must be 1..24 non-empty printable strings (<=16 chars)")
            else:
                merged_spinner["faces"] = tuple(str(f) for f in faces)
        if "verbs" in spinner_in:
            verbs = spinner_in["verbs"]
            if (
                not isinstance(verbs, (list, tuple))
                or not (1 <= len(verbs) <= 32)
                or any(_check_inline_text(v, "spinner.verbs[]", max_len=48) for v in verbs)
            ):
                problems.append("spinner.verbs must be 1..32 non-empty printable strings (<=48 chars)")
            else:
                merged_spinner["verbs"] = tuple(str(v) for v in verbs)
        if "interval_ms" in spinner_in:
            iv = spinner_in["interval_ms"]
            if type(iv) is not int or not (40 <= iv <= 2000):
                problems.append("spinner.interval_ms must be an integer between 40 and 2000")
            else:
                merged_spinner["interval_ms"] = iv
        if "done_symbol" in spinner_in:
            ds = spinner_in["done_symbol"]
            ds_err = _check_inline_text(ds, "spinner.done_symbol", max_len=12)
            if ds_err:
                problems.append(ds_err)
            else:
                merged_spinner["done_symbol"] = ds

    # Branding
    branding_in = raw.get("branding", {} if allow_partial else None)
    merged_branding = dict(base["branding"])
    if not isinstance(branding_in, Mapping):
        problems.append("branding must be a mapping")
    else:
        unknown_br = sorted(set(branding_in.keys()) - set(BRANDING_KEYS))
        if unknown_br:
            problems.append(f"unknown branding keys: {', '.join(unknown_br)}")
        if not allow_partial:
            missing_br = sorted(set(BRANDING_KEYS) - set(branding_in.keys()))
            if missing_br:
                problems.append(f"missing branding keys: {', '.join(missing_br)}")
        for k, v in branding_in.items():
            if k not in BRANDING_KEYS:
                continue
            max_len = 1 if k == "divider_char" else (80 if k == "tagline" else 40)
            b_err = _check_inline_text(v, f"branding.{k}", max_len=max_len)
            if b_err:
                problems.append(b_err)
            elif k == "divider_char" and len(v.strip()) != 1:
                problems.append("branding.divider_char must be a single non-whitespace character")
            else:
                merged_branding[k] = v

    # Tool prefix & emojis
    tool_prefix = raw.get("tool_prefix", base["tool_prefix"] if allow_partial else "")
    tp_err = _check_inline_text(tool_prefix, "tool_prefix", max_len=16)
    if tp_err:
        problems.append(tp_err)

    emojis_in = raw.get("tool_emojis", {} if allow_partial else None)
    merged_emojis = dict(base["tool_emojis"])
    if not isinstance(emojis_in, Mapping):
        problems.append("tool_emojis must be a mapping")
    else:
        if len(emojis_in) > 64:
            problems.append("tool_emojis cannot exceed 64 entries")
        for k, v in emojis_in.items():
            if not isinstance(k, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", k):
                problems.append(f"tool_emojis key {k!r} is invalid")
                continue
            e_err = _check_inline_text(v, f"tool_emojis.{k}", max_len=8)
            if e_err:
                problems.append(e_err)
            else:
                merged_emojis[k] = v

    # Banner logo & hero
    banner_logo = raw.get("banner_logo", base["banner_logo"] if allow_partial else "")
    if not isinstance(banner_logo, str) or not banner_logo.strip():
        problems.append("banner_logo must be a non-empty string")
    elif len(banner_logo) > 2048 or banner_logo.count("\n") > 24:
        problems.append("banner_logo exceeds 2048 chars or 24 lines")
    elif _FORBIDDEN_MULTILINE_RE.search(banner_logo):
        problems.append("banner_logo contains forbidden control or escape characters")

    banner_hero = raw.get("banner_hero", base["banner_hero"] if allow_partial else "")
    bh_err = _check_inline_text(banner_hero, "banner_hero", max_len=200)
    if bh_err:
        problems.append(bh_err)

    if problems:
        raise SkinValidationError("invalid skin specification", problems=tuple(problems))

    return Skin(
        name=str(name),
        description=str(description),
        colors=merged_colors,
        spinner=merged_spinner,
        branding=merged_branding,
        tool_prefix=str(tool_prefix),
        tool_emojis=merged_emojis,
        banner_logo=str(banner_logo),
        banner_hero=str(banner_hero),
        source=source,
        path=path,
    )


BUILTIN_SKINS: dict[str, Skin] = {
    spec["name"]: validate_skin_dict(spec, allow_partial=False, source="builtin")
    for spec in _BUILTIN_SPECS
}


def skins_dir() -> Path:
    """User-authored YAML skins directory under the active profile's data root."""
    return data_path("skins")


def _active_state_path() -> Path:
    return skins_dir() / "active.json"


def validate_skin_file(path: str | Path, *, enforce_stem: bool = False) -> Skin:
    """Validate a YAML skin file on disk and return the parsed :class:`Skin`."""
    target = Path(path)
    try:
        if target.is_symlink() or not target.is_file():
            raise SkinValidationError("skin file must be a regular non-symlink file")
        size = target.stat().st_size
    except OSError as exc:
        raise SkinValidationError(f"cannot read skin file: {exc}") from exc
    if size > MAX_SKIN_BYTES:
        raise SkinValidationError(f"skin file exceeds {MAX_SKIN_BYTES} bytes")
    if target.suffix.lower() not in (".yaml", ".yml"):
        raise SkinValidationError("skin file must have a .yaml or .yml extension")
    try:
        raw_text = target.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise SkinValidationError(f"skin file is not valid UTF-8: {exc}") from exc
    try:
        parsed = yaml.safe_load(raw_text)
    except yaml.YAMLError as exc:
        raise SkinValidationError(f"malformed YAML in skin file: {exc}") from exc
    stem = target.stem.lower()
    if enforce_stem and not _NAME_RE.fullmatch(stem):
        raise SkinValidationError(f"skin filename stem {stem!r} is not a valid skin slug")
    if isinstance(parsed, dict) and "name" not in parsed and _NAME_RE.fullmatch(stem):
        parsed = {**parsed, "name": stem}
    return validate_skin_dict(
        parsed,
        expected_name=stem if enforce_stem else None,
        allow_partial=True,
        source="user",
        path=str(target),
    )


def load_user_skins(*, directory: Path | None = None) -> tuple[dict[str, Skin], dict[str, str]]:
    """Scan ``<data_root>/skins/*.yaml`` and return ``(valid_skins, errors_by_file)``."""
    folder = Path(directory) if directory is not None else skins_dir()
    valid: dict[str, Skin] = {}
    errors: dict[str, str] = {}
    try:
        if folder.is_symlink() or not folder.is_dir():
            return valid, errors
        entries = sorted(folder.iterdir(), key=lambda p: p.name)
    except OSError:
        return valid, errors

    for entry in entries:
        if entry.suffix.lower() not in (".yaml", ".yml"):
            continue
        try:
            skin = validate_skin_file(entry, enforce_stem=True)
        except SkinValidationError as exc:
            errors[entry.name] = str(exc)
            continue
        if skin.name in BUILTIN_SKINS:
            errors[entry.name] = f"cannot shadow built-in skin {skin.name!r}"
            continue
        valid[skin.name] = skin
    return valid, errors


def all_skins(*, directory: Path | None = None) -> tuple[dict[str, Skin], dict[str, str]]:
    """Return ``(all_available_skins, user_skin_errors)``."""
    user_skins, errors = load_user_skins(directory=directory)
    merged = dict(BUILTIN_SKINS)
    merged.update(user_skins)
    return merged, errors


def get_skin(name: str, *, directory: Path | None = None) -> Skin | None:
    if not isinstance(name, str):
        return None
    slug = name.strip().lower()
    skins, _ = all_skins(directory=directory)
    return skins.get(slug)


def active_skin_name(*, env: Mapping[str, str] | None = None, directory: Path | None = None) -> str:
    """Return the active skin slug (env override -> persisted state -> default)."""
    for key in ("NERVA_SKIN", "HERMES_SKIN"):
        raw = env.get(key, "") if env is not None else env_str(key, "")
        candidate = str(raw or "").strip().lower()
        if candidate and get_skin(candidate, directory=directory) is not None:
            return candidate
    state_path = (Path(directory) / "active.json") if directory is not None else _active_state_path()
    try:
        if not state_path.is_symlink() and state_path.is_file():
            data = json.loads(state_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                chosen = str(data.get("skin", "") or "").strip().lower()
                if chosen and get_skin(chosen, directory=directory) is not None:
                    return chosen
    except (OSError, UnicodeDecodeError, ValueError):
        pass
    return DEFAULT_SKIN_NAME


def get_active_skin(*, env: Mapping[str, str] | None = None, directory: Path | None = None) -> Skin:
    name = active_skin_name(env=env, directory=directory)
    return get_skin(name, directory=directory) or BUILTIN_SKINS[DEFAULT_SKIN_NAME]


def set_active_skin(name: str, *, directory: Path | None = None) -> Skin:
    """Persist *name* as the active CLI skin under the data root; raise KeyError if unknown."""
    slug = str(name or "").strip().lower()
    skin = get_skin(slug, directory=directory)
    if skin is None:
        raise KeyError(f"unknown skin: {name!r}")
    folder = Path(directory) if directory is not None else skins_dir()
    if folder.exists() and folder.is_symlink():
        raise SkinValidationError("refusing to write through a symlinked skins directory")
    folder.mkdir(parents=True, exist_ok=True)
    state_path = folder / "active.json"
    if state_path.is_symlink():
        raise SkinValidationError("refusing to overwrite a symlinked active.json")
    tmp_path = folder / ".active.json.tmp"
    tmp_path.write_text(json.dumps({"skin": skin.name}, indent=2) + "\n", encoding="utf-8")
    tmp_path.replace(state_path)
    return skin


def reset_active_skin(*, directory: Path | None = None) -> Skin:
    return set_active_skin(DEFAULT_SKIN_NAME, directory=directory)


def list_skins(*, env: Mapping[str, str] | None = None, directory: Path | None = None) -> dict[str, Any]:
    """Structured skin inventory for `nerva skin list` and `/skin`."""
    skins, errors = all_skins(directory=directory)
    active = active_skin_name(env=env, directory=directory)
    items = [
        {
            "name": skin.name,
            "active": skin.name == active,
            "source": skin.source,
            "description": skin.description,
            "accent": skin.colors["accent"],
            "prompt_symbol": skin.branding["prompt_symbol"],
            "tool_prefix": skin.tool_prefix,
        }
        for skin in skins.values()
    ]
    return {
        "active": active,
        "skins_dir": str(Path(directory) if directory is not None else skins_dir()),
        "skins": items,
        "errors": errors,
    }


# ── ANSI & terminal rendering helpers ────────────────────────────────────────

_ANSI_RESET = "\x1b[0m"


def _color_enabled(env: Mapping[str, str] | None = None) -> bool:
    if env is not None:
        if "NO_COLOR" in env:
            return False
        return str(env.get("TERM", "") or "").lower() != "dumb"
    if env_str("NO_COLOR", "\x00") != "\x00":
        return False
    return env_str("TERM", "").lower() != "dumb"


def ansi_fg(hex_color: str, *, env: Mapping[str, str] | None = None) -> str:
    """Return 24-bit foreground escape for ``#RRGGBB``, or ``""`` when colour is off."""
    if not _color_enabled(env) or not _HEX_COLOR_RE.fullmatch(hex_color or ""):
        return ""
    r = int(hex_color[1:3], 16)
    g = int(hex_color[3:5], 16)
    b = int(hex_color[5:7], 16)
    return f"\x1b[38;2;{r};{g};{b}m"


def _paint(text: str, hex_color: str, *, env: Mapping[str, str] | None = None) -> str:
    code = ansi_fg(hex_color, env=env)
    return f"{code}{text}{_ANSI_RESET}" if code else text


def render_banner(
    skin: Skin | None = None,
    *,
    backend: str = "",
    agents_count: int = 0,
    skills_count: int = 0,
    env: Mapping[str, str] | None = None,
) -> str:
    """Render the themed startup banner for the CLI / REPL."""
    active = skin or get_active_skin(env=env)
    c = active.colors
    b = active.branding
    logo = _paint(active.banner_logo, c["banner_border"], env=env)
    title = _paint(b["product_name"], c["banner_title"], env=env)
    tagline = _paint(b["tagline"], c["banner_accent"], env=env)
    hero = _paint(active.banner_hero, c["banner_text"], env=env)
    divider = _paint(b["divider_char"] * 40, c["border"], env=env)
    lines = [logo, f"  {title} — {tagline}", f"  {hero}"]
    stats: list[str] = [f"skin={active.name}"]
    if backend:
        stats.append(f"backend={backend}")
    if agents_count:
        stats.append(f"agents={agents_count}")
    if skills_count:
        stats.append(f"skills={skills_count}")
    lines.append("  " + _paint(" · ".join(stats), c["banner_dim"], env=env))
    lines.append(f"  {divider}")
    return "\n".join(lines)


def format_spinner_frame(
    skin: Skin | None = None,
    step: int = 0,
    *,
    detail: str = "",
    env: Mapping[str, str] | None = None,
) -> str:
    """Render one animated spinner frame using the skin's faces and thinking verbs."""
    active = skin or get_active_skin(env=env)
    faces = active.spinner["faces"]
    verbs = active.spinner["verbs"]
    idx = max(0, int(step))
    face = faces[idx % len(faces)]
    verb = verbs[(idx // max(1, len(faces))) % len(verbs)]
    head = _paint(f"{face} {verb}…", active.colors["spinner"], env=env)
    if detail:
        return f"{head} {_paint(detail, active.colors['muted'], env=env)}"
    return head


def format_spinner_done(
    skin: Skin | None = None,
    message: str = "done",
    *,
    env: Mapping[str, str] | None = None,
) -> str:
    active = skin or get_active_skin(env=env)
    sym = _paint(str(active.spinner["done_symbol"]), active.colors["ui_ok"], env=env)
    body = _paint(message, active.colors["primary"], env=env)
    return f"{sym} {body}"


def format_tool_line(
    tool_name: str,
    summary: str = "",
    *,
    skin: Skin | None = None,
    env: Mapping[str, str] | None = None,
) -> str:
    """Format a CLI tool-invocation status line with the skin's prefix and tool emoji."""
    active = skin or get_active_skin(env=env)
    emoji = active.tool_emojis.get(tool_name) or active.tool_emojis.get("default", "•")
    prefix = _paint(active.tool_prefix, active.colors["tool_prefix"], env=env)
    label = _paint(f"{emoji} {tool_name}", active.colors["ui_label"], env=env)
    if summary:
        return f"{prefix} {label} {_paint(summary, active.colors['muted'], env=env)}"
    return f"{prefix} {label}"


def format_prompt(skin: Skin | None = None, *, env: Mapping[str, str] | None = None) -> str:
    """Return the themed REPL prompt string."""
    active = skin or get_active_skin(env=env)
    return _paint(active.branding["prompt_symbol"], active.colors["prompt"], env=env) + " "


__all__ = [
    "BRANDING_KEYS",
    "BUILTIN_SKINS",
    "COLOR_KEYS",
    "DEFAULT_SKIN_NAME",
    "MAX_SKIN_BYTES",
    "SPINNER_KEYS",
    "Skin",
    "SkinValidationError",
    "TOP_LEVEL_KEYS",
    "active_skin_name",
    "all_skins",
    "ansi_fg",
    "format_prompt",
    "format_spinner_done",
    "format_spinner_frame",
    "format_tool_line",
    "get_active_skin",
    "get_skin",
    "list_skins",
    "load_user_skins",
    "render_banner",
    "reset_active_skin",
    "set_active_skin",
    "skins_dir",
    "validate_skin_dict",
    "validate_skin_file",
]
