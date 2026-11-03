"""docs/nerva2/ may not call a stale Hermes pin "the latest release" (DRA-58).

The execution-provider pin (`v2026.8.3` / `3c27eb6`) is deliberately frozen — a preflight snapshot
is an immutable observation. What was wrong is the *prose*: two documents asserted that pin was
still upstream's newest release. The separate catalog is now fixed to `v2026.8.31` in
agents/core/skills/hermes_pin_v2.json; this does not rewrite the dated provider preflight.

So the rule is not "keep the pin current" — it is "if you claim currency, name the release that is
actually current".
"""

import json
import os
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
NERVA2 = REPO / "docs/nerva2"
CURRENCY_CLAIM = re.compile(r"no newer release|still the latest release|still current", re.I)


def _upstream_tag() -> str:
    pin = json.loads((REPO / "agents/core/skills/hermes_pin_v2.json").read_text(encoding="utf-8"))
    return pin["release_tag"]


def test_no_doc_calls_the_frozen_pin_the_latest_release() -> None:
    tag = _upstream_tag()
    for path in sorted(NERVA2.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        if "v2026.8.3" not in text:
            continue
        if path.name == "EXECUTION_PROVIDER_E8_1_REFRESH_2026-08-08.md":
            # Its first lines explicitly freeze and supersede the dated answer.
            assert "superseded" in "\n".join(text.splitlines()[:12]).lower()
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
    assert "v2026.8.27" in head  # historical supersession notice, not a live pin


def test_the_frozen_pin_is_stated_as_deliberate_not_as_drift() -> None:
    """The correction must not read as 'the pin is out of date' — it is frozen on purpose."""
    text = (NERVA2 / "EXECUTION_PROVIDER_E8_1A.md").read_text(encoding="utf-8")
    assert _upstream_tag() in text
    assert "v2026.8.3" in text and "3c27eb6" in text
    assert "deliberately stays" in text or "deliberately remains" in text


def test_generated_catalog_covers_every_pinned_skill_and_reference() -> None:
    from scripts import gen_hermes_catalog_docs as generator

    pin = json.loads((REPO / "agents/core/skills/hermes_pin_v2.json").read_text(encoding="utf-8"))
    catalog = REPO / "docs/hermes/catalog"
    slugs = {entry["slug"] for entry in pin["skills"]}
    assert len(slugs) == 190
    assert {path.stem for path in catalog.glob("*.md") if path.name != "README.md"} == slugs
    assert generator.main(["--check"]) == 0
    for entry in pin["skills"]:
        page = (catalog / f"{entry['slug']}.md").read_text(encoding="utf-8")
        assert entry["path"] in page
        assert entry["tier"] in page
        assert entry["content_sha256"] in page
        for reference in entry["files"]:
            assert reference["path"] in page
            assert reference["content_sha256"] in page


def test_catalog_check_detects_drift_without_deleting_unrelated_files(tmp_path, monkeypatch) -> None:
    from scripts import gen_hermes_catalog_docs as generator

    monkeypatch.setattr(generator, "OUTPUT_DIR", tmp_path / "catalog")
    assert generator.main([]) == 0
    catalog = tmp_path / "catalog"
    assert generator.main(["--check"]) == 0
    unrelated = catalog / "owner-notes.md"
    unrelated.write_text("Keep this unrelated note.\n", encoding="utf-8")
    stale = catalog / "old-generated.md"
    stale.write_text(generator.GENERATED_MARKER + "\nold\n", encoding="utf-8")
    linked = catalog / "old-linked.md"
    if os.name != "nt":
        linked.symlink_to(stale)
    assert generator.main(["--check"]) == 1
    assert unrelated.read_text(encoding="utf-8") == "Keep this unrelated note.\n"
    assert stale.exists()
    assert generator.main([]) == 0
    assert generator.main(["--check"]) == 0
    assert not stale.exists()
    if os.name != "nt":
        assert linked.is_symlink()  # A link to our deleted page is still not ours to delete.
    assert unrelated.read_text(encoding="utf-8") == "Keep this unrelated note.\n"
    page = catalog / "github.md"
    original = page.read_text(encoding="utf-8")
    page.write_text(original + "stale\n", encoding="utf-8")
    assert generator.main(["--check"]) == 1
    assert generator.main([]) == 0
    assert page.read_text(encoding="utf-8") == original
    (catalog / "grill-me.md").unlink()
    assert generator.main(["--check"]) == 1
    assert unrelated.read_text(encoding="utf-8") == "Keep this unrelated note.\n"


def test_catalog_writer_refuses_to_replace_an_unowned_page(tmp_path, monkeypatch) -> None:
    from scripts import gen_hermes_catalog_docs as generator

    monkeypatch.setattr(generator, "OUTPUT_DIR", tmp_path / "catalog")
    assert generator.main([]) == 0
    owner_page = generator.OUTPUT_DIR / "github.md"
    owner_page.write_text("Owner's unrelated page.\n", encoding="utf-8")
    assert generator.main(["--check"]) == 1
    assert generator.main([]) == 2
    assert owner_page.read_text(encoding="utf-8") == "Owner's unrelated page.\n"
