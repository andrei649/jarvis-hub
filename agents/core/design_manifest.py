"""design_manifest.py — 0.53 Design System Manifest (inspectable token/component inventory).

The HUD's design system lives as CSS custom properties + component classes in
``frontend/src/styles.css`` and prose in ``docs/BRAND_BOOK.md`` — real, but not *inspectable*
by tools. This extracts a **manifest**: design tokens (per look/accent variant) and the
component-class inventory, so drift is testable and external tools (Figma sync, docs, the
HUD's own tweaks panel) can read one structured source.

Honest by construction: it parses what the stylesheet actually says (no hardcoded token list
to rot); unknown/unparseable declarations are skipped, never invented. Pure stdlib regex —
not a full CSS parser, deliberately bounded to the two shapes the HUD uses (``:root``/
``.hud-root`` token blocks and ``.class`` component selectors).
"""

from __future__ import annotations

import re
from pathlib import Path

# repo_root/agents/core/design_manifest.py → parents[2] = repo root
_REPO = Path(__file__).resolve().parents[2]
DEFAULT_CSS = _REPO / "frontend" / "src" / "styles.css"

_TOKEN_RE = re.compile(r"(--[a-z0-9-]+)\s*:\s*([^;]+);")
_VARIANT_RE = re.compile(r'\.hud-root\[(data-[a-z-]+)="([a-z-]+)"\]')
_CLASS_RE = re.compile(r"(?:^|[\s,}])\.([a-z][a-z0-9-]{1,40})[\s.,:{\[]", re.M)


def extract_tokens(css: str) -> dict:
    """All custom properties: ``{base: {token: value}, variants: {axis=value: {token: value}}}``.

    ``base`` comes from the first ``:root``/``.hud-root`` block; each ``.hud-root[data-*=…]``
    override block becomes a variant keyed ``data-axis=value`` (e.g. ``data-accent=amber``).
    """
    base: dict[str, str] = {}
    variants: dict[str, dict[str, str]] = {}
    for block in re.finditer(r"([^{}]+)\{([^{}]*)\}", css or ""):
        selector, body = block.group(1).strip(), block.group(2)
        tokens = {m.group(1): m.group(2).strip() for m in _TOKEN_RE.finditer(body)}
        if not tokens:
            continue
        var = _VARIANT_RE.search(selector)
        if var:
            variants.setdefault(f"{var.group(1)}={var.group(2)}", {}).update(tokens)
        elif ":root" in selector or ".hud-root" in selector:
            # first/base token block wins for duplicates — later blocks are overrides
            for k, v in tokens.items():
                base.setdefault(k, v)
    return {"base": base, "variants": variants}


def extract_components(css: str) -> list[str]:
    """The sorted component-class inventory (deduped, excluding state-ish suffixes)."""
    names = {m.group(1) for m in _CLASS_RE.finditer(css or "")}
    return sorted(names)


def build_manifest(css_path: str | Path = DEFAULT_CSS) -> dict:
    """The full design-system manifest from a stylesheet on disk.

    ``{source, tokens: {base, variants}, components, counts}`` — or ``{error}`` when the
    stylesheet is missing (honest, not an empty manifest that looks parsed).
    """
    p = Path(css_path)
    if not p.is_file():
        return {"error": f"stylesheet not found: {p}"}
    css = p.read_text(encoding="utf-8", errors="replace")
    tokens = extract_tokens(css)
    components = extract_components(css)
    return {
        "source": p.name,
        "tokens": tokens,
        "components": components,
        "counts": {"base_tokens": len(tokens["base"]),
                   "variants": len(tokens["variants"]),
                   "components": len(components)},
    }
