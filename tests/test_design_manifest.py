"""0.53 Design System Manifest — token/component extraction + drift guard.

Parses the REAL frontend/src/styles.css: the guard pins that the core tokens and the
known component classes stay extractable, so design-system drift breaks a test instead
of silently un-syncing tools that read the manifest.
"""
import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from core import design_manifest as dm  # noqa: E402


def test_extracts_tokens_and_variants_from_synthetic_css():
    css = """
    :root, .hud-root { --accent:#2bb8f0; --font-ui:'X', sans-serif; }
    .hud-root[data-accent="amber"] { --accent:#ffb23f; }
    .panel { color: var(--accent); }
    """
    t = dm.extract_tokens(css)
    assert t["base"]["--accent"] == "#2bb8f0"
    assert t["variants"]["data-accent=amber"]["--accent"] == "#ffb23f"
    assert "panel" in dm.extract_components(css)


def test_real_stylesheet_manifest_core_tokens_present():
    m = dm.build_manifest()
    assert "error" not in m
    base = m["tokens"]["base"]
    # the load-bearing HUD tokens — renaming one breaks tools reading the manifest
    for token in ("--accent", "--accent-light", "--font-ui", "--font-mono",
                  "--ink", "--surface", "--panel-line", "--radius"):
        assert token in base, f"core token {token} missing from styles.css"
    # the four accent variants + graphite look ship as data-* overrides
    assert "data-accent=amber" in m["tokens"]["variants"]
    assert "data-look=graphite" in m["tokens"]["variants"]


def test_real_stylesheet_component_inventory_is_substantial():
    m = dm.build_manifest()
    comps = set(m["components"])
    # a sample of load-bearing component classes across the HUD's surfaces
    for cls in ("panel", "topbar", "convo", "bubble", "inputbar", "rail-btn",
                "art-card", "dcard", "badge"):
        assert cls in comps, f"component .{cls} missing"
    assert m["counts"]["components"] > 100          # the HUD is a real library


def test_missing_stylesheet_is_honest():
    assert "error" in dm.build_manifest("/nope/styles.css")
