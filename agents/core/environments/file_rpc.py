"""File-based RPC primitives for future remote execute_code transports.

The store here is deliberately pure and local-filesystem only. Runtime code can
mirror these files into Docker or SSH environments later while keeping request
validation, UTF-8 JSON handling, and call-limit behavior testable offline.
"""

from __future__ import annotations

import json
import re
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Hard cap on the size of a single RPC file the HOST will read into memory. The
# request directory is a writable bind-mount handed to UNTRUSTED sandbox code, so
# a request (or response) file could be attacker-sized; refuse to load anything
# larger than a generous tool-call payload rather than OOM the host process.
MAX_RPC_FILE_BYTES = 1_000_000

# Canonical request filename: ``req_<zero-padded-seq>.json``. The sequence is
# taken from the FILENAME, never the untrusted file body, so a request can never
# desync from the response/cleanup path derived from that same sequence.
_REQ_NAME_RE = re.compile(r"req_(\d+)\.json")


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

    def pending_requests(self, limit: int | None = None) -> list[FileRPCRequest]:
        # Bound the number of files examined per call: the request directory is
        # attacker-writable, so a burst of files must not make a single poll read
        # an unbounded number of them. Live callers pass a limit; the unbounded
        # default preserves the offline-primitive API used by tests.
        names = sorted(self.root.glob("req_*.json"))
        if limit is not None:
            names = names[: max(0, int(limit))]
        requests = [
            request
            for path in names
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
        except (OSError, ValueError):
            # ValueError covers json.JSONDecodeError AND UnicodeDecodeError, so a
            # non-UTF-8 / garbage file is skipped instead of raising. (No size cap
            # here: responses are host-written and bounded by the tool; the size
            # guard belongs on the attacker-controlled request read path only.)
            return None
        with suppress(OSError):
            path.unlink()
        return payload if isinstance(payload, dict) else None

    def _read_request_file(self, path: Path) -> FileRPCRequest | None:
        # Sequence is authoritative from the canonical filename, not the untrusted
        # file body: this keeps request_path(seq) == this file so response writes
        # and cleanup can never target the wrong path, and it rejects non-canonical
        # names an attacker might craft to evade deletion.
        match = _REQ_NAME_RE.fullmatch(path.name)
        if match is None:
            return None
        seq = int(match.group(1))
        if seq < 1 or path.name != f"req_{format_sequence(seq)}.json":
            return None
        try:
            if path.stat().st_size > MAX_RPC_FILE_BYTES:
                return None
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(payload, dict):
            return None
        tool = payload.get("tool")
        args = payload.get("args")
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
