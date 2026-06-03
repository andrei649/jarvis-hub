"""Tests for H14.2 — Memory Evaluation Harness."""
import sys
from pathlib import Path

from fastapi.testclient import TestClient

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))

from agents.core.memory.eval import (
    ABILITIES, DEFAULT_CORPUS, MemoryEvalCase,
    score_answer, keyword_answer, run_eval,
)


# ── scoring ──────────────────────────────────────────────────────────────────

def test_score_answer_substring():
    c = MemoryEvalCase("x", "extraction", [], "q", expected=["Cosmina"])
    assert score_answer(c, "Her name is Cosmina.") is True
    assert score_answer(c, "Her name is Maria.") is False


def test_score_abstention():
    c = MemoryEvalCase("x", "abstention", [], "q", abstain=True)
    assert score_answer(c, "I don't know.") is True
    assert score_answer(c, "It's a tabby cat.") is False    # hallucinated → fail


def test_score_abstaining_when_answer_expected_fails():
    c = MemoryEvalCase("x", "extraction", [], "q", expected=["Cosmina"])
    assert score_answer(c, "I don't know.") is False


# ── corpus integrity ─────────────────────────────────────────────────────────

def test_corpus_covers_all_abilities():
    seen = {c.ability for c in DEFAULT_CORPUS}
    assert seen == set(ABILITIES)
    # every non-abstention case has expected substrings
    for c in DEFAULT_CORPUS:
        assert c.abstain or c.expected


# ── baseline answerer ────────────────────────────────────────────────────────

def test_keyword_answer_abstains_without_overlap():
    assert "know" in keyword_answer("What is your blood type?",
                                    ["The server is Hephaestus."]).lower()


def test_keyword_answer_recency_tiebreak():
    ans = keyword_answer("What car does Andrei drive now?",
                         ["Andrei's car is a BMW.",
                          "Andrei sold the BMW and now drives a Tesla."])
    assert "Tesla" in ans


# ── harness aggregation ──────────────────────────────────────────────────────

def test_run_eval_perfect_oracle():
    def oracle(question, facts):
        # find the case by question and return its expected/abstain answer
        for c in DEFAULT_CORPUS:
            if c.question == question:
                return "I don't know." if c.abstain else c.expected[0]
        return ""
    report = run_eval(oracle)
    assert report["overall"]["score"] == 1.0
    for ability in ABILITIES:
        assert report["by_ability"][ability]["score"] == 1.0


def test_run_eval_always_abstain():
    report = run_eval(lambda q, f: "I don't know.")
    # only the abstention cases pass
    assert report["by_ability"]["abstention"]["score"] == 1.0
    assert report["by_ability"]["extraction"]["score"] == 0.0
    assert 0.0 < report["overall"]["score"] < 1.0


def test_run_eval_baseline_runs():
    report = run_eval(keyword_answer)
    assert report["overall"]["n"] == len(DEFAULT_CORPUS)
    # baseline should at least handle extraction + abstention
    assert report["by_ability"]["extraction"]["score"] >= 0.5


# ── endpoints ────────────────────────────────────────────────────────────────

def test_eval_endpoints():
    from agents import web
    with TestClient(web.app) as c:
        corpus = c.get("/api/memory/eval/corpus")
        assert corpus.status_code == 200
        assert corpus.json()["abilities"] == ABILITIES
        run = c.post("/api/memory/eval/run")
        assert run.status_code == 200
        assert "overall" in run.json() and "by_ability" in run.json()
