"""H11.3 — SFT data-prep (the testable, no-GPU part)."""
import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from training.prepare_data import (
    trace_to_sft, build_sft_dataset, to_jsonl, trace_score, load_traces,
)


def test_trace_to_sft():
    ex = trace_to_sft({"input": "hi", "output": "hello", "system": "be nice"})
    assert ex["messages"] == [
        {"role": "system", "content": "be nice"},
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]
    assert trace_to_sft({"input": "x"}) is None        # incomplete → dropped


def test_learning_log_format_task_response_success():
    # H7.11 learning logs use task/response/success
    ex = trace_to_sft({"task": "route this", "response": "use tool X"})
    assert ex["messages"][-2]["content"] == "route this"
    assert ex["messages"][-1]["content"] == "use tool X"
    assert trace_score({"success": True}) == 1.0
    assert trace_score({"success": False}) == 0.0
    assert trace_score({"reward": 0.7}) == 0.7
    assert trace_score({}) == 1.0


def test_build_sft_dataset_filters_by_score():
    traces = [{"input": "a", "output": "A", "score": 0.9},
              {"input": "b", "output": "B", "score": 0.2},
              {"prompt": "c", "response": "C"}]            # no score → kept (default 1.0)
    out = build_sft_dataset(traces, min_score=0.5)
    contents = [m[1]["content"] for m in [(e, e["messages"][0]) for e in out]]
    assert contents == ["a", "c"]                          # 'b' filtered out


def test_build_filters_failed_learning_records():
    traces = [{"task": "good", "response": "R", "success": True},
              {"task": "bad", "response": "R", "success": False}]
    out = build_sft_dataset(traces, min_score=1.0)
    assert len(out) == 1 and out[0]["messages"][-2]["content"] == "good"


def test_load_traces_skips_bad_lines(tmp_path):
    p = tmp_path / "t.jsonl"
    p.write_text('{"task": "a", "response": "A"}\n\nnot json\n{"task":"b","response":"B"}\n')
    rows = load_traces([str(p)])
    assert [r["task"] for r in rows] == ["a", "b"]


def test_to_jsonl_roundtrips():
    examples = build_sft_dataset([{"input": "a", "output": "A"}])
    lines = to_jsonl(examples).splitlines()
    assert json.loads(lines[0])["messages"][-1]["content"] == "A"
