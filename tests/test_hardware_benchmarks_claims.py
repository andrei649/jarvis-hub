"""No page may promise measured throughput that HARDWARE_BENCHMARKS.md does not have (DRA-62).

The benchmark table is an honest skeleton: every cell reads `— to measure —` because the runs need
owner hardware. README and COMPATIBILITY nonetheless told the reader that *measured* tokens/sec
lived there. This guard keeps the two in step in both directions — when the owner fills the table,
the placeholder disappears and the claim is free to be made again.
"""

from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BENCH = REPO / "docs/HARDWARE_BENCHMARKS.md"
PLACEHOLDER = "— to measure —"


def _unmeasured() -> bool:
    return PLACEHOLDER in BENCH.read_text(encoding="utf-8")


def test_benchmarks_page_states_its_own_status_honestly() -> None:
    text = BENCH.read_text(encoding="utf-8")
    if _unmeasured():
        assert "awaiting measured runs" in text or "skeleton" in text.lower()


def test_no_doc_claims_measured_throughput_while_the_table_is_empty() -> None:
    if not _unmeasured():
        return  # the owner filled the table; the claim is true now
    for rel in ("README.md", "docs/COMPATIBILITY.md"):
        text = (REPO / rel).read_text(encoding="utf-8")
        for line in text.splitlines():
            if "HARDWARE_BENCHMARKS.md" not in line:
                continue
            lowered = line.lower()
            assert "measured tokens/sec per tier live in" not in lowered, rel
            assert "measured per-tier throughput:" not in lowered, rel
