"""SEC-B6 follow-up — the forget/export erasure invariant.

The AUDIT-2 fix inverted the purge polarity: a forget now erases *everything* under
the data root except the KEEP allowlist (`data_purge.py` `_purge_everything_but_keep`).
The privacy guarantee that matters is therefore not "is every store listed" but:

    nothing a data export can reveal may be exempt from erasure.

i.e. no store the export names (`EXPORT_DBS`, `EXPORT_JSON`) may sit on the forget
KEEP list (`KEEP_FILES`, `KEEP_DIRS`). If it did, deleting your data before handing
the box back (the A7 design-partner promise, `docs/PRIVACY.md`) would leave behind
exactly what an export dumps.

The export set and the KEEP set live in two modules and were maintained separately —
`data_purge.py` names the reconciliation risk in its own docstring. This test makes a
future divergence loud instead of silent (the gap logged in
`docs/qa-runs/2026-08-11-hermetic-adv-run.md`). It holds today; it exists so it can't
quietly stop holding.
"""

from agents.core.data_export import EXPORT_DBS, EXPORT_JSON
from agents.core.data_purge import KEEP_DIRS, KEEP_FILES


def _exported_but_kept(exported: set[str], kept: set[str]) -> set[str]:
    """Stores that a forget would KEEP even though an export names them."""
    return set(exported) & set(kept)


def test_no_exported_store_is_kept_from_forget():
    exported = set(EXPORT_DBS) | set(EXPORT_JSON)
    kept = set(KEEP_FILES) | set(KEEP_DIRS)
    leaked = _exported_but_kept(exported, kept)
    assert not leaked, (
        "A data export names store(s) that a forget KEEPs, so deleting your data would "
        "leave behind what the export reveals. Either drop it from EXPORT_DBS/EXPORT_JSON "
        "(agents/core/data_export.py) or stop keeping it in KEEP_FILES/KEEP_DIRS "
        "(agents/core/data_purge.py): " + ", ".join(sorted(leaked))
    )


def test_the_guard_has_teeth():
    """A synthetic divergence — an exported DB that is also kept — must be detected,
    so the invariant test above cannot pass vacuously if the real sets ever overlap."""
    assert _exported_but_kept({"notes.db", "missions.db"}, {"notes.db"}) == {"notes.db"}
    assert _exported_but_kept({"missions.db"}, {"settings.db"}) == set()
