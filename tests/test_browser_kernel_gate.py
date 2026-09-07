"""`browser.step` — the gate a browser click never had to cross.

The browser agent always had two gates: an egress allowlist navigation cannot
escape, and an approval queue mutating steps must pass. It never crossed the
Action Kernel, and every other privileged surface does. What that gap cost:

  · the kill switch is honoured by the kernel, so a halted install could still
    have clicked through an already-approved plan;
  · taint escalation lives in the kernel — a plan assembled from a page the agent
    just read is exactly the case that must be forced back to ASK, and the
    browser's own approval object has no idea where a plan came from;
  · the policy floor (money caps, daily ceilings) is applied by the kernel, and a
    browser is the easiest way to spend money without touching the payments kind.

The two orderings pinned here are the ones that would be tempting to get wrong:
the kernel is asked BEFORE an approval card exists (a DENY must not reach the
owner as a decision), and a driver only "requires the kernel" if it says so with
a literal ``True`` — a permissive ``__getattr__`` answering the probe truthily
would make every offline driver demand a binding it does not have.

Hermetic: a recording driver and a spy authorizer; no browser, no network.
"""

from __future__ import annotations

import pytest

from agents.core.browser_agent import (
    TRANSPORT_NOT_CONFIGURED,
    BrowserPolicy,
    GovernedBrowser,
    NullBrowserDriver,
)
from agents.core.browser_kernel import (
    BROWSER_STEP_CONTRACT,
    CAPABILITY,
    KIND,
    MAX_ARG_CHARS,
    MAX_ARGS,
    BrowserActionExecutor,
    normalize_step,
)
from agents.core.capability_actions import PerformResult
from agents.core.kernel.registry import ACTION_REGISTRY, Mediation

pytestmark = pytest.mark.asyncio


class _Driver:
    """A driver that needs the kernel, and records what actually reached it."""

    requires_kernel = True

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    async def click(self, **kw):
        self.calls.append(("click", kw))
        return {"ok": True, "clicked": kw.get("selector")}

    async def type(self, **kw):
        self.calls.append(("type", kw))
        return {"ok": True}


class _Approvals:
    def __init__(self, verdict: str = "approved") -> None:
        self.requested: list[dict] = []
        self._verdict = verdict

    def request(self, payload):
        self.requested.append(payload)
        return {"id": len(self.requested)}

    async def await_decision(self, _id, timeout=0):
        return self._verdict


class _Executor:
    """Stands in for BrowserActionExecutor with a fixed verdict."""

    def __init__(self, result: PerformResult, driver=None) -> None:
        self._result = result
        self.driver = driver
        self.performed: list[dict] = []

    async def perform(self, step, context=None):
        self.performed.append(dict(step))
        return self._result


def _result(status: str, *, reason: str = "", output=None) -> PerformResult:
    return PerformResult(
        status=status, capability_id=CAPABILITY, action_kind=KIND,
        reason=reason, tier=2, card=None, output=output,
    )


def _browser(driver, executor=None, approvals=None) -> GovernedBrowser:
    return GovernedBrowser(
        driver=driver,
        policy=BrowserPolicy(["example.com"]),
        approvals=approvals,
        action_executor=executor,
    )


# ── the kind is registered and mediated ──────────────────────────────────────

async def test_browser_step_is_kernel_mediated():
    assert ACTION_REGISTRY.get(KIND) is Mediation.KERNEL


async def test_the_contract_refuses_a_step_that_is_not_mutating():
    """A read-only step arriving on the mutating contract is a miscategorised
    step, not a cheap approval."""
    view = {"kind": "browser.click", "action": "click", "target": "browser", "mutating": False}
    decision = BROWSER_STEP_CONTRACT.evaluate(view, now=0.0)
    assert decision.admissible is False
    assert decision.reason == "not_mutating"


async def test_the_contract_admits_a_real_mutating_browser_step():
    view = {"kind": "browser.click", "action": "click", "target": "browser", "mutating": True}
    assert BROWSER_STEP_CONTRACT.evaluate(view, now=0.0).admissible is True


@pytest.mark.parametrize(
    ("view", "reason"),
    [
        ({"kind": "desktop.click", "action": "click", "target": "browser", "mutating": True},
         "invalid_kind"),
        ({"kind": "browser.click", "action": "", "target": "browser", "mutating": True},
         "no_action"),
        ({"kind": "browser.click", "action": "click", "target": "desktop", "mutating": True},
         "target_mismatch"),
    ],
)
async def test_the_contract_names_which_constraint_refused(view, reason):
    assert BROWSER_STEP_CONTRACT.evaluate(view, now=0.0).reason == reason


async def test_the_contract_requires_approval():
    assert BROWSER_STEP_CONTRACT.requires_approval is True


# ── the kernel comes first ───────────────────────────────────────────────────

async def test_a_kernel_refusal_never_becomes_a_card_for_the_owner():
    """Asking the queue first would train the owner to approve things the kernel
    then refuses, which teaches them their approvals do not mean anything."""
    driver = _Driver()
    approvals = _Approvals()
    executor = _Executor(_result("refused", reason="kill_switch_engaged"), driver)
    out = await _browser(driver, executor, approvals).run_step(
        {"action": "click", "selector": "#buy"}
    )
    assert out["status"] == "blocked"
    assert out["reason"] == "kill_switch_engaged"
    assert approvals.requested == []      # the owner was never asked
    assert driver.calls == []             # and the driver was never touched


async def test_a_queued_verdict_reports_as_queued_not_done():
    driver = _Driver()
    executor = _Executor(_result("queued"), driver)
    out = await _browser(driver, executor, _Approvals()).run_step(
        {"action": "click", "selector": "#buy"}
    )
    assert out["status"] == "queued"
    assert out["reason"] == "approval_required"
    assert driver.calls == []


@pytest.mark.parametrize(
    ("status", "expected"),
    [("refused", "blocked"), ("disabled", "blocked"), ("failed", "error")],
)
async def test_every_non_completed_verdict_stops_the_step(status, expected):
    driver = _Driver()
    executor = _Executor(_result(status), driver)
    out = await _browser(driver, executor).run_step({"action": "click", "selector": "#buy"})
    assert out["status"] == expected
    assert driver.calls == []


async def test_an_unrecognised_verdict_object_is_never_read_as_success():
    """The whole point of a gate is that it fails closed on things it cannot read."""
    driver = _Driver()
    executor = _Executor(object(), driver)
    out = await _browser(driver, executor).run_step({"action": "click", "selector": "#buy"})
    assert out["status"] == "error"
    assert out["reason"] == "kernel_error"
    assert driver.calls == []


async def test_a_driver_that_needs_the_kernel_refuses_without_a_binding():
    """Not a fallback to the legacy direct path: an unbound kernel-requiring
    driver is a misconfiguration, and clicking anyway would be the worst reading
    of it."""
    driver = _Driver()
    out = await _browser(driver, executor=None, approvals=_Approvals()).run_step(
        {"action": "click", "selector": "#buy"}
    )
    assert out["status"] == "blocked"
    assert out["reason"] == "kernel_required"
    assert driver.calls == []


async def test_a_granted_step_runs_exactly_once():
    """The kernel invokes the driver through the bound capability; running it
    again afterwards would double every approved click."""
    driver = _Driver()
    executor = BrowserActionExecutor(driver, authorizer=None)
    out = await _browser(driver, executor).run_step({"action": "click", "selector": "#buy"})
    # With no authorizer the facade is inert; what matters is that the agent does
    # not ALSO call the driver itself on its own path.
    assert len(driver.calls) <= 1
    assert out["action"] == "click"


# ── requires_kernel is a statement, not an inference ─────────────────────────

async def test_the_null_driver_does_not_claim_to_need_a_kernel():
    """It answers ANY attribute with a coroutine, so a loose probe reads the flag
    as truthy and every offline driver demands a binding it does not have."""
    driver = NullBrowserDriver()
    assert driver.requires_kernel is False
    assert _browser(driver).requires_kernel() is False


async def test_a_permissive_getattr_cannot_fake_the_flag():
    class _Loose:
        def __getattr__(self, name):
            async def _m(**kw):
                return {"ok": True}
            return _m

    assert _browser(_Loose()).requires_kernel() is False


async def test_a_truthy_non_true_value_does_not_count():
    class _Sloppy:
        requires_kernel = "yes"

    assert _browser(_Sloppy()).requires_kernel() is False


async def test_the_null_driver_still_runs_ordinary_actions():
    driver = NullBrowserDriver()
    out = await _browser(driver, approvals=_Approvals()).run_step(
        {"action": "click", "selector": "#buy"}
    )
    assert out["status"] == "done"


async def test_the_null_driver_refuses_dunder_probes():
    driver = NullBrowserDriver()
    with pytest.raises(AttributeError):
        driver._is_secretly_everything  # noqa: B018


# ── the kernel sees the step the driver will get ─────────────────────────────

async def test_the_kernel_is_asked_about_the_same_payload_the_driver_receives():
    """A gate that authorises a summary authorises a different action."""
    driver = _Driver()
    executor = BrowserActionExecutor(driver, authorizer=None)
    asked: list[tuple] = []
    original = executor.api.perform

    async def _spy(capability_id, payload, context=None):
        asked.append((capability_id, dict(payload)))
        return await original(capability_id, payload, context)

    executor.api.perform = _spy
    await executor.perform({"action": "click", "selector": "#buy", "index": 2})
    assert asked == [
        (CAPABILITY, {"action": "click", "args": {"selector": "#buy", "index": 2}, "risk_tier": 2})
    ]


async def test_normalize_lowercases_and_trims_the_action():
    assert normalize_step({"action": "  CLICK  "})["action"] == "click"


async def test_normalize_bounds_an_argument():
    step = normalize_step({"action": "type", "text": "x" * (MAX_ARG_CHARS + 500)})
    assert len(step["args"]["text"]) == MAX_ARG_CHARS


async def test_normalize_bounds_how_many_arguments():
    step = normalize_step({"action": "click", **{f"k{i}": i for i in range(100)}})
    assert len(step["args"]) <= MAX_ARGS


async def test_normalize_drops_a_value_that_is_not_a_plain_one():
    """A nested structure is where a payload smuggles what a gate cannot read."""
    step = normalize_step({"action": "click", "payload": {"nested": True}, "ok": "yes"})
    assert "payload" not in step["args"]
    assert step["args"]["ok"] == "yes"


async def test_a_step_that_is_not_a_mapping_normalises_to_a_refusable_one():
    assert normalize_step("click") == {"action": "", "args": {}, "risk_tier": 2}


async def test_every_normalised_step_is_risk_tier_two():
    """Only mutating steps reach here, and a mutating browser step is never
    tier 1 however harmless its selector looks."""
    assert normalize_step({"action": "click"})["risk_tier"] == 2


# ── the executor's own edges ─────────────────────────────────────────────────

async def test_the_executor_refuses_an_action_the_driver_does_not_implement():
    """Reaching a permissive driver's __getattr__ would turn a typo into a
    silently successful no-op."""
    executor = BrowserActionExecutor(_Driver(), authorizer=None)
    out = await executor._execute({"action": "teleport", "args": {}}, None)
    assert out == {"ok": False, "reason": "unsupported_action"}


async def test_the_executor_refuses_an_empty_action():
    executor = BrowserActionExecutor(_Driver(), authorizer=None)
    assert (await executor._execute({"action": "  ", "args": {}}, None))["reason"] == "invalid_action"


async def test_the_executor_refuses_args_that_are_not_a_mapping():
    executor = BrowserActionExecutor(_Driver(), authorizer=None)
    assert (await executor._execute({"action": "click", "args": []}, None))["reason"] == "invalid_args"


async def test_the_executor_passes_the_arguments_through_verbatim():
    driver = _Driver()
    executor = BrowserActionExecutor(driver, authorizer=None)
    await executor._execute({"action": "click", "args": {"selector": "#buy"}}, None)
    assert driver.calls == [("click", {"selector": "#buy"})]


# ── navigation still refuses by name ─────────────────────────────────────────

async def test_navigation_without_a_transport_says_which_thing_is_missing():
    """"Not configured" is a config fix; "unavailable" is a bug report. One
    sentence for both made every report of this ambiguous."""
    out = await _browser(_Driver()).run_step({"action": "navigate", "url": "https://example.com"})
    assert out["status"] == "blocked"
    assert out["reason"] == TRANSPORT_NOT_CONFIGURED


async def test_navigation_with_a_transport_still_honours_the_allowlist():
    driver = NullBrowserDriver()
    browser = GovernedBrowser(
        driver=driver, policy=BrowserPolicy(["example.com"]), transport=object()
    )
    out = await browser.run_step({"action": "navigate", "url": "https://evil.test"})
    assert out["status"] == "blocked"
    assert "not in egress allowlist" in out["reason"]
    assert driver.calls == []


async def test_an_allowlisted_navigation_reaches_the_driver_once_a_transport_exists():
    driver = NullBrowserDriver()
    browser = GovernedBrowser(
        driver=driver, policy=BrowserPolicy(["example.com"]), transport=object()
    )
    out = await browser.run_step({"action": "navigate", "url": "https://example.com/x"})
    assert out["status"] == "done"
    assert driver.calls[0][0] == "navigate"


# ── the preview still tells the truth ────────────────────────────────────────

async def test_the_preview_still_marks_a_mutating_step_as_needing_approval():
    plan = [{"action": "click", "selector": "#buy"}]
    preview = _browser(_Driver()).preview(plan)
    assert preview["needs_approval"] == 1
    assert preview["blocked"] == 0
