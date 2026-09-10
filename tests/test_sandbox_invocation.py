"""K0: who a sandboxed run is, and the four ways that authority can be refused.

The gap this closes is narrow and worth stating precisely. `ToolRPCSandboxRuntime`
called `ToolRPCServer.handle` with no actor, so the server fell back to its own
default agent: an inner call was attributed to `jarvis` whoever started the run, and
the sandbox's reach was the whole registered allowlist rather than the set the outer
turn was actually offered. That is a **missing contract, not a demonstrated bypass** —
the only way in is `POST /sandbox/execute`, behind `user_guard` and refused unless
`DEV_MODE` is on. But the contract has to exist before `execute_code` can be offered
to a model at all, which is why K0 comes before K1.

Four properties, and the tests are mostly about what each one refuses:

1. **Server-resolved** — `bind` has no parameter for an identity or a tool set. Both
   are computed from the principal the door already authenticated, so forging either
   is impossible rather than merely detected.
2. **Immutable** — frozen for the run's lifetime; no later call widens it.
3. **Bounded in time** — expiry is checked per call, not once at the start.
4. **Intersecting** — offered ∩ still-registered. The profile that narrows the outer
   turn narrows the inner one by construction.

The ordering test is the one that matters most: every refusal lands *before*
`handle`, so a gated call cannot enqueue an approval card on its way to being denied.
"""

from __future__ import annotations

import time
from dataclasses import FrozenInstanceError
from types import SimpleNamespace

import pytest

from agents.core import sandbox_invocation
from agents.core.sandbox_invocation import (
    MAX_LIFETIME_SECONDS,
    InvocationRefused,
    SandboxInvocation,
    bind,
)

OWNER = SimpleNamespace(admin=True, channel="web")
GUEST = SimpleNamespace(admin=False, channel="web")
STRANGER = SimpleNamespace(admin=False, channel="telegram")


def rows(*names, gated=()):
    return [{"name": name, "gated": name in set(gated), "description": "", "input_schema": {}}
            for name in names]


def bound(principal=OWNER, tools=None, **kwargs):
    kwargs.setdefault("origin", "operator")
    invocation, decision = bind(
        tools=tools if tools is not None else rows("echo", "time", "send_email", gated=("send_email",)),
        agent="jarvis", principal=principal, session_id="session_1", **kwargs,
    )
    return invocation, decision


# ── server-resolved, and not forgeable ───────────────────────────────────────

def test_the_offer_comes_from_the_posture_not_from_the_caller():
    """`bind` takes no offered-set argument. This is the test that says so."""
    import inspect

    parameters = set(inspect.signature(bind).parameters)
    assert "offered" not in parameters and "offered_tools" not in parameters
    assert "surface" not in parameters and "principal_kind" not in parameters


def test_the_owner_at_the_console_is_offered_every_registered_tool():
    invocation, decision = bound(OWNER)
    assert invocation.surface == "operator" and invocation.principal == "owner"
    assert invocation.offered == {"echo", "time", "send_email"}
    assert decision.withheld == ()


def test_a_guest_at_the_same_door_is_not_offered_a_gated_tool():
    invocation, _ = bound(GUEST)
    assert invocation.principal == "guest"
    assert "send_email" not in invocation.offered
    assert invocation.offered == {"echo", "time"}


def test_a_stranger_on_an_external_channel_is_narrower_still():
    invocation, _ = bound(STRANGER, origin="inbound")
    assert invocation.surface == "inbound" and invocation.principal == "guest"
    assert "send_email" not in invocation.offered


def test_an_agents_own_pattern_list_can_only_narrow():
    invocation, _ = bound(OWNER, agent_patterns=["echo"])
    assert invocation.offered == {"echo"}
    wider, _ = bound(GUEST, agent_patterns=["*"])
    assert "send_email" not in wider.offered, "a pattern cannot re-add what the posture withheld"


# ── immutable, and bounded in time ───────────────────────────────────────────

def test_an_invocation_cannot_be_widened_after_it_is_bound():
    """Frozen, and the error is named rather than "something raised": a dataclass
    that silently accepted the write would still pass a blind `Exception` check if
    any *other* line in the block happened to raise."""
    invocation, _ = bound(GUEST)
    with pytest.raises(FrozenInstanceError):
        invocation.offered = frozenset({"send_email"})
    with pytest.raises(FrozenInstanceError):
        invocation.agent = "someone_else"
    assert invocation.offered == {"echo", "time"}


def test_authority_expires_and_is_checked_on_every_call_not_just_the_first():
    invocation, _ = bound(OWNER, lifetime_seconds=10, now=lambda: 1000.0)
    invocation.authorize("echo", now=1005.0)
    with pytest.raises(InvocationRefused, match="authority_expired"):
        invocation.authorize("echo", now=1010.0)


def test_a_lifetime_is_clamped_rather_than_trusted():
    forever, _ = bound(OWNER, lifetime_seconds=10**9, now=lambda: 0.0)
    assert forever.expires_at == MAX_LIFETIME_SECONDS
    instant, _ = bound(OWNER, lifetime_seconds=-5, now=lambda: 0.0)
    assert instant.expires_at >= 1.0


def test_expiry_is_measured_against_the_wall_clock_by_default():
    invocation, _ = bound(OWNER, lifetime_seconds=1, now=lambda: time.time() - 10)
    assert invocation.expired()


# ── intersecting: offered ∩ still registered ─────────────────────────────────

def test_a_tool_outside_the_offer_is_refused():
    invocation, _ = bound(GUEST)
    with pytest.raises(InvocationRefused, match="tool_not_offered") as refusal:
        invocation.authorize("send_email")
    assert refusal.value.as_response() == {
        "ok": False, "reason": "tool_not_offered", "tool": "send_email"}


def test_a_tool_unregistered_after_binding_is_refused_too():
    """The offer is a ceiling, not a promise: a tool can go away mid-run."""
    invocation, _ = bound(OWNER)
    live = {"echo"}
    invocation.authorize("echo", registered=live.__contains__)
    with pytest.raises(InvocationRefused, match="tool_not_registered"):
        invocation.authorize("time", registered=live.__contains__)


def test_a_revoked_run_is_refused_before_anything_else_it_might_ask_for():
    invocation, _ = bound(OWNER)
    invocation.authorize("echo", revoked=lambda: False)
    with pytest.raises(InvocationRefused, match="authority_revoked"):
        invocation.authorize("echo", revoked=lambda: True)


@pytest.mark.parametrize("broken", [
    lambda: (_ for _ in ()).throw(RuntimeError("state unreadable")),
])
def test_an_unreadable_revocation_state_counts_as_revoked(broken):
    invocation, _ = bound(OWNER)
    with pytest.raises(InvocationRefused, match="authority_revoked"):
        invocation.authorize("echo", revoked=broken)


def test_an_unreadable_registry_offers_nothing():
    invocation, _ = bound(OWNER)

    def broken(_name):
        raise RuntimeError("registry unreadable")

    with pytest.raises(InvocationRefused, match="tool_not_registered"):
        invocation.authorize("echo", registered=broken)


def test_the_refusal_order_is_the_contract():
    """Expiry outranks revocation outranks the offer outranks the registry.

    An expired run must not be told which tools it would have been offered, and a
    revoked one must not learn whether a tool exists."""
    invocation, _ = bound(GUEST, lifetime_seconds=1, now=lambda: 0.0)
    with pytest.raises(InvocationRefused, match="authority_expired"):
        invocation.authorize("send_email", now=100.0, revoked=lambda: True,
                             registered=lambda _n: False)
    fresh, _ = bound(GUEST)
    with pytest.raises(InvocationRefused, match="authority_revoked"):
        fresh.authorize("send_email", revoked=lambda: True, registered=lambda _n: False)


# ── the projection carries no payload ────────────────────────────────────────

def test_the_owner_readable_projection_carries_names_and_ids_only():
    invocation, _ = bound(OWNER)
    value = invocation.as_dict()
    assert set(value) == {
        "agent", "surface", "principal", "session_id", "origin",
        "offered_tools", "withheld_tools", "data_scope", "issued_at", "expires_at"}
    assert value["offered_tools"] == ["echo", "send_email", "time"]
    assert value["data_scope"] is None


def test_a_data_scope_is_carried_when_one_exists():
    invocation, _ = bound(OWNER, data_scope=["notes", "calendar"])
    assert invocation.as_dict()["data_scope"] == ["calendar", "notes"]


# ── the ordering that matters: refusal precedes the server ───────────────────

class _Server:
    """Records whether the governed server was reached at all."""

    def __init__(self, *, allow=("echo",)):
        self.calls: list[str] = []
        self.enqueued: list[str] = []
        self._allow = set(allow)
        self.agent = "default_agent"

    def allows(self, name):
        return name in self._allow

    def tools(self):
        return rows(*sorted(self._allow))

    async def handle(self, request, *, actor=None):
        tool = request["tool"]
        self.calls.append(f"{actor}:{tool}")
        self.enqueued.append(tool)  # stands in for the ask-tier task a gated tool queues
        return {"ok": True, "tool": tool, "actor": actor}


@pytest.mark.asyncio
async def test_a_refused_call_never_reaches_the_server_and_queues_nothing():
    """The acceptance clause: reject before reads and before queue writes.

    A refusal after `handle` would still have run the read, or left an approval card
    in the owner's inbox for something that was never going to be allowed."""
    from agents.core.tool_rpc_runtime import ToolRPCSandboxRuntime

    server = _Server()
    invocation, _ = bound(GUEST, tools=rows("echo", "send_email", gated=("send_email",)))
    runtime = ToolRPCSandboxRuntime(server, SimpleNamespace(), invocation=invocation)

    assert await runtime._handle_request("send_email", {}) == {
        "ok": False, "reason": "tool_not_offered", "tool": "send_email"}
    assert server.calls == [] and server.enqueued == []


@pytest.mark.asyncio
async def test_an_allowed_call_reaches_the_server_as_the_invoking_agent():
    """The other half: the actor is no longer the server's own default."""
    from agents.core.tool_rpc_runtime import ToolRPCSandboxRuntime

    server = _Server()
    invocation, _ = bound(OWNER, tools=rows("echo"))
    runtime = ToolRPCSandboxRuntime(server, SimpleNamespace(), invocation=invocation)

    result = await runtime._handle_request("echo", {"x": 1})
    assert result["actor"] == "jarvis" != server.agent
    assert server.calls == ["jarvis:echo"]


@pytest.mark.asyncio
async def test_a_runtime_with_no_invocation_refuses_everything():
    """There is no default identity left to fall back on. That is the point."""
    from agents.core.tool_rpc_runtime import ToolRPCSandboxRuntime

    server = _Server()
    runtime = ToolRPCSandboxRuntime(server, SimpleNamespace())
    assert await runtime._handle_request("echo", {}) == {
        "ok": False, "reason": "authority_missing", "tool": "echo"}
    assert server.calls == []


@pytest.mark.asyncio
async def test_a_revoked_run_stops_calling_mid_script():
    from agents.core.tool_rpc_runtime import ToolRPCSandboxRuntime

    server = _Server()
    invocation, _ = bound(OWNER, tools=rows("echo"))
    live = {"value": False}
    runtime = ToolRPCSandboxRuntime(
        server, SimpleNamespace(), invocation=invocation, revoked=lambda: live["value"])

    assert (await runtime._handle_request("echo", {}))["ok"] is True
    live["value"] = True
    assert await runtime._handle_request("echo", {}) == {
        "ok": False, "reason": "authority_revoked", "tool": "echo"}
    assert server.calls == ["jarvis:echo"], "only the first call reached the server"


def test_the_module_is_importable_without_a_hub():
    """K0 is a contract, not a service: it must not need an orchestrator to exist."""
    assert isinstance(sandbox_invocation.DEFAULT_LIFETIME_SECONDS, float)
    assert SandboxInvocation.__dataclass_params__.frozen is True
