"""Distinct one-use owner consent for an exact named endpoint choice."""
from __future__ import annotations

import hashlib
import hmac
import json
import threading
from contextvars import ContextVar
from pathlib import Path

from .custom_endpoints import CustomChoice, CustomEndpoint
from .providers.packages import ProviderPackageError
from .providers.selection_consent import _key

_DOMAIN = b'nerva:custom-endpoint-consent:v1\0'
_CREATE_DOMAIN = b'nerva:custom-endpoint-admission:v1\0'
_RECEIPT: ContextVar[tuple | None] = ContextVar('custom_endpoint_owner_receipt', default=None)
_AUDITED: ContextVar[object | None] = ContextVar('custom_endpoint_audited_action', default=None)
_ISSUED: dict[object, tuple] = {}
_CREATIONS: dict[object, tuple] = {}
_VALIDATIONS: dict[object, tuple] = {}
_LOCK = threading.Lock()


def receipt_matches(action) -> bool:
    from .providers.install_service import _owner_current

    receipt = _RECEIPT.get()
    return (receipt is not None and receipt[1] is action
            and receipt[3] == threading.get_ident()
            and receipt[0].enabled() is True and _owner_current(receipt[2]))


def _message(endpoint: CustomEndpoint, home: str, epoch: int, generation: int,
             unknown_price_ack: bool, data_policy_ack: bool) -> bytes:
    if (type(endpoint) is not CustomEndpoint or type(home) is not str or not home
            or type(epoch) is not int or epoch <= 0
            or type(generation) is not int or generation < 0
            or unknown_price_ack is not True or type(data_policy_ack) is not bool
            or endpoint.data_policy in {'unknown', 'trains-on-inputs'}
            and data_policy_ack is not True):
        raise ProviderPackageError('custom consent scope unavailable')
    fields = [home, endpoint.key, endpoint.base_url, endpoint.model,
              endpoint.auth_type, endpoint.data_policy, endpoint.config_revision,
              endpoint.destination_class, epoch, generation,
              unknown_price_ack, data_policy_ack]
    return _DOMAIN + json.dumps(fields, separators=(',', ':'), ensure_ascii=True).encode('ascii')


def _creation_message(endpoint: CustomEndpoint, home: str) -> bytes:
    if type(endpoint) is not CustomEndpoint or type(home) is not str or not home:
        raise ProviderPackageError('custom admission scope unavailable')
    fields = [home, endpoint.key, endpoint.base_url, endpoint.model,
              endpoint.auth_type, endpoint.data_policy, endpoint.config_revision,
              endpoint.destination_class]
    return _CREATE_DOMAIN + json.dumps(fields, separators=(',', ':'), ensure_ascii=True).encode('ascii')


def _issue_creation(service, actor, action, decision, endpoint):
    from agents.core.kernel import Decision, Verdict

    receipt = _RECEIPT.get()
    payload = getattr(action, 'payload', {})
    if (receipt is None or _AUDITED.get() is not action
            or receipt[0] is not service or receipt[1] is not action
            or receipt[2] is not actor or not receipt_matches(action)
            or type(decision) is not Decision or decision.verdict is not Verdict.GRANT
            or decision.tier != 3 or action.kind != 'provider.custom_endpoint'
            or payload.get('operation') != 'create'
            or payload.get('key') != endpoint.key
            or payload.get('base_url') != endpoint.base_url
            or payload.get('model') != endpoint.model
            or payload.get('auth_type') != endpoint.auth_type
            or payload.get('data_policy') != endpoint.data_policy
            or payload.get('config_revision') != endpoint.config_revision):
        raise ProviderPackageError('custom admission mint capability unavailable')
    capability = object()
    with _LOCK:
        _CREATIONS[capability] = (service, actor, Path(service.root),
                                  _creation_message(endpoint, service.home),
                                  threading.get_ident())
    return capability


def mint_creation(root, home, endpoint, *, capability=None):
    if type(capability) is not object:
        raise ProviderPackageError('custom admission mint capability required')
    with _LOCK:
        issued = _CREATIONS.pop(capability, None)
    if issued is None:
        raise ProviderPackageError('custom admission mint capability required')
    from .providers.install_service import _owner_current

    service, actor, issued_root, issued_message, issued_thread = issued
    message = _creation_message(endpoint, home)
    if (issued_root != Path(root) or service.root != Path(root)
            or issued_thread != threading.get_ident()
            or not hmac.compare_digest(issued_message, message)
            or service.enabled() is not True or not _owner_current(actor)):
        raise ProviderPackageError('custom admission mint capability changed')
    return hmac.new(_key(Path(root), create=True), message, hashlib.sha256).hexdigest()


def verify_creation(root, home, endpoint) -> bool:
    if not endpoint.admission_proof:
        return False
    try:
        message = _creation_message(endpoint, home)
        expected = hmac.new(_key(Path(root), create=False), message, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, endpoint.admission_proof)
    except (ProviderPackageError, TypeError, ValueError, OSError):
        return False


def _issue(service, actor, action, decision, endpoint, epoch, generation,
           unknown_price_ack, data_policy_ack):
    from agents.core.kernel import Decision, Verdict

    receipt = _RECEIPT.get()
    payload = getattr(action, 'payload', {})
    if (receipt is None or _AUDITED.get() is not action
            or receipt[0] is not service or receipt[1] is not action
            or receipt[2] is not actor or not receipt_matches(action)
            or type(decision) is not Decision or decision.verdict is not Verdict.GRANT
            or decision.tier != 3 or action.kind != 'provider.custom_endpoint'
            or payload.get('operation') != 'activate'
            or payload.get('key') != endpoint.key
            or payload.get('choice_epoch') != epoch
            or payload.get('credential_generation') != generation
            or payload.get('unknown_price_ack') is not unknown_price_ack
            or payload.get('data_policy_ack') is not data_policy_ack):
        raise ProviderPackageError('custom consent mint capability unavailable')
    capability = object()
    with _LOCK:
        _ISSUED[capability] = (service, actor, Path(service.root),
                               _message(endpoint, service.home, epoch, generation,
                                        unknown_price_ack, data_policy_ack),
                               threading.get_ident())
    return capability


def _issue_validation(service, actor, action, decision, endpoint, epoch, generation):
    from agents.core.kernel import Decision, Verdict

    payload = getattr(action, 'payload', {})
    if (not receipt_matches(action) or _AUDITED.get() is not action
            or type(decision) is not Decision or decision.verdict is not Verdict.GRANT
            or decision.tier != 3 or payload.get('operation') != 'validate'
            or payload.get('key') != endpoint.key or payload.get('choice_epoch') != epoch
            or payload.get('credential_generation') != generation):
        raise ProviderPackageError('custom validation capability unavailable')
    capability = object()
    with _LOCK:
        _VALIDATIONS[capability] = (service, actor, endpoint.key, endpoint.config_revision,
                                    epoch, generation, threading.get_ident())
    return capability


def consume_validation(capability, runtime) -> bool:
    from .providers.install_service import _owner_current

    with _LOCK:
        row = _VALIDATIONS.pop(capability, None)
    if row is None:
        return False
    service, actor, key, config, epoch, generation, _thread = row
    return (service is runtime.service and service.enabled() is True
            and _owner_current(actor) and key == runtime.endpoint.key
            and config == runtime.endpoint.config_revision
            and epoch == runtime.choice.epoch
            and generation == runtime.choice.credential_generation)


def mint(root, endpoint, epoch, generation, *, home='', unknown_price_ack=True,
         data_policy_ack=False, capability=None):
    """A direct internal call cannot turn a raw active row into authority."""
    if type(capability) is not object:
        raise ProviderPackageError('custom consent mint capability required')
    with _LOCK:
        issued = _ISSUED.pop(capability, None)
    if issued is None:
        raise ProviderPackageError('custom consent mint capability required')
    from .providers.install_service import _owner_current

    service, actor, issued_root, issued_message, issued_thread = issued
    message = _message(endpoint, home, epoch, generation,
                       unknown_price_ack, data_policy_ack)
    if (issued_root != Path(root) or service.root != Path(root)
            or issued_thread != threading.get_ident()
            or not hmac.compare_digest(issued_message, message)
            or service.enabled() is not True or not _owner_current(actor)):
        raise ProviderPackageError('custom consent mint capability changed')
    return hmac.new(_key(Path(root), create=True), message, hashlib.sha256).hexdigest()


def verify(root, home: str, endpoint: CustomEndpoint, choice: CustomChoice) -> bool:
    if choice.active_key != endpoint.key or not choice.consent_proof:
        return False
    try:
        message = _message(endpoint, home, choice.epoch,
                           choice.credential_generation, choice.unknown_price_ack,
                           choice.data_policy_ack)
        expected = hmac.new(_key(Path(root), create=False), message, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, choice.consent_proof)
    except (ProviderPackageError, TypeError, ValueError, OSError):
        return False
