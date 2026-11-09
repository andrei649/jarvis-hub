"""H492: owner website refusals are local, bounded, and effective before egress."""

import sqlite3

import httpx
import pytest

from agents.core import settings_db, web_tools
from agents.core.browser_agent import BrowserPolicy, FixtureBrowserPolicy
from agents.core.plugins import websearch
from agents.core.plugins.websearch import WebSearchPlugin
from agents.core.security import website_policy
from agents.core.security.website_policy import website_refusal
from tests.test_web_tools import FakePlugin, _call, _server


def _settings(monkeypatch, tmp_path):
    path = tmp_path / "settings.db"
    monkeypatch.setattr(settings_db, "DB_PATH", path)
    monkeypatch.setattr(settings_db, "_initialized", False)
    monkeypatch.setattr(settings_db, "_initialized_for_path", None)
    return path


def test_fresh_missing_store_is_empty_without_creating_runtime_files(monkeypatch, tmp_path):
    path = _settings(monkeypatch, tmp_path)
    assert website_refusal() is None
    assert website_refusal("https://public.example/") is None
    assert not path.exists()


def test_owner_rules_block_apex_subdomain_glob_and_shared_file_in_safe_mode(monkeypatch, tmp_path):
    _settings(monkeypatch, tmp_path)
    monkeypatch.setenv("JARVIS_SAFE_MODE", "1")
    shared = tmp_path / "shared-sites.txt"
    shared.write_text("# shared\nshared.example\n", encoding="utf-8")
    policy = {"enabled": True, "domains": ["deny.example", "*.wild.example"],
              "shared_files": [str(shared)]}
    assert settings_db.put_category("security", {"website_blocklist": policy}) == (1, [])
    for url in ("https://deny.example/", "https://child.deny.example/",
                "https://sub.wild.example/", "https://shared.example/"):
        assert website_refusal(url) == "website_blocked"
    assert website_refusal("https://wild.example/") is None
    assert website_refusal("https://notdeny.example/") is None


def test_invalid_owner_policy_is_rejected_before_persistence(monkeypatch, tmp_path):
    _settings(monkeypatch, tmp_path)
    bad = {"enabled": True, "domains": "deny.example", "shared_files": []}
    assert settings_db.validate_category("security", {"website_blocklist": bad})
    found, value = settings_db.read_setting("security", "website_blocklist")
    assert found and value != bad


def test_unreadable_enabled_shared_file_refuses_every_website(monkeypatch, tmp_path):
    _settings(monkeypatch, tmp_path)
    policy = {"enabled": True, "domains": [], "shared_files": [str(tmp_path / "missing.txt")]}
    assert settings_db.put_category("security", {"website_blocklist": policy}) == (1, [])
    assert website_refusal() == "website_policy_unavailable"
    assert website_refusal("https://public.example/") == "website_policy_unavailable"


def test_unreadable_existing_settings_store_is_not_treated_as_fresh(monkeypatch, tmp_path):
    path = _settings(monkeypatch, tmp_path)
    path.write_bytes(b"unreadable sqlite content")
    assert website_refusal() == "website_policy_unavailable"


def test_removed_seen_owner_store_remains_unavailable_after_cache_invalidation(monkeypatch, tmp_path):
    path = _settings(monkeypatch, tmp_path)
    settings_db.put_category("security", {"website_blocklist": {
        "enabled": True, "domains": ["blocked.example"], "shared_files": []}})
    assert website_refusal("https://blocked.example/") == "website_blocked"
    path.unlink()
    website_policy.invalidate_cache()
    assert website_refusal("https://blocked.example/") == "website_policy_unavailable"
    assert not path.exists()


def test_disappearing_store_during_guard_read_is_not_recreated(monkeypatch, tmp_path):
    path = _settings(monkeypatch, tmp_path)
    settings_db.put_category("security", {"website_blocklist": {
        "enabled": True, "domains": ["blocked.example"], "shared_files": []}})
    monkeypatch.setattr(settings_db, "_initialized", False)
    monkeypatch.setattr(settings_db, "_initialized_for_path", None)
    original_lstat = type(path).lstat
    removed = [False]

    def vanish_after_lstat(candidate, *args, **kwargs):
        result = original_lstat(candidate, *args, **kwargs)
        if candidate == path and not removed[0]:
            removed[0] = True
            path.unlink()
        return result

    monkeypatch.setattr(type(path), "lstat", vanish_after_lstat)
    assert website_refusal("https://blocked.example/") == "website_policy_unavailable"
    assert removed == [True]
    assert not path.exists()


def test_removed_known_policy_row_is_not_implicit_allow(monkeypatch, tmp_path):
    path = _settings(monkeypatch, tmp_path)
    settings_db.put_category("security", {"website_blocklist": {
        "enabled": True, "domains": ["blocked.example"], "shared_files": []}})
    assert website_refusal("https://blocked.example/") == "website_blocked"
    with sqlite3.connect(path) as conn:
        conn.execute("DELETE FROM settings WHERE category='security' AND key='website_blocklist'")
    website_policy.invalidate_cache()
    assert website_refusal("https://blocked.example/") == "website_policy_unavailable"


def test_legacy_environment_blocklist_still_narrows_when_owner_policy_disabled(monkeypatch, tmp_path):
    _settings(monkeypatch, tmp_path)
    monkeypatch.setenv("JARVIS_WEB_BLOCKED_DOMAINS", "legacy.example")
    assert website_refusal("https://sub.legacy.example/path") == "website_blocked"
    assert website_refusal("https://other.example/") is None


def test_owner_edit_narrows_immediately_after_cached_read(monkeypatch, tmp_path):
    _settings(monkeypatch, tmp_path)
    first = {"enabled": True, "domains": ["first.example"], "shared_files": []}
    second = {"enabled": True, "domains": ["second.example"], "shared_files": []}
    settings_db.put_category("security", {"website_blocklist": first})
    assert website_refusal("https://first.example/") == "website_blocked"
    settings_db.put_category("security", {"website_blocklist": second})
    assert website_refusal("https://second.example/") == "website_blocked"
    assert website_refusal("https://first.example/") is None


def test_shared_file_cache_expires_within_thirty_seconds_and_is_profile_scoped(monkeypatch, tmp_path):
    _settings(monkeypatch, tmp_path)
    website_policy.invalidate_cache()
    clock = [100.0]
    monkeypatch.setattr(website_policy.time, "monotonic", lambda: clock[0])
    shared = tmp_path / "shared.txt"
    shared.write_text("first.example\n", encoding="utf-8")
    settings_db.put_category("security", {"website_blocklist": {
        "enabled": True, "domains": [], "shared_files": [str(shared)]}})
    assert website_refusal("https://first.example/") == "website_blocked"
    shared.write_text("second.example\n", encoding="utf-8")
    clock[0] += 29.9
    assert website_refusal("https://first.example/") == "website_blocked"
    clock[0] += 0.2
    assert website_refusal("https://second.example/") == "website_blocked"
    other = tmp_path / "other.db"
    monkeypatch.setattr(settings_db, "DB_PATH", other)
    monkeypatch.setattr(settings_db, "_initialized", False)
    monkeypatch.setattr(settings_db, "_initialized_for_path", None)
    assert website_refusal("https://second.example/") is None


def test_malformed_or_oversize_enabled_shared_file_is_named_unavailable(monkeypatch, tmp_path):
    _settings(monkeypatch, tmp_path)
    shared = tmp_path / "shared.txt"
    shared.write_bytes(b"\xff\xfe")
    settings_db.put_category("security", {"website_blocklist": {
        "enabled": True, "domains": [], "shared_files": [str(shared)]}})
    assert website_refusal() == "website_policy_unavailable"
    shared.write_bytes(b"a" * (256 * 1024 + 1))
    website_policy.invalidate_cache()
    assert website_refusal("https://public.example/") == "website_policy_unavailable"


def test_owner_rule_preserves_full_fnmatch_and_idna_host_equivalence(monkeypatch, tmp_path):
    _settings(monkeypatch, tmp_path)
    policy = {"enabled": True,
              "domains": ["a?.example.com", "[ab].class.example", "exämple.example",
                          "https://url.example?source=owner"], "shared_files": []}
    assert settings_db.validate_category("security", {"website_blocklist": policy}) == []
    settings_db.put_category("security", {"website_blocklist": policy})
    for url in ("https://ab.example.com/", "https://a.class.example/",
                "https://xn--exmple-cua.example/", "https://url.example/other"):
        assert website_refusal(url) == "website_blocked"
    assert website_refusal("https://a.example.com/") is None


def test_ipv6_rule_matches_equivalent_literal_spellings(monkeypatch, tmp_path):
    _settings(monkeypatch, tmp_path)
    settings_db.put_category("security", {"website_blocklist": {
        "enabled": True, "domains": ["https://[2606:4700:4700::1111]/"],
        "shared_files": []}})
    assert website_refusal("https://[2606:4700:4700:0:0:0:0:1111]/") == "website_blocked"


def test_shared_file_reader_rejects_growth_without_unbounded_read(monkeypatch, tmp_path):
    shared = tmp_path / "shared.txt"
    shared.write_text("first.example\n", encoding="utf-8")
    original_open = website_policy.os.open

    def growing_open(path, flags, *args, **kwargs):
        fd = original_open(path, flags, *args, **kwargs)
        if path == shared:
            shared.write_bytes(b"a" * (256 * 1024 + 1))
        return fd

    monkeypatch.setattr(website_policy.os, "open", growing_open)
    monkeypatch.setattr(type(shared), "read_bytes", lambda _path: pytest.fail("unbounded file read"))
    with pytest.raises(website_policy.WebsitePolicyError):
        website_policy._file_rules(str(shared))


def test_shared_file_reader_rejects_nonregular_input(monkeypatch, tmp_path):
    with pytest.raises(website_policy.WebsitePolicyError):
        website_policy._file_rules(str(tmp_path))


def test_real_browser_policy_refuses_owner_block_before_dns(monkeypatch, tmp_path):
    _settings(monkeypatch, tmp_path)
    policy = {"enabled": True, "domains": ["blocked.example"], "shared_files": []}
    assert settings_db.put_category("security", {"website_blocklist": policy}) == (1, [])
    monkeypatch.setattr("agents.core.security.ssrf.check_ssrf",
                        lambda _url: pytest.fail("blocked site reached DNS"))
    allowed, reason = BrowserPolicy(["blocked.example"]).domain_allowed("https://blocked.example/path")
    assert allowed is False and reason == "website_blocked"


def test_fixture_browser_policy_does_not_bypass_owner_block(monkeypatch, tmp_path):
    _settings(monkeypatch, tmp_path)
    settings_db.put_category("security", {"website_blocklist": {
        "enabled": True, "domains": ["fixture.browser.test"], "shared_files": []}})
    policy = FixtureBrowserPolicy("http://fixture.browser.test:8100/")
    assert policy.domain_allowed("http://fixture.browser.test:8100/page") == (
        False, "website_blocked")


@pytest.mark.asyncio
async def test_page_reader_refuses_blocked_redirect_before_target_transport(monkeypatch, tmp_path):
    _settings(monkeypatch, tmp_path)
    settings_db.put_category("security", {"website_blocklist": {
        "enabled": True, "domains": ["blocked.example"], "shared_files": []}})
    monkeypatch.setattr(websearch, "resolve_and_validate", lambda _host, *a, **k: (["93.184.216.34"], None))
    seen = []

    def reply(request):
        seen.append((request.url.path, request.headers.get("host")))
        return httpx.Response(302, headers={"Location": "https://blocked.example/final"})

    reader = WebSearchPlugin()
    outcome = await reader.read_page("https://public.example/start", _transport=httpx.MockTransport(reply))
    assert outcome.refusal == "site_blocked"
    assert seen == [("/start", "public.example")]


@pytest.mark.asyncio
async def test_toolrpc_search_refuses_unavailable_policy_before_provider_query(monkeypatch, tmp_path):
    _settings(monkeypatch, tmp_path)
    policy = {"enabled": True, "domains": [], "shared_files": [str(tmp_path / "missing.txt")]}
    assert settings_db.put_category("security", {"website_blocklist": policy}) == (1, [])
    plugin = FakePlugin(rows=[{"title": "public", "url": "https://public.example/"}])
    out = await _call(_server(plugin), web_tools.TOOL_SEARCH, {"query": "private query"})
    assert out["result"]["reason"] == "website_policy_unavailable"
    assert plugin.search_calls == []


@pytest.mark.asyncio
async def test_toolrpc_search_drops_owner_blocked_result_and_extract_refuses_before_fetch(monkeypatch, tmp_path):
    _settings(monkeypatch, tmp_path)
    policy = {"enabled": True, "domains": ["blocked.example"], "shared_files": []}
    assert settings_db.put_category("security", {"website_blocklist": policy}) == (1, [])
    plugin = FakePlugin(rows=[{"title": "blocked", "url": "https://blocked.example/page"},
                              {"title": "kept", "url": "https://public.example/page"}], page="public body")
    server = _server(plugin)
    found = await _call(server, web_tools.TOOL_SEARCH, {"query": "q"})
    assert [row["title"] for row in found["result"]["results"]] == ["kept"]
    blocked = await _call(server, web_tools.TOOL_EXTRACT, {"url": "https://blocked.example/page"})
    assert blocked["result"]["reason"] == "site_blocked"
    assert plugin.fetch_calls == []
