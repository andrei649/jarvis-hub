"""Pure file-RPC primitives for future execute_code remote transports."""

import pytest

from agents.core.environments.file_rpc import (
    FileRPCRequest,
    FileRPCStore,
    ToolCallLimitExceeded,
    format_sequence,
)


def test_format_sequence_is_zero_padded_and_rejects_invalid_values():
    assert format_sequence(1) == "000001"
    assert format_sequence(42) == "000042"

    with pytest.raises(ValueError):
        format_sequence(0)


def test_request_round_trips_utf8_json_atomically(tmp_path):
    store = FileRPCStore(tmp_path)
    request = FileRPCRequest(
        seq=1,
        tool="terminal",
        args={"command": "echo 'Bucure\u0219ti \u2192 ok'"},
    )

    path = store.write_request(request)

    assert path.name == "req_000001.json"
    assert not list(tmp_path.glob("*.tmp"))
    assert store.read_request(1) == request


def test_pending_requests_are_sorted_and_malformed_files_are_ignored(tmp_path):
    store = FileRPCStore(tmp_path)
    store.write_request(FileRPCRequest(seq=2, tool="read_file", args={"path": "b"}))
    store.write_request(FileRPCRequest(seq=1, tool="read_file", args={"path": "a"}))
    (tmp_path / "req_broken.json").write_text("{not-json", encoding="utf-8")
    (tmp_path / "req_000003.json").write_text('{"seq":3,"tool":"","args":{}}', encoding="utf-8")

    pending = store.pending_requests()

    assert [request.seq for request in pending] == [1, 2]


def test_response_round_trips_and_is_removed_after_read(tmp_path):
    store = FileRPCStore(tmp_path)
    store.write_response(7, {"ok": True, "result": {"text": "em dash \u2014 arrow \u2192"}})

    assert store.read_response(7) == {"ok": True, "result": {"text": "em dash \u2014 arrow \u2192"}}
    assert store.read_response(7) is None


def test_tool_call_limit_is_enforced_before_writing_request(tmp_path):
    store = FileRPCStore(tmp_path, max_tool_calls=2)
    store.write_request(FileRPCRequest(seq=1, tool="one", args={}))
    store.write_request(FileRPCRequest(seq=2, tool="two", args={}))

    with pytest.raises(ToolCallLimitExceeded):
        store.write_request(FileRPCRequest(seq=3, tool="three", args={}))

    assert not (tmp_path / "req_000003.json").exists()
