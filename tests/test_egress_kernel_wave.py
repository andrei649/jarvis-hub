"""ORIZONT-24 K1 wave-2 — plugin egress routes through the Action Kernel.

The manifest policy (``_enforce_egress``) decides *where* a plugin may reach; the kernel
adds an orthogonal gate that can DENY otherwise-allowed egress (kill-switch engaged →
no outbound calls, over-budget, runaway loop). Decoupled: ``http_client`` never imports
the kernel — the orchestrator injects a plain ``(plugin, method, url, host) -> reason|None``
hook. Default-off behind ``JARVIS_ACTION_KERNEL``.
"""
import pytest

from agents.core import http_client as hc
from agents.core.kernel import Action, Decision, Verdict
from agents.core.kernel.binding import make_egress_kernel_hook


@pytest.fixture(autouse=True)
def _clear_hook():
    """Every test starts and ends with no egress kernel hook installed (global state)."""
    hc.set_egress_kernel_hook(None)
    yield
    hc.set_egress_kernel_hook(None)


def _client():
    # Construct directly (not via for_plugin) so we don't pollute the module client cache;
    # no manifest for this name → _enforce_egress is a no-op and egress reaches the kernel.
    return hc.PluginHTTPClient(plugin_name="egress_kernel_probe")


# ── the hook contract (independent of the kernel) ─────────────────────────────────
def test_no_hook_allows_egress():
    _client()._guard("GET", "https://example.com/x")     # no hook installed → no-op


def test_hook_deny_blocks_egress():
    hc.set_egress_kernel_hook(lambda plugin, method, url, host: "kill-switch engaged")
    with pytest.raises(hc.PluginEgressError, match="blocked by kernel: kill-switch engaged"):
        _client()._guard("GET", "https://example.com/x")


def test_hook_allow_passes_egress():
    seen = []
    hc.set_egress_kernel_hook(lambda *a: seen.append(a) or None)
    _client()._guard("POST", "https://example.com/y")
    assert seen and seen[0][0] == "egress_kernel_probe" and seen[0][1] == "POST"


def test_hook_exception_fails_open_not_closed():
    """A buggy kernel hook must never brick egress — the manifest policy already ran."""
    def _boom(*a):
        raise RuntimeError("kernel exploded")
    hc.set_egress_kernel_hook(_boom)
    _client()._guard("GET", "https://example.com/z")      # must NOT raise


def test_manifest_block_precedes_kernel(monkeypatch):
    """If the manifest policy blocks, the kernel hook is never consulted (ordering)."""
    called = []
    hc.set_egress_kernel_hook(lambda *a: called.append(a) or "deny")
    client = _client()
    monkeypatch.setattr(client, "_enforce_egress",
                        lambda url: (_ for _ in ()).throw(hc.PluginEgressError("no network")))
    with pytest.raises(hc.PluginEgressError, match="no network"):
        client._guard("GET", "https://example.com/x")
    assert called == []


# ── the production hook (make_egress_kernel_hook) ─────────────────────────────────
class _SpyKernel:
    def __init__(self, verdict=Verdict.GRANT, reason="spy"):
        self.calls, self._v, self._r = [], verdict, reason

    def __call__(self, action, capability=None, budget=None):
        self.calls.append(action)
        return Decision(self._v, reason=self._r)


def test_production_hook_default_off(monkeypatch):
    monkeypatch.delenv("JARVIS_ACTION_KERNEL", raising=False)
    spy = _SpyKernel(verdict=Verdict.DENY)               # would block — but flag is off
    hc.set_egress_kernel_hook(make_egress_kernel_hook(lambda: spy))
    _client()._guard("GET", "https://example.com/x")     # no raise
    assert spy.calls == []                                # kernel never consulted while off


def test_production_hook_denies_when_on(monkeypatch):
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    spy = _SpyKernel(verdict=Verdict.DENY, reason="kill-switch engaged for scope 'global'")
    hc.set_egress_kernel_hook(make_egress_kernel_hook(lambda: spy))
    with pytest.raises(hc.PluginEgressError, match="kill-switch engaged"):
        _client()._guard("GET", "https://example.com/x")
    assert spy.calls and spy.calls[-1].kind == "plugin.egress"
    assert spy.calls[-1].payload["host"] == "example.com"


def test_production_hook_none_kernel_allows(monkeypatch):
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    hc.set_egress_kernel_hook(make_egress_kernel_hook(lambda: None))   # no bound kernel
    _client()._guard("GET", "https://example.com/x")     # no raise


# ── integration: the *real* bound kernel + real KillSwitch ─────────────────────────
def test_real_bound_kernel_halt_blocks_egress(tmp_path, monkeypatch):
    """Bind the production kernel.authorize over a real AutonomyPolicy + KillSwitch and
    prove a halted switch denies egress while a released one allows it."""
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    from agents.core.autonomy.policy import AutonomyPolicy
    from agents.core.kernel.binding import make_action_kernel
    from agents.core.security.capability import CapabilityBroker, KillSwitch

    kill = KillSwitch(tmp_path / "kill.json")

    class _Orch:
        autonomy_policy = AutonomyPolicy()
        kill_switch = kill
        capabilities = CapabilityBroker()
        intent_log = None

    hc.set_egress_kernel_hook(make_egress_kernel_hook(lambda: make_action_kernel(_Orch())))
    client = _client()

    kill.engage("global", reason="test")
    with pytest.raises(hc.PluginEgressError, match="blocked by kernel"):
        client._guard("GET", "https://example.com/x")

    kill.disengage("global")
    client._guard("GET", "https://example.com/x")        # released → allowed
