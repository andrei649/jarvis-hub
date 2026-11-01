"""A cloud route waits out a settings writer's lease instead of refusing the turn (#1321).

Every cloud route reads the signed selection under a non-blocking shared lease. While an
admin save, a reset or a fresh process's settings init held the writer lease for its one
transaction, the route raised ``LocalBackendUnavailableError`` and a working Gemini setup
answered "No local language model is available", where main served it. The route now
waits a bounded moment; a lease held past that still refuses. On a store that is not
private no signed selection can be committed, so the check has nothing to read there.
"""
from __future__ import annotations

import threading
import time

import pytest

from agents.core import settings_db
from agents.core.llm import hybrid_router
from agents.core.llm.hybrid_router import HybridRouter, LocalBackendUnavailableError
from agents.core.llm.providers import selection_gates


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_db, "DB_PATH", tmp_path / "settings.db")
    monkeypatch.setattr(settings_db, "_initialized", False)
    settings_db.ensure_initialized()
    return tmp_path / "settings.db"


def _router() -> HybridRouter:
    return HybridRouter.__new__(HybridRouter)  # no network, no probes


def _hold_writer_lease(seconds: float, held: threading.Event) -> threading.Thread:
    def run():
        with settings_db._selection_write_gate({"llm": {"compatible_model": "x"}}):
            held.set()
            time.sleep(seconds)

    thread = threading.Thread(target=run)
    thread.start()
    assert held.wait(5)
    return thread


def test_a_cloud_route_is_served_with_no_writer(store):
    _router()._check_selected_cloud_route(object(), "gemini-2.5-flash", "cloud")


def test_a_cloud_route_waits_out_a_settings_save(store):
    held = threading.Event()
    writer = _hold_writer_lease(0.15, held)
    try:
        _router()._check_selected_cloud_route(object(), "gemini-2.5-flash", "cloud")
    finally:
        writer.join(5)


def test_a_lease_held_past_the_bound_still_refuses(store, monkeypatch):
    monkeypatch.setattr(hybrid_router, "_SELECTION_BUSY_WAIT_SECONDS", 0.1)
    held = threading.Event()
    writer = _hold_writer_lease(1.0, held)
    try:
        with pytest.raises(LocalBackendUnavailableError) as caught:
            _router()._check_selected_cloud_route(object(), "gemini-2.5-flash", "cloud")
        assert isinstance(caught.value.__cause__, selection_gates.SelectionBusy)
    finally:
        writer.join(5)


def test_a_store_that_is_not_private_has_no_signed_selection_to_check(tmp_path, monkeypatch):
    root = tmp_path / "home"
    root.mkdir()
    root.chmod(0o775)
    monkeypatch.setattr(settings_db, "DB_PATH", root / "settings.db")
    monkeypatch.setattr(settings_db, "_initialized", False)
    settings_db.ensure_initialized()
    _router()._check_selected_cloud_route(object(), "gemini-2.5-flash", "cloud")
    # A router that holds a signed runtime there cannot prove it and refuses.
    router = _router()
    router._selected_provider_runtime = object()
    with pytest.raises(LocalBackendUnavailableError):
        router._check_selected_cloud_route(object(), "gemini-2.5-flash", "cloud")
