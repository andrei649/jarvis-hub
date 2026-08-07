from pathlib import Path
import sys, pytest
sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
from check_nerva_issue_movement import MovementError, LEGACY_BASE, MARKER, parse_diff, strict_json, validate_manifest_gate, classify

def test_missing_gate_allowed_only_legacy():
    validate_manifest_gate({}, LEGACY_BASE)
    with pytest.raises(MovementError): validate_manifest_gate({}, "e596920ec60f19d2e7f0937819c892746a1c42b2")
def test_duplicate_json_rejected():
    with pytest.raises(MovementError): strict_json('{"a":1,"a":2}')
def test_diff_requires_complete_nul_records():
    assert parse_diff(b"M\tBACKLOG.md\0") == [("M", "BACKLOG.md")]
    with pytest.raises(MovementError): parse_diff(b"M\tBACKLOG.md")
def test_classifier_is_deterministic():
    assert classify("nerva2/x", "", [])
    assert classify("feature/x", MARKER, [])
    assert not classify("feature/x", "", ["src/app.py"])
