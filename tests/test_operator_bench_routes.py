"""The operator-benchmark routes: read the S1 result, and know when it went stale.

Two user-guarded reads and, deliberately, no route that RUNS the pack — a
benchmark run is minutes of work whose live half needs a real desktop in front of
a real person, so an endpoint that kicked it off would either block for minutes or
lie about having finished.

The rest pin the honest-reporting properties: never-run is reported as never-run
rather than as a zero score, and a result measured against a different set of
questions is marked stale rather than served as though it answered these ones.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "agents"))

from agents.core.observability.operator_benchmark import (  # noqa: E402
    run_pack,
    save_report,
)
from agents.core.observability.operator_pack import (  # noqa: E402
    NEGATIVE_CONTROLS,
    TASKS,
    scored_tasks,
)
from agents.core.routers import operator_bench as bench_routes  # noqa: E402
from agents.core.routers._deps import user_guard  # noqa: E402


def _app():
    app = FastAPI()
    app.include_router(bench_routes.router)
    return app


@pytest.fixture
def client():
    app = _app()
    app.dependency_overrides[user_guard] = lambda: None
    return TestClient(app)


@pytest.fixture
def store(tmp_path, monkeypatch):
    """Point the loader at a temp store so no test reads the real data root."""
    path = tmp_path / "bench.json"
    real = bench_routes.load_report
    monkeypatch.setattr(
        bench_routes, "load_report",
        lambda _p=None, **kw: real(path, **kw),
    )
    return path


# ── the surface, and what it deliberately omits ──────────────────────────────

def test_there_is_no_route_that_runs_the_benchmark(client):
    """Running it is a CLI job. An endpoint would block for minutes or lie."""
    from tests._route_introspect import iter_effective_routes

    paths = {
        (m, r.path)
        for r in iter_effective_routes(_app())
        for m in sorted(getattr(r, "methods", ()) or ())
        if m not in {"HEAD", "OPTIONS"} and r.path.startswith("/api/")
    }
    assert paths == {
        ("GET", "/api/operator/benchmark"),
        ("GET", "/api/operator/benchmark/pack"),
    }


def test_both_routes_are_user_guarded():
    from tests._route_introspect import iter_effective_routes

    guarded = {}
    for route in iter_effective_routes(_app()):
        dep = getattr(route, "dependant", None)
        if not getattr(route, "methods", None) or dep is None:
            continue
        names, stack = set(), list(getattr(dep, "dependencies", []))
        while stack:
            d = stack.pop()
            call = getattr(d, "call", None)
            if call is not None:
                names.add(getattr(call, "__name__", ""))
            stack.extend(getattr(d, "dependencies", []))
        guarded[route.path] = names
    assert guarded == {
        "/api/operator/benchmark": {"user_guard"},
        "/api/operator/benchmark/pack": {"user_guard"},
    }


def test_routes_refuse_without_a_user_token():
    app = _app()

    async def _deny(request: Request):
        raise HTTPException(status_code=401, detail="user token required")

    app.dependency_overrides[user_guard] = _deny
    c = TestClient(app)
    assert c.get("/api/operator/benchmark").status_code == 401
    assert c.get("/api/operator/benchmark/pack").status_code == 401


# ── never run is not a zero score ────────────────────────────────────────────

def test_never_run_is_reported_as_never_run(client, store):
    """"Nobody measured" and "measured and scored nothing" are different claims."""
    body = client.get("/api/operator/benchmark").json()
    assert body["recorded"] is False
    assert body["reason"] == "the operator benchmark has not been run on this install"
    assert body["how"] == "python scripts/operator_bench.py"
    assert "hermetic" not in body


async def test_a_recorded_run_is_served_with_both_columns(client, store):
    save_report(await run_pack(scored_tasks()), store)
    body = client.get("/api/operator/benchmark").json()
    assert body["recorded"] is True
    assert body["hermetic"]["passed"] == 19
    assert body["live"]["rate"] is None
    assert body["stale"] is False
    assert "hermetic" in body["headline"]


async def test_a_result_measured_against_other_questions_is_marked_stale(
    client, store, monkeypatch
):
    save_report(await run_pack(scored_tasks()), store)
    # the pack the loader compares against changes underneath the stored run
    from agents.core.observability.operator_benchmark import Task

    monkeypatch.setattr(
        bench_routes, "scored_tasks",
        lambda: (*scored_tasks(), Task(id="new", surface="files", describe="d",
                                       live_twin="t")),
    )
    assert client.get("/api/operator/benchmark").json()["stale"] is True


def test_the_read_is_not_cached(client, store):
    assert client.get("/api/operator/benchmark").headers["cache-control"].startswith("no-cache")


# ── the questions are readable as data ───────────────────────────────────────

def test_the_pack_route_serves_the_questions_and_their_live_twins(client):
    body = client.get("/api/operator/benchmark/pack").json()
    assert len(body["tasks"]) == len(TASKS) == 20
    assert body["scored"] == 19
    first = body["tasks"][0]
    assert first["id"] and first["surface"] and first["describe"]
    assert first["live_twin"]


def test_the_negative_control_is_labelled_so_its_failure_never_reads_as_a_defect(client):
    body = client.get("/api/operator/benchmark/pack").json()
    flagged = [t["id"] for t in body["tasks"] if t["negative_control"]]
    assert set(flagged) == NEGATIVE_CONTROLS
    assert body["negative_controls"] == sorted(NEGATIVE_CONTROLS)


def test_the_pack_route_is_pure_and_needs_no_stored_run(client, tmp_path):
    body = client.get("/api/operator/benchmark/pack").json()
    assert body["ok"] is True
    assert json.dumps(body)  # serialisable, no live objects leaked
