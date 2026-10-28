"""Owner-controlled signed provider installation, with no implicit selection.

The HTTP controller supplies a live explicit OwnerConsentActor. No request body,
actor string or ambient principal can become permanent approval authority.
"""
from __future__ import annotations

import hashlib
import os
import re
import tempfile
import threading
import time
from copy import deepcopy
from urllib.parse import urlsplit

from agents.core.autonomy.consent_types import OwnerConsentActor
from agents.core.kernel import Decision, Verdict

from .admitted_registry import AdmittedProviderRegistry
from .candidates import Candidate
from .hook_runtime import ProviderHookRuntime
from .packages import ProviderPackageError, ProviderPackageStore, _secure_root

_NAME = re.compile(r'[a-z0-9][a-z0-9._-]{0,63}\Z')
_SOURCES = {'user', 'legacy', 'bundled'}
_PREVIEW_KINDS = {'openai-compatible', 'deepinfra-chat',
                  'openai-compatible-local', 'ollama',
                  'gemini', 'anthropic', 'openai-responses', 'xai-responses'}
_PREVIEW_MODES = {'chat_completions', 'gemini_generate_content',
                  'anthropic_messages', 'responses'}
_PREVIEW_AUTH = {'none', 'bearer', 'api-key'}
_PREVIEW_CAPABILITIES = {'chat', 'cloud', 'local', 'vision', 'streaming',
                         'reasoning', 'reasoning-effort', 'prompt-cache-key',
                         'model-catalog', 'long-context'}


def _owner_current(actor):
    try:
        return (type(actor) is OwnerConsentActor and actor.label in {'admin', 'owner'}
                and actor.decided_by == 'admin' and actor.live() is True)
    except Exception:
        return False


class ProviderInstallService:
    def __init__(self, *, root, signing, profile, kernel, enabled=lambda: False,
                 home, runner=None):
        from pathlib import Path
        self.root = Path(root)
        self.signing, self.profile, self.kernel = signing, profile, kernel
        self.enabled, self.home, self.runner = enabled, home, runner

    def _ready(self):
        if self.enabled() is not True:
            raise ProviderPackageError('provider installation is disabled')

    def _owner(self, actor):
        self._ready()
        if not _owner_current(actor):
            raise ProviderPackageError('current authenticated owner required')

    def incoming(self, source):
        self._ready()
        if source not in _SOURCES:
            raise ProviderPackageError('unknown provider source')
        return _secure_root(self.root / 'incoming' / source)[0]

    def _store(self, *, owner_authorizer=None, actor=None):
        self._ready()
        def authorize(action):
            if (self.enabled() is not True
                    or action.payload.get('phase') == 'promote' and not _owner_current(actor)):
                return Decision(Verdict.DENY, reason='provider owner or runtime unavailable')
            gate = self.kernel()
            if not callable(gate):
                return Decision(Verdict.DENY, reason='bound action kernel unavailable')
            # This callback is called only after the store has reloaded exact
            # permanent owner approval. Bind that receipt to the complete Action;
            # a wider or changed action cannot borrow it.
            snapshot = deepcopy(action)
            return gate(action, approval_check=lambda candidate: candidate == snapshot)
        return ProviderPackageStore(self.root / 'packages', signing=self.signing,
            authorizer=authorize, enabled=self.enabled, owner_authorizer=owner_authorizer)

    @staticmethod
    def _preview_profile(profile):
        """Validate and expose only typed trust attributes before any commit."""
        address = profile.default_base_url
        if (type(address) is not str or not address or len(address) > 2048
                or any(ord(char) < 33 or ord(char) > 126 for char in address)):
            raise ProviderPackageError('provider endpoint is invalid')
        try:
            endpoint = urlsplit(address)
            host, port = endpoint.hostname, endpoint.port
        except ValueError as exc:
            raise ProviderPackageError('provider endpoint is invalid') from exc
        if (endpoint.scheme not in {'https', 'http'} or not host
                or len(host) > 253 or re.fullmatch(r'[A-Za-z0-9.:-]+', host) is None
                or endpoint.username is not None or endpoint.password is not None
                or endpoint.query or endpoint.fragment):
            raise ProviderPackageError('provider endpoint is invalid')
        if (profile.backend_kind not in _PREVIEW_KINDS
                or profile.api_mode not in _PREVIEW_MODES
                or profile.auth_type not in _PREVIEW_AUTH
                or any(type(value) is not str or value not in _PREVIEW_CAPABILITIES
                       for value in profile.capabilities)):
            raise ProviderPackageError('provider trust attributes are unsupported')
        # Free-text package metadata, model names, notes, paths, and header names
        # never enter this response. The URL path is likewise omitted.
        return {'id': profile.id,
                'endpoint': {'scheme': endpoint.scheme, 'host': host, 'port': port},
                'backend_kind': profile.backend_kind, 'api_mode': profile.api_mode,
                'auth': {'type': profile.auth_type,
                         'configured': profile.auth_type == 'none'},
                'capabilities': sorted(profile.capabilities),
                'data_policy': {'policy': profile.data_policy},
                'supports_health_check': profile.supports_health_check,
                'supports_model_listing': profile.supports_model_listing}

    @staticmethod
    def preview(record):
        profile = ProviderInstallService._preview_profile(record.profile)
        return {'artifact_id': record.artifact_id, 'provider_id': record.provider_id,
                'package_hash': record.package_hash, 'source': record.source,
                'replacement_target': record.replacement_target, 'hooks': list(record.hooks),
                'endpoint_host': profile['endpoint']['host'],
                'auth_type': record.profile.auth_type, 'backend_kind': record.profile.backend_kind,
                'profile_summary': profile,
                'sandbox_image': record.manifest['runtime_image'],
                'sandbox': dict(record.manifest['sandbox']),
                'member_count': len(record.members),
                'member_bytes': sum(len(data) for _, data in record.members)}

    def stage(self, name, *, profile, hooks, source, actor, replacement_target=None):
        self._owner(actor)
        if type(name) is not str or _NAME.fullmatch(name) is None or name in {'.', '..'}:
            raise ProviderPackageError('invalid server-managed candidate reference')
        # Package metadata may not choose host credential/environment owners.
        if profile.auth_env or profile.env_vars or profile.base_url_env:
            raise ProviderPackageError('provider credential binding must be host owned')
        from agents.core.llm.provider_request import profile_headers
        profile_headers(profile)
        self._preview_profile(profile)
        record = self._store().stage(self.incoming(source) / name, profile=profile,
            hooks=hooks, source=source, home=self.home if source == 'user' else None,
            replacement_target=replacement_target, sandbox_profile=self.profile)
        return self.preview(record)

    def inspect(self, artifact_id, *, actor):
        self._owner(actor)
        return self.preview(self._store().inspect(artifact_id))

    def propose(self, artifact_id, *, actor):
        self._owner(actor)
        store = self._store()
        record = store.inspect(artifact_id)
        proposal = store.propose(artifact_id)
        return {'proposal_id': proposal, 'status': 'pending', **self.preview(record)}

    def decide(self, proposal_id, *, artifact_id, package_hash, approved, permanent, actor):
        self._owner(actor)
        if type(approved) is not bool or permanent is not True:
            raise ProviderPackageError('literal permanent owner decision required')
        deadline, consumed, lock = time.monotonic() + 30, False, threading.Lock()
        def owner_authorizer(proposal, record, label):
            nonlocal consumed
            with lock:
                if (consumed or time.monotonic() > deadline or label != 'owner'
                        or proposal != proposal_id or record.artifact_id != artifact_id
                        or record.package_hash != package_hash or not _owner_current(actor)):
                    return False
                consumed = True
                return True
        store = self._store(owner_authorizer=owner_authorizer)
        record = store.inspect(artifact_id)
        if record.package_hash != package_hash:
            raise ProviderPackageError('provider decision scope changed')
        if not _owner_current(actor):
            raise ProviderPackageError('provider owner authority expired')
        store.decide(proposal_id, approved=approved, permanent=True, actor='owner',
                     expected_artifact_id=artifact_id, expected_package_hash=package_hash)
        return {'proposal_id': proposal_id, 'status': 'approved' if approved else 'denied'}

    def promote(self, proposal_id, *, actor):
        self._owner(actor)
        return {'status': 'active', **self.preview(self._store(actor=actor).promote(proposal_id))}

    def revoke(self, provider_id, *, actor):
        self._owner(actor)
        self._store().revoke(provider_id)
        return {'provider_id': provider_id, 'status': 'revoked'}

    async def revoke_async(self, provider_id, *, actor):
        self._owner(actor)
        await self._store().revoke_async(provider_id)
        return {'provider_id': provider_id, 'status': 'revoked'}

    def registry(self):
        from . import DEFAULT_REGISTRY
        store = self._store()
        records = store.list_active(home=self.home)
        chosen = {}
        rank = {'bundled': 1, 'legacy': 2, 'user': 3}
        for record in records:
            if record.provider_id not in chosen or rank[record.source] > rank[chosen[record.provider_id].source]:
                chosen[record.provider_id] = record
        runtime = ProviderHookRuntime(store, self.profile, self.root / 'runs',
                                      runner=self.runner, enabled=self.enabled)
        candidates = []
        for record in chosen.values():
            metadata = dict(record.members)['provider.json']
            directory = _secure_root(self.root / 'views' / record.artifact_id)[0]
            # This host cache contains metadata only. Executable members remain
            # in the encrypted signed store and are projected only by the worker.
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(dir=directory, delete=False) as target:
                    temporary = target.name
                    target.write(metadata)
                    target.flush()
                    os.fsync(target.fileno())
                os.replace(temporary, directory / 'provider.json')
            finally:
                if temporary is not None and os.path.exists(temporary):
                    os.unlink(temporary)
            candidates.append(Candidate(record.provider_id, record.profile.aliases, record.source,
                record.home, hashlib.sha256(metadata).hexdigest(), record.replacement_target,
                root=directory.parent, directory=record.artifact_id))
        return AdmittedProviderRegistry(DEFAULT_REGISTRY.list(), candidates, packages=store,
            runtime=runtime, home=self.home,
            bindings={identity:record.package_hash for identity,record in chosen.items()})


def get_install_service(orch):
    """Lazy production composition; disabled status creates no state or runtime."""
    import os
    def enabled():
        return os.environ.get('JARVIS_PROVIDER_PLUGINS', '').strip().lower() in {'1','true','yes','on'}
    if orch is None or not enabled():
        return None
    existing = getattr(orch, 'provider_install_service', None)
    if existing is not None:
        return existing
    from agents.core.acquisition.managed_signing import ManagedSigningKeyStore
    from agents.core.acquisition.sandbox_profile import AcquisitionSandboxProfile
    from agents.core.kernel.binding import make_action_kernel
    from agents.core.paths import data_path
    root = data_path('provider-plugins')
    service = ProviderInstallService(root=root,
        signing=ManagedSigningKeyStore(data_path('acquisition') / 'signing'),
        profile=AcquisitionSandboxProfile(image=os.environ.get('JARVIS_ACQUISITION_SANDBOX_IMAGE','')),
        kernel=lambda: make_action_kernel(orch), enabled=enabled, home=str(root))
    orch.provider_install_service = service
    return service
