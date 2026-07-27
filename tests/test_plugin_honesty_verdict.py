"""The honesty badge, wrong in both directions (adversarial audit 2026-07-25, ADV-069).

`honesty_for` turns the /plugins `configured` signal into the verdict the HUD renders. It
was written specifically to stop mock reading as real, and it was wrong on exactly the
plugins it was written for — because `plugin_configured` returns `(True, "loaded")` when a
class exposes none of configured/available/_configured, and "loaded" was then read as
"live, no setup required". A plugin that has told us *nothing* was reported as working.
"""

import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

import pytest

from agents.core.plugins.honesty import _NEEDS, honesty_for


def test_no_contract_plus_declared_needs_is_not_live():
    """The core error: the module names the key AND badges the plugin green."""
    verdict = honesty_for("telegram", configured=True, configuration_source="loaded")
    assert verdict["status"] == "needs_config", (
        "a plugin whose id is in honesty._NEEDS — the table in this very module naming "
        "the key it requires — was reported live on a keyless boot"
    )
    assert verdict["needs"] == _NEEDS["telegram"]


def test_no_contract_and_no_declared_needs_is_unknown_not_live():
    """'I don't know' and 'this returns real data' are different claims."""
    verdict = honesty_for("a-plugin-with-no-contract", configured=True,
                          configuration_source="loaded")
    assert verdict["status"] == "unknown"
    assert verdict["status"] != "live"


def test_degradation_info_overrides_a_configured_signal():
    """The plugin's own contract beats an inferred `configured`.

    sms-alerts and crm-sync expose no configured attribute but DO report degradation, so
    they used to render a green LIVE chip next to their own [MOCK] chip — a visible
    contradiction rather than a clean lie, but still wrong.
    """
    verdict = honesty_for("sms-alerts", configured=True, configuration_source="loaded",
                          degraded=True)
    assert verdict["status"] == "needs_config"
    assert verdict["needs"] == _NEEDS["sms-alerts"]


def test_a_genuinely_configured_plugin_is_still_live():
    """The fix must not make everything amber."""
    verdict = honesty_for("gmail", configured=True, configuration_source="configured()")
    assert verdict["status"] == "live"
    assert verdict["needs"] == []


def test_needs_config_always_says_what_to_configure():
    """An amber chip with an empty needs list tells the owner nothing actionable."""
    for pid in ("telegram", "an-unlisted-plugin"):
        verdict = honesty_for(pid, configured=False, configuration_source="configured()")
        assert verdict["status"] == "needs_config"
        assert verdict["needs"], f"{pid}: needs_config with nothing to configure"


@pytest.mark.parametrize("pid", sorted(_NEEDS))
def test_no_plugin_that_declares_needs_can_badge_live_without_a_contract(pid):
    """Swept across the whole table, so a plugin added later cannot reintroduce this."""
    verdict = honesty_for(pid, configured=True, configuration_source="loaded")
    assert verdict["status"] != "live", (
        f"{pid} declares required config in honesty._NEEDS yet badges live when it "
        "exposes no configuration contract"
    )


def test_telegram_and_analytics_now_carry_real_contracts():
    """The two the audit named, fixed at the plugin rather than only at the verdict.

    telegram had no contract AND no degradation_info, so its row was cleanly, silently
    green. analytics is the inverse case: its `available()` reports only the optional GA4
    mirror, so the one keyless capability that reads real SQLite badged amber with an
    EMPTY needs list — telling the owner to configure something it could not name.
    """
    from agents.core.plugins.analytics import AnalyticsPlugin
    from agents.core.plugins.telegram_bot import TelegramBotPlugin

    assert TelegramBotPlugin(token="").configured is False
    assert TelegramBotPlugin(token="x").configured is True

    analytics = AnalyticsPlugin.__new__(AnalyticsPlugin)
    assert analytics.configured is True, (
        "local analytics needs no key and returns real data — it must not badge amber"
    )
