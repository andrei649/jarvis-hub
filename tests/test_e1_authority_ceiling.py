"""Successor-local hostile regression for the E1 authority ceiling.

Provenance: closed #854 (ADV-03). The measured comparison report must
serialize the evaluation_only ceiling as constants, never its mutable
self.authority/self.can_* fields, so a tampered in-memory instance
cannot emit elevated authority.
"""

from __future__ import annotations

from pathlib import Path

from tests._nerva_e1_2_checks import _build_report, _report_fixture


def test_e1_authority_ceiling_is_immutable(tmp_path: Path) -> None:
    label_set, batch, store, _environment = _report_fixture(tmp_path)
    report = _build_report(batch, store, label_set)

    object.__setattr__(report, "can_execute", True)
    object.__setattr__(report, "authority", "operator")

    payload = report.to_dict()
    assert payload["authority"] == "evaluation_only"
    assert payload["can_execute"] is False
    assert payload["can_authorize"] is False
    assert payload["can_change_routing"] is False
    assert payload["can_promote"] is False
    assert payload["can_mark_complete"] is False
