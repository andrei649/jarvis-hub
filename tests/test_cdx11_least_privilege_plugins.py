"""CDX-11 — least-privilege plugins under the hardened profile.

11 external-write (TRANSMITTED) plugins ship `agents_served=["all"]`, so by
default any agent persona — including one steered by an injected prompt — can
reach a third-party write. Under least-privilege hardening the `"all"` wildcard
is NOT honored for TRANSMITTED plugins: such a plugin admits only an
explicitly-served agent or an owner-declared grant. Read/LAN/local plugins keep
their wildcard, and the default (hardening off) is byte-for-byte the old behavior.
"""

from agents.core.plugin_gate import (
    DataScope,
    PermissionGate,
    grants_from_env,
    least_privilege_from_env,
)


def _transmitted_wildcard_ids(gate: PermissionGate) -> set[str]:
    return {
        pid for pid, m in gate.plugins.items()
        if m.data_scope == DataScope.TRANSMITTED and "all" in m.agents_served
    }


# ── default posture is unchanged (off) ────────────────────────────────────────
def test_default_off_wildcard_still_serves_everyone():
    gate = PermissionGate(least_privilege=False)
    # social_x is an external-write plugin serving "all" — any agent passes.
    assert gate.check_call("social_x", "frigga") is True
    assert gate.check_call("writeback_github", "some-random-agent") is True
    # and a read plugin too
    assert gate.check_call("weather", "frigga") is True


def test_explicit_and_nonserved_unchanged_by_default():
    gate = PermissionGate(least_privilege=False)
    # gmail serves only stark/pepper/veronica
    assert gate.check_call("gmail", "stark") is True
    assert gate.check_call("gmail", "frigga") is False


# ── hardened: wildcard withheld for external-write surfaces ────────────────────
def test_hardened_blocks_wildcard_external_write():
    gate = PermissionGate(least_privilege=True)
    # No agent is explicitly served by social_x (it was "all"), so under hardening
    # an arbitrary agent is now blocked.
    assert gate.check_call("social_x", "frigga") is False
    assert gate.check_call("writeback_github", "stark") is False
    assert gate.check_call("channel_whatsapp", "jarvis") is False


def test_hardened_grant_readmits_a_specific_agent():
    gate = PermissionGate(least_privilege=True)
    assert gate.check_call("social_x", "veronica") is False
    gate.add_grant("social_x", "veronica")
    assert gate.check_call("social_x", "veronica") is True
    # the grant is scoped to that one plugin + agent
    assert gate.check_call("social_x", "stark") is False
    assert gate.check_call("writeback_github", "veronica") is False


def test_hardened_does_not_touch_read_or_local_plugins():
    gate = PermissionGate(least_privilege=True)
    # weather/news/websearch are PROCESSED reads serving "all" — wildcard kept.
    assert gate.check_call("weather", "frigga") is True
    assert gate.check_call("news", "frigga") is True
    assert gate.check_call("websearch", "frigga") is True
    # homebridge is LAN/local serving jarvis/ultron — unchanged either way.
    assert gate.check_call("homebridge", "jarvis") is True
    assert gate.check_call("homebridge", "frigga") is False


def test_hardened_keeps_explicitly_served_agents():
    gate = PermissionGate(least_privilege=True)
    # cloud-llm is TRANSMITTED but NOT "all" — it names its agents, so hardening
    # leaves it exactly as-is (explicit identities are the whole point).
    assert gate.check_call("cloud-llm", "athena") is True
    assert gate.check_call("cloud-llm", "frigga") is False


# ── the CDX-11 target set: every TRANSMITTED "all" plugin is restricted ────────
def test_all_external_write_wildcards_are_restricted_under_hardening():
    gate = PermissionGate(least_privilege=True)
    targets = _transmitted_wildcard_ids(gate)
    # the 11 external-write surfaces + the telegram comms bus all transmit "all".
    expected = {
        "telegram", "social_x", "writeback_notion", "writeback_github",
        "writeback_google_calendar", "call_twilio", "call_telnyx",
        "channel_whatsapp", "channel_google_chat", "channel_teams",
        "channel_signal", "channel_matrix",
    }
    assert targets == expected
    for pid in targets:
        assert gate.wildcard_restricted(pid) is True
        # blocked for an arbitrary, non-granted agent
        assert gate.check_call(pid, "nobody-special") is False


def test_wildcard_restricted_false_when_off_or_for_reads():
    off = PermissionGate(least_privilege=False)
    assert off.wildcard_restricted("social_x") is False     # hardening off
    on = PermissionGate(least_privilege=True)
    assert on.wildcard_restricted("weather") is False        # read plugin, not TRANSMITTED
    assert on.wildcard_restricted("cloud-llm") is False      # TRANSMITTED but not "all"
    assert on.wildcard_restricted("does-not-exist") is False


# ── env wiring ────────────────────────────────────────────────────────────────
def test_env_toggle_enables_least_privilege(monkeypatch):
    monkeypatch.delenv("JARVIS_HARDENED", raising=False)
    monkeypatch.setenv("JARVIS_PLUGIN_LEAST_PRIVILEGE", "1")
    assert least_privilege_from_env() is True
    assert PermissionGate().least_privilege is True
    monkeypatch.setenv("JARVIS_PLUGIN_LEAST_PRIVILEGE", "0")
    assert least_privilege_from_env() is False


def test_hardened_preset_env_also_enables(monkeypatch):
    monkeypatch.delenv("JARVIS_PLUGIN_LEAST_PRIVILEGE", raising=False)
    monkeypatch.setenv("JARVIS_HARDENED", "true")
    assert least_privilege_from_env() is True
    assert PermissionGate().least_privilege is True


def test_grants_env_is_parsed(monkeypatch):
    monkeypatch.setenv("JARVIS_PLUGIN_LEAST_PRIVILEGE", "1")
    monkeypatch.setenv("JARVIS_PLUGIN_GRANTS", "social_x:veronica, writeback_github:stark ,bad,:,x:")
    parsed = grants_from_env()
    assert parsed == {"social_x": {"veronica"}, "writeback_github": {"stark"}}
    gate = PermissionGate()
    assert gate.check_call("social_x", "veronica") is True
    assert gate.check_call("writeback_github", "stark") is True
    assert gate.check_call("social_x", "stark") is False
