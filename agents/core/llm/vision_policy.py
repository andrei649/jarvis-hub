"""Frozen native vision wire policy for interactive and unattended consumers."""
from __future__ import annotations

import json
import logging
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass, field

import httpx

from . import selection_guards as sg
from .data_handling import DataHandlingRefused, physical_request_scope
from .direct_transport import require_direct_async_transport
from .model_roles import _is_loopback_base
from .providers import DATA_POLICIES, get_profile
from .vision_retry import RETRY_NOTICE, resolve_vision_empty_retries, vision_retry_scope

logger = logging.getLogger('jarvis.llm.vision_policy')


class VisionDestinationChanged(DataHandlingRefused):
    pass


class VisionRemoteAckRequired(DataHandlingRefused):
    pass


class VisionPolicyUnavailable(DataHandlingRefused):
    pass


def native_base_url(base_url):
    url = httpx.URL(base_url)
    if url.scheme not in ('http', 'https') or not url.host:
        raise VisionPolicyUnavailable('invalid vision destination')
    # Match httpx native path/query joining, including existing unusual URL queries.
    return url if url.raw_path.endswith(b'/') else url.copy_with(raw_path=url.raw_path + b'/')


def authorization(base_url, api_key):
    if api_key:
        return f'Bearer {api_key}'
    url = httpx.URL(base_url)
    if url.username or url.password:
        request = httpx.Request('POST', url)
        prepared = next(httpx.BasicAuth(url.username, url.password).auth_flow(request))
        return prepared.headers['Authorization']
    return ''


@dataclass(frozen=True)
class VisionIdentity:
    provider: str
    policy: str
    note: str
    warning: str
    base_url: str = field(repr=False)
    request_url: str = field(repr=False)
    authorization: str = field(repr=False)
    binding: tuple = field(repr=False)
    empty_retries: int = 0

    def public(self):
        public = {'data_policy': self.policy, 'data_policy_note': self.note, 'warning': self.warning}
        if self.empty_retries:
            public.update({'empty_retries': self.empty_retries, 'retry_notice': RETRY_NOTICE})
        return public


def describe(config):
    empty_retries = resolve_vision_empty_retries()
    if config.backend not in ('lmstudio', 'custom') or not isinstance(config.model, str) or not config.model:
        raise VisionPolicyUnavailable('invalid vision configuration')
    profile = get_profile('lm-studio' if config.backend == 'lmstudio' else 'openai-compatible')
    policy, note = profile.data_policy_for(config.model)
    if config.backend == 'custom':
        policy, note = 'unknown', 'Custom vision endpoint data handling is unknown.'
    elif policy == 'local' and not _is_loopback_base(config.base_url):
        policy, note = 'unknown', 'The vision endpoint is outside loopback; data handling is unknown.'
    if policy not in DATA_POLICIES:
        raise VisionPolicyUnavailable('invalid vision data policy')
    base = native_base_url(config.base_url)
    if bool(config.is_local) != _is_loopback_base(str(base)):
        raise VisionPolicyUnavailable('invalid vision locality')
    request_url = str(base.copy_with(raw_path=base.raw_path + b'chat/completions'))
    auth = authorization(config.base_url, config.api_key)
    warning = ('Vision data handling is unknown; images and prompts may be retained or used for training.'
               if policy == 'unknown' else
               'This vision route may use images and prompts for training.' if policy == 'trains-on-inputs' else '')
    binding = (config.backend, config.base_url, config.model, config.is_local, config.api_key,
               profile.id, policy, note, profile.data_policy, tuple(profile.data_policy_models),
               str(base), request_url, auth)
    if empty_retries:
        binding += ('vision-empty-once:v1',)
    return VisionIdentity(profile.id, policy, note[:500], warning, str(base), request_url, auth,
                          binding, empty_retries)


def _wire_matches(backend, frozen):
    client = getattr(backend, 'client', None)
    if (not isinstance(client, httpx.AsyncClient) or not getattr(backend, '_composer_auth', False)
            or type(getattr(client, '_auth', None)) is not httpx.Auth or client.cookies
            or client.headers.get('Authorization') or client.headers.get('Cookie')):
        raise VisionDestinationChanged('vision adapter authentication changed')
    try:
        require_direct_async_transport(client, frozen.request_url)
    except DataHandlingRefused as exc:
        raise VisionDestinationChanged('vision adapter transport changed') from exc
    if (str(native_base_url(backend.base_url)) != frozen.base_url or str(client.base_url) != frozen.base_url
            or authorization(backend.base_url, backend.api_key) != frozen.authorization):
        raise VisionDestinationChanged('vision adapter destination changed')


@contextmanager
def _native_request_scope(config, backend, *, resolve_config, frozen, authorize=None, notice_purpose, request_validity=None):
    request_marker = object()

    def check():
        if request_validity is not None:
            request_validity()
        try:
            current = describe(resolve_config())
            if current.binding != frozen.binding:
                raise VisionDestinationChanged('vision configuration changed')
            findings = sg.evaluate([sg.Choice('vision.model', frozen.provider, config.model)])
            if findings:
                raise sg.SelectionRefused(findings, sorted({finding.needs for finding in findings}))
            _wire_matches(backend, frozen)
            if authorize is not None:
                authorize()
        except (DataHandlingRefused, sg.SelectionRefused):
            raise
        except Exception as exc:
            raise VisionDestinationChanged('vision configuration changed') from exc

    def validate_request(request, *, marked):
        try:
            require_direct_async_transport(backend.client, request.url)
        except DataHandlingRefused as exc:
            raise VisionDestinationChanged('vision physical transport changed') from exc
        try:
            payload = json.loads(request.content)
            same_model = isinstance(payload, dict) and payload.get('model') == config.model
        except (ValueError, httpx.RequestNotRead):
            same_model = False
        if ((request.extensions.get('nerva_composer_vision_request') is request_marker) != marked
                or request.method != 'POST' or str(request.url) != frozen.request_url
                or not same_model
                or request.headers.get('Authorization', '') != frozen.authorization
                or request.headers.get('Cookie')):
            raise VisionDestinationChanged('vision physical request changed')
        if recovery is not None:
            try:
                messages = payload.get('messages', [])
                image_bearing = any(
                    isinstance(message, dict) and isinstance(message.get('content'), list)
                    and any(isinstance(part, dict) and part.get('type') == 'image_url'
                            for part in message['content']) for message in messages)
                if recovery.started or image_bearing:
                    recovery.validate(request, marked=marked)
            except Exception as exc:
                raise VisionDestinationChanged('vision physical request changed') from exc

    def request_check(request):
        validate_request(request, marked=False)
        request.extensions['nerva_composer_vision_request'] = request_marker

    async def last_request_hook(request):
        if backend.client.event_hooks['request'][-1] is not last_request_hook:
            raise VisionDestinationChanged('vision request hooks changed')
        check()
        validate_request(request, marked=True)

    check()
    if frozen.warning:
        from agents.core.turn_notices import record_turn_notice
        logger.warning('%s (purpose=%s)', frozen.warning, notice_purpose)
        record_turn_notice(f'data_handling:{notice_purpose}', frozen.warning)
    scope = vision_retry_scope(backend, config.model, check) if frozen.empty_retries else nullcontext(None)
    with scope as recovery:
        if recovery is not None:
            backend.client.event_hooks['request'].append(last_request_hook)
        try:
            with physical_request_scope(check, request_check=request_check):
                yield check
                check()
        finally:
            if recovery is not None:
                backend.client.event_hooks['request'].remove(last_request_hook)


@contextmanager
def composer_request_scope(config, backend, *, resolve_config, remote_ack, principal, frozen=None):
    if getattr(principal, 'channel', None) != 'web':
        raise VisionPolicyUnavailable('composer vision requires an interactive web request')
    if not config.is_local and remote_ack is not True:
        raise VisionRemoteAckRequired('remote vision acknowledgment required')
    with _native_request_scope(config, backend, resolve_config=resolve_config,
                               frozen=frozen or describe(config), notice_purpose='composer_vision') as check:
        yield check


@dataclass(frozen=True)
class MediaDataTarget:
    target_id: str
    provider: str
    model: str
    mode: str
    policy: str
    note: str
    binding: tuple = field(repr=False)


def media_data_target(config):
    identity = interactive_local_identity(config)
    note = _role_note(identity)
    return MediaDataTarget('role:telegram_media_reader', identity.provider, config.model,
                           'dedicated', identity.policy, note, identity.binding)


def _role_note(identity):
    note = identity.note
    if identity.empty_retries:
        note = f'{note} {RETRY_NOTICE}'.strip()
        if len(note) > 500:
            raise VisionPolicyUnavailable('vision role note too long')
    return note


def describe_media_data_target():
    """Pure configured unattended target; no client construction or grant."""
    from .vlm import resolve_vlm_config
    try:
        return media_data_target(resolve_vlm_config())
    except Exception:
        return None


@contextmanager
def unattended_media_request_scope(config, backend, *, resolve_config, frozen=None):
    """No caller principal or interactive grant authorizes unattended images."""
    from .data_handling import authorize_role_target
    identity = interactive_local_identity(config)
    if frozen is not None and frozen.binding != identity.binding:
        raise VisionDestinationChanged('vision configuration changed')
    target = media_data_target(config)
    with _native_request_scope(config, backend, resolve_config=resolve_config,
                               frozen=frozen or identity,
                               authorize=lambda: authorize_role_target(None, target, actual_use=False),
                               notice_purpose='role:telegram_media_reader') as check:
        yield check


def camera_vision_config(config):
    from .vlm import VLMConfig
    if config is None or not config.enabled:
        raise VisionPolicyUnavailable('camera description disabled')
    return VLMConfig('custom', config.endpoint, config.model, '', True)


def camera_data_target(config):
    identity = interactive_local_identity(camera_vision_config(config))
    binding = ('camera-descriptions-v1', config.endpoint, config.model, config.enabled,
               config.max_image_bytes, identity.binding)
    return MediaDataTarget('role:camera_descriptions', identity.provider, config.model,
                           'dedicated', identity.policy, _role_note(identity), binding)


def describe_camera_data_target(role_context):
    """Only explicit camera context resolves the pure configured role target."""
    from agents.core.cameras.vlm import resolve_camera_vlm_config
    try:
        config = resolve_camera_vlm_config(role_context)
        return camera_data_target(config) if config is not None else None
    except Exception:
        return None


@contextmanager
def unattended_camera_request_scope(config, backend, *, resolve_config, request_validity=None):
    from .data_handling import authorize_role_target
    frozen = interactive_local_identity(camera_vision_config(config))
    target = camera_data_target(config)
    def live_vision_config():
        live = resolve_config()
        if live != config:
            raise VisionDestinationChanged('camera configuration changed')
        return camera_vision_config(live)
    with _native_request_scope(camera_vision_config(config), backend,
            resolve_config=live_vision_config, frozen=frozen,
            authorize=lambda: authorize_role_target(None, target, actual_use=False),
            notice_purpose='role:camera_descriptions', request_validity=request_validity) as check:
        yield check


def public_origin(base_url):
    """Display only the configured scheme/host/port, never wire secrets or paths."""
    url = httpx.URL(base_url)
    if url.scheme not in {'http', 'https'} or not url.host:
        raise VisionPolicyUnavailable('invalid vision destination')
    return str(httpx.URL(scheme=url.scheme, host=url.host, port=url.port))


def interactive_local_identity(config):
    """Freeze an explicit local interactive request before client construction."""
    try:
        frozen = describe(config)
    except VisionPolicyUnavailable:
        raise
    except Exception as exc:
        raise VisionPolicyUnavailable('vision policy unavailable') from exc
    if not config.is_local or not _is_loopback_base(frozen.base_url):
        raise VisionPolicyUnavailable('interactive vision requires loopback')
    return frozen


@contextmanager
def interactive_local_request_scope(config, backend, *, resolve_config, principal, frozen=None):
    """Strict-local HTTP vision shares wire checks without adding a remote grant."""
    identity = interactive_local_identity(config)
    if frozen is not None and frozen.binding != identity.binding:
        raise VisionDestinationChanged('vision configuration changed')
    with composer_request_scope(config, backend, resolve_config=resolve_config,
                                remote_ack=False, principal=principal, frozen=frozen or identity) as check:
        yield check
