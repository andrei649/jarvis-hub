"""ORIZONT 29 wave 1 — the Media Director core (H29.1–H29.4).

Everything runs hermetically: in-memory stores (path=None), fake drivers, no
sockets, no real devices. The kernel/facade integration is covered separately
by the auto-generated action-plane reality case + the facade test below.
"""

import json
import sys
import threading
import time
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.browser_agent import BrowserPolicy, GovernedBrowser  # noqa: E402
from agents.core.media_catalog import MediaCatalog  # noqa: E402
from agents.core.media_director import (  # noqa: E402
    MEDIA_PRESENT_CONTRACT,
    DeviceRegistry,
    MediaDevice,
    MediaDirector,
    MediaError,
    MediaSession,
    NullMediaDriver,
    SessionBoard,
    may_interrupt,
    resolve_content,
)


class FakeDriver:
    def __init__(self, *, fail_play: bool = False, lie_in_status: bool = False):
        self.now_playing = None
        self.fail_play = fail_play
        self.lie_in_status = lie_in_status
        self.calls: list[str] = []

    def play(self, device, content):
        self.calls.append("play")
        if self.fail_play:
            return {"ok": False, "state": "error", "reason": "device_offline"}
        self.now_playing = content
        return {"ok": True, "state": "playing"}

    def pause(self, device):
        self.calls.append("pause")
        return {"ok": True, "state": "paused"}

    def resume(self, device):
        self.calls.append("resume")
        return {"ok": True, "state": "playing"}

    def stop(self, device):
        self.calls.append("stop")
        self.now_playing = None
        return {"ok": True, "state": "idle"}

    def status(self, device):
        if self.lie_in_status:
            return {"ok": True, "state": "idle", "content": {}}
        return {"ok": True, "state": "playing", "content": self.now_playing or {}}


def _director(driver=None, **kwargs):
    registry = DeviceRegistry(path=None)
    registry.register(MediaDevice(id="tv-1", name="Living TV", kind="tv", room="living"))
    registry.register(
        MediaDevice(id="disp-1", name="Kitchen display", kind="browser_tab", room="kitchen")
    )
    drivers = {}
    if driver is not None:
        drivers = {"tv": driver, "browser_tab": driver}
    kwargs.setdefault("browser", GovernedBrowser(policy=BrowserPolicy(["93.184.216.34"])))
    return MediaDirector(
        registry=registry, sessions=SessionBoard(path=None), drivers=drivers, **kwargs
    )


def _payload(**overrides):
    payload = {
        "content": {"type": "url", "value": "https://93.184.216.34/x"},
        "target": "tv-1",
        "mode": "play",
        "privacy": "household",
        "urgency": "normal",
    }
    payload.update(overrides)
    return payload


# ── content resolution ───────────────────────────────────────────────────────


def test_resolve_content_accepts_http_and_refuses_other_schemes():
    browser = GovernedBrowser(policy=BrowserPolicy(["93.184.216.34"]))
    ok = resolve_content(
        {"type": "url", "value": "https://93.184.216.34/v"},
        browser=browser,
    )
    assert ok == {
        "type": "url",
        "value": "https://93.184.216.34/v",
        "provenance": "direct",
    }
    for bad in ("file:///etc/passwd", "javascript:alert(1)", "ftp://x"):
        with pytest.raises(MediaError):
            resolve_content({"type": "url", "value": bad}, browser=browser)


def test_resolve_local_requires_roots_and_blocks_escapes(tmp_path):
    with pytest.raises(MediaError, match="media.roots"):
        resolve_content({"type": "local", "value": str(tmp_path / "a.mp4")})
    root = tmp_path / "media"
    root.mkdir()
    inside = root / "film.mp4"
    inside.write_bytes(b"media")
    ok = resolve_content({"type": "local", "value": str(inside)}, local_roots=(root,))
    assert ok["value"] == str(inside.resolve())
    assert ok["provenance"] == "direct"
    with pytest.raises(MediaError, match="escapes"):
        resolve_content(
            {"type": "local", "value": str(root / ".." / "secret.mp4")}, local_roots=(root,)
        )


def test_resolve_local_requires_an_existing_regular_file(tmp_path):
    root = tmp_path / "media"
    root.mkdir()
    with pytest.raises(MediaError, match="regular file"):
        resolve_content({"type": "local", "value": str(root / "missing.mp4")}, local_roots=(root,))
    with pytest.raises(MediaError, match="regular file"):
        resolve_content({"type": "local", "value": str(root)}, local_roots=(root,))


def test_catalog_id_uses_real_catalog_then_revalidates_local_target(tmp_path):
    root = tmp_path / "media"
    root.mkdir()
    allowed = root / "allowed.png"
    allowed.write_bytes(b"png")
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"png")
    catalog = MediaCatalog(tmp_path / "catalog.json")
    good = catalog.add(kind="image", prompt="safe", path=str(allowed), now=1.0)
    bad = catalog.add(kind="image", prompt="outside", path=str(outside), now=2.0)

    resolved = resolve_content(
        {"type": "catalog", "value": good["id"]},
        local_roots=(root,),
        catalog=catalog,
    )

    assert resolved == {
        "type": "local",
        "value": str(allowed.resolve()),
        "provenance": "catalog",
        "catalog_id": good["id"],
    }
    with pytest.raises(MediaError, match="escapes"):
        resolve_content(
            {"type": "catalog", "value": bad["id"]},
            local_roots=(root,),
            catalog=catalog,
        )


def test_catalog_query_requires_one_unique_match_and_bounds_candidate_metadata(tmp_path):
    root = tmp_path / "media"
    root.mkdir()
    catalog = MediaCatalog(tmp_path / "catalog.json")
    for index in range(7):
        path = root / f"aurora-{index}.png"
        path.write_bytes(b"png")
        catalog.add(kind="image", prompt=f"aurora {index}", path=str(path), now=float(index))

    with pytest.raises(MediaError) as ambiguous:
        resolve_content(
            {"type": "query", "value": "aurora"},
            local_roots=(root,),
            catalog=catalog,
        )
    assert ambiguous.value.reason == "catalog_query_ambiguous"
    assert len(ambiguous.value.detail["candidates"]) == 5
    assert set(ambiguous.value.detail["candidates"][0]) == {"id", "kind", "created_at"}

    with pytest.raises(MediaError) as missing:
        resolve_content(
            {"type": "query", "value": "missing"},
            local_roots=(root,),
            catalog=catalog,
        )
    assert missing.value.reason == "catalog_query_missing"
    assert missing.value.detail == {"candidates": []}

    unique = resolve_content(
        {"type": "query", "value": "aurora 3"},
        local_roots=(root,),
        catalog=catalog,
    )
    assert unique["provenance"] == "catalog_query"
    assert unique["catalog_id"]


def test_ambiguous_query_candidate_timestamps_are_finite_json(tmp_path):
    root = tmp_path / "media"
    root.mkdir()
    path = root / "aurora.png"
    path.write_bytes(b"png")
    catalog_path = tmp_path / "catalog.json"
    catalog_path.write_text(
        json.dumps(
            [
                {
                    "id": "md-nan",
                    "kind": "image",
                    "prompt": "aurora one",
                    "path": str(path),
                    "created_at": float("nan"),
                },
                {
                    "id": "md-inf",
                    "kind": "image",
                    "prompt": "aurora two",
                    "path": str(path),
                    "created_at": float("inf"),
                },
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(MediaError) as ambiguous:
        resolve_content(
            {"type": "query", "value": "aurora"},
            local_roots=(root,),
            catalog=MediaCatalog(catalog_path),
        )

    candidates = ambiguous.value.detail["candidates"]
    assert [candidate["created_at"] for candidate in candidates] == [0.0, 0.0]
    json.dumps(ambiguous.value.detail, allow_nan=False)


def test_url_resolution_uses_governed_preview_without_fetching():
    class NoFetchDriver:
        def __init__(self):
            self.calls = []

        async def navigate(self, **kwargs):
            self.calls.append(kwargs)
            raise AssertionError("resolution must not fetch")

    driver = NoFetchDriver()
    allowed_browser = GovernedBrowser(
        driver=driver,
        policy=BrowserPolicy(["93.184.216.34"]),
    )
    resolved = resolve_content(
        {"type": "url", "value": "https://93.184.216.34/media"},
        browser=allowed_browser,
    )
    assert resolved["provenance"] == "direct"
    assert driver.calls == []

    for browser, url in (
        (GovernedBrowser(policy=BrowserPolicy([])), "https://93.184.216.34/media"),
        (allowed_browser, "https://203.0.113.9/media"),
        (GovernedBrowser(policy=BrowserPolicy(["127.0.0.1"])), "http://127.0.0.1/media"),
    ):
        with pytest.raises(MediaError, match="url_refused"):
            resolve_content({"type": "url", "value": url}, browser=browser)


def test_malformed_governed_browser_preview_fails_closed():
    class MalformedBrowser:
        def preview(self, _plan):
            return {"steps": [None]}

    with pytest.raises(MediaError, match="url_refused"):
        resolve_content(
            {"type": "url", "value": "https://93.184.216.34/media"},
            browser=MalformedBrowser(),
        )


@pytest.mark.parametrize(
    "preview",
    [
        {
            "steps": [
                {"i": 0, "action": "navigate", "kind": "read", "decision": "run", "reason": ""},
                {"i": 1, "action": "navigate", "kind": "read", "decision": "run", "reason": ""},
            ],
            "blocked": 0,
            "needs_approval": 0,
        },
        {"steps": [{"i": 1, "action": "navigate", "kind": "read", "decision": "run", "reason": ""}], "blocked": 0, "needs_approval": 0},
        {"steps": [{"i": 0, "action": "click", "kind": "read", "decision": "run", "reason": ""}], "blocked": 0, "needs_approval": 0},
        {"steps": [{"i": 0, "action": "navigate", "kind": "risky", "decision": "run", "reason": ""}], "blocked": 0, "needs_approval": 0},
        {"steps": [{"i": 0, "action": "navigate", "kind": "read", "decision": "run", "reason": "spoofed"}], "blocked": 0, "needs_approval": 0},
        {"steps": [{"i": 0, "action": "navigate", "kind": "read", "decision": "run", "reason": ""}], "blocked": 1, "needs_approval": 0},
        {"steps": [{"i": 0, "action": "navigate", "kind": "read", "decision": "run", "reason": ""}], "blocked": 0, "needs_approval": 1},
    ],
)
def test_semantically_malformed_governed_preview_cannot_spoof_run(preview):
    class SpoofedBrowser:
        def preview(self, _plan):
            return preview

    with pytest.raises(MediaError, match="url_refused"):
        resolve_content(
            {"type": "url", "value": "https://93.184.216.34/media"},
            browser=SpoofedBrowser(),
        )


def test_query_normalizes_malformed_persisted_catalog_timestamp(tmp_path):
    root = tmp_path / "media"
    root.mkdir()
    target = root / "aurora.png"
    target.write_bytes(b"png")
    catalog_path = tmp_path / "catalog.json"
    catalog_path.write_text(
        json.dumps(
            [
                {
                    "id": "md-malformed-time",
                    "kind": "image",
                    "prompt": "aurora",
                    "path": str(target),
                    "created_at": "not-a-number",
                }
            ]
        ),
        encoding="utf-8",
    )

    resolved = resolve_content(
        {"type": "query", "value": "aurora"},
        local_roots=(root,),
        catalog=MediaCatalog(catalog_path),
    )

    assert resolved["value"] == str(target.resolve())
    assert resolved["provenance"] == "catalog_query"


def test_resolution_refusal_happens_before_media_driver_invocation(tmp_path):
    driver = FakeDriver()
    director = _director(
        driver,
        catalog=MediaCatalog(tmp_path / "catalog.json"),
        browser=GovernedBrowser(policy=BrowserPolicy([])),
    )

    result = director.present(_payload(content={"type": "query", "value": "missing"}))

    assert result["reason"] == "catalog_query_missing"
    assert result["detail"] == {"candidates": []}
    assert driver.calls == []


def test_resolve_content_refuses_junk_shapes():
    for junk in ("just-a-string", {"type": "nope", "value": "x"}, {"type": "url", "value": ""}):
        with pytest.raises(MediaError):
            resolve_content(junk)


# ── devices ──────────────────────────────────────────────────────────────────


def test_device_registry_register_resolve_and_room_targeting(tmp_path):
    registry = DeviceRegistry(path=tmp_path / "devices.json")
    registry.register(MediaDevice(id="a", name="A", kind="speaker", room="office"))
    registry.register(MediaDevice(id="b", name="B", kind="tv", room="living"))
    assert registry.resolve_target("a").id == "a"
    assert registry.resolve_target("living").id == "b"
    with pytest.raises(MediaError, match="unknown target"):
        registry.resolve_target("garage")
    # persistence round-trip (corrupt-safe store)
    reloaded = DeviceRegistry(path=tmp_path / "devices.json")
    assert {d["id"] for d in reloaded.list()} == {"a", "b"}


def test_ambiguous_room_is_refused_not_guessed():
    registry = DeviceRegistry(path=None)
    registry.register(MediaDevice(id="a", name="A", kind="speaker", room="living"))
    registry.register(MediaDevice(id="b", name="B", kind="tv", room="living"))
    with pytest.raises(MediaError, match="ambiguous"):
        registry.resolve_target("living")


def test_device_validation_and_corrupt_store_degrade(tmp_path):
    with pytest.raises(MediaError):
        MediaDevice(id="x", name="X", kind="teleporter")
    (tmp_path / "devices.json").write_text("{corrupt", encoding="utf-8")
    assert DeviceRegistry(path=tmp_path / "devices.json").list() == []


def test_device_identity_and_supported_operations_are_strictly_validated():
    with pytest.raises(MediaError, match="strings"):
        MediaDevice(id=1, name="TV", kind="tv")
    with pytest.raises(MediaError, match="supports"):
        MediaDevice(id="tv", name="TV", kind="tv", supports="play")
    with pytest.raises(MediaError, match="unsupported device operation"):
        MediaDevice(id="tv", name="TV", kind="tv", supports=("teleport",))


def test_parseable_rows_with_invalid_types_degrade_without_breaking_startup(tmp_path):
    devices = tmp_path / "devices.json"
    devices.write_text(
        json.dumps([{"id": ["not-hashable"], "name": "TV", "kind": "tv"}]),
        encoding="utf-8",
    )
    sessions = tmp_path / "sessions.json"
    sessions.write_text(
        json.dumps(
            [
                {
                    "device_id": ["not-hashable"],
                    "content": {"type": "url", "value": "https://example.local/x"},
                    "mode": "play",
                    "privacy": "household",
                    "started_at": 1.0,
                }
            ]
        ),
        encoding="utf-8",
    )

    assert DeviceRegistry(path=devices).list() == []
    assert SessionBoard(path=sessions).list() == []


def test_oversized_registry_file_degrades_without_parsing_unbounded_input(tmp_path):
    path = tmp_path / "devices.json"
    path.write_text(
        json.dumps([{"id": "big", "name": "X" * 1_100_000, "kind": "tv"}]),
        encoding="utf-8",
    )

    assert DeviceRegistry(path=path).list() == []


def test_discovery_seam_merges_and_survives_broken_discoverers():
    registry = DeviceRegistry(path=None)
    added = registry.discover(
        [
            lambda: [MediaDevice(id="cast-1", name="Cast", kind="chromecast", room="living")],
            lambda: (_ for _ in ()).throw(RuntimeError("host scan broke")),
            lambda: [{"id": "bad", "name": "Bad", "kind": "not-a-kind"}],
        ]
    )
    assert added == 1
    assert registry.get("cast-1") is not None


def test_device_cap_remains_atomic_under_concurrent_registration():
    registry = DeviceRegistry(path=None)
    existing = {
        f"d-{index}": MediaDevice(id=f"d-{index}", name=f"D {index}", kind="tv")
        for index in range(199)
    }
    first_in_set = threading.Event()
    second_checked_cap = threading.Event()

    class YieldingDict(dict):
        first_writer = None

        def __len__(self):
            if first_in_set.is_set() and threading.get_ident() != self.first_writer:
                second_checked_cap.set()
            return super().__len__()

        def __setitem__(self, key, value):
            if not first_in_set.is_set():
                self.first_writer = threading.get_ident()
                first_in_set.set()
                second_checked_cap.wait(0.2)
            return super().__setitem__(key, value)

    registry._devices = YieldingDict(existing)
    errors = []

    def add(device_id):
        try:
            registry.register(MediaDevice(id=device_id, name=device_id, kind="tv"))
        except MediaError as exc:
            errors.append(exc)

    first = threading.Thread(target=add, args=("new-a",))
    first.start()
    assert first_in_set.wait(1)
    second = threading.Thread(target=add, args=("new-b",))
    second.start()
    first.join(2)
    second.join(2)

    assert not first.is_alive() and not second.is_alive()
    assert len(registry.list()) == 200
    assert len(errors) == 1 and "cap reached" in str(errors[0])


# ── etiquette (H29.4) ────────────────────────────────────────────────────────


def test_session_etiquette_only_high_urgency_interrupts():
    driver = FakeDriver()
    director = _director(driver)
    assert director.present(_payload())["ok"] is True
    blocked = director.present(
        _payload(content={"type": "url", "value": "https://93.184.216.34/y"})
    )
    assert blocked["ok"] is False and blocked["reason"] == "session_etiquette"
    override = director.present(
        _payload(
            urgency="high",
            content={"type": "url", "value": "https://93.184.216.34/y"},
        )
    )
    assert override["ok"] is True


def test_may_interrupt_free_when_idle():
    assert may_interrupt(None, urgency="low") is True


def test_session_memory_and_disk_do_not_diverge_under_concurrent_updates(tmp_path):
    path = tmp_path / "sessions.json"
    board = SessionBoard(path=path)
    original_save = board._store.save
    first_save = threading.Event()
    second_saved = threading.Event()
    save_count = 0
    count_lock = threading.Lock()

    def reordered_save(items):
        nonlocal save_count
        with count_lock:
            save_count += 1
            current = save_count
        if current == 1:
            first_save.set()
            second_saved.wait(0.2)
            original_save(items)
        else:
            original_save(items)
            second_saved.set()

    board._store.save = reordered_save

    def set_session(value):
        board.set(
            MediaSession(
                device_id="tv-1",
                content={"type": "url", "value": value},
                mode="play",
                privacy="household",
                started_at=1.0,
            )
        )

    first = threading.Thread(target=set_session, args=("https://example.local/first",))
    first.start()
    assert first_save.wait(1)
    second = threading.Thread(target=set_session, args=("https://example.local/second",))
    second.start()
    first.join(2)
    second.join(2)

    assert not first.is_alive() and not second.is_alive()
    assert board.get("tv-1").content["value"] == "https://example.local/second"
    reloaded = SessionBoard(path=path)
    assert reloaded.get("tv-1").content["value"] == "https://example.local/second"


# ── present() end-to-end (H29.2) ─────────────────────────────────────────────


def test_present_verifies_via_driver_status_and_records_session():
    driver = FakeDriver()
    director = _director(driver)
    result = director.present(_payload())
    assert result["ok"] is True and result["verified"] is True
    session = director.sessions.get("tv-1")
    assert session is not None and session.state == "playing"


def test_default_clock_records_real_start_time(monkeypatch):
    monkeypatch.setattr(time, "time", lambda: 1_234.5)
    director = _director(FakeDriver())

    assert director.present(_payload())["ok"] is True
    assert director.sessions.get("tv-1").started_at == 1_234.5


def test_present_never_claims_verified_when_status_disagrees():
    director = _director(FakeDriver(lie_in_status=True))
    result = director.present(_payload())
    assert result["ok"] is True
    assert result["verified"] is False
    assert result["verification"] == "unverified-driver-status"


def test_present_contract_denies_bad_mode_and_unbounded_duration():
    director = _director(FakeDriver())
    assert director.present(_payload(mode="teleport"))["ok"] is False
    too_long = director.present(_payload(duration_seconds=999_999_999))
    assert too_long["ok"] is False and too_long["reason"] == "duration_out_of_bounds"


def test_present_refuses_a_mode_the_target_does_not_support():
    driver = FakeDriver()
    director = _director(driver)

    result = director.present(_payload(mode="show"))

    assert result == {"ok": False, "reason": "unsupported_mode"}
    assert driver.calls == []


def test_present_with_no_driver_refuses_honestly():
    director = _director(driver=None)  # NullMediaDriver everywhere
    result = director.present(_payload())
    assert result["ok"] is False
    assert "no media driver" in result["reason"]
    assert director.sessions.get("tv-1") is None  # a refusal records nothing


def test_present_offline_device_is_refused_without_session():
    director = _director(FakeDriver(fail_play=True))
    result = director.present(_payload())
    assert result["ok"] is False and result["reason"] == "device_offline"
    assert director.sessions.get("tv-1") is None


def test_driver_exceptions_degrade_honestly_without_leaking_host_details():
    class ExplodingDriver(FakeDriver):
        def play(self, device, content):
            raise RuntimeError("secret host driver detail")

    director = _director(ExplodingDriver())
    result = director.present(_payload())

    assert result == {"ok": False, "reason": "driver_error", "state": "unavailable"}
    assert "secret host driver detail" not in repr(result)
    assert director.sessions.get("tv-1") is None


def test_status_exception_records_real_actuation_as_unverified():
    class StatusExplodes(FakeDriver):
        def status(self, device):
            raise RuntimeError("status transport broke")

    director = _director(StatusExplodes())
    result = director.present(_payload())

    assert result["ok"] is True
    assert result["verified"] is False
    assert result["verification"] == "unverified-driver-status"
    assert director.sessions.get("tv-1") is not None


# ── restore() rollback (the manifest's RollbackContract) ────────────────────


def test_restore_replays_previous_session_or_stops_to_idle():
    driver = FakeDriver()
    director = _director(driver)
    director.present(_payload())
    director.present(
        _payload(
            urgency="high",
            content={"type": "url", "value": "https://93.184.216.34/second"},
        )
    )
    restored = director.restore("tv-1")
    assert restored == {"ok": True, "restored": "previous_session"}
    assert director.sessions.get("tv-1").content["value"] == "https://93.184.216.34/x"

    # No previous snapshot → stop to idle and clear the session.
    idle = director.restore("tv-1")
    assert idle["ok"] is True and idle["restored"] == "idle"
    assert director.sessions.get("tv-1") is None


def test_repeated_interrupts_keep_only_one_bounded_restore_snapshot():
    director = _director(FakeDriver())
    director.present(_payload())
    director.present(
        _payload(
            urgency="high",
            content={"type": "url", "value": "https://93.184.216.34/second"},
        )
    )
    director.present(
        _payload(
            urgency="high",
            content={"type": "url", "value": "https://93.184.216.34/third"},
        )
    )

    previous = director.sessions.get("tv-1").previous
    assert previous is not None
    assert previous["previous"] is None


def test_restore_unknown_device_or_no_session_is_honest():
    director = _director(FakeDriver())
    assert director.restore("tv-1")["ok"] is False
    assert "no session" in director.restore("tv-1")["reason"]


def test_restore_driver_exception_preserves_the_session_and_redacts_error():
    class RestoreExplodes(FakeDriver):
        def stop(self, device):
            raise RuntimeError("private transport detail")

    director = _director(RestoreExplodes())
    director.sessions.set(
        MediaSession(
            device_id="tv-1",
            content={"type": "url", "value": "https://example.local/x"},
            mode="play",
            privacy="household",
            started_at=1.0,
        )
    )

    result = director.restore("tv-1")

    assert result == {"ok": False, "reason": "driver_error"}
    assert director.sessions.get("tv-1") is not None


# ── the O27 facade binding ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_facade_perform_mediates_and_invokes_the_director(monkeypatch):
    from agents.core.capability_actions import CapabilityActionAPI, PerformContext
    from agents.core.kernel import Decision, Verdict
    from agents.core.media_director import register_media_capability

    monkeypatch.setenv("JARVIS_UNIFIED_ACTION_API", "1")
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    seen = []

    def grant(action, capability=None, budget=None):
        seen.append(action.kind)
        return Decision(verdict=Verdict.GRANT, reason="test-grant", tier=1)

    api = CapabilityActionAPI(authorizer=grant)
    register_media_capability(api, _director(FakeDriver()))
    result = await api.perform(
        "action:media.present", _payload(), PerformContext(agent="jarvis", title="t")
    )
    assert seen == ["media.present"]
    assert result.status == "completed"
    assert result.output["ok"] is True and result.output["verified"] is True


@pytest.mark.asyncio
async def test_facade_deny_never_reaches_the_driver(monkeypatch):
    from agents.core.capability_actions import CapabilityActionAPI, PerformContext
    from agents.core.kernel import Decision, Verdict
    from agents.core.media_director import register_media_capability

    monkeypatch.setenv("JARVIS_UNIFIED_ACTION_API", "1")
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    driver = FakeDriver()

    api = CapabilityActionAPI(
        authorizer=lambda action, capability=None, budget=None: Decision(
            verdict=Verdict.DENY, reason="halted", tier=3
        )
    )
    register_media_capability(api, _director(driver))
    result = await api.perform(
        "action:media.present", _payload(), PerformContext(agent="jarvis", title="t")
    )
    assert result.status == "refused" and result.reason == "halted"
    assert driver.calls == []


@pytest.mark.asyncio
async def test_facade_restore_is_separately_authorized_before_driver_actuation(monkeypatch):
    from agents.core.capability_actions import CapabilityActionAPI, PerformContext
    from agents.core.kernel import Decision, Verdict
    from agents.core.media_director import register_media_capability

    monkeypatch.setenv("JARVIS_UNIFIED_ACTION_API", "1")
    monkeypatch.setenv("JARVIS_ACTION_KERNEL", "1")
    driver = FakeDriver()
    director = _director(driver)
    director.sessions.set(
        MediaSession(
            device_id="tv-1",
            content={"type": "url", "value": "https://example.local/current"},
            mode="play",
            privacy="household",
            started_at=1.0,
        )
    )
    seen = []

    def deny(action, capability=None, budget=None):
        seen.append(action.kind)
        return Decision(verdict=Verdict.DENY, reason="halted", tier=2)

    api = CapabilityActionAPI(authorizer=deny)
    register_media_capability(api, director)
    result = await api.perform(
        "action:media.restore",
        {"device_id": "tv-1"},
        PerformContext(agent="jarvis", title="restore tv-1"),
    )

    assert seen == ["media.restore"]
    assert result.status == "refused" and result.reason == "halted"
    assert driver.calls == []
    assert director.sessions.get("tv-1") is not None


def test_null_driver_is_the_default_and_refuses():
    device = MediaDevice(id="x", name="X", kind="speaker")
    outcome = NullMediaDriver().play(device, {"type": "url", "value": "https://x"})
    assert outcome["ok"] is False and "host seam" in outcome["reason"]


def test_contract_constraint_order_is_deterministic():
    decision = MEDIA_PRESENT_CONTRACT.evaluate({})
    assert decision.admissible is False
    assert decision.reason.startswith("missing_field")
