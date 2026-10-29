"""Private, nonsecret identity of one owner-selected signed provider."""
from __future__ import annotations

import asyncio
from contextlib import contextmanager
from contextvars import ContextVar

import httpx

from agents.core.llm.provider_selection import SelectionRecord, read_selection
from agents.core.security.ssrf import resolve_and_validate

from .admitted_profiles import AdmittedProviderProfile
from .credentials import CredentialBinding, credential_binding
from .packages import ProviderPackageError

AUTH_MARKER = 'nerva-selected-host-credential'
_CONSTRUCTION: ContextVar[object | None] = ContextVar('selected_provider_construction', default=None)


def current_construction():
    return _CONSTRUCTION.get()


@contextmanager
def construction_scope(runtime):
    if type(runtime) is not SelectedProviderRuntime:
        raise ProviderPackageError('trusted selected construction required')
    token = _CONSTRUCTION.set(runtime)
    try:
        yield
    finally:
        _CONSTRUCTION.reset(token)


class SelectedProviderRuntime:
    """No key value, live socket, or owner token is retained in a backend."""

    def __init__(self, service, selection: SelectionRecord):
        if (type(selection) is not SelectionRecord or service.enabled() is not True
                or read_selection() != selection):
            raise ProviderPackageError('current signed selection required')
        self.service = service
        self.selection = selection
        self.binding = selection.binding
        self.active = True
        self.backend = None
        self.router = None
        self.registry = service.registry()
        self.profile = self.registry.get(self.binding.provider_id)
        self.check()

    def check(self):
        if not self.active or read_selection() != self.selection:
            raise ProviderPackageError('signed selection changed')
        b = self.binding
        store = self.service._store()
        record = store.require_runnable(b.provider_id, expected_hash=b.package_hash,
                                        home=self.service.home)
        if (record.artifact_id != b.artifact_id or record.source != b.source
                or record.profile.default_base_url != b.endpoint
                or record.profile.auth_type != b.auth_type
                or b.model not in record.profile.fallback_models
                or self.service.home != b.home):
            raise ProviderPackageError('signed selection admission changed')
        policy, _note = record.profile.data_policy_for(b.model)
        if (b.unknown_price_ack is not True
                or policy in {'unknown', 'trains-on-inputs'} and b.data_policy_ack is not True):
            raise ProviderPackageError('signed selection risk consent unavailable')
        if not self.proven_consent(record.profile, policy):
            raise ProviderPackageError('signed selection consent proof unavailable')
        profile = self.service.registry().get(b.provider_id)
        if (type(profile) is not AdmittedProviderProfile
                or profile._package_hash != b.package_hash
                or profile._home != record.home):
            raise ProviderPackageError('signed selected profile changed')
        scope = credential_binding(record, self.service.home)
        status = self.service._credentials().status(scope)
        if (status['generation'] != b.credential_generation
                or b.auth_type != 'none' and not status['configured']):
            raise ProviderPackageError('signed selected credential changed')
        if (profile.id != self.profile.id or profile.backend_kind != self.profile.backend_kind
                or profile.fallback_models != self.profile.fallback_models
                or profile.data_policy != self.profile.data_policy):
            raise ProviderPackageError('signed selected declaration changed')
        return self.profile

    def proven_consent(self, profile, policy: str) -> bool:
        """Check current revision, vault generation and proof without a package lock."""
        from .selection_consent import verify

        try:
            b = self.binding
            if (not self.active or read_selection() != self.selection
                    or not verify(self.service.root, self.selection, profile, policy)):
                return False
            scope = CredentialBinding(b.authority, b.home, b.provider_id, b.source,
                                      b.artifact_id, b.package_hash, b.endpoint, b.auth_type)
            status = self.service._credentials().status(scope)
            return (status['generation'] == b.credential_generation
                    and (b.auth_type == 'none' or status['configured']))
        except Exception:
            return False

    def bind_backend(self, backend, router):
        if self.backend is not None or getattr(backend, '_selected_provider_runtime', None) is not self:
            raise ProviderPackageError('selected backend binding refused')
        self.backend, self.router = backend, router

    def retire(self):
        self.active = False

    def scope_material(self):
        b = self.binding
        return [b.authority, b.home, b.provider_id, b.source, b.artifact_id,
                b.package_hash, b.endpoint, b.model, self.selection.revision,
                b.credential_generation]

    async def resolve_public(self):
        host = httpx.URL(self.binding.endpoint).host
        addresses, error = await asyncio.to_thread(resolve_and_validate, host, mode='public')
        if error or not addresses:
            raise ProviderPackageError('selected provider DNS refused')
        # The resolver contract rejects a mixed public/private answer. Verify
        # every returned literal as well, even if a substituted resolver lied.
        for address in addresses:
            checked, reason = resolve_and_validate(address, mode='public')
            if reason or checked != [address]:
                raise ProviderPackageError('selected provider DNS refused')
        return addresses[0]

    def validate_locked_record(self, record):
        b = self.binding
        if (not self.active or record.provider_id != b.provider_id
                or record.artifact_id != b.artifact_id
                or record.package_hash != b.package_hash
                or record.source != b.source or record.profile.default_base_url != b.endpoint
                or record.profile.auth_type != b.auth_type
                or b.model not in record.profile.fallback_models):
            raise ProviderPackageError('selected provider signed record changed')

    def wire_request(self, request, address, key):
        b = self.binding
        logical = request.url
        endpoint = httpx.URL(b.endpoint)
        if (request.method != 'POST' or logical.scheme != 'https'
                or logical.host != endpoint.host or logical.port != endpoint.port
                or logical.userinfo or logical.fragment):
            raise ProviderPackageError('selected provider logical destination changed')
        headers = httpx.Headers(request.headers)
        auth = {'anthropic': 'x-api-key', 'gemini': 'x-goog-api-key'}.get(
            self.profile.backend_kind, 'authorization')
        if b.auth_type == 'none':
            if key not in (None, ''):
                raise ProviderPackageError('unexpected selected credential')
        else:
            if type(key) is not str or not key:
                raise ProviderPackageError('selected credential unavailable')
            headers[auth] = key if auth != 'authorization' else 'Bearer ' + key
        authority = logical.host
        if logical.port not in (None, 443):
            authority += ':' + str(logical.port)
        headers['Host'] = authority
        extensions = dict(request.extensions)
        extensions.pop('nerva.admitted', None)
        extensions['sni_hostname'] = logical.host
        return httpx.Request(request.method, logical.copy_with(host=address),
                             headers=headers, content=request.content, extensions=extensions)
