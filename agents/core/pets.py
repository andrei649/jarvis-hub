"""
pets.py — H214 + H238 + H590 Nerva Companion / Petdex / Hatch-a-Pet System.

Delivers:
  - H214 (desktop / HUD): Hatch-a-Pet flow (concept prompt, example chips, image-backend
    picker, optional reference image palette extraction, 4-draft candidate grid,
    confirmed remix, hatching transition & adopt), Petdex gallery, and floating
    always-on-top companion overlay with roam, scale, pop-out, and delete confirmation.
  - H238 (TUI / core): Pet info, meta, cells, gallery, select, remove, export/import
    (.zip), rename, thumb (SVG), disable/enable, scale, candidate generation + status +
    cancel, hatching draft into installed pet, and Unicode half-block (`▀`) frame rendering.
  - H590 (feature-pages / CLI / slash): Companion animated by live agent state
    (`idle` / `thinking` / `tool` / `finishing` / `failing`), `/pet` and `/hatch` slash
    commands, `nerva pets` CLI family (with Kitty/iTerm2 inline graphics protocols +
    half-block fallback), `pets.*` declared settings, and `nerva pets doctor`.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import re
import struct
import time
import uuid
import zipfile
import zlib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from agents.core.paths import data_path
from agents.core.persistence import JsonStore

DEFAULT_PATH = data_path("pets.json")

AGENT_STATES = ("idle", "thinking", "tool", "finishing", "failing")
IMAGE_BACKENDS = ("procedural-pixel", "svg-synth", "local-vlm")
EXAMPLE_PROMPTS = (
    "cyberpunk barn owl with copper goggles",
    "bioluminescent deep-sea axolotl",
    "clockwork origami fox with brass tail",
    "tiny volcanic forge golem with ember core",
)

_HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,47}$")
_MAX_ZIP_BYTES = 512 * 1024
_MAX_ZIP_ENTRIES = 8
_MAX_REF_IMAGE_BYTES = 1024 * 1024

VIBE_REACTIONS: dict[str, str] = {
    "idle": "perched quietly · watching the workspace",
    "thinking": "ears perked · tracing reasoning paths",
    "tool": "sparks flying · operating governed tools",
    "finishing": "happy bounce · wrapping up the turn",
    "failing": "alert ruffle · checking diagnostics",
}


class PetError(Exception):
    """Structured error raised by PetStore operations."""

    def __init__(self, reason: str, status: int = 400, detail: str = "") -> None:
        super().__init__(detail or reason)
        self.reason = reason
        self.status = status
        self.detail = detail or reason


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    c = (hex_color or "#000000").strip()
    if not _HEX_COLOR_RE.fullmatch(c):
        return (95, 168, 216)
    return (int(c[1:3], 16), int(c[3:5], 16), int(c[5:7], 16))


def _rgb_to_hex(r: int, g: int, b: int) -> str:
    return f"#{max(0, min(255, r)):02x}{max(0, min(255, g)):02x}{max(0, min(255, b)):02x}"


def _shift_hex(hex_color: str, dr: int, dg: int, db: int) -> str:
    r, g, b = _hex_to_rgb(hex_color)
    return _rgb_to_hex(r + dr, g + dg, b + db)


def _build_state_frames(
    mask_idle: list[str],
    palette: dict[str, str],
) -> dict[str, list[list[list[str]]]]:
    """Build deterministic 2-frame 8x8 RGB hex grids for each of the 5 live agent states."""
    bg = palette["bg"]
    pri = palette["primary"]
    sec = palette["secondary"]
    acc = palette["accent"]
    eye = palette["eye"]

    def _map_row(row_str: str, *, eye_override: str | None = None, accent_override: str | None = None) -> list[str]:
        table = {
            ".": bg,
            "P": pri,
            "S": sec,
            "A": accent_override or acc,
            "E": eye_override or eye,
        }
        return [table.get(ch, bg) for ch in row_str[:8].ljust(8, ".")]

    idle_f0 = [_map_row(r) for r in mask_idle]
    # Frame 1 subtle breathing shift (bob top/bottom row if empty or blink accent)
    idle_f1 = [_map_row(r, accent_override=_shift_hex(acc, 20, 20, 20)) for r in mask_idle]

    thinking_f0 = [_map_row(r, eye_override="#ffd166", accent_override="#7fd6ff") for r in mask_idle]
    thinking_f1 = [list(reversed(row)) for row in thinking_f0]

    tool_f0 = [_map_row(r, eye_override="#41f59b", accent_override="#41f59b") for r in mask_idle]
    tool_f1 = [_map_row(r, eye_override="#ffffff", accent_override="#00d4aa") for r in mask_idle]

    finishing_f0 = [_map_row(r, eye_override="#a8ff78", accent_override="#ffd166") for r in mask_idle]
    finishing_f1 = [idle_f0[(idx + 1) % 8] for idx in range(8)]

    failing_f0 = [_map_row(r, eye_override="#ff5a52", accent_override="#ff5a52") for r in mask_idle]
    failing_f1 = [_map_row(r, eye_override="#ffb703", accent_override="#d62828") for r in mask_idle]

    return {
        "idle": [idle_f0, idle_f1],
        "thinking": [thinking_f0, thinking_f1],
        "tool": [tool_f0, tool_f1],
        "finishing": [finishing_f0, finishing_f1],
        "failing": [failing_f0, failing_f1],
    }


_BUILTIN_SPECS: tuple[dict[str, Any], ...] = (
    {
        "id": "spark-owl",
        "name": "Spark Owl",
        "species": "Strigiform Automaton",
        "rarity": "starter",
        "vibe": "vigilant",
        "palette": {
            "bg": "#0d1b2a",
            "primary": "#5fa8d8",
            "secondary": "#1b4965",
            "accent": "#ffd166",
            "eye": "#41f59b",
        },
        "mask": [
            ".A....A.",
            ".PPPPPP.",
            "PPEPPEPP",
            "PPPPPPPP",
            ".PSSSSP.",
            ".PSSSSP.",
            "..PPPP..",
            "..A..A..",
        ],
    },
    {
        "id": "circuit-fox",
        "name": "Circuit Fox",
        "species": "Vulpes Silicon",
        "rarity": "uncommon",
        "vibe": "nimble",
        "palette": {
            "bg": "#14111f",
            "primary": "#f77f00",
            "secondary": "#fcbf49",
            "accent": "#4cc9f0",
            "eye": "#ffffff",
        },
        "mask": [
            "P......P",
            "PP....PP",
            "PPPPPPPP",
            "PEPPPPEP",
            ".PSSSSP.",
            "..PPPP..",
            ".PPPPPP.",
            "AA....AA",
        ],
    },
    {
        "id": "nebula-cat",
        "name": "Nebula Cat",
        "species": "Felis Astral",
        "rarity": "rare",
        "vibe": "curious",
        "palette": {
            "bg": "#10002b",
            "primary": "#9d4edd",
            "secondary": "#c77dff",
            "accent": "#72efdd",
            "eye": "#ffea00",
        },
        "mask": [
            ".P....P.",
            ".PP..PP.",
            ".PPPPPP.",
            ".PEAAEP.",
            "..PPPP..",
            ".PSSSSP.",
            ".PPPPPP.",
            ".A....A.",
        ],
    },
    {
        "id": "forge-golem",
        "name": "Forge Golem",
        "species": "Lithos Core",
        "rarity": "rare",
        "vibe": "steadfast",
        "palette": {
            "bg": "#1b1a17",
            "primary": "#6c757d",
            "secondary": "#495057",
            "accent": "#ff6b35",
            "eye": "#ffd166",
        },
        "mask": [
            "..AAAA..",
            ".PPPPPP.",
            "PPE..EPP",
            "PPPPPPPP",
            "PSSAAASP",
            "PPPPPPPP",
            ".PP..PP.",
            ".SS..SS.",
        ],
    },
    {
        "id": "void-axolotl",
        "name": "Void Axolotl",
        "species": "Ambystoma Abyssal",
        "rarity": "epic",
        "vibe": "serene",
        "palette": {
            "bg": "#081c24",
            "primary": "#ff70a6",
            "secondary": "#ff9770",
            "accent": "#70d6ff",
            "eye": "#1b263b",
        },
        "mask": [
            "A.PPPP.A",
            "AAPPPPAA",
            ".PEPPPE.",
            ".PPPPPP.",
            "..SSSS..",
            ".PPPPPP.",
            "..P..P..",
            ".A....A.",
        ],
    },
    {
        "id": "pixel-raven",
        "name": "Pixel Raven",
        "species": "Corvus Cipher",
        "rarity": "uncommon",
        "vibe": "analytic",
        "palette": {
            "bg": "#0b0c10",
            "primary": "#3a506b",
            "secondary": "#1c2541",
            "accent": "#6fffe9",
            "eye": "#6fffe9",
        },
        "mask": [
            "...PPP..",
            "..PPPPP.",
            ".PPEPPAA",
            ".PPPPPP.",
            "PPSSSSP.",
            "PPPPPPP.",
            "..P..P..",
            "..A..A..",
        ],
    },
)


def _builtin_pets() -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for spec in _BUILTIN_SPECS:
        pid = spec["id"]
        out[pid] = {
            "id": pid,
            "name": spec["name"],
            "species": spec["species"],
            "rarity": spec["rarity"],
            "vibe": spec["vibe"],
            "builtin": True,
            "created_at": 0.0,
            "palette": dict(spec["palette"]),
            "frames": _build_state_frames(spec["mask"], spec["palette"]),
        }
    return out


_BUILTINS = _builtin_pets()


def _procedural_candidate(seed_text: str, index: int, ref_hex: str | None = None) -> dict[str, Any]:
    digest = hashlib.sha256(f"{seed_text}:{index}".encode()).digest()
    pri = ref_hex if (ref_hex and index % 2 == 0) else _rgb_to_hex(60 + digest[0] % 180, 60 + digest[1] % 180, 80 + digest[2] % 165)
    sec = _rgb_to_hex(40 + digest[3] % 160, 50 + digest[4] % 160, 60 + digest[5] % 160)
    acc = _rgb_to_hex(120 + digest[6] % 135, 100 + digest[7] % 155, 80 + digest[8] % 175)
    eye = ("#41f59b", "#ffd166", "#7fd6ff", "#ffffff")[digest[9] % 4]
    bg = "#0f172a"
    palette = {"bg": bg, "primary": pri, "secondary": sec, "accent": acc, "eye": eye}

    # Build a symmetrical 8x8 creature mask from digest bits.
    chars = (".", "P", "S", "A")
    mask: list[str] = []
    for row_idx in range(8):
        half = []
        for col_idx in range(4):
            b = digest[(row_idx * 4 + col_idx) % len(digest)]
            if row_idx == 2 and col_idx == 1:
                half.append("E")
            elif row_idx in (0, 7) and col_idx in (1, 2):
                half.append("." if b % 2 == 0 else "A")
            elif 1 <= row_idx <= 6 and col_idx >= 1:
                half.append(chars[1 + (b % 3)])
            else:
                half.append("." if b % 3 else "P")
        left = "".join(half)
        mask.append(left + left[::-1])

    vibes = ("playful", "focused", "arcane", "bolted", "radiant", "stoic")
    rarities = ("common", "uncommon", "rare", "epic")
    vibe = vibes[digest[10] % len(vibes)]
    rarity = rarities[digest[11] % len(rarities)]
    frames = _build_state_frames(mask, palette)
    return {
        "draft_id": f"draft_{index + 1}_{digest.hex()[:6]}",
        "index": index,
        "vibe": vibe,
        "rarity": rarity,
        "palette": palette,
        "mask": mask,
        "frames": frames,
        "thumb_svg": render_svg_thumbnail(frames["idle"][0]),
    }


def _extract_reference_color(reference_image_b64: str) -> str | None:
    if not reference_image_b64 or not reference_image_b64.strip():
        return None
    raw_str = reference_image_b64.strip()
    if "," in raw_str and raw_str.lower().startswith("data:"):
        raw_str = raw_str.split(",", 1)[1]
    try:
        decoded = base64.b64decode(raw_str, validate=False)
    except Exception as exc:
        raise PetError("invalid_reference_image", status=400, detail="invalid base64 reference image") from exc
    if len(decoded) > _MAX_REF_IMAGE_BYTES:
        raise PetError("reference_image_too_large", status=413, detail="reference image exceeds 1 MiB")
    if not decoded:
        return None
    h = hashlib.sha256(decoded).digest()
    return _rgb_to_hex(70 + h[0] % 170, 70 + h[1] % 170, 70 + h[2] % 170)


def render_svg_thumbnail(cells_grid: list[list[str]], *, pixel_size: int = 8) -> str:
    """Render an 8x8 hex color grid as crisp, dependency-free SVG markup."""
    rows = len(cells_grid)
    cols = len(cells_grid[0]) if rows else 0
    w = cols * pixel_size
    h = rows * pixel_size
    rects: list[str] = []
    for y, row in enumerate(cells_grid):
        for x, color in enumerate(row):
            safe_c = color if _HEX_COLOR_RE.fullmatch(str(color)) else "#0d1b2a"
            rects.append(
                f'<rect x="{x * pixel_size}" y="{y * pixel_size}" '
                f'width="{pixel_size}" height="{pixel_size}" fill="{safe_c}"/>'
            )
    body = "".join(rects)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" '
        f'width="{w}" height="{h}" shape-rendering="crispEdges">{body}</svg>'
    )


def render_halfblock(cells_grid: list[list[str]], *, ansi: bool = True) -> str:
    """Render a 2D hex color cell grid using Unicode upper-half-blocks (`▀`)."""
    if not cells_grid:
        return ""
    lines: list[str] = []
    height = len(cells_grid)
    for y in range(0, height, 2):
        top_row = cells_grid[y]
        bot_row = cells_grid[y + 1] if (y + 1) < height else top_row
        chunks: list[str] = []
        for top_hex, bot_hex in zip(top_row, bot_row, strict=False):
            if ansi:
                tr, tg, tb = _hex_to_rgb(top_hex)
                br, bg_c, bb = _hex_to_rgb(bot_hex)
                chunks.append(f"\x1b[38;2;{tr};{tg};{tb}m\x1b[48;2;{br};{bg_c};{bb}m▀")
            else:
                top_luma = sum(_hex_to_rgb(top_hex)) / 3
                bot_luma = sum(_hex_to_rgb(bot_hex)) / 3
                if top_luma > 80 and bot_luma > 80:
                    chunks.append("█")
                elif top_luma > 80:
                    chunks.append("▀")
                elif bot_luma > 80:
                    chunks.append("▄")
                else:
                    chunks.append(" ")
        suffix = "\x1b[0m" if ansi else ""
        lines.append("".join(chunks) + suffix)
    return "\n".join(lines)


def encode_rgba_png(cells_grid: list[list[str]], *, scale_px: int = 4) -> bytes:
    """Encode a 2D hex color grid as a valid RGBA PNG using stdlib `struct` + `zlib`."""
    rows = len(cells_grid)
    cols = len(cells_grid[0]) if rows else 0
    width = max(1, cols * scale_px)
    height = max(1, rows * scale_px)

    raw_scanlines = bytearray()
    for row in cells_grid:
        rgb_row = [_hex_to_rgb(c) for c in row]
        for _ in range(scale_px):
            raw_scanlines.append(0)  # PNG filter type 0 (None)
            for r, g, b in rgb_row:
                for _ in range(scale_px):
                    raw_scanlines.extend((r, g, b, 255))

    def _chunk(chunk_type: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(chunk_type + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + chunk_type + data + struct.pack(">I", crc)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    idat = zlib.compress(bytes(raw_scanlines), level=6)
    return b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", idat) + _chunk(b"IEND", b"")


def render_terminal_protocol(
    cells_grid: list[list[str]],
    *,
    protocol: str = "auto",
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Render sprite cells via Kitty graphics, iTerm2 inline image, or Unicode half-block fallback."""
    environ = env if env is not None else os.environ
    chosen = (protocol or "auto").strip().lower()
    if chosen == "auto":
        if environ.get("KITTY_WINDOW_ID") or "kitty" in (environ.get("TERM") or "").lower():
            chosen = "kitty"
        elif environ.get("TERM_PROGRAM") == "iTerm.app" or environ.get("LC_TERMINAL") == "iTerm2":
            chosen = "iterm2"
        else:
            chosen = "halfblock"

    no_color = bool(environ.get("NO_COLOR"))
    if chosen == "kitty":
        png_b64 = base64.b64encode(encode_rgba_png(cells_grid, scale_px=6)).decode("ascii")
        rendered = f"\x1b_Ga=T,f=100,m=0;{png_b64}\x1b\\"
        return {"protocol": "kitty", "rendered": rendered}
    if chosen == "iterm2":
        png_bytes = encode_rgba_png(cells_grid, scale_px=6)
        png_b64 = base64.b64encode(png_bytes).decode("ascii")
        rendered = f"\x1b]1337;File=inline=1;size={len(png_bytes)};preserveAspectRatio=1:{png_b64}\a"
        return {"protocol": "iterm2", "rendered": rendered}
    if chosen in {"halfblock", "ascii"}:
        use_ansi = (chosen == "halfblock") and not no_color
        return {
            "protocol": "halfblock" if use_ansi else "ascii",
            "rendered": render_halfblock(cells_grid, ansi=use_ansi),
        }
    raise PetError("unsupported_protocol", status=400, detail=f"unknown terminal protocol {chosen!r}")


def derive_agent_state(orch: Any = None) -> dict[str, Any]:
    """Derive live companion animation state from the real orchestrator runtime."""
    state = "idle"
    detail = "idle"
    if orch is not None:
        if bool(getattr(orch, "_estop_active", False)):
            state = "failing"
            detail = "emergency stop active"
        elif bool(getattr(orch, "_active_tool_name", "")):
            state = "tool"
            detail = f"running tool {getattr(orch, '_active_tool_name', '')}"
        elif bool(getattr(orch, "_turn_in_progress", False)):
            state = "thinking"
            detail = "reasoning in progress"
        else:
            subagents = getattr(orch, "subagents", None)
            list_fn = getattr(subagents, "list", None)
            if callable(list_fn):
                try:
                    items = list_fn() or []
                    if any(isinstance(x, dict) and x.get("status") == "running" for x in items):
                        state = "tool"
                        detail = "delegated sub-agent running"
                    elif any(isinstance(x, dict) and x.get("status") == "failed" for x in items[:2]):
                        state = "failing"
                        detail = "recent sub-agent failed"
                except Exception:
                    pass
    return {
        "agent_state": state,
        "detail": detail,
        "vibe_reaction": VIBE_REACTIONS.get(state, VIBE_REACTIONS["idle"]),
    }


class PetStore(JsonStore):
    """Persistent store for Petdex companions, Hatch-a-Pet drafts, and companion settings."""

    def __init__(self, path: str | Path = DEFAULT_PATH) -> None:
        super().__init__(path)

    def _serialize(self):
        return self._data

    def _deserialize(self, raw) -> None:
        base = raw if isinstance(raw, dict) else {}
        self._data: dict[str, Any] = {
            "enabled": bool(base.get("enabled", True)),
            "active_id": str(base.get("active_id") or "spark-owl"),
            "scale": float(base.get("scale", 1.0)),
            "roam": bool(base.get("roam", False)),
            "overlay_enabled": bool(base.get("overlay_enabled", False)),
            "image_backend": str(base.get("image_backend") or "procedural-pixel"),
            "name_overrides": dict(base.get("name_overrides") or {}),
            "custom_pets": dict(base.get("custom_pets") or {}),
            "jobs": dict(base.get("jobs") or {}),
        }
        if self._data["active_id"] not in _BUILTINS and self._data["active_id"] not in self._data["custom_pets"]:
            self._data["active_id"] = "spark-owl"

    def _resolve_pet_locked(self, pet_id: str | None = None) -> dict[str, Any]:
        pid = (pet_id or self._data["active_id"] or "spark-owl").strip().lower()
        if pid in _BUILTINS:
            pet = dict(_BUILTINS[pid])
        elif pid in self._data["custom_pets"]:
            pet = dict(self._data["custom_pets"][pid])
        else:
            raise PetError("pet_not_found", status=404, detail=f"pet {pid!r} not found")
        override = self._data["name_overrides"].get(pid)
        if override:
            pet["name"] = override
        return pet

    def _sync_settings_db(self, updates: dict[str, Any]) -> None:
        try:
            from agents.core import settings_db

            settings_db.put_category("pets", updates)
        except Exception:
            pass

    # ── H238 core read/mutate verbs ──────────────────────────────────────────

    def info(self, *, orch: Any = None, state_override: str = "") -> dict[str, Any]:
        live = derive_agent_state(orch)
        if state_override and state_override in AGENT_STATES:
            live = {
                "agent_state": state_override,
                "detail": f"preview:{state_override}",
                "vibe_reaction": VIBE_REACTIONS[state_override],
            }
        with self._lock:
            active = self._resolve_pet_locked(self._data["active_id"])
            st = live["agent_state"]
            grid = active["frames"].get(st, active["frames"]["idle"])[0]
            return {
                "ok": True,
                "enabled": self._data["enabled"],
                "active_id": active["id"],
                "active_pet": self._public_meta(active),
                "scale": self._data["scale"],
                "roam": self._data["roam"],
                "overlay_enabled": self._data["overlay_enabled"],
                "image_backend": self._data["image_backend"],
                "installed_count": len(_BUILTINS) + len(self._data["custom_pets"]),
                "custom_count": len(self._data["custom_pets"]),
                "example_prompts": list(EXAMPLE_PROMPTS),
                "image_backends": list(IMAGE_BACKENDS),
                "agent_states": list(AGENT_STATES),
                **live,
                "current_cells": grid,
                "thumb_svg": render_svg_thumbnail(grid),
            }

    @staticmethod
    def _public_meta(pet: dict[str, Any]) -> dict[str, Any]:
        idle_grid = pet["frames"]["idle"][0]
        return {
            "id": pet["id"],
            "name": pet["name"],
            "species": pet["species"],
            "rarity": pet.get("rarity", "common"),
            "vibe": pet.get("vibe", "calm"),
            "builtin": bool(pet.get("builtin", False)),
            "created_at": float(pet.get("created_at", 0.0)),
            "palette": dict(pet.get("palette") or {}),
            "states": list(pet["frames"].keys()),
            "thumb_svg": render_svg_thumbnail(idle_grid),
        }

    def meta(self, pet_id: str | None = None) -> dict[str, Any]:
        with self._lock:
            pet = self._resolve_pet_locked(pet_id)
            return {"ok": True, "pet": self._public_meta(pet)}

    def cells(
        self, pet_id: str | None = None, *, state: str = "idle", frame: int = 0
    ) -> dict[str, Any]:
        st = (state or "idle").strip().lower()
        if st not in AGENT_STATES:
            raise PetError("invalid_state", status=400, detail=f"state must be one of {AGENT_STATES}")
        with self._lock:
            pet = self._resolve_pet_locked(pet_id)
            frames = pet["frames"][st]
            idx = max(0, int(frame)) % len(frames)
            grid = frames[idx]
            return {
                "ok": True,
                "pet_id": pet["id"],
                "name": pet["name"],
                "state": st,
                "frame": idx,
                "frame_count": len(frames),
                "rows": len(grid),
                "cols": len(grid[0]) if grid else 0,
                "cells": grid,
                "all_frames": frames,
            }

    def gallery(self) -> dict[str, Any]:
        with self._lock:
            active_id = self._data["active_id"]
            pets: list[dict[str, Any]] = []
            for pid in list(_BUILTINS.keys()) + sorted(self._data["custom_pets"].keys()):
                pet = self._resolve_pet_locked(pid)
                entry = self._public_meta(pet)
                entry["active"] = pid == active_id
                pets.append(entry)
            return {
                "ok": True,
                "active_id": active_id,
                "enabled": self._data["enabled"],
                "pets": pets,
            }

    def select(self, pet_id: str) -> dict[str, Any]:
        with self._lock:
            pet = self._resolve_pet_locked(pet_id)
            self._data["active_id"] = pet["id"]
            self._data["enabled"] = True
            self._save()
        self._sync_settings_db({"active_id": pet["id"], "enabled": True})
        return {"ok": True, "active_id": pet["id"], "enabled": True, "pet": self._public_meta(pet)}

    def rename(self, pet_id: str, new_name: str) -> dict[str, Any]:
        cleaned = (new_name or "").strip()[:48]
        if not cleaned:
            raise PetError("invalid_name", status=400, detail="new_name must not be empty")
        with self._lock:
            pet = self._resolve_pet_locked(pet_id)
            pid = pet["id"]
            if pid in self._data["custom_pets"]:
                self._data["custom_pets"][pid]["name"] = cleaned
            else:
                self._data["name_overrides"][pid] = cleaned
            self._save()
            updated = self._resolve_pet_locked(pid)
            return {"ok": True, "pet": self._public_meta(updated)}

    def set_scale(self, factor: float) -> dict[str, Any]:
        val = float(factor)
        if val < 0.5 or val > 3.0:
            raise PetError("invalid_scale", status=400, detail="scale must be between 0.5 and 3.0")
        rounded = round(val, 2)
        with self._lock:
            self._data["scale"] = rounded
            self._save()
        self._sync_settings_db({"scale": rounded})
        return {"ok": True, "scale": rounded}

    def update_preferences(
        self,
        *,
        enabled: bool | None = None,
        roam: bool | None = None,
        overlay_enabled: bool | None = None,
        scale: float | None = None,
        image_backend: str | None = None,
    ) -> dict[str, Any]:
        db_updates: dict[str, Any] = {}
        with self._lock:
            if enabled is not None:
                self._data["enabled"] = bool(enabled)
                db_updates["enabled"] = bool(enabled)
            if roam is not None:
                self._data["roam"] = bool(roam)
                db_updates["roam"] = bool(roam)
            if overlay_enabled is not None:
                self._data["overlay_enabled"] = bool(overlay_enabled)
                db_updates["overlay_enabled"] = bool(overlay_enabled)
            if scale is not None:
                s = float(scale)
                if s < 0.5 or s > 3.0:
                    raise PetError("invalid_scale", status=400, detail="scale must be between 0.5 and 3.0")
                self._data["scale"] = round(s, 2)
                db_updates["scale"] = round(s, 2)
            if image_backend is not None:
                b = image_backend.strip().lower()
                if b not in IMAGE_BACKENDS:
                    raise PetError("invalid_backend", status=400, detail=f"backend must be in {IMAGE_BACKENDS}")
                self._data["image_backend"] = b
                db_updates["image_backend"] = b
            self._save()
        if db_updates:
            self._sync_settings_db(db_updates)
        return self.info()

    def disable(self) -> dict[str, Any]:
        return self.update_preferences(enabled=False)

    def enable(self) -> dict[str, Any]:
        return self.update_preferences(enabled=True)

    def remove(self, pet_id: str, *, confirm: bool = False) -> dict[str, Any]:
        if not confirm:
            raise PetError(
                "confirm_required",
                status=409,
                detail="explicit confirm=True required to delete an installed pet",
            )
        pid = (pet_id or "").strip().lower()
        with self._lock:
            if pid in _BUILTINS:
                raise PetError(
                    "builtin_protected",
                    status=409,
                    detail="built-in Petdex species cannot be deleted (use disable instead)",
                )
            if pid not in self._data["custom_pets"]:
                raise PetError("pet_not_found", status=404, detail=f"pet {pid!r} not found")
            del self._data["custom_pets"][pid]
            self._data["name_overrides"].pop(pid, None)
            if self._data["active_id"] == pid:
                self._data["active_id"] = "spark-owl"
            self._save()
            return {"ok": True, "removed": pid, "active_id": self._data["active_id"]}

    def thumb(self, pet_id: str | None = None, *, state: str = "idle") -> dict[str, Any]:
        st = (state or "idle").strip().lower()
        if st not in AGENT_STATES:
            st = "idle"
        with self._lock:
            pet = self._resolve_pet_locked(pet_id)
            grid = pet["frames"][st][0]
            svg = render_svg_thumbnail(grid, pixel_size=12)
            b64 = base64.b64encode(svg.encode("utf-8")).decode("ascii")
            return {
                "ok": True,
                "pet_id": pet["id"],
                "state": st,
                "mime_type": "image/svg+xml",
                "svg": svg,
                "data_uri": f"data:image/svg+xml;base64,{b64}",
            }

    # ── H238 zip export / re-import ──────────────────────────────────────────

    def export_zip(self, pet_id: str | None = None) -> tuple[str, bytes]:
        with self._lock:
            pet = self._resolve_pet_locked(pet_id)
        meta_doc = {
            "format": "nerva-pet-v1",
            "id": pet["id"],
            "name": pet["name"],
            "species": pet["species"],
            "rarity": pet.get("rarity", "common"),
            "vibe": pet.get("vibe", "calm"),
            "palette": pet.get("palette", {}),
            "exported_at": time.time(),
        }
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("pet.json", json.dumps(meta_doc, indent=2, sort_keys=True))
            zf.writestr("cells.json", json.dumps(pet["frames"], indent=2, sort_keys=True))
            zf.writestr("thumb.svg", render_svg_thumbnail(pet["frames"]["idle"][0], pixel_size=12))
        return f"{pet['id']}.pet.zip", buf.getvalue()

    def import_zip(self, raw_bytes: bytes) -> dict[str, Any]:
        if not isinstance(raw_bytes, (bytes, bytearray)) or not raw_bytes:
            raise PetError("invalid_zip", status=400, detail="empty zip archive")
        if len(raw_bytes) > _MAX_ZIP_BYTES:
            raise PetError("zip_too_large", status=413, detail="pet archive exceeds 512 KiB")
        try:
            zf = zipfile.ZipFile(io.BytesIO(bytes(raw_bytes)), "r")
        except zipfile.BadZipFile as exc:
            raise PetError("invalid_zip", status=400, detail="corrupt zip archive") from exc

        with zf:
            infos = zf.infolist()
            if len(infos) > _MAX_ZIP_ENTRIES:
                raise PetError("invalid_zip", status=400, detail="too many files in pet archive")
            total_uncompressed = 0
            files: dict[str, bytes] = {}
            for info in infos:
                fname = info.filename
                if fname.startswith("/") or ".." in fname.split("/") or "\\" in fname:
                    raise PetError("unsafe_zip_path", status=400, detail="unsafe path in zip archive")
                total_uncompressed += info.file_size
                if total_uncompressed > _MAX_ZIP_BYTES:
                    raise PetError("zip_too_large", status=413, detail="uncompressed archive exceeds 512 KiB")
                files[fname] = zf.read(fname)

        if "pet.json" not in files or "cells.json" not in files:
            raise PetError("invalid_zip", status=400, detail="archive requires pet.json and cells.json")
        try:
            meta_doc = json.loads(files["pet.json"].decode("utf-8"))
            frames_doc = json.loads(files["cells.json"].decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise PetError("invalid_zip", status=400, detail="invalid JSON in pet archive") from exc

        if not isinstance(meta_doc, dict) or meta_doc.get("format") != "nerva-pet-v1":
            raise PetError("invalid_zip", status=400, detail="unsupported pet archive format")
        if not isinstance(frames_doc, dict):
            raise PetError("invalid_zip", status=400, detail="cells.json must be an object")

        validated_frames: dict[str, list[list[list[str]]]] = {}
        for st in AGENT_STATES:
            st_frames = frames_doc.get(st)
            if not isinstance(st_frames, list) or not st_frames:
                raise PetError("invalid_zip", status=400, detail=f"missing frames for state {st}")
            clean_st_frames: list[list[list[str]]] = []
            for grid in st_frames[:4]:
                if not isinstance(grid, list) or len(grid) != 8:
                    raise PetError("invalid_zip", status=400, detail="each frame must be 8x8")
                clean_grid: list[list[str]] = []
                for row in grid:
                    if not isinstance(row, list) or len(row) != 8:
                        raise PetError("invalid_zip", status=400, detail="each frame row must have 8 cells")
                    clean_row = [
                        c if isinstance(c, str) and _HEX_COLOR_RE.fullmatch(c) else "#0d1b2a"
                        for c in row
                    ]
                    clean_grid.append(clean_row)
                clean_st_frames.append(clean_grid)
            validated_frames[st] = clean_st_frames

        raw_slug = re.sub(r"[^a-z0-9_-]+", "-", str(meta_doc.get("id") or "pet").lower()).strip("-")
        if not _SLUG_RE.fullmatch(raw_slug) or raw_slug in _BUILTINS:
            raw_slug = f"custom-{uuid.uuid4().hex[:8]}"

        with self._lock:
            if raw_slug in self._data["custom_pets"]:
                raw_slug = f"{raw_slug[:36]}-{uuid.uuid4().hex[:6]}"
            record = {
                "id": raw_slug,
                "name": str(meta_doc.get("name") or raw_slug)[:48],
                "species": str(meta_doc.get("species") or "Imported Companion")[:64],
                "rarity": str(meta_doc.get("rarity") or "custom")[:24],
                "vibe": str(meta_doc.get("vibe") or "calm")[:32],
                "builtin": False,
                "created_at": time.time(),
                "palette": dict(meta_doc.get("palette") or {}),
                "frames": validated_frames,
            }
            self._data["custom_pets"][raw_slug] = record
            self._save()
            return {"ok": True, "pet": self._public_meta(record)}

    # ── H214 + H238 Hatch-a-Pet generation, remix, cancel, and adopt ─────────

    def generate_drafts(
        self,
        prompt: str,
        *,
        image_backend: str = "",
        reference_image_b64: str = "",
        defer_completion: bool = False,
    ) -> dict[str, Any]:
        cleaned_prompt = (prompt or "").strip()[:300]
        if not cleaned_prompt:
            raise PetError("prompt_required", status=400, detail="concept prompt is required")
        backend = (image_backend or self._data.get("image_backend") or "procedural-pixel").strip().lower()
        if backend not in IMAGE_BACKENDS:
            raise PetError("invalid_backend", status=400, detail=f"image_backend must be one of {IMAGE_BACKENDS}")

        ref_color = _extract_reference_color(reference_image_b64)
        job_id = f"pgen_{uuid.uuid4().hex[:12]}"
        now = time.time()
        drafts = [
            _procedural_candidate(f"{cleaned_prompt}|{backend}", idx, ref_hex=ref_color)
            for idx in range(4)
        ]
        job = {
            "job_id": job_id,
            "prompt": cleaned_prompt,
            "image_backend": backend,
            "has_reference_image": bool(ref_color),
            "reference_tint": ref_color,
            "status": "running" if defer_completion else "completed",
            "created_at": now,
            "updated_at": now,
            "drafts": [] if defer_completion else drafts,
            "_staged_drafts": drafts if defer_completion else [],
            "hatched_pet_id": None,
        }
        with self._lock:
            # Bound retained draft jobs to 24.
            if len(self._data["jobs"]) >= 24:
                oldest = min(self._data["jobs"], key=lambda k: self._data["jobs"][k].get("created_at", 0))
                self._data["jobs"].pop(oldest, None)
            self._data["jobs"][job_id] = job
            self._save()
        return self._public_job(job)

    @staticmethod
    def _public_job(job: dict[str, Any]) -> dict[str, Any]:
        drafts_out = [
            {
                "draft_id": d["draft_id"],
                "index": d["index"],
                "vibe": d["vibe"],
                "rarity": d["rarity"],
                "palette": d["palette"],
                "thumb_svg": d["thumb_svg"],
                "preview_cells": d["frames"]["idle"][0],
            }
            for d in job.get("drafts") or []
        ]
        return {
            "ok": True,
            "job_id": job["job_id"],
            "prompt": job["prompt"],
            "image_backend": job["image_backend"],
            "has_reference_image": job.get("has_reference_image", False),
            "reference_tint": job.get("reference_tint"),
            "status": job["status"],
            "created_at": job["created_at"],
            "updated_at": job["updated_at"],
            "drafts": drafts_out,
            "hatched_pet_id": job.get("hatched_pet_id"),
        }

    def generation_status(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            job = self._data["jobs"].get(job_id)
            if job is None:
                raise PetError("job_not_found", status=404, detail=f"generation job {job_id!r} not found")
            if job["status"] == "running" and job.get("_staged_drafts"):
                job["drafts"] = job.pop("_staged_drafts")
                job["status"] = "completed"
                job["updated_at"] = time.time()
                self._save()
            return self._public_job(job)

    def cancel_generation(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            job = self._data["jobs"].get(job_id)
            if job is None:
                raise PetError("job_not_found", status=404, detail=f"generation job {job_id!r} not found")
            if job["status"] == "hatched":
                raise PetError("already_hatched", status=409, detail="job has already hatched a pet")
            job["status"] = "cancelled"
            job.pop("_staged_drafts", None)
            job["updated_at"] = time.time()
            self._save()
            return self._public_job(job)

    def remix_draft(
        self,
        job_id: str,
        draft_id: str,
        *,
        instruction: str = "",
        confirm: bool = False,
    ) -> dict[str, Any]:
        if not confirm:
            raise PetError(
                "confirm_required",
                status=409,
                detail="explicit confirm=True required before remixing candidate drafts",
            )
        with self._lock:
            job = self._data["jobs"].get(job_id)
            if job is None:
                raise PetError("job_not_found", status=404, detail=f"generation job {job_id!r} not found")
            if job["status"] == "cancelled":
                raise PetError("job_cancelled", status=409, detail="cannot remix a cancelled job")
            target_idx = next(
                (i for i, d in enumerate(job.get("drafts") or []) if d["draft_id"] == draft_id),
                None,
            )
            if target_idx is None:
                raise PetError("draft_not_found", status=404, detail=f"draft {draft_id!r} not found")
            seed = f"{job['prompt']}|remix|{instruction.strip()}|{time.time_ns()}"
            remixed = _procedural_candidate(seed, target_idx, ref_hex=job.get("reference_tint"))
            job["drafts"][target_idx] = remixed
            job["updated_at"] = time.time()
            self._save()
            return {
                **self._public_job(job),
                "remixed_draft_id": remixed["draft_id"],
            }

    def hatch_draft(
        self,
        job_id: str,
        draft_id: str,
        *,
        name: str = "",
        adopt_active: bool = True,
    ) -> dict[str, Any]:
        with self._lock:
            job = self._data["jobs"].get(job_id)
            if job is None:
                raise PetError("job_not_found", status=404, detail=f"generation job {job_id!r} not found")
            if job["status"] == "cancelled":
                raise PetError("job_cancelled", status=409, detail="cannot hatch a cancelled job")
            chosen = next(
                (d for d in (job.get("drafts") or []) if d["draft_id"] == draft_id),
                None,
            )
            if chosen is None:
                raise PetError("draft_not_found", status=404, detail=f"draft {draft_id!r} not found")

            pet_id = f"hatch-{uuid.uuid4().hex[:8]}"
            display_name = (name or "").strip()[:48] or f"{chosen['vibe'].title()} Hatchling"
            now = time.time()
            record = {
                "id": pet_id,
                "name": display_name,
                "species": f"Hatched ({job['image_backend']})",
                "rarity": chosen["rarity"],
                "vibe": chosen["vibe"],
                "builtin": False,
                "created_at": now,
                "prompt": job["prompt"],
                "palette": dict(chosen["palette"]),
                "frames": chosen["frames"],
            }
            self._data["custom_pets"][pet_id] = record
            job["status"] = "hatched"
            job["hatched_pet_id"] = pet_id
            job["updated_at"] = now
            if adopt_active:
                self._data["active_id"] = pet_id
                self._data["enabled"] = True
            self._save()

        if adopt_active:
            self._sync_settings_db({"active_id": pet_id, "enabled": True})
        return {
            "ok": True,
            "hatch_stage": "hatched",
            "adopted": bool(adopt_active),
            "active_id": self._data["active_id"],
            "pet": self._public_meta(record),
            "preview_cells": record["frames"]["finishing"][0],
        }

    # ── H590 doctor ──────────────────────────────────────────────────────────

    def doctor(self, *, env: Mapping[str, str] | None = None) -> dict[str, Any]:
        environ = env if env is not None else os.environ
        checks: list[dict[str, Any]] = []

        # 1. Persistence check
        store_dir = self.path.parent
        writable = store_dir.exists() and os.access(store_dir, os.W_OK) or os.access(store_dir.parent, os.W_OK)
        checks.append(
            {
                "name": "store_writable",
                "ok": bool(writable),
                "detail": str(self.path),
            }
        )

        # 2. Active pet frame completeness across all 5 states
        with self._lock:
            active = self._resolve_pet_locked(self._data["active_id"])
        states_ok = all(
            st in active["frames"] and len(active["frames"][st]) >= 1
            for st in AGENT_STATES
        )
        checks.append(
            {
                "name": "active_sprite_frames",
                "ok": states_ok,
                "detail": f"{active['id']} ({len(active['frames'])} states)",
            }
        )

        # 3. Terminal rendering capability detection
        term_render = render_terminal_protocol(active["frames"]["idle"][0], protocol="auto", env=environ)
        checks.append(
            {
                "name": "terminal_renderer",
                "ok": bool(term_render["rendered"]),
                "detail": f"auto-detected protocol={term_render['protocol']}",
            }
        )

        # 4. Declared settings_db integration
        settings_ok = False
        try:
            from agents.core import settings_db

            cats = settings_db.get_category("pets")
            settings_ok = isinstance(cats, list) and any(
                isinstance(r, dict) and r.get("key") == "enabled" for r in cats
            )
        except Exception:
            settings_ok = False
        checks.append(
            {
                "name": "settings_schema",
                "ok": settings_ok,
                "detail": "pets.* declared in settings_db",
            }
        )

        return {
            "ok": all(c["ok"] for c in checks),
            "active_id": active["id"],
            "terminal_protocol": term_render["protocol"],
            "checks": checks,
        }
