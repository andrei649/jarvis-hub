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
from contextvars import ContextVar
from copy import deepcopy
from urllib.parse import urlsplit

from agents.core.autonomy.consent_types import OwnerConsentActor
from agents.core.kernel import Action, Decision, Verdict

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
_CREDENTIAL_RECEIPT: ContextVar[tuple | None] = ContextVar(
    'signed_provider_credential_receipt', default=None)


def _owner_current(actor):
    try:
        return (type(actor) is OwnerConsentActor and actor.label in {'admin', 'owner'}
                and actor.decided_by == 'admin' and actor.live() is True)
    except Exception:
        return False


def credential_receipt_matches(action):
    """Kernel-visible proof of this exact live service operation."""
    receipt = _CREDENTIAL_RECEIPT.get()
    return (receipt is not None and receipt[2] is action
            and receipt[4] == threading.get_ident()
            and receipt[0].enabled() is True and _owner_current(receipt[3]))


class ProviderInstallService:
    def __init__(self, *, root, signing, profile, kernel, enabled=lambda: False,
                 home, runner=None, audit=None):
        from pathlib import Path
        self.root = Path(root)
        self.signing, self.profile, self.kernel = signing, profile, kernel
        self.enabled, self.home, self.runner, self.audit = enabled, home, runner, audit

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
        store = None
        def authorize(action):
            if (self.enabled() is not True
                    or action.payload.get('phase') == 'promote' and not _owner_current(actor)):
                return Decision(Verdict.DENY, reason='provider owner or runtime unavailable')
            if (action.kind == 'plugin.egress'
                    and (store is None or not store._native_egress_receipt_matches(action))):
                return Decision(Verdict.DENY, reason='signed provider egress receipt unavailable')
            if action.kind == 'provider.credential':
                receipt = _CREDENTIAL_RECEIPT.get()
                if (store is None or receipt is None or receipt[0] is not self
                        or receipt[1] is not store or not credential_receipt_matches(action)):
                    return Decision(Verdict.DENY, reason='signed provider credential receipt unavailable')
            gate = self.kernel()
            if not callable(gate):
                return Decision(Verdict.DENY, reason='bound action kernel unavailable')
            # This callback is called only after the store has reloaded exact
            # permanent owner approval. Bind that receipt to the complete Action;
            # a wider or changed action cannot borrow it.
            snapshot = deepcopy(action)
            return gate(action, approval_check=lambda candidate: candidate == snapshot
                        and (action.kind != 'provider.credential'
                             or candidate is action and credential_receipt_matches(action)))
        store = ProviderPackageStore(self.root / 'packages', signing=self.signing,
            authorizer=authorize, enabled=self.enabled, owner_authorizer=owner_authorizer)
        return store

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

    def _credentials(self):
        from .credentials import ProviderCredentialStore
        self._ready()
        return ProviderCredentialStore(self.root / 'credentials')

    def _credential_record_locked(self, store, provider_id, package_hash):
        if (type(provider_id) is not str or type(package_hash) is not str
                or re.fullmatch(r'[a-f0-9]{64}', package_hash) is None):
            raise ProviderPackageError('exact signed credential target required')
        record = store._require_runnable_locked(provider_id, package_hash, self.home)
        if record.provider_id != provider_id or record.package_hash != package_hash:
            raise ProviderPackageError('signed credential target changed')
        return record

    def credential_status(self, provider_id, package_hash, *, actor):
        from .credentials import credential_binding
        self._owner(actor)
        store = self._store(actor=actor)
        with store._locked():
            record = self._credential_record_locked(store, provider_id, package_hash)
            return self._credentials().status(credential_binding(record, self.home))

    def _credential_mutation(self, provider_id, package_hash, value, *, actor, operation):
        from agents.core.action_origin import current_action_origin
        from agents.core.kernel import kernel_enabled
        from agents.core.security.types import SecurityEvent, SecurityEventType

        from .credentials import credential_binding
        self._owner(actor)
        if not kernel_enabled() or not callable(getattr(self.audit, 'log', None)):
            raise ProviderPackageError('credential kernel or audit unavailable')
        store = self._store(actor=actor)
        with store._locked():
            record = self._credential_record_locked(store, provider_id, package_hash)
            binding = credential_binding(record, self.home)
            if binding.auth_type == 'none':
                raise ProviderPackageError('provider does not accept a host credential')
            vault = self._credentials()
            before = {'generation': vault.high_water(binding)}
            action = Action(
                kind='provider.credential', agent='jarvis',
                title='Owner signed provider credential mutation',
                origin=current_action_origin(), scope='provider:' + record.provider_id,
                payload={'schema': 'provider-credential-v1',
                         'authority': binding.authority, 'home': binding.home,
                         'provider_id': record.provider_id, 'source': record.source,
                         'artifact_id': record.artifact_id, 'package_hash': record.package_hash,
                         'endpoint': binding.endpoint, 'auth_type': binding.auth_type,
                         'operation': operation, 'current_generation': before['generation'],
                         'risk_tier': 3, 'irreversible': True})
            receipt = _CREDENTIAL_RECEIPT.set((self, store, action, actor, threading.get_ident()))
            try:
                gate = self.kernel()
                if not callable(gate):
                    raise ProviderPackageError('credential kernel unavailable')
                decision = gate(action, approval_check=lambda candidate: candidate is action
                                and credential_receipt_matches(action))
            finally:
                _CREDENTIAL_RECEIPT.reset(receipt)
            if (type(decision) is not Decision or decision.verdict is not Verdict.GRANT
                    or decision.tier != 3):
                raise ProviderPackageError('credential mutation refused')
            try:
                self.audit.log(SecurityEvent(
                    event_type=SecurityEventType.SETTINGS_CHANGE, timestamp=time.time(),
                    action_taken='provider_credential_' + operation + '_authorized',
                    content_preview=(f'provider={record.provider_id}; '
                                     f'artifact={record.artifact_id}; '
                                     f'generation={before["generation"]}')))
            except Exception:
                raise ProviderPackageError('credential mutation audit unavailable') from None
            self._owner(actor)
            if self._credential_record_locked(store, provider_id, package_hash) != record:
                raise ProviderPackageError('signed credential record changed')
            return (vault.put(binding, value) if operation == 'write'
                    else vault.delete(binding))

    def put_credential(self, provider_id, package_hash, value, *, actor):
        return self._credential_mutation(provider_id, package_hash, value,
                                         actor=actor, operation='write')

    def delete_credential(self, provider_id, package_hash, *, actor):
        return self._credential_mutation(provider_id, package_hash, None,
                                         actor=actor, operation='delete')

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
        kernel=lambda: make_action_kernel(orch), enabled=enabled, home=str(root),
        audit=getattr(orch, 'audit', None))
    orch.provider_install_service = service
    return service
