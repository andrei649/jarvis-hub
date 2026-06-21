"""Tests for the third-party auto-update script (scripts/update_thirdparty.py).

Offline only: the clone/network step is injected via a fake VendorRunner, so no
git and no network are touched. Covers:
  * manifest pin rewrite to the new version (and version_source file refresh),
  * doc-pinned bump (manifest pin + plain version string in the doc),
  * no-op when already current,
  * a re-vendor invokes the injected runner with the right repo/dest,
  * the post-update consistency check (check_thirdparty_drift) still passes.
"""

import json
import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "scripts"))

import check_thirdparty_drift as drift
import update_thirdparty as up


# ── fixtures / helpers ────────────────────────────────────────────────────────

def _vendored_manifest():
    return {
        "sources": [
            {
                "name": "superpowers",
                "repo": "obra/superpowers",
                "kind": "vendored",
                "path": ".claude/plugins/superpowers/",
                "pinned_version": "6.0.3",
                "license": "LICENSES/superpowers-MIT.txt",
                "version_source": {
                    "file": ".claude/plugins/superpowers/.claude-plugin/plugin.json",
                    "json_key": "version",
                },
                "track_drift": True,
            }
        ]
    }


def _doc_manifest():
    return {
        "sources": [
            {
                "name": "codebase-memory-mcp",
                "repo": "DeusData/codebase-memory-mcp",
                "kind": "doc-pinned (trial host binary)",
                "path": "docs/dev/codebase-memory-mcp.md",
                "pinned_version": "0.8.1",
                "update_doc": "docs/dev/codebase-memory-mcp.md",
            }
        ]
    }


def _seed_vendored_tree(root: Path, version: str = "6.0.3"):
    plugin = root / ".claude/plugins/superpowers/.claude-plugin"
    plugin.mkdir(parents=True)
    (plugin / "plugin.json").write_text(json.dumps({"name": "superpowers", "version": version}))
    (root / ".claude/plugins/superpowers/LICENSE").write_text("OLD MIT TEXT")
    (root / "LICENSES").mkdir()
    (root / "LICENSES/superpowers-MIT.txt").write_text("OLD MIT TEXT")


def _fake_runner(records, new_license_text="NEW MIT TEXT", new_version="6.1.0"):
    """Return a VendorRunner that records its call and simulates a fresh clone:
    it writes a new LICENSE and a plugin.json carrying *new_version* into dest."""
    def runner(repo, version, dest):
        records.append({"repo": repo, "version": version, "dest": dest})
        import shutil
        if dest.exists():
            shutil.rmtree(dest)
        (dest / ".claude-plugin").mkdir(parents=True)
        (dest / ".claude-plugin" / "plugin.json").write_text(
            json.dumps({"name": "superpowers", "version": new_version})
        )
        (dest / "LICENSE").write_text(new_license_text)
    return runner


# ── manifest pin rewrite (vendored) ───────────────────────────────────────────

def test_vendored_update_rewrites_pin_and_persists_manifest(tmp_path):
    _seed_vendored_tree(tmp_path)
    manifest = _vendored_manifest()
    manifest_path = tmp_path / ".github" / "third-party-manifest.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")

    records = []
    summary = up.update_entry(
        manifest, "superpowers", "6.1.0", tmp_path,
        runner=_fake_runner(records, new_version="6.1.0"),
        manifest_path=manifest_path,
    )

    assert summary["changed"] is True
    assert summary["vendored"] is True
    # in-memory pin bumped
    assert manifest["sources"][0]["pinned_version"] == "6.1.0"
    # persisted to disk
    on_disk = json.loads(manifest_path.read_text())
    assert on_disk["sources"][0]["pinned_version"] == "6.1.0"


def test_vendored_update_invokes_runner_with_repo_and_dest(tmp_path):
    _seed_vendored_tree(tmp_path)
    manifest = _vendored_manifest()
    records = []

    up.update_entry(
        manifest, "superpowers", "6.1.0", tmp_path,
        runner=_fake_runner(records),
    )

    assert len(records) == 1
    call = records[0]
    assert call["repo"] == "obra/superpowers"
    assert call["version"] == "6.1.0"
    assert call["dest"] == tmp_path / ".claude/plugins/superpowers/"


def test_vendored_update_refreshes_license_and_version_source(tmp_path):
    _seed_vendored_tree(tmp_path)
    manifest = _vendored_manifest()
    records = []

    summary = up.update_entry(
        manifest, "superpowers", "6.1.0", tmp_path,
        runner=_fake_runner(records, new_license_text="NEW MIT TEXT", new_version="6.1.0"),
    )

    # license mirror was refreshed from the freshly-vendored LICENSE
    assert summary["license_refreshed"] is True
    assert (tmp_path / "LICENSES/superpowers-MIT.txt").read_text() == "NEW MIT TEXT"
    # version_source already carried 6.1.0 from the fake clone → no rewrite needed
    assert summary["version_source_updated"] is False
    plugin = json.loads(
        (tmp_path / ".claude/plugins/superpowers/.claude-plugin/plugin.json").read_text()
    )
    assert plugin["version"] == "6.1.0"


def test_vendored_update_rewrites_version_source_when_clone_lags(tmp_path):
    # Simulate a clone whose plugin.json doesn't match the pin → script fixes it
    # so the consistency check stays green.
    _seed_vendored_tree(tmp_path)
    manifest = _vendored_manifest()
    records = []

    summary = up.update_entry(
        manifest, "superpowers", "6.1.0", tmp_path,
        runner=_fake_runner(records, new_version="0.0.0"),  # stale plugin.json
    )

    assert summary["version_source_updated"] is True
    plugin = json.loads(
        (tmp_path / ".claude/plugins/superpowers/.claude-plugin/plugin.json").read_text()
    )
    assert plugin["version"] == "6.1.0"


def test_consistency_passes_after_vendored_update(tmp_path):
    _seed_vendored_tree(tmp_path)
    manifest = _vendored_manifest()
    records = []

    up.update_entry(
        manifest, "superpowers", "6.1.0", tmp_path,
        runner=_fake_runner(records, new_version="6.1.0"),
    )

    # Mirror the --consistency path: track_drift off, no network fetch.
    offline = {"sources": [{**s, "track_drift": False} for s in manifest["sources"]]}
    results = drift.run_checks(offline, lambda r: None, tmp_path)
    mismatch, _ = drift.summarize(results)
    assert mismatch is False


# ── doc-pinned bump ───────────────────────────────────────────────────────────

def test_doc_pinned_bump_updates_pin_and_doc(tmp_path):
    manifest = _doc_manifest()
    doc = tmp_path / "docs/dev/codebase-memory-mcp.md"
    doc.parent.mkdir(parents=True)
    doc.write_text("Trialing codebase-memory-mcp, pinned at 0.8.1 for now.\n")

    records = []
    summary = up.update_entry(
        manifest, "codebase-memory-mcp", "0.9.0", tmp_path,
        runner=_fake_runner(records),  # must NOT be called for doc-pinned
    )

    assert records == []                       # runner never invoked
    assert summary["vendored"] is False
    assert summary["doc_updated"] is True
    assert manifest["sources"][0]["pinned_version"] == "0.9.0"
    text = doc.read_text()
    assert "0.9.0" in text
    assert "0.8.1" not in text


def test_doc_pinned_bump_leaves_glued_version_tokens_alone(tmp_path):
    # The bare pin is rewritten, but a token glued to other chars (e.g. inside
    # "v0.8.10") must not be clobbered.
    manifest = _doc_manifest()
    doc = tmp_path / "docs/dev/codebase-memory-mcp.md"
    doc.parent.mkdir(parents=True)
    doc.write_text("pinned at 0.8.1; unrelated tag v0.8.10 stays.\n")

    up.update_entry(
        manifest, "codebase-memory-mcp", "0.9.0", tmp_path, runner=_fake_runner([]),
    )

    text = doc.read_text()
    assert "pinned at 0.9.0;" in text
    assert "v0.8.10 stays" in text             # untouched


def test_doc_pinned_bump_when_no_version_string_in_doc(tmp_path):
    manifest = _doc_manifest()
    doc = tmp_path / "docs/dev/codebase-memory-mcp.md"
    doc.parent.mkdir(parents=True)
    doc.write_text("A trial doc with no explicit version token.\n")

    summary = up.update_entry(
        manifest, "codebase-memory-mcp", "0.9.0", tmp_path,
        runner=_fake_runner([]),
    )

    # Pin still bumps; doc just wasn't touched.
    assert summary["changed"] is True
    assert summary["doc_updated"] is False
    assert manifest["sources"][0]["pinned_version"] == "0.9.0"


# ── no-op when already current ────────────────────────────────────────────────

def test_no_op_when_already_current(tmp_path):
    _seed_vendored_tree(tmp_path)
    manifest = _vendored_manifest()
    records = []

    summary = up.update_entry(
        manifest, "superpowers", "6.0.3", tmp_path,  # same as pinned
        runner=_fake_runner(records),
    )

    assert summary["changed"] is False
    assert records == []                       # no re-vendor
    assert manifest["sources"][0]["pinned_version"] == "6.0.3"


def test_no_op_when_target_is_older(tmp_path):
    _seed_vendored_tree(tmp_path)
    manifest = _vendored_manifest()
    records = []

    summary = up.update_entry(
        manifest, "superpowers", "6.0.0", tmp_path,  # older than pinned 6.0.3
        runner=_fake_runner(records),
    )

    assert summary["changed"] is False
    assert records == []


# ── misc ──────────────────────────────────────────────────────────────────────

def test_unknown_name_raises(tmp_path):
    manifest = _vendored_manifest()
    try:
        up.update_entry(manifest, "nope", "1.0.0", tmp_path, runner=_fake_runner([]))
    except KeyError:
        pass
    else:
        raise AssertionError("expected KeyError for unknown manifest name")


def test_find_entry():
    manifest = _vendored_manifest()
    assert up.find_entry(manifest, "superpowers")["repo"] == "obra/superpowers"
    assert up.find_entry(manifest, "missing") is None
