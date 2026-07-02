"""K2 — least-privilege capability set per agent (derive + issue).

An agent's capabilities are derived from what it declares (plugins/channel/policy), so it
can only be granted what it asked for. Strict-local agents never get a cloud capability.
"""

from agents.core.kernel import capabilities as caps
from agents.core.security.capability import CapabilityBroker


# ── derivation (least-privilege) ───────────────────────────────────────────────
def test_derive_only_grants_declared_plugins():
    c = caps.derive_agent_capabilities("stark", {"plugins": ["gmail"], "llm_policy": "auto", "channel": "telegram"})
    assert "plugin:gmail" in c
    assert "plugin:telegram" not in c          # not declared
    assert "agent:stark" in c and "channel:telegram" in c
    assert "model:local" in c and "model:cloud" in c   # auto policy → cloud allowed


def test_strict_local_agent_never_gets_cloud():
    c = caps.derive_agent_capabilities("frigga", {"plugins": [], "llm_policy": "auto"})
    assert "model:local" in c
    assert "model:cloud" not in c              # frigga is LOCAL_ONLY


def test_local_policy_agent_has_no_cloud():
    c = caps.derive_agent_capabilities("x", {"llm_policy": "local"})
    assert "model:cloud" not in c


def test_derive_accepts_attr_objects():
    class _Cfg:
        plugins = ["news"]
        channel = "web"
        llm_policy = "claude"
    c = caps.derive_agent_capabilities("vision", _Cfg())
    assert "plugin:news" in c and "channel:web" in c and "model:cloud" in c


# ── issuance against the real broker ─────────────────────────────────────────────
def test_issue_for_agent_token_grants_only_its_caps():
    broker = CapabilityBroker()
    tok = caps.issue_for_agent(broker, "stark", {"plugins": ["gmail"], "llm_policy": "auto"})
    assert broker.check(tok["id"], "plugin:gmail") is True
    assert broker.check(tok["id"], "plugin:telegram") is False    # never granted
    assert broker.check(tok["id"], "model:cloud") is True


def test_issue_all_is_per_agent_and_least_privilege():
    broker = CapabilityBroker()
    agents = {
        "frigga": {"plugins": ["whatsapp-bridge"], "llm_policy": "local"},
        "stark": {"plugins": ["gmail"], "llm_policy": "auto"},
    }
    tokens = caps.issue_all(broker, agents)
    assert set(tokens) == {"frigga", "stark"}
    # frigga's token can't reach the cloud or stark's gmail
    assert broker.check(tokens["frigga"], "model:cloud") is False
    assert broker.check(tokens["frigga"], "plugin:gmail") is False
    assert broker.check(tokens["stark"], "plugin:gmail") is True


# ── K2 wave-4b: issue_operator_capability (mint-on-demand for HTTP operators) ────

def test_issue_operator_capability_grants_only_the_named_capability():
    broker = CapabilityBroker()
    token_id = caps.issue_operator_capability(broker, "kg:write")
    assert token_id
    assert broker.check(token_id, "kg:write") is True
    assert broker.check(token_id, "admin:kill_switch") is False   # least-privilege


def test_issue_operator_capability_no_broker_returns_empty():
    assert caps.issue_operator_capability(None, "kg:write") == ""


def test_issue_operator_capability_broker_hiccup_fails_closed_to_empty():
    class _BoomBroker:
        def issue(self, *a, **kw):
            raise RuntimeError("boom")
    # never raises — a broker error must degrade to an empty (fail-closed) token,
    # not propagate and break the request the guard already authorized.
    assert caps.issue_operator_capability(_BoomBroker(), "kg:write") == ""
