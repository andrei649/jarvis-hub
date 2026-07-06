"""File-based RPC primitives for future remote execute_code transports.

The store here is deliberately pure and local-filesystem only. Runtime code can
mirror these files into Docker or SSH environments later while keeping request
validation, UTF-8 JSON handling, and call-limit behavior testable offline.
"""

from __future__ import annotations

import json
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ToolCallLimitExceeded(RuntimeError):
    """Raised when a file-RPC script exceeds its allowed tool-call budget."""


@dataclass(frozen=True)
class FileRPCRequest:
    """One tool call requested by a sandboxed script."""

    seq: int
    tool: str
    args: dict[str, Any]


def format_sequence(seq: int) -> str:
    """Return the canonical six-digit sequence token."""

    if not isinstance(seq, int) or seq < 1:
        raise ValueError("file-rpc sequence must be a positive integer")
    return f"{seq:06d}"


class FileRPCStore:
    """UTF-8 JSON request/response store for file-based RPC."""

    def __init__(self, root: str | Path, *, max_tool_calls: int = 50) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.max_tool_calls = max(0, int(max_tool_calls))

    def request_path(self, seq: int) -> Path:
        return self.root / f"req_{format_sequence(seq)}.json"

    def response_path(self, seq: int) -> Path:
        return self.root / f"res_{format_sequence(seq)}.json"

    def write_request(self, request: FileRPCRequest) -> Path:
        if len(self.pending_requests()) >= self.max_tool_calls:
            raise ToolCallLimitExceeded(
                f"file-rpc tool call limit exceeded ({self.max_tool_calls})"
            )
        if not request.tool:
            raise ValueError("file-rpc request tool must be non-empty")
        if not isinstance(request.args, dict):
            raise ValueError("file-rpc request args must be a dict")

        path = self.request_path(request.seq)
        self._write_json_atomic(path, {
            "seq": request.seq,
            "tool": request.tool,
            "args": request.args,
        })
        return path

    def read_request(self, seq: int) -> FileRPCRequest | None:
        return self._read_request_file(self.request_path(seq))

    def pending_requests(self) -> list[FileRPCRequest]:
        requests = [
            request
            for path in self.root.glob("req_*.json")
            if (request := self._read_request_file(path)) is not None
        ]
        return sorted(requests, key=lambda request: request.seq)

    def write_response(self, seq: int, response: dict[str, Any]) -> Path:
        path = self.response_path(seq)
        self._write_json_atomic(path, response)
        return path

    def read_response(self, seq: int) -> dict[str, Any] | None:
        path = self.response_path(seq)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        with suppress(OSError):
            path.unlink()
        return payload if isinstance(payload, dict) else None

    def _read_request_file(self, path: Path) -> FileRPCRequest | None:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict):
            return None
        seq = payload.get("seq")
        tool = payload.get("tool")
        args = payload.get("args")
        if not isinstance(seq, int) or seq < 1:
            return None
        if not isinstance(tool, str) or not tool:
            return None
        if not isinstance(args, dict):
            return None
        return FileRPCRequest(seq=seq, tool=tool, args=args)

    @staticmethod
    def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
        tmp_path = path.with_name(f"{path.name}.tmp")
        tmp_path.write_text(
            json.dumps(payload, ensure_ascii=False),
            encoding="utf-8",
        )
        tmp_path.replace(path)
