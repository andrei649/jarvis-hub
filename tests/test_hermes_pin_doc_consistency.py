"""docs/nerva2/ may not call a stale Hermes pin "the latest release" (DRA-58).

The execution-provider pin (`v2026.8.3` / `3c27eb6`) is deliberately frozen — a preflight snapshot
is an immutable observation. What was wrong is the *prose*: two documents asserted that pin was
still upstream's newest release, which stopped being true when `v2026.8.27` shipped (recorded in
agents/core/skills/hermes_pin_v1.json, analysed in the 2026-08-28 delta port).

So the rule is not "keep the pin current" — it is "if you claim currency, name the release that is
actually current".
"""

import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
NERVA2 = REPO / "docs/nerva2"
CURRENCY_CLAIM = re.compile(r"no newer release|still the latest release|still current", re.I)


def _upstream_tag() -> str:
    pin = json.loads((REPO / "agents/core/skills/hermes_pin_v1.json").read_text(encoding="utf-8"))
    return pin["release_tag"]


def test_no_doc_calls_the_frozen_pin_the_latest_release() -> None:
    tag = _upstream_tag()
    for path in sorted(NERVA2.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        if "v2026.8.3" not in text:
            continue
        for line in text.splitlines():
            if CURRENCY_CLAIM.search(line):
                assert tag in text, (
                    f"{path.name} claims currency ({line.strip()!r}) but never mentions the "
                    f"release that is actually current ({tag})"
                )


def test_the_dated_refresh_is_marked_superseded() -> None:
    text = (NERVA2 / "EXECUTION_PROVIDER_E8_1_REFRESH_2026-08-08.md").read_text(encoding="utf-8")
    head = "\n".join(text.splitlines()[:12])
    assert "superseded" in head.lower()
    assert _upstream_tag() in head


def test_the_frozen_pin_is_stated_as_deliberate_not_as_drift() -> None:
    """The correction must not read as 'the pin is out of date' — it is frozen on purpose."""
    text = (NERVA2 / "EXECUTION_PROVIDER_E8_1A.md").read_text(encoding="utf-8")
    assert _upstream_tag() in text
    assert "v2026.8.3" in text and "3c27eb6" in text
    assert "deliberately stays" in text or "deliberately remains" in text
