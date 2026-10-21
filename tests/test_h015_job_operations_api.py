"""H015 owner job operations through the real ASGI router and durable store."""

from __future__ import annotations

import io
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from agents import web
from agents.cli.client import HubError
from agents.cli.nerva import EXIT_OK, EXIT_USAGE, Context, main
from agents.core.autonomy.jobs import JobRunner, JobStore, utc_now

ADMIN = {"x-admin-token": "secret"}


@pytest.fixture
def hub(tmp_path, monkeypatch):
    monkeypatch.setattr(web, "ADMIN_TOKEN", "secret")
    store = JobStore(tmp_path / "jobs.db")
    orch = SimpleNamespace()
    orch.jobs = JobRunner(store, orch=orch, scheduler=lambda: None, quiet=lambda: False)
    with TestClient(web.app) as client:
        real = web.orch
        web.orch = orch
        try:
            yield client, store, orch
        finally:
            web.orch = real
    store.close()


def _job(store):
    return store.create(name="daily", schedule_text="every day at 9",
                        action={"type": "ask", "prompt": "report", "deliver": False},
                        options={"continuity": False, "deliver": []})


class _ASGIHub:
    def __init__(self, client):
        self.client = client
        self.calls = []

    def request(self, method, path, body=None):
        self.calls.append((method, path, body))
        response = self.client.request(method, path, headers=ADMIN, json=body)
        if response.status_code >= 400:
            raise HubError(response.status_code, response.json().get("error", "request refused"))
        return response.json()

    def get(self, path):
        return self.request("GET", path)

    def post(self, path, body=None):
        return self.request("POST", path, body or {})


def _cli(client, args):
    out, err = io.StringIO(), io.StringIO()
    hub = _ASGIHub(client)
    ctx = Context(environ={}, out=out, err=err, inp=io.StringIO(), client_factory=lambda _env: hub)
    return main(["jobs", *args], context=ctx), out.getvalue(), err.getvalue(), hub.calls


def test_incident_ack_and_history_survive_delete_with_owner_gate(hub):
    client, store, orch = hub
    job = _job(store)
    store.record_run(job.id, started_at=utc_now(), finished_at=utc_now(), status="ok", summary="done")
    orch.jobs._failed(store.get(job.id), utc_now(), RuntimeError("failed once"))
    assert client.get("/api/jobs/incidents").status_code == 401
    assert client.get("/api/jobs/runs").status_code == 401
    response = client.get("/api/jobs/incidents", headers=ADMIN)
    assert response.status_code == 200
    (incident,) = response.json()["incidents"]
    assert incident["job_id"] == job.id and incident["state"] == "detected"
    assert client.post(f"/api/jobs/incidents/{incident['id']}/ack").status_code == 401
    assert client.post(f"/api/jobs/incidents/{incident['id']}/ack", headers=ADMIN).json()["incident"]["state"] == "closed"
    assert client.post("/api/jobs/incidents/999999/ack", headers=ADMIN).status_code == 404
    assert client.get("/api/jobs/incidents", params={"state": "closed", "job_id": job.id},
                      headers=ADMIN).json()["incidents"][0]["id"] == incident["id"]
    assert client.get("/api/jobs/incidents", params={"state": "bad"}, headers=ADMIN).status_code == 422
    assert client.get("/api/jobs/incidents", params={"limit": 101}, headers=ADMIN).status_code == 422
    assert client.delete(f"/api/jobs/{job.id}", headers=ADMIN).status_code == 200
    assert client.get("/api/jobs/runs", params={"job_id": job.id}, headers=ADMIN).json()["runs"]
    assert client.get(f"/api/jobs/{job.id}/runs", headers=ADMIN).json()["runs"]
    assert client.get("/api/jobs/incidents", params={"job_id": job.id}, headers=ADMIN).json()["incidents"][0]["state"] == "closed"
    reopened = JobStore(store._path)
    try:
        orch.jobs = JobRunner(reopened, orch=orch, scheduler=lambda: None, quiet=lambda: False)
        assert client.get(f"/api/jobs/{job.id}/runs", headers=ADMIN).json()["runs"]
        assert client.get("/api/jobs/incidents", params={"job_id": job.id},
                          headers=ADMIN).json()["incidents"][0]["state"] == "closed"
    finally:
        reopened.close()


def test_kv_query_key_roundtrip_bounds_and_legacy_note(hub):
    client, store, _orch = hub
    job = _job(store)
    url = f"/api/jobs/{job.id}/notepad/keys"
    assert client.get(url).status_code == 401
    assert client.put(url, json={"key": "section/α", "value": "first"}).status_code == 401
    assert client.put(url, headers=ADMIN, json={"key": "section/α", "value": "first"}).status_code == 200
    assert client.put(url, headers=ADMIN, json={"key": "other", "value": "second"}).status_code == 200
    assert [row["key"] for row in client.get(url, headers=ADMIN).json()["entries"]] == ["other", "section/α"]
    assert client.get(url, params={"key": "section/α"}, headers=ADMIN).json()["entry"]["value"] == "first"
    assert client.get(url, params={"key": "missing"}, headers=ADMIN).status_code == 404
    assert client.put(url, headers=ADMIN, json={"key": "x", "value": "z" * (16 * 1024 + 1)}).status_code == 422
    assert client.put(url, headers=ADMIN, json={"key": "x", "value": "ok", "extra": True}).status_code == 422
    assert client.put(f"/api/jobs/{job.id}/notepad", headers=ADMIN, json={"text": "model output"}).status_code == 200
    assert store.get(job.id).notepad == "model output"
    assert client.delete(url, params={"key": "section/α"}, headers=ADMIN).status_code == 200
    assert client.delete(url, params={"key": "section/α"}, headers=ADMIN).status_code == 404
    assert client.delete(url, headers=ADMIN).status_code == 422
    assert client.delete(f"/api/jobs/{job.id}", headers=ADMIN).status_code == 200
    assert client.get(url, headers=ADMIN).status_code == 404


def test_continuity_partial_edit_validates_shape_and_merges_latest_options(hub):
    client, store, _orch = hub
    job = _job(store)
    path = f"/api/jobs/{job.id}"
    assert client.patch(path, headers=ADMIN, json={"options": {"deliver": []},
                                                   "continuity": True}).status_code == 422
    assert client.patch(path, headers=ADMIN, json={"continuity": "true"}).status_code == 422
    store.update(job.id, options={"continuity": False, "deliver": [], "repeat": 3})
    response = client.patch(path, headers=ADMIN, json={"continuity": True, "name": "renamed"})
    assert response.status_code == 200 and response.json()["job"]["name"] == "renamed"
    assert store.get(job.id).options == {"continuity": True, "deliver": [], "repeat": 3}


def test_new_operations_require_runner(hub):
    client, _store, orch = hub
    orch.jobs = None
    for method, url in [("get", "/api/jobs/incidents"), ("get", "/api/jobs/runs"),
                        ("get", "/api/jobs/x/notepad/keys"),
                        ("post", "/api/jobs/incidents/1/ack")]:
        assert getattr(client, method)(url, headers=ADMIN).status_code == 503


def test_cli_operations_use_real_api_and_preserve_unrelated_options(hub):
    client, store, orch = hub
    job = _job(store)
    old = store.get(job.id).options
    assert old["continuity"] is False and old["deliver"] == []
    code, _out, _err, calls = _cli(client, ["edit", job.id, "--continuity"])
    assert code == EXIT_OK and calls == [("PATCH", f"/api/jobs/{job.id}", {"continuity": True})]
    assert store.get(job.id).options == {**old, "continuity": True}
    code, _out, _err, _calls = _cli(client, ["edit", job.id, "--options", '{"continuity":false}'])
    assert code == EXIT_OK and store.get(job.id).options == {"continuity": False}

    assert _cli(client, ["notepad", job.id, "set", "part/α", "one"])[0] == EXIT_OK
    code, out, _err, _calls = _cli(client, ["notepad", job.id, "get", "part/α"])
    assert code == EXIT_OK and "one" in out
    assert _cli(client, ["notepad", job.id, "list"])[0] == EXIT_OK
    assert _cli(client, ["notepad", job.id, "--text", "legacy"])[0] == EXIT_OK
    assert store.get(job.id).notepad == "legacy" and store.notepad_kv.get(job.id, "part/α") == "one"
    assert _cli(client, ["notepad", job.id, "set", "x", "y", "--text", "wrong"])[0] == EXIT_USAGE
    assert _cli(client, ["notepad", job.id, "delete", "part/α"])[0] == EXIT_OK

    orch.jobs._failed(store.get(job.id), utc_now(), RuntimeError("retry later"))
    code, out, _err, _calls = _cli(client, ["incidents", "list", "--job-id", job.id])
    assert code == EXIT_OK and "retry later" in out
    incident = store.incidents.list(job_id=job.id)[0]
    assert _cli(client, ["incidents", "ack", str(incident["id"])])[0] == EXIT_OK
    assert store.incidents.list(job_id=job.id)[0]["state"] == "closed"
    assert store.delete(job.id)
    code, out, _err, _calls = _cli(client, ["runs", job.id, "--limit", "2"])
    assert code == EXIT_OK and "retry later" in out


def test_cli_continuity_create_and_usage_refusals_do_not_change_jobs(hub):
    client, store, _orch = hub
    code, _out, _err, _calls = _cli(client, ["create", "--name", "brief", "--when", "every day at 9",
                                      "--action", '{"type":"ask","prompt":"brief"}',
                                      "--no-continuity", "--options", '{"deliver":[]}'])
    assert code == EXIT_OK
    (created,) = store.list()
    assert created.options == {"deliver": [], "continuity": False}
    for args in (["incidents", "ack"], ["incidents", "list", "2"],
                 ["incidents", "list", "--limit", "101"],
                 ["runs", "--limit", "0"], ["notepad", created.id, "get"],
                 ["notepad", created.id, "set", "key"],
                 ["notepad", created.id, "delete", "key", "extra"],
                 ["notepad", created.id, "set", "k", "v", "--text", "legacy"]):
        code, _out, err, calls = _cli(client, list(args))
        assert code == EXIT_USAGE and err and calls == [], args
    code, _out, _err, calls = _cli(client, ["edit", created.id, "--continuity", "--no-continuity"])
    assert code == EXIT_USAGE and calls == []
    assert store.get(created.id).notepad == "" and store.notepad_kv.list(created.id) == []


def test_cli_new_user_text_is_terminal_safe_and_json_still_structured(hub):
    client, store, orch = hub
    job = _job(store)
    store.notepad_kv.set(job.id, "safe", "line\n\u202eoverride")
    orch.jobs._failed(store.get(job.id), utc_now(), RuntimeError("bad\n\u202erun"))
    for args in (["notepad", job.id, "list"], ["notepad", job.id, "get", "safe"],
                 ["incidents"], ["runs", job.id]):
        code, out, _err, _calls = _cli(client, list(args))
        assert code == EXIT_OK and "\u202e" not in out and "\n\n" not in out
    code, out, _err, _calls = _cli(client, ["notepad", job.id, "get", "safe", "--json"])
    assert code == EXIT_OK and "\\u202e" in out and "\u202e" not in out


def test_cli_notepad_get_returns_entire_bounded_multiline_value(hub):
    client, store, _orch = hub
    job = _job(store)
    value = "A" * 300 + "\n" + "B" * 300 + "\n"
    store.notepad_kv.set(job.id, "long", value)
    code, out, err, _calls = _cli(client, ["notepad", job.id, "get", "long"])
    assert (code, out, err) == (EXIT_OK, value, "")
