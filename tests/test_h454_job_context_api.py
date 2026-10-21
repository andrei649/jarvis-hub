"""H454 owner job context configuration through the guarded API and CLI."""

from __future__ import annotations

import io

import pytest

from agents.cli.nerva import EXIT_OK, EXIT_USAGE, Context, main
from agents.core.autonomy.jobs import JobStore
from tests.test_h015_job_operations_api import ADMIN, _cli, _job, hub  # noqa: F401


def test_context_patch_is_guarded_strict_and_preserves_other_options(hub):
    client, store, _orch = hub
    source = _job(store)
    destination = _job(store)
    path = f"/api/jobs/{destination.id}"
    original = store.get(destination.id).options

    assert client.patch(path, json={"context_from": source.id}).status_code == 401
    for invalid in (17, True, [source.id, 17], {"job": source.id}):
        assert client.patch(path, headers=ADMIN, json={"context_from": invalid}).status_code == 422
    assert client.patch(path, headers=ADMIN, json={
        "options": {"deliver": []}, "context_from": [],
    }).status_code == 422
    assert client.patch(path, headers=ADMIN, json={
        "options": {"deliver": []}, "continuity": False,
    }).status_code == 422
    assert store.get(destination.id).options == original

    response = client.patch(path, headers=ADMIN, json={
        "context_from": [source.id.upper(), "SELF"], "continuity": True,
        "name": "with context",
    })
    assert response.status_code == 200
    assert response.json()["job"]["name"] == "with context"
    assert store.get(destination.id).options == {
        **original, "context_from": [source.id, "self"], "continuity": True,
    }
    assert client.patch(path, headers=ADMIN, json={
        "context_from": None, "name": "same context",
    }).status_code == 200
    assert store.get(destination.id).options["context_from"] == [source.id, "self"]
    assert client.patch(path, headers=ADMIN, json={"context_from": source.id.upper()}).status_code == 200
    assert store.get(destination.id).options["context_from"] == [source.id]

    store.update(destination.id, options={**store.get(destination.id).options, "repeat": 3})
    response = client.patch(path, headers=ADMIN, json={"context_from": []})
    assert response.status_code == 200
    assert store.get(destination.id).options == {
        **original, "continuity": True, "context_from": [], "repeat": 3,
    }
    reopened = JobStore(store._path)
    try:
        assert reopened.get(destination.id).options == store.get(destination.id).options
    finally:
        reopened.close()


def test_cli_create_edit_and_clear_context_use_real_api(hub):
    client, store, _orch = hub
    source = _job(store)
    args = ["create", "--name", "brief", "--when", "every day at 9", "--action",
            '{"type":"ask","prompt":"brief"}']
    code, _out, _err, calls = _cli(client, [*args, "--options", '{"deliver":[],"repeat":3}',
                                          "--context-from", source.id.upper(),
                                          "--context-from", "SELF", "--continuity"])
    assert code == EXIT_OK
    assert calls[0][0:2] == ("POST", "/api/jobs")
    assert calls[0][2]["options"] == {
        "deliver": [], "repeat": 3, "context_from": [source.id.upper(), "SELF"], "continuity": True,
    }
    created = next(job for job in store.list() if job.id != source.id)
    assert created.options["context_from"] == [source.id, "self"]
    assert created.options["repeat"] == 3

    code, _out, _err, calls = _cli(client, ["edit", created.id, "--context-from", source.id,
                                          "--no-continuity"])
    assert code == EXIT_OK
    assert calls == [("PATCH", f"/api/jobs/{created.id}", {
        "context_from": [source.id], "continuity": False,
    })]
    assert store.get(created.id).options == {
        "deliver": [], "repeat": 3, "context_from": [source.id], "continuity": False,
    }

    code, _out, _err, calls = _cli(client, ["edit", created.id, "--clear-context-from"])
    assert code == EXIT_OK
    assert calls == [("PATCH", f"/api/jobs/{created.id}", {"context_from": []})]
    assert store.get(created.id).options["context_from"] == []
    code, _out, _err, calls = _cli(client, ["edit", created.id, "--options", '{"deliver":[]}',
                                          "--context-from", "self"])
    assert code == EXIT_OK
    assert calls == [("PATCH", f"/api/jobs/{created.id}", {
        "options": {"deliver": [], "context_from": ["self"]},
    })]
    assert store.get(created.id).options == {"deliver": [], "context_from": ["self"]}
    code, _out, _err, calls = _cli(client, ["edit", created.id, "--options",
                                          '{"deliver":[],"context_from":["self"]}',
                                          "--clear-context-from"])
    assert code == EXIT_OK
    assert calls == [("PATCH", f"/api/jobs/{created.id}", {
        "options": {"deliver": [], "context_from": []},
    })]
    assert store.get(created.id).options == {"deliver": [], "context_from": []}


@pytest.mark.parametrize("args", [
    ["--context-from", "self", "--clear-context-from"],
    ["--clear-context-from", "--context-from", "self"],
])
def test_cli_rejects_conflicting_context_flags_before_hub_call(args):
    class NoHub:
        def request(self, *_args, **_kwargs):
            pytest.fail("conflicting flags must be rejected before a hub request")

    output, errors = io.StringIO(), io.StringIO()
    ctx = Context(environ={}, out=output, err=errors, inp=io.StringIO(),
                  client_factory=lambda _env: NoHub())
    assert main(["jobs", "edit", "abc123abc123", *args], context=ctx) == EXIT_USAGE
