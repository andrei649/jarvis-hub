"""Integrity checks for the Nerva 2.0 E0 evidence baseline."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "docs" / "nerva2" / "BASELINE.md"
DISPOSITION = ROOT / "docs" / "nerva2" / "REUSE_BUILD_RETIRE.md"
SNAPSHOT = "616f4d3e348675d56f0f600cca2d622b58ded804"

RUNTIME_STATES = ("`LIVE`", "`GATED`", "`SEAM`", "`STUB`", "`MIXED`")
DECISIONS = ("`REUSE`", "`INTEGRATE`", "`BUILD`", "`REFACTOR`", "`RETIRE`")

# These are the load-bearing implementation paths used to justify the first E0
# decisions. The test intentionally does not attempt to parse every Markdown
# code span; it guards the core evidence set against silent moves/deletions.
EVIDENCE_PATHS = (
    "NERVA_VISION.md",
    "agents/core/orchestrator.py",
    "agents/core/router.py",
    "agents/core/agent_runtime.py",
    "agents/core/tool_rpc.py",
    "agents/core/tool_rpc_runtime.py",
    "agents/core/kernel/__init__.py",
    "agents/core/autonomy/observer.py",
    "agents/core/autonomy/queue.py",
    "agents/core/autonomy/worker.py",
    "agents/core/scheduler_service.py",
    "agents/core/observability/capability_registry.py",
    "agents/core/observability/reality_harness.py",
    "agents/core/observability/eval.py",
    "agents/core/memory/bitemporal.py",
    "agents/core/cognition/memory.py",
    "agents/core/learning/background_review.py",
    "agents/core/autonomy/reflection.py",
    "agents/core/acquisition/runtime.py",
    "agents/core/data_purge.py",
    "tests/test_agent_runtime_v2.py",
    "tests/test_kernel_syscalls.py",
    "tests/test_h27_registry_planning.py",
    "tests/test_o26_p2_memory_consolidation.py",
    "tests/test_h32_synthesis_pipeline.py",
    "docs/research/2026-07-18-live-vs-plumbing-capability-audit.md",
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_nerva2_e0_docs_exist_and_are_nontrivial():
    for path in (BASELINE, DISPOSITION):
        assert path.is_file(), f"missing Nerva 2.0 E0 document: {path.relative_to(ROOT)}"
        assert len(_read(path).splitlines()) >= 80


def test_baseline_is_pinned_and_does_not_claim_e0_complete():
    text = _read(BASELINE)
    assert SNAPSHOT in text
    assert "does **not** close E0" in text
    assert "Remaining E0 work" in text


def test_runtime_and_migration_vocabularies_are_explicit():
    baseline = _read(BASELINE)
    disposition = _read(DISPOSITION)
    for state in RUNTIME_STATES:
        assert state in baseline
    for decision in DECISIONS:
        assert decision in disposition


def test_load_bearing_evidence_paths_still_exist():
    missing = [path for path in EVIDENCE_PATHS if not (ROOT / path).exists()]
    assert missing == [], f"Nerva E0 evidence paths moved or disappeared: {missing}"


def test_baseline_avoids_unresolved_template_markers():
    combined = f"{_read(BASELINE)}\n{_read(DISPOSITION)}"
    for marker in ("TODO", "TBD", "FIXME", "<fill", "???"):
        assert marker not in combined
