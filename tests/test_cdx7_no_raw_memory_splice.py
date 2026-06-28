"""CDX-7 regression gate — the three memory→prompt splice sites must route through rag_guard.

A static guard so a future edit can't silently re-introduce a raw retrieved-memory splice
into an LLM prompt (the indirect-injection surface CDX-7 closed). It asserts each known
site references `wrap_memory` and that the old raw-splice patterns are gone — fail-loud if
the choke point is bypassed.
"""

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
ORCH = _ROOT / "agents" / "core" / "orchestrator.py"
AGENT = _ROOT / "agents" / "core" / "agent.py"

# The raw splices CDX-7 removed — if any reappears, a memory→prompt path skipped the guard.
_BANNED = [
    'shot_lines = [f"- Andrei:',                                  # Howard archive few-shot splice
    '"Relevant long-term memory (recall):\\n"',                   # _recall_block raw join
]


def test_recall_sites_route_through_rag_guard():
    for path in (ORCH, AGENT):
        src = path.read_text(encoding="utf-8")
        assert "rag_guard" in src and "wrap_memory" in src, (
            f"{path.name} no longer routes retrieved memory through rag_guard.wrap_memory"
        )


def test_old_raw_memory_splices_are_gone():
    orch = ORCH.read_text(encoding="utf-8")
    agent = AGENT.read_text(encoding="utf-8")
    blob = orch + "\n" + agent
    for pat in _BANNED:
        assert pat not in blob, f"raw memory splice reappeared (bypasses CDX-7 guard): {pat!r}"
