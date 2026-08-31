"""DRA-46 — NERVA_VISION.md must not claim the execution-target layer never executes.

#980 shipped `GovernedTargetRunner`, which authorizes against the target policy
plane and then executes (docker only), and wired it into production at
`autonomy_coordinator.py`. The vision doc kept asserting the pre-#980 state in two
places, contradicting its own changelog.

Half of the original claim is still TRUE and must stay sayable: `local` and `ssh`
refuse honestly and there is no SSH transport. So this pins the falsified half
only, and pins it against the CODE — if a future change really did remove the
production caller, the guard inverts instead of demanding the doc stay silent.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
VISION = REPO / "NERVA_VISION.md"


def _runner_is_wired() -> bool:
    """Is GovernedTargetRunner constructed anywhere in production (not tests)?"""
    return any(
        "GovernedTargetRunner(" in p.read_text(encoding="utf-8")
        for p in (REPO / "agents").rglob("*.py")
        if p.name != "execution.py"
    )


def test_the_runner_really_is_wired_in_production():
    """The premise. If this fails the doc claim below is no longer false."""
    assert _runner_is_wired(), (
        "GovernedTargetRunner has no production constructor — if that is a deliberate "
        "removal, DRA-46's correction must be reverted rather than this test relaxed"
    )


def test_vision_does_not_assert_the_layer_never_executes():
    text = VISION.read_text(encoding="utf-8")
    offenders = [
        line.strip()
        for line in text.splitlines()
        # the corrective sentence quotes the old wording; a live claim does not
        if "never executes" in line and "closed the" not in line
    ]
    assert not offenders, (
        "NERVA_VISION.md still asserts the execution-target layer never executes, but "
        f"GovernedTargetRunner is wired in production: {offenders}"
    )


def test_the_still_true_half_is_preserved():
    """Do not let the correction overshoot: no SSH transport is still the truth."""
    text = VISION.read_text(encoding="utf-8").lower()
    assert "no ssh transport" in text or "no paramiko/asyncssh" in text, (
        "the correction dropped the half of the claim that is still true — ssh really "
        "does refuse and no SSH transport exists"
    )
