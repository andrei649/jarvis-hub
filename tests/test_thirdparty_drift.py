"""Tests for the third-party drift checker (scripts/check_thirdparty_drift.py).

Offline: the GitHub fetcher is injected. Also guards that the real manifest stays
consistent with the vendored files it tracks.
"""

import json
import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "scripts"))

import check_thirdparty_drift as drift


def test_is_behind_semver():
    assert drift.is_behind("6.0.3", "6.0.4") is True
    assert drift.is_behind("6.0.3", "6.1.0") is True
    assert drift.is_behind("6.0.3", "6.0.3") is False
    assert drift.is_behind("6.0.3", "5.9.9") is False


def test_is_behind_normalizes_v_prefix_and_lengths():
    assert drift.is_behind("6.0.3", "v6.0.3") is False     # v-prefix ignored
    assert drift.is_behind("1.2", "1.2.1") is True          # uneven lengths
    assert drift.is_behind("v1.0.0", "1.0.0") is False


def test_is_behind_non_semver_falls_back_to_inequality():
    # Neither parses as semver → string-inequality fallback (so drift still shows).
    assert drift.is_behind("alpha", "beta") is True
    assert drift.is_behind("abc", "abc") is False


def test_read_source_version_json(tmp_path):
    f = tmp_path / "plugin.json"
    f.write_text(json.dumps({"version": "6.0.3"}))
    v = drift.read_source_version({"file": "plugin.json", "json_key": "version"}, tmp_path)
    assert v == "6.0.3"


def test_run_checks_flags_drift_and_consistency(tmp_path):
    (tmp_path / "plugin.json").write_text(json.dumps({"version": "6.0.3"}))
    manifest = {"sources": [
        {"name": "up-to-date", "repo": "o/a", "pinned_version": "6.0.3",
         "version_source": {"file": "plugin.json", "json_key": "version"},
         "track_drift": True},
        {"name": "behind", "repo": "o/b", "pinned_version": "1.0.0", "track_drift": True},
        {"name": "stale-manifest", "repo": "o/c", "pinned_version": "9.9.9",
         "version_source": {"file": "plugin.json", "json_key": "version"},
         "track_drift": False},
    ]}
    latest = {"o/a": "6.0.3", "o/b": "2.0.0", "o/c": "9.9.9"}
    results = drift.run_checks(manifest, lambda r: latest[r], tmp_path)

    by = {r["name"]: r for r in results}
    assert by["up-to-date"]["drift"] == "ok"
    assert by["up-to-date"]["consistency"] == "ok"
    assert by["behind"]["drift"] == "DRIFT"
    assert by["stale-manifest"]["consistency"] == "MISMATCH"   # 9.9.9 != 6.0.3

    mismatch, has_drift = drift.summarize(results)
    assert mismatch is True and has_drift is True


def test_run_checks_handles_fetch_error(tmp_path):
    manifest = {"sources": [{"name": "x", "repo": "o/x", "pinned_version": "1.0.0", "track_drift": True}]}

    def boom(repo):
        raise RuntimeError("rate limited")

    results = drift.run_checks(manifest, boom, tmp_path)
    assert results[0]["drift"].startswith("error:")
    # an error is not a hard drift
    assert drift.summarize(results) == (False, False)


def test_real_manifest_is_consistent():
    """Guard: the committed manifest's pinned versions match the vendored files."""
    manifest_path = repo_root / ".github" / "third-party-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    # No network: force track_drift off so only the offline consistency check runs.
    offline = {"sources": [{**s, "track_drift": False} for s in manifest["sources"]]}
    results = drift.run_checks(offline, lambda r: None, repo_root)
    mismatch, _ = drift.summarize(results)
    assert not mismatch, f"manifest stale vs vendored files: {results}"
