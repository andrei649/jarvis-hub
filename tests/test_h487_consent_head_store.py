"""Durable consent head CAS is independent of the B7 mediation head."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))

from agents.core.autonomy.consent_head_store import make_consent_head_anchor  # noqa: E402
from agents.core.autonomy.mediation import ZERO_HASH, MediationHead  # noqa: E402
from agents.core.autonomy.mediation_head_store import (  # noqa: E402
    FileMediationHeadStore,
)


def _head(sequence: int) -> MediationHead:
    return MediationHead(
        version=1,
        last_sequence=sequence,
        last_event_hash=ZERO_HASH if sequence == 0 else f"{sequence:064x}",
        event_count=sequence,
        signature="a" * 64,
    )


def test_bootstrap_persists_and_reopens_at_explicit_path(tmp_path):
    path = tmp_path / "security" / "consent.json"
    first = make_consent_head_anchor(path)
    assert first.read() is None
    assert first.advance(None, _head(0)) is True

    reopened = make_consent_head_anchor(path)
    assert reopened.read() == _head(0)
    assert reopened.advance(_head(0), _head(1)) is True
    assert make_consent_head_anchor(path).read() == _head(1)
    assert json.loads(path.read_text(encoding="utf-8"))["last_sequence"] == 1


def test_two_handles_reject_stale_and_non_monotonic_advances(tmp_path):
    path = tmp_path / "consent.json"
    first = make_consent_head_anchor(path)
    second = make_consent_head_anchor(path)
    assert first.advance(None, _head(1)) is False
    assert first.advance(None, _head(0)) is True
    stale = second.read()
    assert stale == _head(0)
    assert first.advance(_head(0), _head(1)) is True
    assert second.advance(stale, _head(2)) is False
    assert second.advance(_head(1), _head(1)) is False
    assert second.advance(_head(1), _head(0)) is False
    assert second.advance(None, _head(0)) is False
    assert second.advance(_head(1), _head(2)) is True
    assert first.read() == _head(2)


@pytest.mark.parametrize("payload", ["{broken", "[]", '{"version": 1}',
                                    '{"version": 1, "last_sequence": 0, "last_event_hash": "' + "0" * 64 + '", "event_count": 0, "signature": "' + "a" * 64 + '", "extra": 1}'])
def test_existing_invalid_file_never_allows_bootstrap(tmp_path, payload):
    path = tmp_path / "consent.json"
    path.write_text(payload, encoding="utf-8")
    anchor = make_consent_head_anchor(path)
    assert anchor.read() is None
    assert anchor.advance(None, _head(0)) is False
    assert path.read_text(encoding="utf-8") == payload


def test_existing_unreadable_path_never_allows_bootstrap(tmp_path):
    path = tmp_path / "consent.json"
    path.mkdir()
    anchor = make_consent_head_anchor(path)
    assert anchor.read() is None
    assert anchor.advance(None, _head(0)) is False
    assert path.is_dir()


def test_default_path_resolves_at_factory_call_in_each_home(tmp_path, monkeypatch):
    first_home = tmp_path / "first"
    second_home = tmp_path / "second"
    monkeypatch.setenv("JARVIS_HOME", str(first_home))
    first = make_consent_head_anchor()
    assert first.advance(None, _head(0)) is True
    monkeypatch.setenv("JARVIS_HOME", str(second_home))
    second = make_consent_head_anchor()
    assert second.read() is None
    assert second.advance(None, _head(0)) is True
    assert (first_home / "security" / "h487_consent_head.json").exists()
    assert (second_home / "security" / "h487_consent_head.json").exists()
    assert first.read() == _head(0)


def test_failed_fsync_refuses_advance_and_cleans_temp_file(tmp_path, monkeypatch):
    from agents.core.autonomy import consent_head_store

    path = tmp_path / "consent.json"
    anchor = make_consent_head_anchor(path)

    def fail_fsync(_fd):
        raise OSError("durability unavailable")

    monkeypatch.setattr(consent_head_store.os, "fsync", fail_fsync)
    assert anchor.advance(None, _head(0)) is False
    assert anchor.read() is None
    assert list(tmp_path.glob("consent.json.*.tmp")) == []


def test_consent_and_b7_heads_use_independent_default_files(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path))
    b7_path = tmp_path / "security" / "task_mediation_head.json"
    b7 = FileMediationHeadStore()
    assert b7.compare_and_swap(None, _head(0)) is True
    before = b7_path.read_bytes()
    consent = make_consent_head_anchor()
    assert consent.advance(None, _head(0)) is True
    assert consent.advance(_head(0), _head(1)) is True
    assert b7_path.read_bytes() == before
    assert b7.read() == _head(0)
