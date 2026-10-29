import hashlib
import json
from types import SimpleNamespace

import pytest

from agents.core.llm.providers import ProviderProfile
from agents.core.llm.providers.admitted_profiles import AdmittedProviderProfile
from agents.core.llm.providers.admitted_registry import AdmittedProviderRegistry
from agents.core.llm.providers.candidates import Candidate


def rig(tmp_path):
    raw = json.dumps({'schema_version': 1, 'id': 'addon', 'aliases': ['alias']}).encode()
    (tmp_path / 'addon').mkdir()
    (tmp_path / 'addon/provider.json').write_bytes(raw)
    candidate = Candidate('addon', ('alias',), 'user', 'home',
                          hashlib.sha256(raw).hexdigest(), None, tmp_path, 'addon')
    profile = ProviderProfile(id='addon', aliases=('alias',), display_name='Synthetic',
                              backend_kind='openai-compatible', is_user_defined=True,
                              capabilities=frozenset({'chat', 'cloud'}))
    record = SimpleNamespace(profile=profile, provider_id='addon', package_hash='a' * 64,
                             home='home', source='user', replacement_target=None,
                             members=(('provider.json', raw),))

    class Packages:
        revoked = False
        calls = []

        def require_runnable(self, provider_id, *, expected_hash, home):
            self.calls.append((provider_id, expected_hash, home))
            if self.revoked or expected_hash != record.package_hash or home != record.home:
                raise RuntimeError('refused')
            return record

    return candidate, record, Packages()


def test_discovery_never_promotes_or_selects_unbound_package(tmp_path):
    candidate, _record, packages = rig(tmp_path)
    registry = AdmittedProviderRegistry((), (candidate,), packages=packages,
                                       runtime=object(), home='home')
    assert registry.list() == [] and packages.calls == []


def test_explicit_exact_binding_exposes_host_profile_and_rechecks_revoke(tmp_path):
    candidate, record, packages = rig(tmp_path)
    registry = AdmittedProviderRegistry((), (candidate,), packages=packages,
                                       runtime=object(), home='home', bindings={'addon': record.package_hash})
    result = registry.get('alias')
    assert isinstance(result, AdmittedProviderProfile) and result.id == 'addon'
    packages.revoked = True
    with pytest.raises(KeyError):
        registry.get('alias')
    assert registry.list() == []


def test_binding_does_not_follow_new_package_hash_or_home(tmp_path):
    candidate, record, packages = rig(tmp_path)
    registry = AdmittedProviderRegistry((), (candidate,), packages=packages,
                                       runtime=object(), home='home', bindings={'addon': record.package_hash})
    record.package_hash = 'b' * 64
    with pytest.raises(KeyError):
        registry.get('addon')


def test_existing_builtin_choice_survives_inert_discovery(tmp_path):
    candidate, _record, packages = rig(tmp_path)
    builtin = ProviderProfile(id='builtin', display_name='Builtin', backend_kind='openai-compatible')
    registry = AdmittedProviderRegistry((builtin,), (candidate,), packages=packages, runtime=object(),
                                       home='home')
    assert registry.get('builtin') is builtin


def test_catalog_matches_registry_shape_and_excludes_revoked_entries(tmp_path):
    candidate, record, packages = rig(tmp_path)
    builtin = ProviderProfile(id='builtin', display_name='Builtin', backend_kind='openai-compatible')
    registry = AdmittedProviderRegistry((builtin,), (candidate,), packages=packages,
                                       runtime=object(), home='home',
                                       bindings={'addon': record.package_hash})
    catalog = registry.catalog(environ={'UNRELATED_SECRET': 'value'})
    assert catalog == [builtin.status(environ={'UNRELATED_SECRET': 'value'}),
                       registry.get('addon').status(environ={'UNRELATED_SECRET': 'value'})]
    packages.revoked = True
    assert registry.catalog() == [builtin.status()]
