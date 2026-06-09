"""H11.3 — SFT data-prep (the testable, no-GPU part)."""
import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from training.prepare_data import trace_to_sft, build_sft_dataset, to_jsonl


def test_trace_to_sft():
    ex = trace_to_sft({"input": "hi", "output": "hello", "system": "be nice"})
    assert ex["messages"] == [
        {"role": "system", "content": "be nice"},
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]
    assert trace_to_sft({"input": "x"}) is None        # incomplete → dropped


def test_build_sft_dataset_filters_by_score():
    traces = [{"input": "a", "output": "A", "score": 0.9},
              {"input": "b", "output": "B", "score": 0.2},
              {"prompt": "c", "response": "C"}]            # no score → kept (default 1.0)
    out = build_sft_dataset(traces, min_score=0.5)
    contents = [m[1]["content"] for m in [(e, e["messages"][0]) for e in out]]
    assert contents == ["a", "c"]                          # 'b' filtered out


def test_to_jsonl_roundtrips():
    examples = build_sft_dataset([{"input": "a", "output": "A"}])
    lines = to_jsonl(examples).splitlines()
    assert json.loads(lines[0])["messages"][-1]["content"] == "A"
