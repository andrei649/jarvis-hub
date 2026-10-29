"""Live owner decisions for H367; storage APIs alone confer no authority."""
from __future__ import annotations

import asyncio
import hashlib
import json
import threading
import time
from contextlib import suppress
from pathlib import Path

from agents.core import settings_db
from agents.core.action_origin import current_action_origin
from agents.core.kernel import Action, Decision, Verdict, kernel_enabled
from agents.core.security.types import SecurityEvent, SecurityEventType

from . import custom_endpoint_consent as consent
from . import custom_endpoints as metadata
from . import selection_guards
from .custom_endpoint_credentials import CustomCredentialBinding, CustomCredentialStore
from .providers import ProviderProfile, selection_gates
from .providers.install_service import _owner_current
from .providers.packages import ProviderPackageError


def profile_for(endpoint: metadata.CustomEndpoint) -> ProviderProfile:
    return ProviderProfile(endpoint.identity, endpoint.name, 'openai-compatible',
                           auth_type=endpoint.auth_type, default_base_url=endpoint.base_url,
                           fallback_models=(endpoint.model,), data_policy=endpoint.data_policy,
                           # Even a loopback proxy is not a trusted strict-local
                           # agent backend; it occupies the governed compatible slot.
                           capabilities=frozenset({'chat', 'cloud'}),
                           is_user_defined=True, supports_model_listing=True)


class CustomEndpointService:
    def __init__(self, *, root, home, kernel, audit, enabled=lambda: True):
        self.root = Path(root)
        self.home = home
        self.kernel = kernel
        self.audit = audit
        self.enabled = enabled

    def _owner(self, actor):
        if (self.enabled() is not True or not kernel_enabled()
                or not _owner_current(actor)):
            raise ProviderPackageError('current custom endpoint owner unavailable')

    def _credentials(self):
        return CustomCredentialStore(self.root / 'credentials')

    def _binding(self, endpoint):
        return CustomCredentialBinding(self.home, endpoint.key, endpoint.base_url,
                                       endpoint.auth_type)

    def _credential_status(self, endpoint):
        if endpoint.auth_type == 'none':
            return {'configured': False, 'generation': 0}
        return self._credentials().status(self._binding(endpoint))

    @staticmethod
    def _current(conn, key):
        row = conn.execute('SELECT key,name,base_url,model,auth_type,data_policy,revision,config_revision,admission_proof '
                           'FROM custom_endpoints WHERE key=?', (key,)).fetchone()
        if row is None:
            raise metadata.CustomEndpointInvalid('endpoint missing')
        return metadata._endpoint(row)

    def _authorize(self, endpoint, *, operation, actor, choice_epoch, generation,
                   unknown_price_ack=False, data_policy_ack=False, grant_destination=False):
        self._owner(actor)
        if not callable(getattr(self.audit, 'log', None)):
            raise ProviderPackageError('custom endpoint audit unavailable')
        findings = []
        if operation == 'activate':
            if unknown_price_ack is not True:
                raise ProviderPackageError('unknown custom model price acknowledgment required')
            if endpoint.data_policy in {'unknown', 'trains-on-inputs'} and data_policy_ack is not True:
                raise ProviderPackageError('custom data policy acknowledgment required')
            profile = profile_for(endpoint)
            choice = selection_guards.Choice('provider.custom_endpoint', endpoint.identity,
                                             endpoint.model)
            with selection_guards._custom_candidate(profile, endpoint.identity, endpoint.model):
                findings = selection_guards.enforce([choice], acknowledge_training=data_policy_ack)
        if operation == 'create' and endpoint.destination_class != 'loopback' and grant_destination is not True:
            raise ProviderPackageError('explicit destination grant required')
        if operation == 'activate' and endpoint.destination_class != 'loopback' and grant_destination is not True:
            raise ProviderPackageError('explicit activation destination grant required')
        scope_digest = hashlib.sha256(json.dumps(
            [self.home, endpoint.key, endpoint.base_url, endpoint.model,
             endpoint.auth_type, endpoint.data_policy, endpoint.config_revision,
             choice_epoch, generation, operation, unknown_price_ack,
             data_policy_ack, grant_destination], separators=(',', ':')).encode()).hexdigest()
        action = Action(kind='provider.custom_endpoint', agent='jarvis',
            title='Owner named compatible endpoint', origin=current_action_origin(),
            scope='provider:' + endpoint.identity,
            payload={'schema': 'custom-endpoint-v1', 'authority': 'custom-endpoint-owner-v1',
                     'home': self.home, 'operation': operation, 'key': endpoint.key,
                     'base_url': endpoint.base_url, 'model': endpoint.model,
                     'auth_type': endpoint.auth_type, 'data_policy': endpoint.data_policy,
                     'destination_class': endpoint.destination_class,
                     'config_revision': endpoint.config_revision,
                     'choice_epoch': choice_epoch, 'credential_generation': generation,
                     'unknown_price_ack': unknown_price_ack, 'data_policy_ack': data_policy_ack,
                     'grant_destination': grant_destination,
                     'risk_tier': 3, 'irreversible': True})
        token = consent._RECEIPT.set((self, action, actor, threading.get_ident()))
        try:
            gate = self.kernel()
            if not callable(gate):
                raise ProviderPackageError('custom endpoint kernel unavailable')
            decision = gate(action, approval_check=lambda candidate:
                            candidate is action and consent.receipt_matches(action))
            if (type(decision) is not Decision or decision.verdict is not Verdict.GRANT
                    or decision.tier != 3):
                raise ProviderPackageError('custom endpoint decision refused')
            try:
                self.audit.log(SecurityEvent(
                    event_type=SecurityEventType.SETTINGS_CHANGE, timestamp=time.time(),
                    action_taken='custom_endpoint_' + operation + '_authorized',
                    content_preview=(f'key={endpoint.key}; operation={operation}; '
                                     f'destination_grant={grant_destination}; '
                                     f'unknown_price_ack={unknown_price_ack}; '
                                     f'data_policy_ack={data_policy_ack}; '
                                     f'scope_sha256={scope_digest}')))
                selection_guards.record(findings, 'custom endpoint activation', self.audit)
            except Exception:
                raise ProviderPackageError('custom endpoint audit unavailable') from None
            self._owner(actor)
            if operation == 'activate':
                audited = consent._AUDITED.set(action)
                try:
                    capability = consent._issue(
                        self, actor, action, decision, endpoint, choice_epoch,
                        generation, unknown_price_ack, data_policy_ack)
                    return consent.mint(self.root, endpoint, choice_epoch, generation,
                                        home=self.home, unknown_price_ack=unknown_price_ack,
                                        data_policy_ack=data_policy_ack, capability=capability)
                finally:
                    consent._AUDITED.reset(audited)
            if operation == 'create':
                audited = consent._AUDITED.set(action)
                try:
                    capability = consent._issue_creation(self, actor, action, decision,
                                                          endpoint)
                    return consent.mint_creation(self.root, self.home, endpoint,
                                                 capability=capability)
                finally:
                    consent._AUDITED.reset(audited)
            if operation == 'validate':
                audited = consent._AUDITED.set(action)
                try:
                    return consent._issue_validation(self, actor, action, decision,
                                                     endpoint, choice_epoch, generation)
                finally:
                    consent._AUDITED.reset(audited)
            return None
        finally:
            consent._RECEIPT.reset(token)

    @staticmethod
    def _public(endpoint, *, active=False, generation=0, configured=False):
        return {'key': endpoint.key, 'identity': endpoint.identity, 'name': endpoint.name,
                'host': endpoint.base_url.split('/')[2], 'model': endpoint.model,
                'auth_type': endpoint.auth_type, 'data_policy': endpoint.data_policy,
                'destination_class': endpoint.destination_class,
                'revision': endpoint.revision, 'config_revision': endpoint.config_revision,
                'active': active, 'credential_configured': configured,
                'credential_generation': generation}

    def list(self, *, actor):
        self._owner(actor)
        try:
            choice = metadata.read_choice()
            epoch, active, unavailable = choice.epoch, choice.active_key, False
        except metadata.CustomEndpointInvalid:
            epoch = metadata._with_read(lambda conn: conn.execute(
                'SELECT epoch FROM provider_choice_epoch WHERE singleton=1').fetchone()[0])
            active, unavailable = None, True
        rows = []
        try:
            endpoints = metadata.list_endpoints()
        except metadata.CustomEndpointInvalid:
            endpoints, unavailable = [], True
        for endpoint in endpoints:
            try:
                status = self._credential_status(endpoint)
            except (ProviderPackageError, OSError):
                status, unavailable = {'generation': 0, 'configured': False}, True
            rows.append(self._public(endpoint, active=active == endpoint.key,
                                     generation=status['generation'],
                                     configured=status['configured']))
        if active is not None:
            selected = next((item for item in endpoints if item.key == active), None)
            if selected is None or not consent.verify(self.root, self.home, selected, choice):
                unavailable = True
            else:
                try:
                    current = self._credential_status(selected)
                    if (current['generation'] != choice.credential_generation
                            or selected.auth_type != 'none' and not current['configured']):
                        unavailable = True
                except (ProviderPackageError, OSError):
                    unavailable = True
        legacy_candidate = None
        try:
            found, provider = settings_db.read_setting('llm', 'compatible_provider')
            if found and provider == 'custom' and active is None:
                eligible = []
                for item in endpoints:
                    if not consent.verify_creation(self.root, self.home, item):
                        continue
                    try:
                        status = self._credential_status(item)
                    except (ProviderPackageError, OSError):
                        continue
                    if item.auth_type == 'none' or status['configured']:
                        eligible.append(item.identity)
                legacy_candidate = next(iter(eligible), None)
        except Exception:
            pass
        return {'endpoints': rows, 'choice_epoch': epoch,
                'active': f'custom:{active}' if active else None,
                'legacy_recovery_candidate': legacy_candidate,
                'unavailable': unavailable}

    def _authorize_recovery_clear(self, actor, epoch):
        self._owner(actor)
        if not callable(getattr(self.audit, 'log', None)):
            raise ProviderPackageError('custom endpoint audit unavailable')
        action = Action(kind='provider.custom_endpoint', agent='jarvis',
            title='Owner clear unavailable custom endpoint', origin=current_action_origin(),
            scope='provider:custom:recovery',
            payload={'schema': 'custom-endpoint-v1', 'authority': 'custom-endpoint-owner-v1',
                     'home': self.home, 'operation': 'clear', 'key': 'recovery',
                     'base_url': '', 'model': '', 'auth_type': 'none',
                     'data_policy': 'unknown', 'destination_class': 'recovery',
                     'config_revision': 0, 'choice_epoch': epoch,
                     'credential_generation': 0, 'unknown_price_ack': False,
                     'data_policy_ack': False, 'grant_destination': False,
                     'risk_tier': 3, 'irreversible': True})
        token = consent._RECEIPT.set((self, action, actor, threading.get_ident()))
        try:
            gate = self.kernel()
            if not callable(gate):
                raise ProviderPackageError('custom recovery kernel unavailable')
            decision = gate(action, approval_check=lambda candidate:
                            candidate is action and consent.receipt_matches(action))
            if (type(decision) is not Decision or decision.verdict is not Verdict.GRANT
                    or decision.tier != 3):
                raise ProviderPackageError('custom recovery refused')
            try:
                self.audit.log(SecurityEvent(
                    event_type=SecurityEventType.SETTINGS_CHANGE, timestamp=time.time(),
                    action_taken='custom_endpoint_clear_authorized',
                    content_preview=f'custom choice recovery; epoch={epoch}'))
            except Exception:
                raise ProviderPackageError('custom recovery audit unavailable') from None
            self._owner(actor)
        finally:
            consent._RECEIPT.reset(token)

    def clear(self, *, expected_choice_epoch, actor):
        self._owner(actor)
        with selection_gates.exclusive(settings_db.DB_PATH, signed=True):
            settings_db._ensure_init()
            conn = settings_db.get_conn()
            try:
                row = conn.execute('SELECT epoch FROM provider_choice_epoch WHERE singleton=1').fetchone()
                if row is None or row[0] != expected_choice_epoch:
                    raise metadata.CustomEndpointConflict('effective provider choice changed')
                active = conn.execute('SELECT active_key FROM custom_endpoint_choice WHERE singleton=1').fetchone()
                if active is None or active[0] is None:
                    raise metadata.CustomEndpointInvalid('no custom choice to clear')
                try:
                    endpoint = self._current(conn, active[0])
                except Exception:
                    endpoint = None
                if endpoint is None:
                    self._authorize_recovery_clear(actor, row[0])
                else:
                    self._authorize(endpoint, operation='clear', actor=actor,
                                    choice_epoch=row[0], generation=0)
                self._owner(actor)
                choice = metadata.clear_endpoint_choice(expected_choice_epoch=row[0])
                return {'active': None, 'choice_epoch': choice.epoch}
            finally:
                conn.close()

    def create(self, key, name, base_url, model, auth_type, data_policy, *, actor,
               grant_destination=False):
        self._owner(actor)
        metadata._validate(key, name, base_url, model, auth_type, data_policy)
        proposed = metadata.CustomEndpoint(key, name, base_url, model,
                                           auth_type, data_policy, 1, 1)
        with selection_gates.exclusive(settings_db.DB_PATH, signed=True):
            settings_db._ensure_init()
            conn = settings_db.get_conn()
            try:
                epoch = metadata._choice(conn).epoch
                if conn.execute('SELECT 1 FROM custom_endpoints WHERE key=?', (key,)).fetchone():
                    raise metadata.CustomEndpointInvalid('endpoint key already exists')
                proof = self._authorize(proposed, operation='create', actor=actor,
                                        choice_epoch=epoch, generation=0,
                                        grant_destination=grant_destination)
                self._owner(actor)
                created = metadata.create_endpoint(key, name, base_url, model,
                                                   auth_type, data_policy,
                                                   admission_proof=proof)
                return self._public(created)
            finally:
                conn.close()

    def activate(self, key, *, expected_revision, expected_choice_epoch,
                 acknowledge_unknown_price=False, acknowledge_data_policy=False,
                 grant_destination=False, actor):
        self._owner(actor)
        with selection_gates.exclusive(settings_db.DB_PATH, signed=True):
            settings_db._ensure_init()
            conn = settings_db.get_conn()
            try:
                endpoint = self._current(conn, key)
                choice = metadata._choice(conn)
                if endpoint.revision != expected_revision or choice.epoch != expected_choice_epoch:
                    raise metadata.CustomEndpointConflict('custom endpoint choice changed')
                credential = self._credential_status(endpoint)
                if endpoint.auth_type != 'none' and not credential['configured']:
                    raise ProviderPackageError('custom credential unavailable')
                proof = self._authorize(
                    endpoint, operation='activate', actor=actor,
                    choice_epoch=choice.epoch + 1, generation=credential['generation'],
                    unknown_price_ack=acknowledge_unknown_price,
                    data_policy_ack=acknowledge_data_policy,
                    grant_destination=grant_destination)
                self._owner(actor)
                chosen = metadata.activate_endpoint(
                    key, expected_revision=endpoint.revision,
                    expected_choice_epoch=choice.epoch, proof=proof,
                    credential_generation=credential['generation'],
                    unknown_price_ack=acknowledge_unknown_price,
                    data_policy_ack=acknowledge_data_policy)
                return {'active': endpoint.identity, 'choice_epoch': chosen.epoch,
                        'revision': endpoint.revision}
            finally:
                conn.close()

    def current_runtime(self):
        from .providers.custom_runtime import CustomEndpointRuntime

        # A response body may hold SH. Its exact proof remains authoritative;
        # representation repair can wait for the next refresh.
        with suppress(selection_gates.SelectionBusy):
            self._normalize_proven_alias()
        return CustomEndpointRuntime.from_current(self)

    def _normalize_proven_alias(self):
        """Repair only the name of an already current, independently proven choice.

        A raw bare ``custom`` row with no valid active consent remains inert.
        This changes no epoch, choice, endpoint, credential, or authority proof.
        """
        if self.enabled() is not True:
            return
        settings_db._ensure_init()
        with selection_gates.shared(settings_db.DB_PATH):
            conn = settings_db.get_conn()
            try:
                row = conn.execute("SELECT value FROM settings WHERE category='llm' "
                                   "AND key='compatible_provider'").fetchone()
                if row is None or row[0] != '"custom"':
                    return
            finally:
                conn.close()
        with selection_gates.exclusive(settings_db.DB_PATH, signed=True):
            settings_db._ensure_init()
            conn = settings_db.get_conn()
            try:
                with conn:
                    row = conn.execute("SELECT value FROM settings WHERE category='llm' "
                                       "AND key='compatible_provider'").fetchone()
                    if row is None or row[0] != '"custom"':
                        return
                    choice = metadata._choice(conn)
                    if choice.active_key is None:
                        return
                    from .provider_selection import _row as signed_row

                    if signed_row(conn)[1] is not None:
                        return
                    endpoint = self._current(conn, choice.active_key)
                    if (choice.config_revision != endpoint.config_revision
                            or not consent.verify(self.root, self.home, endpoint, choice)):
                        return
                    status = self._credential_status(endpoint)
                    if (status['generation'] != choice.credential_generation
                            or endpoint.auth_type != 'none' and not status['configured']):
                        return
                    changed = conn.execute("UPDATE settings SET value=? WHERE category='llm' "
                                           "AND key='compatible_provider' AND value='\"custom\"'",
                                           (json.dumps(endpoint.identity),))
                    if changed.rowcount != 1 or metadata._choice(conn) != choice:
                        raise metadata.CustomEndpointConflict('legacy alias changed')
            finally:
                conn.close()

    def rename(self, key, name, *, expected_revision, actor):
        self._owner(actor)
        with selection_gates.exclusive(settings_db.DB_PATH, signed=True):
            settings_db._ensure_init()
            conn = settings_db.get_conn()
            try:
                endpoint = self._current(conn, key)
                choice = metadata._choice(conn)
                if endpoint.revision != expected_revision:
                    raise metadata.CustomEndpointConflict('endpoint revision changed')
                metadata._validate(key, name, endpoint.base_url, endpoint.model,
                                   endpoint.auth_type, endpoint.data_policy)
                self._authorize(endpoint, operation='rename', actor=actor,
                                choice_epoch=choice.epoch, generation=0)
                self._owner(actor)
                return self._public(metadata.rename_endpoint(key, name,
                                                               expected_revision=expected_revision),
                                    active=choice.active_key == key)
            finally:
                conn.close()

    def delete(self, key, *, expected_revision, actor):
        self._owner(actor)
        with selection_gates.exclusive(settings_db.DB_PATH, signed=True):
            settings_db._ensure_init()
            conn = settings_db.get_conn()
            try:
                endpoint = self._current(conn, key)
                choice = metadata._choice(conn)
                if endpoint.revision != expected_revision:
                    raise metadata.CustomEndpointConflict('endpoint revision changed')
                self._authorize(endpoint, operation='delete', actor=actor,
                                choice_epoch=choice.epoch, generation=0)
                self._owner(actor)
                if endpoint.auth_type != 'none':
                    self._credentials().delete(self._binding(endpoint))
                metadata.delete_endpoint(key, expected_revision=expected_revision)
                return {'deleted': endpoint.identity}
            finally:
                conn.close()

    def credential_status(self, key, *, actor):
        self._owner(actor)
        endpoint = metadata.read_endpoint(key)
        if endpoint is None:
            raise metadata.CustomEndpointInvalid('endpoint missing')
        return self._credential_status(endpoint)

    def credential_mutation(self, key, *, value=None, delete=False, actor):
        self._owner(actor)
        with selection_gates.exclusive(settings_db.DB_PATH, signed=True):
            settings_db._ensure_init()
            conn = settings_db.get_conn()
            try:
                endpoint = self._current(conn, key)
                if endpoint.auth_type == 'none':
                    raise ProviderPackageError('endpoint does not accept credentials')
                choice = metadata._choice(conn)
                vault = self._credentials()
                binding = self._binding(endpoint)
                status = vault.status(binding)
                self._authorize(endpoint, operation='credential_delete' if delete else 'credential_write',
                                actor=actor, choice_epoch=choice.epoch,
                                generation=status['generation'])
                self._owner(actor)
                result = vault.delete(binding) if delete else vault.put(binding, value)
                if choice.active_key == key:
                    metadata.clear_endpoint_choice(expected_choice_epoch=choice.epoch)
                return result
            finally:
                conn.close()

    async def validate(self, key, *, actor, inner=None):
        """A bounded explicit /models probe with the same physical route as generation."""
        from types import SimpleNamespace

        from .provider_selection import _row as signed_row
        from .providers.custom_runtime import custom_client, validation_scope

        def authorize_probe():
            self._owner(actor)
            with selection_gates.exclusive(settings_db.DB_PATH, signed=True):
                settings_db._ensure_init()
                conn = settings_db.get_conn()
                try:
                    endpoint = self._current(conn, key)
                    choice = metadata._choice(conn)
                    if choice.active_key != key:
                        raise ProviderPackageError('custom validation requires active endpoint')
                    if (signed_row(conn)[1] is not None
                            or not consent.verify(self.root, self.home, endpoint, choice)):
                        raise ProviderPackageError('custom validation authority unavailable')
                    return self._authorize(endpoint, operation='validate', actor=actor,
                        choice_epoch=choice.epoch,
                        generation=choice.credential_generation)
                finally:
                    conn.close()

        # The EX authorizer must finish before the HTTP attempt takes SH.
        ticket = await asyncio.to_thread(authorize_probe)
        runtime = await asyncio.to_thread(self.current_runtime)
        if runtime is None or runtime.endpoint.key != key:
            raise ProviderPackageError('custom validation choice changed')
        client = custom_client(runtime, inner=inner)
        backend = SimpleNamespace(profile=runtime.profile, _custom_endpoint_runtime=runtime)
        runtime.bind_backend(backend, SimpleNamespace(_compatible_backend=backend))
        try:
            with validation_scope(ticket):
                async with client, client.stream('GET', '/models', timeout=10.0) as response:
                    if response.status_code != 200:
                        return {'ok': False, 'models': 0, 'identity': runtime.endpoint.identity}
                    data = b''
                    async for chunk in response.aiter_bytes():
                        data += chunk
                        if len(data) > 65_536:
                            raise ProviderPackageError('custom model listing too large')
            parsed = json.loads(data)
            rows = parsed.get('data') if type(parsed) is dict else None
            if type(rows) is not list or len(rows) > 1000:
                raise ProviderPackageError('custom model listing invalid')
            return {'ok': True, 'models': len(rows), 'identity': runtime.endpoint.identity}
        finally:
            runtime.retire()


def get_custom_endpoint_service(orch):
    """Lazy composition: no configured endpoint or network probe at startup."""
    if orch is None:
        return None
    existing = getattr(orch, 'custom_endpoint_service', None)
    if existing is not None:
        return existing
    from agents.core.kernel.binding import make_action_kernel
    from agents.core.orchestrator_bindings import bind_external_orchestrator_attribute
    from agents.core.paths import data_path

    root = data_path('custom-endpoints')
    service = CustomEndpointService(root=root, home=str(root),
                                    kernel=lambda: make_action_kernel(orch),
                                    audit=getattr(orch, 'audit', None),
                                    enabled=kernel_enabled)
    bind_external_orchestrator_attribute(orch, "custom_endpoint_service", service)
    return service
