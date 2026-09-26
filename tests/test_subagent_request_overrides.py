"""H681 — per-child API settings for a delegated sub-agent.

A child always ran on the parent's model with the parent's request settings:
``SubAgentManager.spawn`` took only a task, an agent, a parent and an output schema,
and the production runner called ``orch.process`` with nothing else. Now:

- ``spawn(..., model=, provider=, overrides=)`` — the model and provider are validated
  like a job's pin and the child runs inside the same ``selection_scope``; the
  overrides (``max_tokens``, ``temperature``, ``extra_body``) are bounded and apply to
  every generation the child makes;
- with neither given, ``autonomy.subagent_model`` / ``autonomy.subagent_provider``
  choose; with neither set, the child runs as the parent does. The spawn record says
  which of the three it was;
- ``extra_body`` is merged one level deep into an OpenAI-compatible request, never
  over the keys the hub owns (the model, the messages, the owner's provider routing);
- choosing a model this way passes the H378 guards like every other model choice.
"""
from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from fastapi import FastAPI

from agents.core.llm import request_context as rc
from agents.core.llm.job_selection import current_selection
from agents.core.subagents import SubAgentManager

_NO_COST = dict


def _mgr(runner=None, **kw):
    kw.setdefault("cost_probe", _NO_COST)
    kw.setdefault("persist", False)
    return SubAgentManager(runner=runner, **kw)


class _Seen:
    """A runner that records what the child saw from inside its own run."""

    def __init__(self):
        self.calls = []

    async def __call__(self, task, session_id, agent, selection=None):
        sel = current_selection()
        ov = rc.current_overrides()
        self.calls.append({
            "task": task, "selection": selection,
            "scoped_model": sel.model if sel else None,
            "scoped_provider": sel.provider if sel else None,
            "overrides": ov,
        })
        return {"output": f"done {task}"}


# ── the pin reaches the child ────────────────────────────────────────────────────

async def test_an_explicit_model_is_the_childs_selection():
    seen = _Seen()
    out = await _mgr(seen).spawn("t", model="m1")
    assert out["ok"] is True
    [call] = seen.calls
    assert call["scoped_model"] == "m1" and call["scoped_provider"] is None
    assert call["selection"] == {"model": "m1", "provider": None, "overrides": None, "source": "explicit"}
    assert out["selection"] == {"model": "m1", "provider": None, "overrides": None, "source": "explicit"}


async def test_the_selection_closes_with_the_child():
    seen = _Seen()
    m = _mgr(seen)
    await m.spawn("t", model="m1", provider="ollama")
    assert current_selection() is None and rc.current_overrides() is None
    assert seen.calls[0]["scoped_provider"] == "ollama"


async def test_a_runner_without_the_selection_kwarg_still_runs_scoped():
    scoped = []

    async def plain(task, session_id, agent):
        scoped.append(current_selection().model)
        return {"output": "ok"}

    out = await _mgr(plain).spawn("t", model="m2")
    assert out["ok"] is True and scoped == ["m2"]


async def test_the_setting_chooses_when_the_spawn_does_not():
    seen = _Seen()
    m = _mgr(seen, selection_defaults=lambda: {"model": "s1", "provider": "lm-studio"})
    out = await m.spawn("t")
    assert seen.calls[0]["scoped_model"] == "s1" and seen.calls[0]["scoped_provider"] == "lm-studio"
    assert out["selection"]["source"] == "setting"
    assert m.get(out["id"])["selection"]["source"] == "setting"


async def test_an_explicit_pin_wins_over_the_setting_as_a_pair():
    seen = _Seen()
    m = _mgr(seen, selection_defaults=lambda: {"model": "s1", "provider": "lm-studio"})
    out = await m.spawn("t", model="m1")
    # The setting's provider is not paired with another model the owner never chose.
    assert (seen.calls[0]["scoped_model"], seen.calls[0]["scoped_provider"]) == ("m1", None)
    assert out["selection"]["source"] == "explicit"


async def test_with_nothing_set_the_child_runs_as_the_parent():
    seen = _Seen()
    m = _mgr(seen, selection_defaults=lambda: {"model": "", "provider": ""})
    out = await m.spawn("t")
    assert seen.calls[0]["scoped_model"] is None and seen.calls[0]["selection"]["source"] == "parent"
    assert out["selection"] == {"model": None, "provider": None, "overrides": None, "source": "parent"}


async def test_an_unreadable_setting_runs_the_child_as_the_parent(caplog):
    def broken():
        raise OSError("settings store unreadable")

    seen = _Seen()
    out = await _mgr(seen, selection_defaults=broken).spawn("t")
    assert out["ok"] is True and out["selection"]["source"] == "parent"
    assert "autonomy.subagent_model" in caplog.text


async def test_a_bad_setting_value_is_refused_not_run():
    seen = _Seen()
    out = await _mgr(seen, selection_defaults=lambda: {"model": "no spaces allowed"}).spawn("t")
    assert out["ok"] is False and out["reason"] == "invalid_selection"
    assert "autonomy.subagent_model" in out["detail"] and seen.calls == []


# ── what a spawn may ask for ──────────────────────────────────────────────────────

@pytest.mark.parametrize("kwargs", [
    {"model": "has space"},
    {"model": 42},
    {"model": "x" * 300},
    {"provider": "not-a-provider"},
    {"overrides": {"max_tokens": 0}},
    {"overrides": {"max_tokens": 65537}},
    {"overrides": {"max_tokens": True}},
    {"overrides": {"max_tokens": 1.5}},
    {"overrides": {"temperature": -0.1}},
    {"overrides": {"temperature": 2.01}},
    {"overrides": {"temperature": float("nan")}},
    {"overrides": {"temperature": "hot"}},
    {"overrides": {"top_k": 3}},
    {"overrides": "fast"},
    {"overrides": {"extra_body": ["a"]}},
    {"overrides": {"extra_body": {"model": "other"}}},
    {"overrides": {"extra_body": {"provider": {"data_collection": "allow"}}}},
    {"overrides": {"extra_body": {"messages": []}}},
    {"overrides": {"extra_body": {"stream": True}}},
    {"overrides": {"extra_body": {"tools": []}}},
    {"overrides": {"extra_body": {"max_tokens": 9}}},
    {"overrides": {"extra_body": {"reasoning": {"effort": "high"}}}},
    {"overrides": {"extra_body": {"MODEL": "other"}}},
    {"overrides": {"extra_body": {"blob": "x" * 5000}}},
    {"overrides": {"extra_body": {"nan": float("nan")}}},
    {"overrides": {"extra_body": {1: "a"}}},
])
async def test_an_invalid_selection_is_refused_before_anything_runs(kwargs):
    seen = _Seen()
    m = _mgr(seen)
    out = await m.spawn("t", **kwargs)
    assert out["ok"] is False and out["reason"] == "invalid_selection" and out["detail"]
    assert seen.calls == [] and m.stats()["total"] == 0 and m.stats()["active"] == 0


async def test_an_invalid_selection_spends_no_budget():
    from agents.core.iteration_budget import IterationBudget

    m = _mgr(_Seen(), budget=IterationBudget(1))
    assert (await m.spawn("t", model="bad model"))["reason"] == "invalid_selection"
    assert (await m.spawn("t"))["ok"] is True


def test_the_bounds_accept_their_edges():
    ov = rc.validate_overrides({"max_tokens": 1, "temperature": 0, "extra_body": {"top_k": 40}})
    assert (ov.max_tokens, ov.temperature, ov.extra_body) == (1, 0.0, {"top_k": 40})
    ov = rc.validate_overrides({"max_tokens": 65536, "temperature": 2})
    assert (ov.max_tokens, ov.temperature, ov.extra_body) == (65536, 2.0, None)
    assert rc.validate_overrides(None) is None and rc.validate_overrides({}) is None


def test_extra_body_is_bounded_by_its_json_size():
    fits = {"k": "x" * (rc.EXTRA_BODY_MAX_BYTES - 20)}
    assert len(json.dumps(fits)) <= rc.EXTRA_BODY_MAX_BYTES
    assert rc.validate_overrides({"extra_body": fits}).extra_body == fits
    with pytest.raises(ValueError):
        rc.validate_overrides({"extra_body": {"k": "x" * rc.EXTRA_BODY_MAX_BYTES}})


def test_a_validated_extra_body_is_a_private_copy():
    body = {"metadata": {"a": 1}}
    ov = rc.validate_overrides({"extra_body": body})
    body["metadata"]["a"] = 2
    body["model"] = "sneaked"
    assert ov.extra_body == {"metadata": {"a": 1}}


# ── the overrides apply to the child's generations ─────────────────────────────────

def test_generation_parameters_take_the_overrides_only_inside_the_scope(monkeypatch):
    from agents.core import agent as agent_mod

    monkeypatch.setattr("agents.core.settings_db.get_value",
                        lambda cat, key, default=None: {"max_tokens": 2048, "deep_max_tokens": 8192,
                                                        "temperature": 0.7}.get(key, default))
    a = agent_mod.Agent.__new__(agent_mod.Agent)
    assert a._gen_params("") == (2048, 0.7)
    with rc.request_overrides_scope(rc.validate_overrides({"max_tokens": 300, "temperature": 0.1})) as frame:
        assert a._gen_params("") == (300, 0.1)
        assert a._gen_params("local-deep") == (300, 0.1)
        assert frame.applied == {"max_tokens", "temperature"}
    assert a._gen_params("") == (2048, 0.7)


def test_one_override_leaves_the_other_parameter_as_configured(monkeypatch):
    from agents.core import agent as agent_mod

    monkeypatch.setattr("agents.core.settings_db.get_value",
                        lambda cat, key, default=None: {"max_tokens": 2048, "temperature": 0.7}.get(key, default))
    a = agent_mod.Agent.__new__(agent_mod.Agent)
    with rc.request_overrides_scope(rc.validate_overrides({"temperature": 1.3})) as frame:
        assert a._gen_params("") == (2048, 1.3)
        assert frame.applied == {"temperature"}


def test_the_orchestrator_fallback_reads_the_overrides_too():
    from agents.core.orchestrator import Orchestrator

    orch = Orchestrator.__new__(Orchestrator)
    orch.get_setting = lambda key, default=None: {"llm.max_tokens": 1000, "llm.temperature": 0.5}.get(key, default)
    bare = object()                                   # an agent without _gen_params
    assert orch._agent_gen_params(bare, "") == (1000, 0.5)
    with rc.request_overrides_scope(rc.validate_overrides({"max_tokens": 77})):
        assert orch._agent_gen_params(bare, "") == (77, 0.5)


async def test_the_overrides_reach_the_child_and_close_with_it():
    seen = _Seen()
    m = _mgr(seen)
    out = await m.spawn("t", overrides={"max_tokens": 128, "extra_body": {"top_k": 5}})
    ov = seen.calls[0]["overrides"]
    assert (ov.max_tokens, ov.temperature, ov.extra_body) == (128, None, {"top_k": 5})
    assert out["selection"]["overrides"] == {"max_tokens": 128, "extra_body": {"top_k": 5}}
    assert out["selection"]["source"] == "parent"      # no model chosen: the parent's route
    assert rc.current_overrides() is None


async def test_the_record_says_which_overrides_a_provider_applied():
    async def runner(task, session_id, agent):
        rc.apply_generation_overrides(10, 0.7)         # what _gen_params does
        return {"output": "ok"}

    out = await _mgr(runner).spawn("t", overrides={"max_tokens": 64, "extra_body": {"top_k": 5}})
    # extra_body was never merged into a request: the child's route is not OpenAI-compatible.
    assert out["overrides_applied"] == ["max_tokens"]
    assert out["overrides_ignored"] == ["extra_body"]


def test_extra_body_merges_one_level_deep_and_never_over_what_the_hub_owns():
    payload = {"model": "m", "messages": [], "provider": {"data_collection": "deny"},
               "metadata": {"a": 1, "b": 2}, "top_p": 0.9}
    ov = rc.validate_overrides({"extra_body": {"metadata": {"b": 3, "c": 4}, "top_p": 0.5, "seed": 7}})
    with rc.request_overrides_scope(ov) as frame:
        rc.merge_extra_body(payload)
    assert payload == {"model": "m", "messages": [], "provider": {"data_collection": "deny"},
                       "metadata": {"a": 1, "b": 3, "c": 4}, "top_p": 0.5, "seed": 7}
    assert frame.applied == {"extra_body"}
    untouched = {"model": "m"}
    rc.merge_extra_body(untouched)                    # outside a scope: nothing
    assert untouched == {"model": "m"}


def test_a_nested_value_is_copied_into_the_request_not_shared():
    ov = rc.validate_overrides({"extra_body": {"metadata": {"tags": ["a"]}}})
    first, second = {}, {}
    with rc.request_overrides_scope(ov):
        rc.merge_extra_body(first)
        first["metadata"]["tags"].append("b")
        rc.merge_extra_body(second)
    assert second == {"metadata": {"tags": ["a"]}}


async def test_an_openai_compatible_request_carries_the_extra_body():
    from agents.core.llm.openrouter import OpenRouterBackend

    sent = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "hi"}}]}, request=request)

    backend = OpenRouterBackend(api_key="sk-or-test",
                                client=httpx.AsyncClient(base_url="https://openrouter.test/api/v1",
                                                         transport=httpx.MockTransport(handler)))
    ov = rc.validate_overrides({"max_tokens": 50, "extra_body": {"top_k": 20, "metadata": {"x": 1}}})
    with rc.request_overrides_scope(ov) as frame:
        assert await backend.generate("vendor/m", "p", max_tokens=50) == "hi"
    assert sent[0]["top_k"] == 20 and sent[0]["metadata"] == {"x": 1}
    assert sent[0]["model"] == "vendor/m"
    assert "extra_body" in frame.applied
    await backend.generate("vendor/m", "p")
    assert "top_k" not in sent[1]


# ── the routes ─────────────────────────────────────────────────────────────────────

class _Orch:
    def __init__(self, subagents, audit=None):
        self.subagents = subagents
        self.audit = audit


class _Audit:
    def __init__(self):
        self.rows = []

    def log(self, event):
        self.rows.append(event)


def _client(orch, monkeypatch):
    from agents.core.routers import _component, mesh
    from agents.core.routers._deps import admin_guard, user_guard

    monkeypatch.setattr(mesh, "get_orch", lambda: orch)
    monkeypatch.setattr(_component, "get_orch", lambda: orch)
    app = FastAPI()
    app.include_router(mesh.router)
    app.dependency_overrides[user_guard] = lambda: None
    app.dependency_overrides[admin_guard] = lambda: None
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_the_spawn_route_takes_a_model_provider_and_overrides(monkeypatch):
    seen = _Seen()
    async with _client(_Orch(_mgr(seen)), monkeypatch) as client:
        r = await client.post("/api/subagents/spawn", json={
            "task": "t", "model": "qwen3:8b", "provider": "ollama",
            "overrides": {"max_tokens": 256, "temperature": 0.2}})
    assert r.status_code == 200, r.text
    assert seen.calls[0]["scoped_model"] == "qwen3:8b" and seen.calls[0]["overrides"].max_tokens == 256
    assert r.json()["selection"]["source"] == "explicit"


@pytest.mark.parametrize("body", [
    {"task": "t", "model": "bad model"},
    {"task": "t", "provider": "nope"},
    {"task": "t", "overrides": {"extra_body": {"model": "x"}}},
    {"task": "t", "overrides": {"max_tokens": 0}},
])
async def test_the_spawn_route_refuses_an_invalid_selection_with_422(monkeypatch, body):
    seen = _Seen()
    async with _client(_Orch(_mgr(seen)), monkeypatch) as client:
        r = await client.post("/api/subagents/spawn", json=body)
    assert r.status_code == 422 and seen.calls == []
    assert r.json().get("reason") == "invalid_selection" or r.json().get("detail")


async def test_an_expensive_model_for_a_child_is_refused_until_confirmed(monkeypatch):
    seen, audit = _Seen(), _Audit()
    async with _client(_Orch(_mgr(seen), audit), monkeypatch) as client:
        r = await client.post("/api/subagents/spawn", json={"task": "t", "model": "claude-fable-5"})
        assert r.status_code == 409 and r.json()["needs"] == ["confirm_expensive"]
        assert seen.calls == []
        r = await client.post("/api/subagents/spawn", json={"task": "t", "model": "claude-fable-5",
                                                             "confirm_expensive": True})
    assert r.status_code == 200 and len(seen.calls) == 1
    [row] = [e for e in audit.rows if e.action_taken == "model_cost_confirmed"]
    assert "subagent.model" in row.content_preview and "claude-fable-5" in row.content_preview


async def test_a_training_tier_for_a_child_needs_the_acknowledgement_written_first(monkeypatch):
    seen, audit = _Seen(), _Audit()
    body = {"task": "t", "model": "meta-llama/llama-4-maverick:free", "provider": "openrouter"}
    async with _client(_Orch(_mgr(seen), audit), monkeypatch) as client:
        r = await client.post("/api/subagents/spawn", json=body)
        assert r.status_code == 409 and r.json()["needs"] == ["acknowledge_training"]
        r = await client.post("/api/subagents/spawn", json={**body, "acknowledge_training": True})
        assert r.status_code == 200
        broken = _Orch(_mgr(seen), None)                     # no audit log: no consent, no child
    async with _client(broken, monkeypatch) as client:
        r = await client.post("/api/subagents/spawn", json={**body, "acknowledge_training": True})
    assert r.status_code == 503 and r.json()["error"] == "consent_not_recorded"
    assert len(seen.calls) == 1
    assert [e.action_taken for e in audit.rows] == ["model_training_consent"]


async def test_a_spawn_without_a_model_is_never_asked(monkeypatch):
    seen = _Seen()
    m = _mgr(seen, selection_defaults=lambda: {"model": "claude-fable-5", "provider": "anthropic"})
    async with _client(_Orch(m), monkeypatch) as client:
        # The setting was guarded when it was stored; the spawn chose nothing.
        r = await client.post("/api/subagents/spawn", json={"task": "t"})
    assert r.status_code == 200 and seen.calls[0]["scoped_model"] == "claude-fable-5"


# ── the settings ───────────────────────────────────────────────────────────────────

@pytest.fixture
def store(tmp_path, monkeypatch):
    from agents.core import settings_db

    monkeypatch.setattr(settings_db, "DB_PATH", tmp_path / "settings.db")
    monkeypatch.setattr(settings_db, "_initialized", False, raising=False)
    settings_db.init_db(force=True)
    return settings_db


def test_the_settings_are_declared_empty_by_default(store):
    assert store.get_value("autonomy", "subagent_model") == ""
    assert store.get_value("autonomy", "subagent_provider") == ""


@pytest.mark.parametrize("values,ok", [
    ({"subagent_model": ""}, True),
    ({"subagent_model": "qwen3:8b"}, True),
    ({"subagent_model": "vendor/model-name:free"}, True),
    ({"subagent_model": "has space"}, False),
    ({"subagent_model": "x" * 300}, False),
    ({"subagent_model": 3}, False),
    ({"subagent_provider": ""}, True),
    ({"subagent_provider": "ollama"}, True),
    ({"subagent_provider": "openrouter"}, True),
    ({"subagent_provider": "somewhere"}, False),
])
def test_the_settings_are_validated_like_a_pin(store, values, ok):
    assert (store.validate_category("autonomy", values) == []) is ok


def test_the_subagent_model_is_a_model_choice_for_the_guards(store):
    from agents.core.llm import selection_guards as sg

    current = {"subagent_provider": "anthropic", "subagent_model": "claude-haiku-4-5"}.get
    names = lambda cs: [(c.setting, c.provider, c.model) for c in cs]  # noqa: E731
    assert names(sg.choices_from_settings("autonomy", {"subagent_model": "claude-fable-5"}, current)) == [
        ("autonomy.subagent_model", "anthropic", "claude-fable-5")]
    # The provider changes under the stored model.
    assert names(sg.choices_from_settings("autonomy", {"subagent_provider": "openrouter"}, current)) == [
        ("autonomy.subagent_model", "openrouter", "claude-haiku-4-5")]
    assert sg.choices_from_settings("autonomy", {"subagent_model": ""}, current) == []
    assert sg.choices_from_settings("autonomy", {"max_subagents": 4}, current) == []


def test_a_settings_import_guards_both_categories_at_once(store):
    from agents.core.llm import selection_guards as sg

    changes = {"llm": {"claude_model": "claude-fable-5"},
               "autonomy": {"subagent_model": "claude-opus-4-1-20250805", "subagent_provider": "anthropic"}}
    choices = sg.choices_from_changes(changes, store.get_value)
    assert [(c.setting, c.model) for c in choices] == [
        ("llm.claude_model", "claude-fable-5"), ("autonomy.subagent_model", "claude-opus-4-1-20250805")]


@pytest.fixture
def admin_client(store, monkeypatch):
    from fastapi.testclient import TestClient

    from agents import web
    from agents.core.llm import selection_guards as sg
    from agents.core.routers import admin

    audit = _Audit()
    monkeypatch.setattr(web, "ADMIN_TOKEN", "adm-h681")
    orch = type("O", (), {"audit": audit})()
    monkeypatch.setattr(admin, "get_orch", lambda: orch)
    monkeypatch.setattr(sg, "_orch", lambda: orch, raising=False)
    return TestClient(web.app), audit


ADMIN = {"X-Admin-Token": "adm-h681"}


def test_an_expensive_subagent_model_is_refused_until_confirmed(admin_client, store):
    client, audit = admin_client
    r = client.put("/api/admin/settings/autonomy", json={"values": {"subagent_model": "claude-fable-5"}}, headers=ADMIN)
    assert r.status_code == 409 and r.json()["needs"] == ["confirm_expensive"]
    assert store.get_value("autonomy", "subagent_model") == ""
    r = client.put("/api/admin/settings/autonomy", json={"values": {"subagent_model": "claude-fable-5"},
                                                          "confirm_expensive": True}, headers=ADMIN)
    assert r.status_code == 200 and store.get_value("autonomy", "subagent_model") == "claude-fable-5"


def test_an_import_that_sets_an_expensive_subagent_model_is_refused_until_confirmed(admin_client, store):
    client, _audit = admin_client
    doc = {"settings": {"autonomy": {"subagent_model": "claude-fable-5"}}}
    dry = client.post("/api/admin/settings/import", json={**doc, "dry_run": True}, headers=ADMIN)
    assert dry.status_code == 200 and [g["setting"] for g in dry.json()["guards"]] == ["autonomy.subagent_model"]
    r = client.post("/api/admin/settings/import", json=doc, headers=ADMIN)
    assert r.status_code == 409 and store.get_value("autonomy", "subagent_model") == ""
    r = client.post("/api/admin/settings/import", json={**doc, "confirm_expensive": True}, headers=ADMIN)
    assert r.status_code == 200 and store.get_value("autonomy", "subagent_model") == "claude-fable-5"


def test_the_cli_guards_the_subagent_model_and_reads_its_own_category(store, monkeypatch):
    import io

    from agents.cli import nerva

    audit = _Audit()
    monkeypatch.setattr(nerva, "_audit_log", lambda: audit, raising=False)
    store.put_category("autonomy", {"subagent_provider": "openrouter"})

    def run(*argv):
        out, err = io.StringIO(), io.StringIO()
        code = nerva.main(list(argv), context=nerva.Context(environ={}, out=out, err=err))
        return code, err.getvalue()

    code, err = run("config", "set", "autonomy.subagent_model", "meta-llama/llama-4-maverick:free")
    # The stored autonomy provider (openrouter) is read, not llm's.
    assert code != 0 and "--acknowledge-training" in err
    code, _ = run("config", "set", "autonomy.subagent_model", "meta-llama/llama-4-maverick:free",
                  "--acknowledge-training")
    assert code == 0 and store.get_value("autonomy", "subagent_model") == "meta-llama/llama-4-maverick:free"


# ── the production wiring ──────────────────────────────────────────────────────────

def test_the_coordinator_reads_the_settings_for_a_childs_default():
    from types import SimpleNamespace

    from agents.core.autonomy_coordinator import AutonomyCoordinator

    stored = {"autonomy.subagent_model": " qwen3:8b ", "autonomy.subagent_provider": "ollama"}
    coord = SimpleNamespace(_orch=SimpleNamespace(get_setting=lambda k, d=None: stored.get(k, d)))
    assert AutonomyCoordinator._subagent_selection_defaults(coord) == {"model": "qwen3:8b", "provider": "ollama"}
    stored.clear()
    assert AutonomyCoordinator._subagent_selection_defaults(coord) == {"model": "", "provider": ""}


def test_overrides_are_bounded_on_the_wire_too():
    assert asyncio.iscoroutinefunction(SubAgentManager.spawn)
    assert rc.OVERRIDE_KEYS == ("max_tokens", "temperature", "extra_body")
    assert {"model", "messages", "provider", "stream", "tools"} <= rc.RESERVED_BODY_KEYS


# ── edges (added by the mutation pass) ─────────────────────────────────────────────

def test_a_zero_temperature_is_applied_not_ignored(monkeypatch):
    from agents.core import agent as agent_mod

    monkeypatch.setattr("agents.core.settings_db.get_value",
                        lambda cat, key, default=None: {"max_tokens": 2048, "temperature": 0.7}.get(key, default))
    a = agent_mod.Agent.__new__(agent_mod.Agent)
    with rc.request_overrides_scope(rc.validate_overrides({"temperature": 0})) as frame:
        assert a._gen_params("") == (2048, 0.0)
        assert frame.applied == {"temperature"}


def test_extra_body_at_exactly_the_limit_is_accepted():
    overhead = len(json.dumps({"k": ""}))
    exact = {"k": "x" * (rc.EXTRA_BODY_MAX_BYTES - overhead)}
    assert len(json.dumps(exact).encode()) == rc.EXTRA_BODY_MAX_BYTES
    assert rc.validate_overrides({"extra_body": exact}).extra_body == exact
    over = {"k": "x" * (rc.EXTRA_BODY_MAX_BYTES - overhead + 1)}
    with pytest.raises(ValueError):
        rc.validate_overrides({"extra_body": over})


def test_an_empty_extra_body_is_no_override():
    assert rc.validate_overrides({"extra_body": {}}) is None


def test_merging_without_an_extra_body_marks_nothing_applied():
    with rc.request_overrides_scope(rc.validate_overrides({"max_tokens": 5})) as frame:
        payload = {"model": "m"}
        rc.merge_extra_body(payload)
    assert payload == {"model": "m"} and frame.applied == set()


async def test_an_empty_explicit_model_is_no_pin():
    seen = _Seen()
    m = _mgr(seen, selection_defaults=lambda: {"model": "s1"})
    out = await m.spawn("t", model="", provider="")
    assert out["ok"] is True and seen.calls[0]["scoped_model"] == "s1"
    assert out["selection"]["source"] == "setting"


async def test_defaults_that_are_not_an_object_read_as_unset():
    seen = _Seen()
    out = await _mgr(seen, selection_defaults=lambda: None).spawn("t")
    assert out["ok"] is True and out["selection"]["source"] == "parent"


async def test_an_invalid_selection_records_no_consent_even_when_confirmed(monkeypatch):
    seen, audit = _Seen(), _Audit()
    async with _client(_Orch(_mgr(seen), audit), monkeypatch) as client:
        r = await client.post("/api/subagents/spawn", json={
            "task": "t", "model": "claude-fable-5", "confirm_expensive": True,
            "overrides": {"max_tokens": 0}})
    assert r.status_code == 422 and r.json()["reason"] == "invalid_selection"
    assert audit.rows == [] and seen.calls == []


def test_the_provider_options_match_the_pinnable_providers(store):
    from agents.core.llm.job_selection import PROVIDERS

    [row] = [r for r in store.DEFAULTS if r["category"] == "autonomy" and r["key"] == "subagent_provider"]
    assert set(row["opts"]) == {""} | set(PROVIDERS)
