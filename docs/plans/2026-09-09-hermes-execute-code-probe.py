"""Synthetic K1 authority inspection; no sandbox/code execution or external queue."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from agents.core.data_spaces import DataSpaces  # noqa: E402
from agents.core.memory.session_search import register_session_search  # noqa: E402
from agents.core.tool_profiles import ToolPosture, resolve_tools  # noqa: E402
from agents.core.tool_rpc import ToolRPCServer  # noqa: E402
from agents.core.tool_rpc_runtime import ToolRPCSandboxRuntime  # noqa: E402

SOURCES = (
    "agents/core/agent_runtime.py",
    "agents/core/autonomy_coordinator.py",
    "agents/core/data_spaces.py",
    "agents/core/memory/session_search.py",
    "agents/core/orchestrator.py",
    "agents/core/routers/data_spaces.py",
    "agents/core/sandbox.py",
    "agents/core/tool_profiles.py",
    "agents/core/tool_rpc.py",
    "agents/core/tool_rpc_runtime.py",
)


def git(*args: str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=REPO, text=True, encoding="utf-8"
    ).strip()


async def inspect_authority() -> dict:
    queue: list[dict] = []
    handler_calls: list[dict] = []

    def enqueue(agent, kind, title, **kwargs):
        queue.append({"actor": agent, "kind": kind})
        return "synthetic-task"

    async def noop(args):
        handler_calls.append(args)
        return {"synthetic": True}

    server = ToolRPCServer(enqueue=enqueue)
    server.register_tool("echo", noop)
    server.register_tool("synthetic_mutation", noop, gated=True)
    offered, _ = resolve_tools(
        server.tools(), posture=ToolPosture("operator", "owner"), agent_patterns=["echo"]
    )
    # The bridge method under inspection does not use or start a sandbox.
    bridge = ToolRPCSandboxRuntime(server, SimpleNamespace())
    bridge_result = await bridge._handle_request("synthetic_mutation", {})
    with tempfile.TemporaryDirectory(prefix="hermes-k1-authority-") as directory:
        root = Path(directory)
        sessions = root / "sessions"
        sessions.mkdir()
        spaces = DataSpaces(root / "spaces.json")
        # These source labels are synthetic: there is no canonical runtime mapping
        # from a session to a DataSpaces source. This is the missing contract.
        spaces.define_space("restricted", ["session_allowed"])
        spaces.assign("frigga", "restricted")
        for session in ("session_allowed", "session_other"):
            (sessions / (session + ".json")).write_text(
                json.dumps({
                    "session_id": session,
                    "turns": [{"role": "user", "content": "synthetic needle"}],
                }),
                encoding="utf-8",
            )
        register_session_search(server, directory=sessions)
        search = await server.handle(
            {"tool": "session_search", "args": {"query": "needle"}}, actor="frigga"
        )
        return {
            "outer_actor_intended": "frigga",
            "outer_offered": [row["name"] for row in offered],
            "inner_request_result": bridge_result,
            "queue_records": queue,
            "gated_handler_calls": len(handler_calls),
            "configured_sources": sorted(spaces.allowed_sources("frigga")),
            "session_search_hit_ids": sorted(
                hit["session_id"] for hit in search["result"]["hits"]
            ),
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="New JSON file; refuses overwrite")
    args = parser.parse_args()
    evidence = {
        "generated_at": datetime.now(UTC).isoformat(),
        "head_sha": git("rev-parse", "HEAD"),
        "source_sha256": {
            path: hashlib.sha256((REPO / path).read_bytes()).hexdigest() for path in SOURCES
        },
        "source_worktree_status": git("status", "--porcelain", "--", *SOURCES),
        "probe_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "observation": asyncio.run(inspect_authority()),
        "limitations": [
            "Only temporary synthetic files and an in-memory queue were used.",
            "No generated code, sandbox backend, external action or live isolation proof.",
            "The outer actor/profile is the intended invocation contract, not bound by this bridge API.",
            "No runtime contract maps or enforces DataSpaces sources for session_search.",
            "This is a missing authority binding, not evidence of an implemented session ACL bypass.",
            "HEAD identifies the checkout; exact source hashes describe the files inspected.",
            "A nonempty source_worktree_status means HEAD alone does not identify that source.",
        ],
    }
    output = json.dumps(evidence, indent=2) + "\n"
    if args.output:
        with args.output.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(output)
    else:
        print(output, end="")


if __name__ == "__main__":
    main()
