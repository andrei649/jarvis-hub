"""Local pilot prerequisites use existing hub metadata; no generation or tool call."""

import copy
import json
import urllib.error

import pytest

from scripts import doctor


def _answers():
    return {
        "/readyz": {"ready": True},
        "/api/models/local": {
            "backend": "ollama", "configured_model": "synthetic-model",
            "models": [{"provider": "ollama", "id": "synthetic-model",
                        "configured": True, "available": True, "resident": True}],
        },
        "/api/admin/settings/llm": {"llm": [{"key": "cloud_fallback", "value": "never"}]},
        "/api/mcp/server/rpc": {
            "jsonrpc": "2.0", "id": 1, "result": {"tools": [{
                "name": "route_memory_search", "annotations": {"readOnlyHint": True},
                "inputSchema": {"type": "object", "properties": {"q": {"type": "string"}},
                                "required": ["q"]},
            }]},
        },
    }


class Response:
    status = 200

    def __init__(self, value):
        self.raw = json.dumps(value).encode()

    def read(self, limit=-1):
        return self.raw if limit < 0 else self.raw[:limit]

    def close(self):
        pass


def _open(answers, seen):
    def open_(request, timeout):
        from urllib.parse import urlsplit
        url = getattr(request, "full_url", request)
        path = urlsplit(url).path
        seen.append(request)
        assert timeout <= 10
        value = answers[path]  # Fail if any unplanned endpoint is contacted.
        if isinstance(value, Exception):
            raise value
        return Response(value)
    return open_


def _run(tmp_path, answers=None, env=None):
    seen = []
    root = tmp_path / "untouched"
    report = doctor.run_local_pilot(root, env=env or {},
                                    opener=_open(answers or _answers(), seen))
    assert not root.exists()  # No install/data-root probe or settings bootstrap.
    return report, seen


@pytest.mark.parametrize("provider", ["ollama", "lm-studio"])
def test_local_pilot_reuses_metadata_without_generating_or_querying_memory(tmp_path, provider):
    answers = _answers()
    answers["/api/models/local"]["backend"] = provider
    answers["/api/models/local"]["models"][0]["provider"] = provider
    report, seen = _run(tmp_path, answers, env={"JARVIS_ADMIN_TOKEN": "synthetic-admin",
                                               "JARVIS_USER_TOKEN": "synthetic-user"})
    assert report.ok is True
    assert len(seen) == 4
    requests = [request for request in seen if hasattr(request, "get_method")]
    assert [request.get_method() for request in requests] == ["GET", "GET", "POST"]
    assert json.loads(requests[-1].data) == {
        "jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {},
    }
    assert requests[0].get_header("X-admin-token") == "synthetic-admin"
    assert requests[1].get_header("X-admin-token") == "synthetic-admin"
    assert requests[-1].get_header("X-user-token") == "synthetic-user"
    text = doctor.format_local_pilot(report)
    assert "synthetic-model" in text and provider in text
    assert "inference: not tested" in text and "memory read: not tested" in text
    assert "explicit cloud agents" in text
    assert "authentication audit" in text
    assert "synthetic-admin" not in text and "synthetic-user" not in text


def test_catalog_check_accepts_the_real_hub_memory_descriptor(tmp_path):
    from agents.core.mcp.route_tools import build_route_tools
    from agents.core.mcp.server import JarvisMCPServer
    from agents.core.routers import memory_kg

    async def unexpected(*args, **kwargs):
        pytest.fail("catalog inspection must not execute a tool or agent")

    hub = JarvisMCPServer(unexpected, {}, route_tools=build_route_tools({
        "memory_search": memory_kg.memory_search,
    }))
    answers = _answers()
    answers["/api/mcp/server/rpc"]["result"]["tools"] = hub.list_tools()
    report, _ = _run(tmp_path, answers)
    assert report.by_name()["mcp_memory"].status == doctor.OK


@pytest.mark.parametrize("key,value", [
    ("resident", False), ("resident", None), ("resident", "true"),
    ("available", False), ("available", None), ("configured", False),
    ("provider", "lm-studio"), ("id", "another-model"),
])
def test_a_different_or_unproven_local_model_never_passes(tmp_path, key, value):
    answers = _answers()
    answers["/api/models/local"]["models"][0][key] = value
    report, _ = _run(tmp_path, answers)
    assert report.ok is False
    assert report.by_name()["local_model"].status == doctor.FAIL
    assert report.by_name()["mcp_memory"].status == doctor.OK


@pytest.mark.parametrize("fallback", ["on-demand", "always", None, True])
def test_fallback_must_be_known_and_disabled_for_this_pilot(tmp_path, fallback):
    answers = _answers()
    answers["/api/admin/settings/llm"]["llm"][0]["value"] = fallback
    report, _ = _run(tmp_path, answers)
    assert report.ok is False
    assert report.by_name()["fallback_policy"].status == doctor.FAIL


@pytest.mark.parametrize("hint", [False, None, "true", 1])
def test_memory_catalog_requires_literal_read_permission(tmp_path, hint):
    answers = _answers()
    answers["/api/mcp/server/rpc"]["result"]["tools"][0]["annotations"]["readOnlyHint"] = hint
    report, _ = _run(tmp_path, answers)
    assert report.ok is False
    assert report.by_name()["mcp_memory"].reason == "memory_read_hint_missing"


@pytest.mark.parametrize("change", ["missing", "duplicate", "query_type", "required", "rpc_id", "error"])
def test_incompatible_memory_catalog_is_not_presented_as_ready(tmp_path, change):
    answers = _answers()
    rpc = answers["/api/mcp/server/rpc"]
    tool = rpc["result"]["tools"][0]
    if change == "missing":
        rpc["result"]["tools"] = []
    elif change == "duplicate":
        rpc["result"]["tools"].append(copy.deepcopy(tool))
    elif change == "query_type":
        tool["inputSchema"]["properties"]["q"]["type"] = "number"
    elif change == "required":
        tool["inputSchema"]["required"].append("unexpected")
    elif change == "rpc_id":
        rpc["id"] = 2
    else:
        rpc["error"] = {"message": "synthetic-private-error"}
    report, _ = _run(tmp_path, answers)
    assert report.ok is False
    assert report.by_name()["mcp_memory"].status == doctor.FAIL
    assert "synthetic-private-error" not in doctor.format_local_pilot(report)


@pytest.mark.parametrize("url", ["https://remote.invalid", "file:///tmp/settings",
                                "http://user:synthetic-secret@127.0.0.1:8080",
                                "http://127.0.0.1:8080/?token=synthetic-secret"])
def test_nonlocal_or_credential_bearing_hub_is_refused_before_network(tmp_path, url):
    report, seen = _run(tmp_path, env={"NERVA_HUB_URL": url})
    assert report.ok is False and seen == []
    assert "synthetic-secret" not in doctor.format_local_pilot(report)


def test_offline_hub_skips_dependent_checks_without_writing(tmp_path):
    answers = _answers()
    answers["/readyz"] = urllib.error.URLError("offline")
    report, seen = _run(tmp_path, answers)
    assert report.ok is False and len(seen) == 1
    assert [c.status for c in report.checks] == [doctor.FAIL, doctor.SKIP, doctor.SKIP, doctor.SKIP]


def test_settings_refusal_remains_unknown_and_other_checks_continue(tmp_path):
    answers = _answers()
    answers["/api/admin/settings/llm"] = urllib.error.HTTPError(
        "http://127.0.0.1", 403, "synthetic-private-error", {}, None)
    report, seen = _run(tmp_path, answers)
    assert report.ok is False and len(seen) == 4
    assert report.by_name()["fallback_policy"].reason == "http_status:403"
    assert "synthetic-private-error" not in json.dumps(report.to_dict())


def test_pilot_cli_labels_unexecuted_acceptance_and_returns_failure(tmp_path, monkeypatch, capsys):
    answers = _answers()
    answers["/api/models/local"]["models"] = []
    report, _ = _run(tmp_path, answers)
    monkeypatch.setattr(doctor, "run_local_pilot", lambda *a, **kw: report)
    assert doctor.main(["--local-pilot", "--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["mode"] == "local_pilot"
    assert payload["inference_tested"] is False
    assert payload["memory_read_tested"] is False
    assert payload["agent_routing_tested"] is False


def test_pilot_and_smoke_cannot_be_combined():
    with pytest.raises(SystemExit) as error:
        doctor.main(["--local-pilot", "--smoke"])
    assert error.value.code == 2
