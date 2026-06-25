"""H23.19 — trust/security docs exist, are grounded (not boilerplate), and discoverable.

Guards against bit-rot: the threat model must keep naming real seams, the privacy doc
must keep its telemetry stance, and both must stay linked from README + SECURITY.md.
"""

from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


def test_threat_model_has_core_sections_and_real_seams():
    t = _read("docs/THREAT_MODEL.md")
    for section in ("trust boundaries", "Assets", "Threats & mitigations", "Residual risks", "Reporting"):
        assert section in t, f"THREAT_MODEL missing: {section}"
    # grounded in the actual architecture, not generic prose
    assert "kernel.authorize" in t
    assert "egress" in t.lower()


def test_privacy_discloses_telemetry_stance():
    p = _read("docs/PRIVACY.md").lower()
    assert "no telemetry" in p
    for phrase in ("local-first", "your controls", "third parties"):
        assert phrase in p, f"PRIVACY missing: {phrase}"


def test_trust_docs_are_discoverable():
    readme = _read("README.md")
    assert "THREAT_MODEL.md" in readme and "PRIVACY.md" in readme
    security = _read("SECURITY.md")
    assert "THREAT_MODEL" in security and "PRIVACY" in security
