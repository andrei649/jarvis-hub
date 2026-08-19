"""Gate tests for ``scripts/qa_audit_probes.py`` — the adversarial-audit probe tool.

These pin the **machinery**, never the verdicts. Every probe answers "does the mechanism
the 2026-07-25 audit described still reproduce on this checkout?", so a verdict flipping
from OPEN to CLOSED is the *desired* outcome of fixing a finding and must not break CI.
What must never change:

* a probe reports ``N/A`` with a ``probe_error`` when it cannot measure — never ``CLOSED``
  (a silent failure reported as "fixed" is the single worst output this tool could have,
  and ``docs/test-manual/15-audit-gap-verification.md`` ADV-150 tests the same property
  by hand);
* the chain probe stays inside a temp directory and never opens the live audit DB;
* nothing derived from a key or a signature reaches the output (ADV-149) — a detector
  that echoes what it detects is the classic own-goal, and this repo has already been
  bitten by it once in ``scripts/check_test_manual.py``;
* every probe is wired to a case id that exists in the chapter.
"""

import ast
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts/qa_audit_probes.py"
CHAPTER = REPO / "docs/test-manual/15-audit-gap-verification.md"


def _load():
    spec = importlib.util.spec_from_file_location("qa_audit_probes", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def probes():
    return _load()


def test_every_probe_is_wired_to_a_case_that_exists(probes):
    """A probe pointing at a case id nobody wrote sends the tester nowhere."""
    chapter = CHAPTER.read_text(encoding="utf-8")
    defined = set(re.findall(r"(?m)^#{2,5}\s+(ADV-\d{3})", chapter))
    assert defined, "chapter 15 defines no ADV case headings — did the file move?"
    for name in probes.PROBES:
        case = probes.CASES.get(name)
        assert case, f"probe {name!r} has no case id in CASES"
        assert case in defined, (
            f"probe {name!r} points at {case}, which chapter 15 does not define. "
            "Renumbering a case without updating CASES sends the tester to the wrong "
            "reproduction — and the probe's verdict is only a lead to that case."
        )


def test_verdicts_are_only_the_three_documented_values(probes):
    assert {probes.OPEN, probes.CLOSED, probes.NA} == {"OPEN", "CLOSED", "N/A"}


def test_a_failing_probe_reports_na_not_closed(probes, monkeypatch):
    """The property ADV-150 tests by hand: a broken probe must never look like a fix."""
    def _boom():
        raise RuntimeError("dependency vanished")

    monkeypatch.setitem(probes.PROBES, "chain", _boom)
    out = probes.run(["chain"])["chain"]
    assert out["verdict"] == probes.NA, (
        "a probe that raised reported a verdict other than N/A — a silent failure "
        "presented as CLOSED would tell the owner a live break was fixed"
    )
    assert "probe_error" in out["detail"]
    assert "dependency vanished" in out["detail"]["probe_error"]


def test_every_probe_returns_the_documented_shape(probes):
    results = probes.run(list(probes.PROBES))
    assert set(results) == set(probes.PROBES)
    for name, r in results.items():
        assert r["verdict"] in (probes.OPEN, probes.CLOSED, probes.NA), name
        assert r["claim"] and isinstance(r["claim"], str), name
        assert isinstance(r["detail"], dict) and r["detail"], name
        assert r["means"], name


def test_closed_reality_probe_describes_the_actuator_resolution_it_observed(probes):
    result = probes.probe_reality()

    assert result["verdict"] == probes.CLOSED
    assert "resolves the declared manifest implementation" in result["claim"]
    lines = probes._means_lines(result["means"], result["verdict"])
    assert lines[0].startswith("→ CLOSED:")
    assert "declared actuator" in lines[0]


def test_no_probe_writes_to_the_live_data_root(probes, tmp_path, monkeypatch):
    """ADV-148 by hand; here as a gate so a future probe cannot quietly gain a side effect.

    The whole tool is a measurement instrument. One that mutates the thing it measures is
    a disaster with a good excuse.
    """
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path))
    before = sorted(p.name for p in tmp_path.rglob("*"))
    probes.run(list(probes.PROBES))
    after = sorted(p.name for p in tmp_path.rglob("*"))
    assert before == after, f"a probe wrote into the data root: {set(after) - set(before)}"


def test_chain_probe_never_touches_the_real_audit_db(probes):
    """It must build its own DB in a temp dir — the live chain is evidence, not a fixture.

    Covers ``probe_chain`` and every ``_probe_chain*`` helper it delegates to, so moving
    the body into a helper cannot quietly drop the guarantee.
    """
    src = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    fns = [n for n in ast.walk(src)
           if isinstance(n, ast.FunctionDef) and n.name.lstrip("_").startswith("probe_chain")]
    assert fns, "probe_chain not found"
    body = "\n".join(ast.unparse(f) for f in fns)
    assert "TemporaryDirectory" in body, "probe_chain must forge rows in a throwaway DB"
    assert "data_path" not in body and "data_root" not in body, (
        "the chain probe resolves a real data path — it must never open the live audit chain"
    )


def test_chain_probe_closes_its_connections_and_leaves_no_temp_dir(probes):
    """A leaked sqlite handle is invisible on POSIX and fatal on Windows.

    POSIX unlinks an open file happily, so `TemporaryDirectory` cleanup succeeds and a
    leaked `AuditLogger._conn` never shows. Windows raises PermissionError [WinError 32]
    out of the cleanup and takes the whole probe with it — which is exactly how this
    surfaced, green on ubuntu and red on windows-latest in the same CI run.

    Checking that no `adv001-*` directory survives is the portable form of the property.
    It is weak on Linux by construction; it is the assertion that fails on Windows.
    """
    root = Path(tempfile.gettempdir())
    before = {p.name for p in root.glob("adv001-*")}
    probes.probe_chain()
    leaked = {p.name for p in root.glob("adv001-*")} - before
    assert not leaked, (
        f"probe_chain left its temp dir behind: {leaked}. On Windows this is a held sqlite "
        "handle and the cleanup raises instead — close every AuditLogger before the "
        "TemporaryDirectory exits (tests/test_audit_hardening.py does the same)."
    )


def test_chain_probe_restores_the_audit_key_env(probes, monkeypatch):
    """It needs *a* key to write hmac rows; it must not leave one in the owner's process."""
    monkeypatch.delenv("JARVIS_AUDIT_KEY", raising=False)
    probes.probe_chain()
    assert "JARVIS_AUDIT_KEY" not in os.environ, (
        "probe_chain leaked its own key into the environment — later probes would then "
        "measure the probe's configuration instead of the host's"
    )
    monkeypatch.setenv("JARVIS_AUDIT_KEY", "QAFAKE-preexisting-value")
    probes.probe_chain()
    assert os.environ["JARVIS_AUDIT_KEY"] == "QAFAKE-preexisting-value", (
        "probe_chain clobbered a real audit key instead of restoring it"
    )


def test_no_probe_carries_key_material_into_its_output(probes, monkeypatch):
    """ADV-149: a secret detector that prints the secret is the own-goal to avoid.

    Plants recognisable values in both key env vars and asserts no fragment survives into
    the rendered output. The probes may report *whether* a key is configured; never any
    part of one.
    """
    marker_audit = "QAFAKE-audit-marker-do-not-print"
    marker_sign = "QAFAKE-signing-marker-do-not-print"
    monkeypatch.setenv("JARVIS_AUDIT_KEY", marker_audit)
    monkeypatch.setenv("JARVIS_SKILL_SIGNING_KEY", marker_sign)
    rendered = json.dumps(probes.run(list(probes.PROBES)), default=str)
    for marker in (marker_audit, marker_sign):
        assert marker not in rendered, f"a probe echoed key material: {marker!r}"
        # also reject a partial echo — trimming a secret does not declassify it
        assert marker[:12] not in rendered, f"a probe echoed part of a key: {marker[:12]!r}"


def test_signing_probe_reports_presence_not_value(probes, monkeypatch):
    monkeypatch.setenv("JARVIS_SKILL_SIGNING_KEY", "QAFAKE-signing-marker-do-not-print")
    detail = probes.probe_signing()["detail"]
    assert isinstance(detail["signing_is_configured_on_this_host"], bool)


def test_cli_runs_and_is_deterministic():
    """ADV-147 as a gate: two runs must agree, or the verdicts are not usable."""
    def _run():
        proc = subprocess.run(
            [sys.executable, str(SCRIPT), "--json", "purge", "clear", "parity", "ambient"],
            cwd=REPO, capture_output=True, text=True, timeout=300,
        )
        assert proc.returncode == 0, proc.stderr
        return json.loads(proc.stdout)

    assert _run() == _run(), "the probe tool is not deterministic — its verdicts cannot be trusted"


def test_cli_list_names_every_probe():
    proc = subprocess.run([sys.executable, str(SCRIPT), "--list"],
                          cwd=REPO, capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    mod = _load()
    for name in mod.PROBES:
        assert name in proc.stdout


def test_cli_rejects_an_unknown_probe():
    proc = subprocess.run([sys.executable, str(SCRIPT), "no-such-probe"],
                          cwd=REPO, capture_output=True, text=True, timeout=120)
    assert proc.returncode == 2
    assert "unknown probe" in proc.stderr


def test_chapter_15_points_at_the_tool():
    """If the chapter and the tool drift apart, the tester retypes a 40-line repro by hand."""
    chapter = CHAPTER.read_text(encoding="utf-8")
    assert "scripts/qa_audit_probes.py" in chapter
    mod = _load()
    for name in mod.PROBES:
        assert f"qa_audit_probes.py {name}" in chapter, (
            f"chapter 15 never invokes the {name!r} probe — either wire it into its case "
            "or drop the probe"
        )
