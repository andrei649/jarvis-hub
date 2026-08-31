"""The unbuilt payment rail must be visible in the owner lane (DRA-20).

`payments.settle()` is deliberately rail-agnostic: the governance layer (mandates, caps,
allowlist, audit chain) is complete, but no money moves and no adapter may be written until the
owner picks a rail, supplies credentials and accepts liability. That makes it an owner decision —
and it was tracked only in BACKLOG.md, in none of the 120 triage items or the owner lane.

The assertion is conditional on purpose: once the backlog row is ticked (a rail exists), the
owner-lane decision entry is free to go.
"""

from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BACKLOG_ROW = "Real payment rail adapter (AP2/ACP/x402) at `payments.settle()`"


def _backlog_row_is_open() -> bool:
    for line in (REPO / "BACKLOG.md").read_text(encoding="utf-8").splitlines():
        if BACKLOG_ROW in line and line.lstrip().startswith("- [ ]"):
            return True
    return False


def test_owner_lane_carries_the_payment_rail_decision_while_it_is_open() -> None:
    if not _backlog_row_is_open():
        return  # a rail shipped; the owner decision no longer needs a parking-lot entry
    text = (REPO / "docs/OWNER_TASKS.md").read_text(encoding="utf-8")
    assert "payments.settle()" in text
    assert "AP2" in text and "x402" in text


def test_owner_lane_entry_states_the_three_owner_inputs_and_the_no_adapter_rule() -> None:
    if not _backlog_row_is_open():
        return
    text = (REPO / "docs/OWNER_TASKS.md").read_text(encoding="utf-8")
    lower = text.lower()
    assert "merchant" in lower and "liabilit" in lower
    # the standing instruction that keeps a fake seam from being written
    assert "NullRail" in text or "no rail adapter" in lower


def test_the_entry_sits_in_the_parking_lot_not_a_release_gate() -> None:
    if not _backlog_row_is_open():
        return
    text = (REPO / "docs/OWNER_TASKS.md").read_text(encoding="utf-8")
    parking = text.split("## Parking lot (decisions, no rush)", 1)
    assert len(parking) == 2, "parking-lot heading moved"
    assert "payments.settle()" in parking[1], "payment-rail entry is not under the parking lot"
