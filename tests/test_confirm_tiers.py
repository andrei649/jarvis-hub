"""H168 — the HUD's confirmation tiers are the approval queue's RiskTier, name for name.

frontend/src/confirm.tsx grades every confirmation by `RISK_TIER` (one click, two steps,
a typed phrase). If RiskTier gains, loses or renumbers a tier and the HUD does not follow,
the UI and the queue stop describing risk the same way; this test is the tie.
"""
import re
from pathlib import Path

from agents.core.autonomy.policy import RiskTier

ROOT = Path(__file__).resolve().parents[1]


def _hud_tiers() -> dict[str, int]:
    source = (ROOT / "frontend" / "src" / "confirm.tsx").read_text(encoding="utf-8")
    block = re.search(r"export const RISK_TIER = \{([^}]*)\} as const;", source)
    assert block, "RISK_TIER is not declared as a literal object in confirm.tsx"
    return {name: int(value) for name, value in re.findall(r"(\w+):\s*(\d+)", block.group(1))}


def test_the_hud_tiers_are_risk_tier():
    assert _hud_tiers() == {tier.name: int(tier) for tier in RiskTier}


def test_every_destructive_confirmation_in_the_hud_goes_through_the_primitive():
    """The sites that used to hand-roll a confirmation import and use ConfirmAction."""
    src = ROOT / "frontend" / "src"
    sites = ("gap.tsx", "panels/marketplace-admin.tsx", "panels/webhooks.tsx",
             "panels/trust-ops.tsx", "modes3.tsx")
    for rel in sites:
        text = (src / rel).read_text(encoding="utf-8")
        assert re.search(r"import \{ ConfirmAction, RISK_TIER \} from '\.\.?/confirm';", text), \
            f"{rel} does not import ConfirmAction"
        assert "<ConfirmAction" in text, f"{rel} does not use ConfirmAction"
        assert "window.confirm(" not in text, f"{rel} still uses window.confirm"
