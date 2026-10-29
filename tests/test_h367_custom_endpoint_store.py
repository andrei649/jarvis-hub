"""H367 catalog identity and mutually exclusive owner choice, offline."""
import pytest

from agents.core import settings_db


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_db, "DB_PATH", tmp_path / "settings.db")
    monkeypatch.setattr(settings_db, "_initialized", False)
    settings_db.init_db(force=True)
    return settings_db.DB_PATH


def test_named_records_survive_reopen_and_rename_preserves_identity(store):
    from agents.core.llm import custom_endpoints as custom

    first = custom.create_endpoint("local-a", "Local A", "http://127.0.0.1:1234/v1",
                                   "model-a", "none", "local")
    second = custom.create_endpoint("local-b", "Local B", "http://localhost:1235/v1",
                                    "model-b", "none", "local")
    assert first.identity == "custom:local-a"
    assert [row.key for row in custom.list_endpoints()] == ["local-a", "local-b"]
    renamed = custom.rename_endpoint("local-a", "Renamed", expected_revision=first.revision)
    assert renamed.identity == first.identity
    assert custom.custom_provider_slug(renamed) == "custom:local-a"
    assert "Renamed" in custom.custom_provider_aliases(renamed)
    assert "Local A" in custom.custom_provider_aliases(renamed)
    assert custom.resolve_custom_provider_alias('Local A').identity == 'custom:local-a'
    assert custom.resolve_custom_provider_alias('Renamed').identity == 'custom:local-a'
    assert custom.resolve_custom_provider_alias('custom:local-a').identity == 'custom:local-a'
    assert custom.resolve_custom_provider_alias('custom') is None
    assert custom.read_endpoint("local-b") == second
    with pytest.raises(custom.CustomEndpointConflict):
        custom.rename_endpoint("local-a", "Stale", expected_revision=first.revision)
    with pytest.raises(custom.CustomEndpointInvalid):
        custom.create_endpoint("local-a", "Duplicate", "http://127.0.0.1:9/v1",
                               "m", "none", "local")
    with pytest.raises(custom.CustomEndpointInvalid):
        custom.rename_endpoint('local-b', 'Local A', expected_revision=second.revision)


def test_choice_epoch_and_generic_pair_invalidation(store):
    from agents.core.llm import custom_endpoints as custom

    row = custom.create_endpoint("local-a", "A", "http://127.0.0.1:1234/v1",
                                 "m", "none", "local")
    before = custom.read_choice()
    assert before.active_key is None
    chosen = custom.activate_endpoint(row.key, expected_revision=row.revision,
                                      expected_choice_epoch=before.epoch, proof="0" * 64)
    assert chosen.active_key == row.key and chosen.epoch == before.epoch + 1
    settings_db.put_category("llm", {"compatible_provider": "openrouter"})
    invalidated = custom.read_choice()
    assert invalidated.active_key is None and invalidated.epoch > chosen.epoch


def test_invalid_metadata_refused_and_inactive_delete_preserves_choice(store):
    from agents.core.llm import custom_endpoints as custom

    for key, url, policy in (("UPPER", "http://127.0.0.1:2/v1", "local"),
                             ("ok", "http://user@127.0.0.1/v1", "local"),
                             ("ok", "http://public.invalid/v1", "unknown"),
                             ("ok", "http://192.168.1.3/v1", "local")):
        with pytest.raises(custom.CustomEndpointInvalid):
            custom.create_endpoint(key, "A", url, "m", "none", policy)
    with pytest.raises(custom.CustomEndpointInvalid):
        custom.create_endpoint('reserved', 'custom:other',
                               'http://127.0.0.1:1234/v1', 'm', 'none', 'local')
    first = custom.create_endpoint("one", "One", "http://127.0.0.1:1234/v1", "m", "none", "local")
    second = custom.create_endpoint("two", "Two", "http://127.0.0.1:1235/v1", "m", "none", "local")
    chosen = custom.activate_endpoint(first.key, expected_revision=first.revision,
                                      expected_choice_epoch=custom.read_choice().epoch, proof="0" * 64)
    custom.delete_endpoint(second.key, expected_revision=second.revision)
    assert custom.read_choice() == chosen


def test_signed_cas_atomically_retires_custom_and_bumps_common_epoch(store):
    from agents.core.llm import custom_endpoints as custom
    from agents.core.llm import provider_selection

    row = custom.create_endpoint("one", "One", "http://127.0.0.1:1234/v1", "m", "none", "local")
    active = custom.activate_endpoint(row.key, expected_revision=row.revision,
                                      expected_choice_epoch=custom.read_choice().epoch,
                                      proof="0" * 64)
    binding = provider_selection.SelectionBinding(
        "local-owner-v1", "owner-home", "synthetic", "m", "user", "1" * 32,
        "2" * 64, "https://synthetic.invalid/v1", "none", 0,
        unknown_price_ack=True, choice_epoch=active.epoch + 1)
    provider_selection.compare_and_swap(store, binding,
                                        expected_revision=provider_selection.current_revision())
    after = custom.read_choice()
    assert after.active_key is None and after.epoch == active.epoch + 1
    assert provider_selection.read_selection().binding == binding


def test_custom_activation_retires_signed_and_bumps_common_epoch(store):
    from agents.core.llm import custom_endpoints as custom
    from agents.core.llm import provider_selection

    current = custom.read_choice()
    binding = provider_selection.SelectionBinding(
        "local-owner-v1", "owner-home", "synthetic", "m", "user", "1" * 32,
        "2" * 64, "https://synthetic.invalid/v1", "none", 0,
        unknown_price_ack=True, choice_epoch=current.epoch + 1)
    selected = provider_selection.compare_and_swap(store, binding,
                                                   expected_revision=provider_selection.current_revision())
    row = custom.create_endpoint("one", "One", "http://127.0.0.1:1234/v1", "m", "none", "local")
    custom.activate_endpoint(row.key, expected_revision=row.revision,
                             expected_choice_epoch=custom.read_choice().epoch,
                             proof="0" * 64)
    assert provider_selection.read_selection() is None
    assert provider_selection.current_revision() == selected.revision + 1


def test_fresh_registry_composes_custom_without_mutating_builtins(store):
    from agents.core.llm import custom_endpoints as custom
    from agents.core.llm.providers import DEFAULT_REGISTRY, custom_provider_registry

    custom.create_endpoint("one", "One", "http://127.0.0.1:1234/v1", "m", "none", "local")
    composed = custom_provider_registry()
    assert composed.get("custom:one").fallback_models == ("m",)
    assert composed.get("custom:one").auth_env is None
    with pytest.raises(KeyError):
        DEFAULT_REGISTRY.get("custom:one")


def test_url_classes_allow_bounded_proxy_prefix_and_refuse_ambiguous_paths(store):
    from agents.core.llm.custom_endpoints import CustomEndpointInvalid, classify_url

    assert classify_url('http://localhost:1234/api/v1') == 'loopback'
    assert classify_url('http://modelbox.lan:1234/v1') == 'lan'
    assert classify_url('http://192.168.1.3:1234/v1') == 'lan'
    assert classify_url('https://example.org/api/v1') == 'public'
    # Admission must agree with the physical LAN resolver, which accepts only
    # loopback and RFC1918 destinations rather than all ipaddress.is_private.
    for address in ('198.18.0.1', '100.64.0.1', '169.254.1.1'):
        with pytest.raises(CustomEndpointInvalid):
            classify_url(f'http://{address}:1234/v1')
    for url in ('https://example.org/v1/../v1', 'https://example.org/%76%31',
                'https://example.org/v1?model=m', 'http://example.org/v1',
                'http://metadata.google.internal/v1'):
        with pytest.raises(CustomEndpointInvalid):
            classify_url(url)


def test_existing_pair_trigger_migrates_without_double_epoch_bump(store):
    from agents.core.llm import custom_endpoints as custom

    conn = settings_db.get_conn()
    with conn:
        conn.execute('DROP TRIGGER signed_selection_pair_update')
        conn.execute('CREATE TRIGGER signed_selection_pair_update AFTER UPDATE OF value ON settings '
                     "WHEN NEW.category='llm' AND NEW.key='compatible_model' BEGIN "
                     'UPDATE signed_provider_selection SET revision=revision+1,record_json=NULL,'
                     'record_hash=NULL WHERE singleton=1; END')
    conn.close()
    settings_db.init_db()
    row = custom.create_endpoint('one', 'One', 'http://127.0.0.1:1234/v1',
                                 'm', 'none', 'local')
    chosen = custom.activate_endpoint(row.key, expected_revision=row.revision,
                                      expected_choice_epoch=custom.read_choice().epoch,
                                      proof='0' * 64)
    settings_db.put_category('llm', {'compatible_model': 'other'})
    after = custom.read_choice()
    assert after.active_key is None
    assert after.epoch == chosen.epoch + 1


def test_corrupt_custom_catalog_does_not_hide_builtin_profiles(store):
    from agents.core.llm import custom_endpoints as custom
    from agents.core.llm.hybrid_router import HybridRouter

    custom.create_endpoint('one', 'One', 'http://127.0.0.1:1234/v1',
                           'm', 'none', 'local')
    conn = settings_db.get_conn()
    with conn:
        conn.execute("UPDATE custom_endpoints SET data_policy='corrupt' WHERE key='one'")
    conn.close()
    catalog = HybridRouter.provider_catalog(object())
    assert any(row['id'] == 'openrouter' for row in catalog)
    assert all(row['id'] != 'custom:one' for row in catalog)
