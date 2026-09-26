"""H378 — be warned before choosing a model that is very expensive or trains on your data.

Choosing a model was an ordinary settings write: `llm.claude_model=claude-fable-5` ($10/M
in, $50/M out) or an OpenRouter `:free` variant (served by providers that may train on the
prompts) was stored at once, from the HUD, a settings import, `nerva config set` or a job's
model pin, with no price shown and nothing asked. Now one registry of guards runs once over
every model choice, server-side, before it is stored, on each of those surfaces:

- **cost** — a model whose output costs at least `llm.cost_confirm_usd_per_mtok` ($40/M by
  default; 0 = never ask) needs `confirm_expensive`, and the refusal names its prices;
- **data policy** — a model or route whose vendor trains on prompts needs
  `acknowledge_training`, and the acknowledgement is a consent row in the audit log,
  written before the choice is stored (no row, no choice).

A guard registered once appears on every surface at once.
"""

from __future__ import annotations

import io

import pytest

from agents.core import settings_db
from agents.core.llm import selection_guards as sg

ADMIN = {"X-Admin-Token": "adm-h378"}
FABLE = "claude-fable-5"            # $10 / $50 per million tokens
FREE = "meta-llama/llama-4-maverick:free"


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_db, "DB_PATH", tmp_path / "settings.db")
    monkeypatch.setattr(settings_db, "_initialized", False, raising=False)
    settings_db.init_db(force=True)
    return settings_db


class Audit:
    def __init__(self, fail=False):
        self.rows, self.fail = [], fail

    def log(self, event):
        if self.fail:
            raise OSError("audit disk full")
        self.rows.append(event)


@pytest.fixture
def audit():
    return Audit()


@pytest.fixture
def client(store, audit, monkeypatch):
    from fastapi.testclient import TestClient

    from agents import web
    from agents.core.routers import admin, jobs

    monkeypatch.setattr(web, "ADMIN_TOKEN", "adm-h378")
    orch = type("O", (), {"audit": audit})()
    monkeypatch.setattr(admin, "get_orch", lambda: orch)
    monkeypatch.setattr(jobs, "get_orch", lambda: orch)
    monkeypatch.setattr(sg, "_orch", lambda: orch, raising=False)
    return TestClient(web.app)


def _consents(audit):
    return [e for e in audit.rows if e.action_taken == "model_training_consent"]


def _cost_rows(audit):
    return [e for e in audit.rows if e.action_taken == "model_cost_confirmed"]


# ── the guards ──────────────────────────────────────────────────────────────────

def test_the_cost_guard_names_the_price_of_an_expensive_model(store):
    [f] = sg.evaluate([sg.Choice("llm.claude_model", "anthropic", FABLE)])
    assert (f.guard, f.needs) == ("cost", "confirm_expensive")
    assert f.detail == {"input": 10.0, "output": 50.0, "threshold": 40.0}
    assert "$10" in f.message and "$50" in f.message and FABLE in f.message


def test_a_model_below_the_line_or_unpriced_passes_the_cost_guard(store):
    assert sg.evaluate([sg.Choice("llm.claude_model", "anthropic", "claude-sonnet-4-6")]) == []
    assert sg.evaluate([sg.Choice("llm.claude_model", "anthropic", "claude-opus-5")]) == []     # $25 out
    assert sg.evaluate([sg.Choice("llm.compatible_model", "openai-compatible", "somebody/unknown-7b")]) == []


def test_the_line_is_the_owners_and_zero_never_asks(store):
    store.put_category("llm", {"cost_confirm_usd_per_mtok": 20})
    [f] = sg.evaluate([sg.Choice("llm.claude_model", "anthropic", "claude-opus-5")])        # $25 out ≥ $20
    assert f.detail["threshold"] == 20.0
    store.put_category("llm", {"cost_confirm_usd_per_mtok": 0})
    assert sg.evaluate([sg.Choice("llm.claude_model", "anthropic", FABLE)]) == []


def test_exactly_at_the_line_asks(store):
    store.put_category("llm", {"cost_confirm_usd_per_mtok": 50})
    assert [f.guard for f in sg.evaluate([sg.Choice("llm.claude_model", "anthropic", FABLE)])] == ["cost"]
    store.put_category("llm", {"cost_confirm_usd_per_mtok": 50.01})
    assert sg.evaluate([sg.Choice("llm.claude_model", "anthropic", FABLE)]) == []


def test_a_routed_slug_is_priced_by_its_model(store):
    assert sg.price_of("anthropic/claude-fable-5") == {"input": 10.0, "output": 50.0}
    assert sg.price_of("claude-fable-5:beta") == {"input": 10.0, "output": 50.0}
    assert sg.price_of("nobody/knows") is None
    assert sg.price_of("") is None


def test_a_free_openrouter_variant_needs_an_acknowledgement(store):
    [f] = sg.evaluate([sg.Choice("llm.compatible_model", "openrouter", FREE)])
    assert (f.guard, f.needs) == ("data_policy", "acknowledge_training")
    assert "train" in f.message and FREE in f.message


def test_allowing_openrouter_upstreams_that_train_needs_an_acknowledgement(store):
    [f] = sg.evaluate([sg.Choice("llm.openrouter_data_collection", "openrouter", "", route="data_collection=allow")])
    assert f.needs == "acknowledge_training" and "store or train" in f.message


def test_a_vendor_that_does_not_train_passes(store):
    assert sg.evaluate([sg.Choice("llm.claude_model", "anthropic", "claude-sonnet-4-6")]) == []
    assert sg.evaluate([sg.Choice("llm.compatible_model", "openrouter", "anthropic/claude-sonnet-4-6")]) == []
    # an unknown provider on a pin still gets the model-level rule; a named one only its own
    [f] = sg.evaluate([sg.Choice("job.model", "", FREE)])
    assert f.guard == "data_policy"
    assert sg.evaluate([sg.Choice("job.model", "anthropic", "claude-haiku-4-5:free")]) == []


def test_every_provider_declares_a_data_policy():
    from agents.core.llm.providers import list_profiles

    for profile in list_profiles():
        assert profile.data_policy in sg.DATA_POLICIES, profile.id
        assert profile.status()["data_policy"]["policy"] == profile.data_policy
    local = {p.id: p.data_policy for p in list_profiles()}
    assert local["lm-studio"] == local["ollama"] == "local"
    assert local["anthropic"] == "no-training"


def test_one_choice_can_trip_both_guards(store):
    both = sg.evaluate([sg.Choice("llm.compatible_model", "openrouter", "anthropic/claude-fable-5:free")])
    assert [(f.guard, f.needs) for f in both] == [("cost", "confirm_expensive"), ("data_policy", "acknowledge_training")]


def test_an_unreadable_or_odd_line_keeps_the_shipped_one(store, monkeypatch):
    for odd in (-5, True, "40", None):
        monkeypatch.setattr(settings_db, "get_value", lambda *a, _v=odd, **k: _v)
        assert sg._cost_line() == 40.0, odd


def test_a_profile_must_declare_a_known_policy():
    from agents.core.llm.providers import ProviderProfile

    with pytest.raises(ValueError):
        ProviderProfile(id="x", display_name="X", backend_kind="k", data_policy="sometimes")
    with pytest.raises(ValueError):
        ProviderProfile(id="x", display_name="X", backend_kind="k", data_policy_models=(("*", "maybe", ""),))
    ok = ProviderProfile(id="x", display_name="X", backend_kind="k", data_policy_models=[["*:free", "trains-on-inputs", "n"]])
    assert ok.data_policy_for("A:FREE") == ("trains-on-inputs", "n")          # case-insensitive
    assert ok.data_policy_for("") == ("unknown", "")


def test_every_guard_runs_once_per_choice(store, monkeypatch):
    calls = []
    monkeypatch.setattr(sg, "GUARDS", [lambda c: calls.append(c.model)])
    sg.evaluate([sg.Choice("a", "anthropic", "m1"), sg.Choice("b", "gemini", "m2")])
    assert calls == ["m1", "m2"]


def test_enforce_refuses_what_is_not_cleared_and_names_the_flags(store):
    both = [sg.Choice("llm.claude_model", "anthropic", FABLE), sg.Choice("llm.compatible_model", "openrouter", FREE)]
    with pytest.raises(sg.SelectionRefused) as nothing:
        sg.enforce(both)
    assert nothing.value.payload()["needs"] == ["acknowledge_training", "confirm_expensive"]
    with pytest.raises(sg.SelectionRefused) as refused:
        sg.enforce(both, confirm_expensive=True)
    payload = refused.value.payload()
    assert payload["error"] == "selection_guard"
    assert payload["needs"] == ["acknowledge_training"]
    assert {g["guard"] for g in payload["guards"]} == {"cost", "data_policy"}      # all of them, to resend both flags
    assert len(sg.enforce(both, confirm_expensive=True, acknowledge_training=True)) == 2
    assert sg.enforce([sg.Choice("llm.claude_model", "anthropic", "claude-sonnet-4-6")]) == []


def test_choices_follow_the_settings_that_pick_a_model(store):
    current = {"compatible_provider": "openrouter", "compatible_model": FREE}.get
    names = lambda cs: [(c.setting, c.provider, c.model, c.route) for c in cs]  # noqa: E731
    assert names(sg.choices_from_settings("llm", {"claude_model": FABLE}, current)) == [("llm.claude_model", "anthropic", FABLE, "")]
    assert names(sg.choices_from_settings("llm", {"gemini_model": "gemini-2.5-pro"}, current)) == [("llm.gemini_model", "gemini", "gemini-2.5-pro", "")]
    # the provider changes under a stored model, or the model under a stored provider
    assert names(sg.choices_from_settings("llm", {"compatible_provider": "openrouter"}, current)) == [("llm.compatible_model", "openrouter", FREE, "")]
    assert names(sg.choices_from_settings("llm", {"compatible_model": "x/y"}, current)) == [("llm.compatible_model", "openrouter", "x/y", "")]
    assert names(sg.choices_from_settings("llm", {"compatible_model": "x/y", "compatible_provider": ""}, current)) == []
    assert names(sg.choices_from_settings("llm", {"openrouter_data_collection": "allow"}, current)) == [
        ("llm.openrouter_data_collection", "openrouter", "", "data_collection=allow")]
    assert sg.choices_from_settings("llm", {"openrouter_data_collection": "deny", "temperature": 0.2}, current) == []
    assert sg.choices_from_settings("system", {"claude_model": FABLE}, current) == []


# ── the settings write (HUD, v1 admin) ──────────────────────────────────────────

def test_an_expensive_model_is_refused_until_confirmed(client, audit):
    r = client.put("/api/admin/settings/llm", json={"values": {"claude_model": FABLE}}, headers=ADMIN)
    assert r.status_code == 409
    body = r.json()
    assert body["error"] == "selection_guard" and body["needs"] == ["confirm_expensive"]
    assert body["guards"][0]["detail"]["output"] == 50.0
    assert settings_db.get_value("llm", "claude_model") != FABLE                   # nothing written
    r = client.put("/api/admin/settings/llm", json={"values": {"claude_model": FABLE}, "confirm_expensive": True}, headers=ADMIN)
    assert r.status_code == 200 and settings_db.get_value("llm", "claude_model") == FABLE
    assert [g["guard"] for g in r.json()["guards"]] == ["cost"]
    [row] = _cost_rows(audit)
    assert FABLE in row.content_preview and "$50" in row.content_preview


def test_a_consent_must_be_a_literal_true(client):
    r = client.put("/api/admin/settings/llm", json={"values": {"claude_model": FABLE}, "confirm_expensive": "yes"}, headers=ADMIN)
    assert r.status_code == 422
    r = client.put("/api/admin/settings/llm", json={"values": {"claude_model": FABLE}, "confirm_expensive": 1}, headers=ADMIN)
    assert r.status_code == 422


def test_a_training_tier_is_refused_until_acknowledged_and_the_consent_is_audited(client, audit):
    values = {"compatible_provider": "openrouter", "compatible_model": FREE}
    r = client.put("/api/admin/settings/llm", json={"values": values}, headers=ADMIN)
    assert r.status_code == 409 and r.json()["needs"] == ["acknowledge_training"]
    assert _consents(audit) == []
    r = client.put("/api/admin/settings/llm", json={"values": values, "acknowledge_training": True}, headers=ADMIN)
    assert r.status_code == 200 and settings_db.get_value("llm", "compatible_model") == FREE
    [row] = _consents(audit)
    assert FREE in row.content_preview and "openrouter" in row.content_preview and "settings" in row.content_preview


def test_no_consent_row_means_no_choice(client, audit):
    audit.fail = True
    values = {"compatible_provider": "openrouter", "compatible_model": FREE}
    r = client.put("/api/admin/settings/llm", json={"values": values, "acknowledge_training": True}, headers=ADMIN)
    assert r.status_code == 503
    assert settings_db.get_value("llm", "compatible_model") != FREE


def test_no_audit_log_means_no_consent(client, monkeypatch):
    from agents.core.routers import admin

    monkeypatch.setattr(admin, "get_orch", lambda: None)
    monkeypatch.setattr(sg, "_orch", lambda: None, raising=False)
    values = {"compatible_provider": "openrouter", "compatible_model": FREE}
    r = client.put("/api/admin/settings/llm", json={"values": values, "acknowledge_training": True}, headers=ADMIN)
    assert r.status_code == 503


def test_switching_openrouter_to_allow_is_refused_until_acknowledged(client, audit):
    r = client.put("/api/admin/settings/llm", json={"values": {"openrouter_data_collection": "allow"}}, headers=ADMIN)
    assert r.status_code == 409
    r = client.put("/api/admin/settings/llm", json={"values": {"openrouter_data_collection": "allow"}, "acknowledge_training": True}, headers=ADMIN)
    assert r.status_code == 200 and len(_consents(audit)) == 1


def test_an_ordinary_write_is_not_asked_even_with_an_expensive_model_stored(client, store, audit):
    store.put_category("llm", {"claude_model": FABLE})
    r = client.put("/api/admin/settings/llm", json={"values": {"temperature": 0.3}}, headers=ADMIN)
    assert r.status_code == 200 and "guards" not in r.json()
    assert _cost_rows(audit) == [] and _consents(audit) == []


def test_an_invalid_value_is_still_a_422_before_any_guard(client):
    r = client.put("/api/admin/settings/llm", json={"values": {"openrouter_data_collection": "sometimes"}}, headers=ADMIN)
    assert r.status_code == 422


# ── a settings import ───────────────────────────────────────────────────────────

def _import(client, doc):
    return client.post("/api/admin/settings/import", json=doc, headers=ADMIN)


def test_an_import_that_picks_an_expensive_model_is_refused_until_confirmed(client, audit):
    doc = {"settings": {"llm": {"claude_model": FABLE}}}
    dry = _import(client, {**doc, "dry_run": True})
    assert dry.status_code == 200 and [g["guard"] for g in dry.json()["guards"]] == ["cost"]
    r = _import(client, doc)
    assert r.status_code == 409 and r.json()["needs"] == ["confirm_expensive"]
    assert settings_db.get_value("llm", "claude_model") != FABLE
    r = _import(client, {**doc, "confirm_expensive": True})
    assert r.status_code == 200 and settings_db.get_value("llm", "claude_model") == FABLE
    assert len(_cost_rows(audit)) == 1


def test_an_import_acknowledges_training_the_same_way(client, audit):
    doc = {"settings": {"llm": {"compatible_provider": "openrouter", "compatible_model": FREE}}}
    assert _import(client, doc).status_code == 409
    assert _import(client, {**doc, "acknowledge_training": True}).status_code == 200
    assert len(_consents(audit)) == 1


# ── a job's model pin ───────────────────────────────────────────────────────────

class Runner:
    def __init__(self):
        self.armed, self.edits = [], []
        self.store = self
        self.jobs = {}

    def arm(self, **kw):
        self.armed.append(kw)
        job = type("J", (), {"id": "j1", "action": {}, "options": kw.get("options") or {},
                             "as_dict": lambda s: {"id": "j1"}})()
        self.jobs["j1"] = job
        return job, None, "armed"

    def edit(self, job_id, **kw):
        self.edits.append(kw)
        return self.jobs[job_id]

    def get(self, job_id):
        return self.jobs.get(job_id)


@pytest.fixture
def runner(client, monkeypatch):
    from agents.core.routers import jobs

    r = Runner()
    monkeypatch.setattr(jobs, "_runner", lambda: r)
    return r


ASK = {"type": "ask", "prompt": "summarise the day"}


def test_a_job_pinned_to_an_expensive_model_is_refused_until_confirmed(client, runner, audit):
    body = {"name": "digest", "schedule_text": "every day at 7", "action": ASK,
            "options": {"model": FABLE, "provider": "anthropic"}}
    r = client.post("/api/jobs", json=body, headers=ADMIN)
    assert r.status_code == 409 and r.json()["needs"] == ["confirm_expensive"]
    assert runner.armed == []
    r = client.post("/api/jobs", json={**body, "confirm_expensive": True}, headers=ADMIN)
    assert r.status_code == 201 and len(runner.armed) == 1
    assert "confirm_expensive" not in runner.armed[0]                                  # never stored with the job
    assert len(_cost_rows(audit)) == 1


def test_a_job_pinned_to_a_training_tier_needs_the_acknowledgement(client, runner, audit):
    body = {"name": "digest", "schedule_text": "every day at 7", "action": ASK,
            "options": {"model": FREE, "provider": "openrouter"}}
    assert client.post("/api/jobs", json=body, headers=ADMIN).status_code == 409
    assert client.post("/api/jobs", json={**body, "acknowledge_training": True}, headers=ADMIN).status_code == 201
    [row] = _consents(audit)
    assert "job" in row.content_preview


def test_a_job_edit_asks_only_when_the_pin_changes(client, runner, audit):
    body = {"name": "digest", "schedule_text": "every day at 7", "action": ASK,
            "options": {"model": FABLE, "provider": "anthropic"}}
    assert client.post("/api/jobs", json={**body, "confirm_expensive": True}, headers=ADMIN).status_code == 201
    same = client.patch("/api/jobs/j1", json={"name": "digest 2", "options": {"model": FABLE, "provider": "anthropic"}}, headers=ADMIN)
    assert same.status_code == 200                                                      # the pin did not move
    runner.jobs["j1"].options = {"model": "claude-sonnet-4-6", "provider": "anthropic"}
    moved = client.patch("/api/jobs/j1", json={"options": {"model": FABLE, "provider": "anthropic"}}, headers=ADMIN)
    assert moved.status_code == 409 and len(runner.edits) == 1
    ok = client.patch("/api/jobs/j1", json={"options": {"model": FABLE, "provider": "anthropic"}, "confirm_expensive": True}, headers=ADMIN)
    assert ok.status_code == 200 and len(runner.edits) == 2


def test_a_job_without_a_pin_is_never_asked(client, runner):
    body = {"name": "digest", "schedule_text": "every day at 7", "action": ASK}
    assert client.post("/api/jobs", json=body, headers=ADMIN).status_code == 201


# ── nerva config set ────────────────────────────────────────────────────────────

def _cli(argv, monkeypatch, audit):
    from agents.cli import nerva

    monkeypatch.setattr(nerva, "_audit_log", lambda: audit, raising=False)
    out, err = io.StringIO(), io.StringIO()
    code = nerva.main(argv, context=nerva.Context(environ={}, out=out, err=err))
    return code, out.getvalue(), err.getvalue()


def test_the_cli_refuses_an_expensive_model_until_confirmed(store, monkeypatch, audit):
    code, _out, err = _cli(["config", "set", "llm.claude_model", FABLE], monkeypatch, audit)
    assert code != 0 and "$50" in err and "--confirm-expensive" in err
    assert settings_db.get_value("llm", "claude_model") != FABLE
    code, out, _err = _cli(["config", "set", "llm.claude_model", FABLE, "--confirm-expensive"], monkeypatch, audit)
    assert code == 0 and settings_db.get_value("llm", "claude_model") == FABLE
    assert len(_cost_rows(audit)) == 1


def test_the_cli_writes_the_training_consent_before_the_choice(store, monkeypatch, audit):
    store.put_category("llm", {"compatible_provider": "openrouter"})
    code, _out, err = _cli(["config", "set", "llm.compatible_model", FREE], monkeypatch, audit)
    assert code != 0 and "--acknowledge-training" in err
    audit.fail = True
    code, _out, err = _cli(["config", "set", "llm.compatible_model", FREE, "--acknowledge-training"], monkeypatch, audit)
    assert code != 0 and settings_db.get_value("llm", "compatible_model") != FREE
    audit.fail = False
    code, _out, _err = _cli(["config", "set", "llm.compatible_model", FREE, "--acknowledge-training"], monkeypatch, audit)
    assert code == 0 and settings_db.get_value("llm", "compatible_model") == FREE
    [row] = _consents(audit)
    assert "cli" in row.content_preview


def test_the_jobs_cli_passes_the_flags_to_the_hub(monkeypatch):
    from agents.cli import nerva

    sent = []

    class Client:
        def post(self, path, body):
            sent.append((path, body))
            return {"ok": True, "job": {"id": "j1"}, "confirmation": "armed"}

        def request(self, method, path, body=None):
            sent.append((path, body))
            return {"ok": True, "job": {"id": "j1"}}

    ctx = nerva.Context(environ={}, out=io.StringIO(), err=io.StringIO(), client_factory=lambda env: Client())
    nerva.main(["jobs", "create", "--name", "d", "--when", "every day at 7", "--action", '{"type":"ask","prompt":"p"}',
                "--options", '{"model":"claude-fable-5"}', "--confirm-expensive", "--acknowledge-training"], context=ctx)
    nerva.main(["jobs", "edit", "j1", "--options", '{"model":"claude-fable-5"}', "--confirm-expensive"], context=ctx)
    assert sent[0][1]["confirm_expensive"] is True and sent[0][1]["acknowledge_training"] is True
    assert sent[1][1]["confirm_expensive"] is True and "acknowledge_training" not in sent[1][1]


def test_the_jobs_cli_names_the_flags_when_the_hub_refuses(monkeypatch):
    from agents.cli import nerva
    from agents.cli.client import HubError

    class Client:
        def post(self, path, body):
            raise HubError(409, "claude-fable-5 costs $10/M input and $50/M output tokens")

    err = io.StringIO()
    ctx = nerva.Context(environ={}, out=io.StringIO(), err=err, client_factory=lambda env: Client())
    code = nerva.main(["jobs", "create", "--name", "d", "--when", "every day at 7", "--action", '{"type":"ask","prompt":"p"}',
                       "--options", '{"model":"claude-fable-5"}'], context=ctx)
    assert code != 0 and "$50" in err.getvalue() and "--confirm-expensive" in err.getvalue()


# ── the settings row ────────────────────────────────────────────────────────────

def test_the_line_is_a_declared_non_negative_number(store):
    spec = settings_db._SPEC[("llm", "cost_confirm_usd_per_mtok")]
    assert spec["value"] == 40 and spec["kind"] == "number"
    assert settings_db.validate_category("llm", {"cost_confirm_usd_per_mtok": -1})
    assert settings_db.validate_category("llm", {"cost_confirm_usd_per_mtok": 12.5}) == []
