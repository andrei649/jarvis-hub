"""Tests for H9.3b — Dataset Regression Tracking.

Covers versioned dataset persistence, running a dataset through a fake runner
(offline), the run log, and run-to-run regression comparison + the endpoints.
"""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))

from agents.core.observability.datasets import DatasetStore


# ── dataset versioning ──────────────────────────────────────────────────────

def test_save_and_load_versions(tmp_path):
    store = DatasetStore(root=tmp_path)
    v1 = store.save_version("smoke", [{"name": "a", "prompt": "hi", "expect_contains": "x"}])
    v2 = store.save_version("smoke", [
        {"name": "a", "prompt": "hi", "expect_contains": "x"},
        {"name": "b", "prompt": "yo", "expect_contains": "y"},
    ])
    assert v1 == 1 and v2 == 2
    assert store.versions("smoke") == [1, 2]
    assert store.latest_version("smoke") == 2
    assert len(store.load("smoke")) == 2          # latest
    assert len(store.load("smoke", version=1)) == 1
    assert store.load("missing") == []


def test_list_datasets(tmp_path):
    store = DatasetStore(root=tmp_path)
    store.save_version("d1", [{"name": "a", "prompt": "p", "expect_contains": "p"}])
    listing = store.list_datasets()
    assert len(listing) == 1
    assert listing[0]["name"] == "d1"
    assert listing[0]["latest_version"] == 1
    assert listing[0]["cases"] == 1


# ── running + run log ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_run_dataset_records_run(tmp_path):
    store = DatasetStore(root=tmp_path)
    store.save_version("qa", [
        {"name": "greet", "prompt": "say hello", "expect_contains": "hello"},
        {"name": "math", "prompt": "2+2", "expect_contains": "four"},
    ])

    async def runner(prompt: str) -> str:
        # passes "greet" (echoes prompt containing 'hello'), fails "math"
        return f"echo: {prompt}"

    result = await store.run_dataset("qa", runner)
    assert result["total"] == 2
    assert result["passed"] == 1          # only greet passes
    assert 0.0 < result["score"] < 1.0
    runs = store.runs("qa")
    assert len(runs) == 1
    assert runs[0]["run_id"] == result["run_id"]


@pytest.mark.asyncio
async def test_run_missing_dataset(tmp_path):
    store = DatasetStore(root=tmp_path)
    result = await store.run_dataset("nope", lambda p: None)  # type: ignore[arg-type]
    assert "error" in result


# ── regression comparison ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_compare_detects_regression(tmp_path):
    store = DatasetStore(root=tmp_path)
    store.save_version("reg", [
        {"name": "k1", "prompt": "hello", "expect_contains": "hello"},
        {"name": "k2", "prompt": "world", "expect_contains": "world"},
    ])

    async def good(prompt: str) -> str:
        return prompt                      # both contain their expected substr

    async def broken(prompt: str) -> str:
        return "world" if prompt == "world" else "???"   # k1 now fails

    base = await store.run_dataset("reg", good)
    cand = await store.run_dataset("reg", broken)

    cmp = store.compare("reg", base["run_id"], cand["run_id"])
    assert cmp["regression"] is True
    assert "k1" in cmp["regressed"]
    assert cmp["improved"] == []
    assert cmp["score_delta"] < 0


@pytest.mark.asyncio
async def test_compare_detects_improvement(tmp_path):
    store = DatasetStore(root=tmp_path)
    store.save_version("imp", [{"name": "k1", "prompt": "hello", "expect_contains": "hello"}])

    async def bad(prompt: str) -> str:
        return "nope"

    async def fixed(prompt: str) -> str:
        return "hello there"

    a = await store.run_dataset("imp", bad)
    b = await store.run_dataset("imp", fixed)
    cmp = store.compare("imp", a["run_id"], b["run_id"])
    assert cmp["regression"] is False
    assert "k1" in cmp["improved"]
    assert cmp["score_delta"] > 0


def test_compare_unknown_run(tmp_path):
    store = DatasetStore(root=tmp_path)
    store.save_version("x", [{"name": "a", "prompt": "p", "expect_contains": "p"}])
    out = store.compare("x", "deadbeef", "cafebabe")
    assert "error" in out


# ── endpoints ───────────────────────────────────────────────────────────────

def test_dataset_endpoints_shape():
    from agents import web
    with TestClient(web.app) as c:
        resp = c.get("/api/eval/datasets")
        assert resp.status_code == 200
        assert "datasets" in resp.json()
        # run on a non-existent dataset → 404 with error
        resp = c.post("/api/eval/datasets/run", json={"name": "does-not-exist"})
        assert resp.status_code == 404
        assert "error" in resp.json()
