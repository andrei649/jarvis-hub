"""Native, opt-in approval-judge auxiliary temperature repair (offline HTTPX)."""
from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest

from agents.core import settings_db
from agents.core.autonomy import approval_judge as aj
from agents.core.llm import data_handling as dh
from agents.core.llm.egress import llm_async_client

BASE = "https://judge.invalid/v1"
KEY = "synthetic-judge-key"
MODEL = "synthetic-judge"
ADVISORY = {"id": "review-item", "agent": "pepper", "tool": "write_file",
            "summary": "Write one file", "args": {"path": "notes/a.md"}}


@pytest.fixture(autouse=True)
def isolated_judge(monkeypatch, tmp_path):
    monkeypatch.setattr(settings_db, "DB_PATH", tmp_path / "judge-settings.db")
    monkeypatch.setattr(settings_db, "_initialized", False)
    settings_db.init_db(force=True)
    monkeypatch.setattr(dh, "_scope_key", lambda: b"active-auxiliary-test-scope")
    for name in ("JARVIS_SAFE_MODE", "JARVIS_STRICT_LOCAL", "JARVIS_SMART_APPROVALS",
                 "JARVIS_SMART_APPROVAL_POLICY", "JARVIS_SMART_APPROVAL_DENY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("JARVIS_ROLE_APPROVAL_JUDGE_MODEL", MODEL)
    monkeypatch.setenv("JARVIS_ROLE_APPROVAL_JUDGE_PROVIDER", "openai-compatible")
    monkeypatch.setenv("JARVIS_ROLE_APPROVAL_JUDGE_BASE_URL", BASE)
    monkeypatch.setenv("JARVIS_ROLE_APPROVAL_JUDGE_ALLOW_REMOTE", "1")
    monkeypatch.setenv("JARVIS_ROLE_APPROVAL_JUDGE_KEY", KEY)


def grant():
    target = aj.describe_data_target()
    assert target is not None
    dh.acknowledge(None, target.provider, True, dh.role_target_scope(target),
                   SimpleNamespace(log=lambda event: None), target="role:approval_judge")


async def judge_with_wire(handler):
    status = aj.approval_judge_status(settings=lambda *_: "on-demand")
    backend = aj._backend_for(status)
    await backend.client.aclose()
    backend.client = llm_async_client("openai-compatible", base_url=BASE, trust_env=False,
                                      transport=httpx.MockTransport(handler))
    return aj.ApprovalJudge(backend_factory=lambda _: backend,
                            settings=lambda *_: "on-demand"), backend


def smart_snapshot():
    return {
        "id": "14:digest", "task_id": 14, "snapshot_sha256": "a" * 64,
        "tool": "terminal_run", "agent": "jarvis", "summary": "Run terminal command",
        "args": {"kind": "toolrpc.terminal_run",
                 "payload": {"tool": "terminal_run", "target": "terminal_run",
                             "args": {"target": "local-host", "command": "pwd",
                                      "cwd": "/tmp", "timeout": 15}},
                 "risk_tier": 2, "origin": "owner", "autonomy_level": "ask"},
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("smart", [False, True])
async def test_native_judge_recovers_only_temperature_and_keeps_exact_cap(monkeypatch, smart):
    if smart:
        monkeypatch.setenv("JARVIS_SMART_APPROVALS", "1")
        monkeypatch.setenv("JARVIS_SMART_APPROVAL_POLICY", "Approve a harmless pwd in /tmp.")
    seen = []

    def handler(request):
        seen.append(request)
        body = json.loads(request.content)
        if "temperature" in body:
            return httpx.Response(400, json={"error": {"code": "unsupported_parameter",
                                                       "param": "temperature",
                                                       "message": "temperature is not supported"}})
        text = "approve" if smart else '{"risk": 37, "why": "Review the file"}'
        return httpx.Response(200, json={"choices": [{"message": {"content": text}}]})

    judge, backend = await judge_with_wire(handler)
    grant()
    result = await judge.score(smart_snapshot() if smart else ADVISORY, judge.status())

    if smart:
        assert result.verdict == "approve"
    else:
        assert result["score"] == 37 and result["advisory"] is True
    assert len(seen) == 2
    first, second = (json.loads(request.content) for request in seen)
    assert first["temperature"] == 0 and "temperature" not in second
    assert {key: value for key, value in first.items() if key != "temperature"} == second
    assert first["max_tokens"] == (16 if smart else 96)
    assert all(request.url == httpx.URL(BASE + "/chat/completions") for request in seen)
    assert all(request.headers["Authorization"] == "Bearer " + KEY for request in seen)
    assert backend.client.is_closed


@pytest.mark.asyncio
async def test_advisory_queue_stores_only_recovered_opinion(tmp_path):
    import asyncio

    from agents.core.autonomy.action_approvals import ActionApprovalQueue

    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        if len(seen) == 1:
            return httpx.Response(400, json={"error": {"code": "unsupported_parameter",
                                                       "param": "temperature",
                                                       "message": "temperature is not supported"}})
        return httpx.Response(200, json={"choices": [{"message": {
            "content": '{"risk": 44, "why": "Owner should review"}'}}]})

    judge, _ = await judge_with_wire(handler)
    grant()
    queue = ActionApprovalQueue(tmp_path / "approvals.json")
    queue.attach_judge(judge, loop=asyncio.get_running_loop())
    item = queue.request(dict(ADVISORY))
    for _ in range(50):
        tasks = list(queue._judge_tasks)
        if not tasks:
            await asyncio.sleep(0)
            if not queue._judge_tasks:
                break
        else:
            await asyncio.gather(*tasks, return_exceptions=True)
    stored = queue.get(item["id"])
    assert stored["status"] == "pending" and stored["judge"]["score"] == 44
    assert stored["judge"]["advisory"] is True
    assert len(seen) == 2 and seen[0]["max_tokens"] == seen[1]["max_tokens"] == 96


@pytest.mark.asyncio
@pytest.mark.parametrize("rejection", ["unrelated", "output_cap", "auth", "malformed",
                                              "oversized", "transport"])
async def test_unrelated_native_failure_never_replays_or_leaks(rejection, caplog):
    sent = []
    secret = "private-provider-body-credential"

    def handler(request):
        sent.append(request)
        if rejection == "transport":
            raise httpx.ConnectError(secret)
        if rejection == "unrelated":
            return httpx.Response(400, json={"error": {"code": "context_length_exceeded",
                                                       "message": "context too long " + secret}})
        if rejection == "output_cap":
            return httpx.Response(400, json={"error": {"code": "unsupported_parameter",
                                                       "param": "max_tokens",
                                                       "message": "max_tokens is not supported " + secret}})
        if rejection == "auth":
            return httpx.Response(401, json={"error": {"message": secret}})
        if rejection == "oversized":
            return httpx.Response(400, content=json.dumps({"error": {
                "param": "temperature", "message": "temperature is not supported " + secret + "x" * 4096}}))
        return httpx.Response(400, content="not-json " + secret)

    judge, backend = await judge_with_wire(handler)
    grant()
    with pytest.raises(RuntimeError, match="approval judge provider request failed") as exc:
        await judge.score(ADVISORY, judge.status())
    assert len(sent) == 1 and backend.client.is_closed
    assert secret not in str(exc.value) and secret not in caplog.text


@pytest.mark.asyncio
async def test_rejected_temperature_twice_never_gets_a_third_send():
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(400, json={"error": {"code": "unsupported_parameter",
                                                   "param": "temperature",
                                                   "message": "temperature is not supported"}})

    judge, backend = await judge_with_wire(handler)
    grant()
    with pytest.raises(RuntimeError, match="provider request failed"):
        await judge.score(ADVISORY, judge.status())
    assert len(seen) == 2 and "temperature" in seen[0] and "temperature" not in seen[1]
    assert [body["max_tokens"] for body in seen] == [96, 96]
    assert backend.client.is_closed


@pytest.mark.asyncio
async def test_next_judgement_starts_with_configured_temperature_again():
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        if "temperature" in seen[-1]:
            return httpx.Response(400, json={"error": {"code": "unsupported_parameter",
                                                       "param": "temperature",
                                                       "message": "temperature is not supported"}})
        return httpx.Response(200, json={"choices": [{"message": {
            "content": '{"risk": 12, "why": "Review"}'}}]})

    grant()
    for _ in range(2):
        judge, backend = await judge_with_wire(handler)
        assert (await judge.score(ADVISORY, judge.status()))["score"] == 12
        assert backend.client.is_closed
    assert len(seen) == 4 and ["temperature" in body for body in seen] == [True, False, True, False]
    assert all(body["max_tokens"] == 96 for body in seen)


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["key", "model", "base", "remote_off", "safe_mode",
                                     "h513_revoke", "client_base", "late_hook", "transport"])
async def test_rejection_rechecks_exact_route_before_second_send(monkeypatch, change):
    seen = []
    holder = {}

    def handler(request):
        seen.append(request)
        if change == "key":
            monkeypatch.setenv("JARVIS_ROLE_APPROVAL_JUDGE_KEY", "changed-key")
        elif change == "model":
            monkeypatch.setenv("JARVIS_ROLE_APPROVAL_JUDGE_MODEL", "changed-model")
        elif change == "base":
            monkeypatch.setenv("JARVIS_ROLE_APPROVAL_JUDGE_BASE_URL", "https://other.invalid/v1")
        elif change == "remote_off":
            monkeypatch.setenv("JARVIS_ROLE_APPROVAL_JUDGE_ALLOW_REMOTE", "0")
        elif change == "safe_mode":
            monkeypatch.setenv("JARVIS_SAFE_MODE", "1")
        elif change == "h513_revoke":
            target = aj.describe_data_target()
            dh.acknowledge(None, target.provider, False, dh.role_target_scope(target),
                           SimpleNamespace(log=lambda event: None), target="role:approval_judge")
        elif change == "client_base":
            holder["backend"].client.base_url = "https://other.invalid/v1"
        elif change == "late_hook":
            async def extra_hook(request):
                raise AssertionError("late hook must never run")
            holder["backend"].client.event_hooks["request"].insert(0, extra_hook)
        else:
            holder["backend"].client._transport_for_url = lambda url: None
        return httpx.Response(400, json={"error": {"code": "unsupported_parameter",
                                                   "param": "temperature",
                                                   "message": "temperature is not supported"}})

    judge, backend = await judge_with_wire(handler)
    holder["backend"] = backend
    grant()
    with pytest.raises(dh.DataHandlingRefused):
        await judge.score(ADVISORY, judge.status())
    assert len(seen) == 1 and backend.client.is_closed


@pytest.mark.asyncio
async def test_stale_after_recovered_response_cannot_become_opinion(monkeypatch):
    seen = []

    def handler(request):
        seen.append(request)
        if len(seen) == 1:
            return httpx.Response(400, json={"error": {"code": "unsupported_parameter",
                                                       "param": "temperature",
                                                       "message": "temperature is not supported"}})
        monkeypatch.setenv("JARVIS_ROLE_APPROVAL_JUDGE_MODEL", "changed-after-send")
        return httpx.Response(200, json={"choices": [{"message": {
            "content": '{"risk": 0, "why": "Stale"}'}}]})

    judge, backend = await judge_with_wire(handler)
    grant()
    with pytest.raises(dh.DataHandlingRefused):
        await judge.score(ADVISORY, judge.status())
    assert len(seen) == 2 and backend.client.is_closed


@pytest.mark.asyncio
async def test_native_request_hook_refuses_changed_cap_before_transport():
    sent = []
    judge, backend = await judge_with_wire(lambda request: sent.append(request))

    async def change_cap(request):
        body = json.loads(request.content)
        body["max_tokens"] = 1
        request._content = json.dumps(body).encode()

    backend.client.event_hooks["request"].insert(0, change_cap)
    grant()
    with pytest.raises(dh.DataHandlingRefused, match="physical request body changed"):
        await judge.score(ADVISORY, judge.status())
    assert sent == [] and backend.client.is_closed


@pytest.mark.asyncio
async def test_smart_observer_sees_each_recovered_physical_attempt(monkeypatch):
    from agents.core.autonomy import smart_observers

    monkeypatch.setenv("JARVIS_SMART_APPROVALS", "1")
    monkeypatch.setenv("JARVIS_SMART_APPROVAL_POLICY", "Approve a harmless pwd in /tmp.")
    calls = []
    original = smart_observers.requested

    def requested(snapshot):
        calls.append(snapshot["id"])
        return original(snapshot)

    monkeypatch.setattr(smart_observers, "requested", requested)
    sent = []

    def handler(request):
        sent.append(request)
        if len(sent) == 1:
            return httpx.Response(400, json={"error": {"code": "unsupported_parameter",
                                                       "param": "temperature",
                                                       "message": "temperature is not supported"}})
        return httpx.Response(200, json={"choices": [{"message": {"content": "approve"}}]})

    judge, _ = await judge_with_wire(handler)
    grant()
    result = await judge.score(smart_snapshot(), judge.status())
    assert result.verdict == "approve" and len(sent) == 2
    assert calls == ["14:digest", "14:digest"]


@pytest.mark.asyncio
async def test_queue_decision_between_rejection_and_retry_drops_opinion(tmp_path):
    import asyncio

    from agents.core.autonomy.action_approvals import ActionApprovalQueue

    sent = []
    holder = {}

    def handler(request):
        sent.append(request)
        holder["queue"].decide(holder["item"]["id"], False)
        return httpx.Response(400, json={"error": {"code": "unsupported_parameter",
                                                   "param": "temperature",
                                                   "message": "temperature is not supported"}})

    judge, _ = await judge_with_wire(handler)
    grant()
    queue = ActionApprovalQueue(tmp_path / "approval.json")
    holder["queue"] = queue
    queue.attach_judge(judge, loop=asyncio.get_running_loop())
    item = queue.request(dict(ADVISORY))
    holder["item"] = item
    for _ in range(50):
        tasks = list(queue._judge_tasks)
        if not tasks:
            await asyncio.sleep(0)
            if not queue._judge_tasks:
                break
        else:
            await asyncio.gather(*tasks, return_exceptions=True)
    assert len(sent) == 1 and "judge" not in queue.get(item["id"])


@pytest.mark.asyncio
async def test_cancellation_during_recovered_send_cleans_client():
    import asyncio

    entered = asyncio.Event()
    release = asyncio.Event()
    sent = []

    async def handler(request):
        sent.append(request)
        if len(sent) == 1:
            return httpx.Response(400, json={"error": {"code": "unsupported_parameter",
                                                       "param": "temperature",
                                                       "message": "temperature is not supported"}})
        entered.set()
        await release.wait()
        return httpx.Response(200, json={"choices": [{"message": {"content": "approve"}}]})

    judge, backend = await judge_with_wire(handler)
    grant()
    task = asyncio.create_task(judge.score(ADVISORY, judge.status()))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(sent) == 2 and backend.client.is_closed
    release.set()


@pytest.mark.asyncio
async def test_both_sends_share_one_total_timeout(monkeypatch):
    import asyncio

    monkeypatch.setenv(aj.ENV_TIMEOUT, "1")
    sent = []

    async def handler(request):
        sent.append(request)
        if len(sent) == 1:
            await asyncio.sleep(0.7)
            return httpx.Response(400, json={"error": {"code": "unsupported_parameter",
                                                       "param": "temperature",
                                                       "message": "temperature is not supported"}})
        await asyncio.sleep(10)
        return httpx.Response(200, json={"choices": [{"message": {
            "content": '{"risk": 0, "why": "Too late"}'}}]})

    judge, backend = await judge_with_wire(handler)
    grant()
    with pytest.raises(TimeoutError):
        await judge.score(ADVISORY, judge.status())
    assert len(sent) == 2 and backend.client.is_closed


@pytest.mark.asyncio
@pytest.mark.parametrize("hooks", ["missing", "after_recorder"])
async def test_initial_hook_refusal_closes_owned_client_without_sending(hooks):
    sent = []
    judge, backend = await judge_with_wire(lambda request: sent.append(request))

    async def late_hook(request):
        raise AssertionError("an unguarded late hook must never run")

    if hooks == "missing":
        backend.client.event_hooks["request"] = []
    else:
        backend.client.event_hooks["request"].append(late_hook)
    grant()
    with pytest.raises(dh.DataHandlingRefused, match="physical request hook is unavailable"):
        await judge.score(ADVISORY, judge.status())
    assert sent == []
    assert backend.client.is_closed
