"""Frozen native vision wire policy for interactive and unattended consumers."""
from __future__ import annotations

import json
import logging
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass, field, replace

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
    provider_block: str = field(default="", repr=False)
    selection_findings: tuple[str, ...] = field(default=(), repr=False)
    wire_mode: str = "chat_completions"
    prompt_cache_retention: str = "in_memory"

    def selection_choice(self, model):
        route = ('data_collection=allow' if self.provider_block
                 and json.loads(self.provider_block).get('data_collection') == 'allow' else '')
        return sg.Choice('vision.model', self.provider, model, route=route)

    def public(self):
        public = {'data_policy': self.policy, 'data_policy_note': self.note, 'warning': self.warning}
        if self.empty_retries:
            public.update({'empty_retries': self.empty_retries, 'retry_notice': RETRY_NOTICE})
        if self.selection_findings:
            public['selection_requirements'] = [
                {'needs': finding['needs'], 'message': finding['message']}
                for finding in (json.loads(item) for item in self.selection_findings)
            ]
        return public


def canonical_selection_findings(findings):
    """Freeze complete guard details while exposing only bounded prompts in status."""
    findings = tuple(findings)
    if len(findings) > 8:
        raise VisionPolicyUnavailable('vision selection policy unavailable')
    seen = set()
    result = []
    for finding in findings:
        need, message = finding.needs, finding.message
        if (type(need) is not str or need not in (sg.ACKNOWLEDGE_TRAINING, sg.CONFIRM_EXPENSIVE)
                or need in seen or type(message) is not str or not message.strip()
                or len(message) > 500
                or any(ord(char) < 32 or ord(char) == 127 for char in message)):
            raise VisionPolicyUnavailable('vision selection policy unavailable')
        seen.add(need)
        try:
            result.append(json.dumps(finding.as_dict(), sort_keys=True, separators=(',', ':'),
                                     ensure_ascii=False, allow_nan=False))
        except (TypeError, ValueError, UnicodeError) as exc:
            raise VisionPolicyUnavailable('vision selection policy unavailable') from exc
    return tuple(result)


def describe(config):
    empty_retries = resolve_vision_empty_retries()
    if config.backend not in ('lmstudio', 'ollama', 'custom', 'openrouter', 'deepinfra', 'nous', 'anthropic', 'gemini', 'openai-responses') or not isinstance(config.model, str) or not config.model:
        raise VisionPolicyUnavailable('invalid vision configuration')
    profile = get_profile({'lmstudio': 'lm-studio', 'ollama': 'ollama', 'custom': 'openai-compatible',
                           'openrouter': 'openrouter', 'deepinfra': 'deepinfra', 'nous': 'nous',
                           'anthropic': 'anthropic', 'gemini': 'gemini',
                           'openai-responses': 'openai-responses'}[config.backend])
    provider_block = ''
    policy, note = profile.data_policy_for(config.model)
    if config.backend == 'openrouter':
        from .vision_openrouter import current_provider_block, policy_for
        block = current_provider_block()
        provider_block = json.dumps(block, sort_keys=True, separators=(',', ':'))
        policy, note = policy_for(config.model, block)
    if config.backend == 'custom':
        policy, note = 'unknown', 'Custom vision endpoint data handling is unknown.'
    elif policy == 'local' and not _is_loopback_base(config.base_url):
        policy, note = 'unknown', 'The vision endpoint is outside loopback; data handling is unknown.'
    if config.backend == 'openai-responses':
        note = f'{note} Prompt cache retention: {config.prompt_cache_retention}.'
    if policy not in DATA_POLICIES:
        raise VisionPolicyUnavailable('invalid vision data policy')
    base = native_base_url(config.base_url)
    if bool(config.is_local) != _is_loopback_base(str(base)):
        raise VisionPolicyUnavailable('invalid vision locality')
    if config.backend == 'anthropic':
        from .anthropic import ANTHROPIC_API_BASE
        if (config.base_url != ANTHROPIC_API_BASE or config.is_local or not config.api_key
                or len(config.api_key) > 4096
                or any(ord(char) < 33 or ord(char) > 126 for char in config.api_key)):
            raise VisionPolicyUnavailable('invalid Anthropic vision authority')
    if config.backend == 'gemini':
        from .gemini import GEMINI_API_BASE
        if (config.base_url != GEMINI_API_BASE or config.is_local or not config.api_key
                or len(config.api_key) > 4096
                or any(ord(char) < 33 or ord(char) > 126 for char in config.api_key)):
            raise VisionPolicyUnavailable('invalid Gemini vision authority')
    if config.backend == 'openai-responses':
        from .responses import ENDPOINT, MODELS
        if (config.base_url != ENDPOINT.removesuffix('/responses') or config.is_local
                or config.model not in MODELS or not config.api_key
                or len(config.api_key) > 4096
                or any(ord(char) < 33 or ord(char) > 126 for char in config.api_key)
                or config.prompt_cache_retention not in {'in_memory', '24h'}):
            raise VisionPolicyUnavailable('invalid Responses vision authority')
    wire_mode = getattr(config, 'wire_mode', 'chat_completions')
    if wire_mode not in {'chat_completions', 'anthropic_messages', 'ollama_chat', 'gemini_generate_content', 'responses'} or (
            wire_mode == 'anthropic_messages' and config.backend not in {'nous', 'anthropic'}) or (
            wire_mode == 'ollama_chat' and config.backend != 'ollama') or (
            wire_mode == 'gemini_generate_content' and config.backend != 'gemini') or (
            wire_mode == 'responses' and config.backend != 'openai-responses') or (
            config.backend == 'gemini' and wire_mode != 'gemini_generate_content') or (
            config.backend == 'openai-responses' and wire_mode != 'responses'):
        raise VisionPolicyUnavailable('invalid vision wire mode')
    if config.backend == 'gemini':
        from .video_native import VideoNativeRefused, gemini_request_url
        try:
            request_url = gemini_request_url(config.base_url, config.model)
        except VideoNativeRefused:
            raise VisionPolicyUnavailable('invalid Gemini vision model') from None
    else:
        path = (b'responses' if wire_mode == 'responses' else
                b'messages' if wire_mode == 'anthropic_messages' else
                b'api/chat' if wire_mode == 'ollama_chat' else b'chat/completions')
        request_url = str(base.copy_with(raw_path=base.raw_path + path))
    auth = '' if config.backend in {'anthropic', 'gemini'} else authorization(config.base_url, config.api_key)
    warning = ('Vision data handling is unknown; images and prompts may be retained or used for training.'
               if policy == 'unknown' else
               'This vision route may use images and prompts for training.' if policy == 'trains-on-inputs' else '')
    binding = (config.backend, config.base_url, config.model, config.is_local, config.api_key,
               profile.id, policy, note, profile.data_policy, tuple(profile.data_policy_models),
               str(base), request_url, auth)
    if config.backend == 'openai-responses':
        binding += ('responses-vision:v1', wire_mode, config.prompt_cache_retention)
    if empty_retries:
        binding += ('vision-empty-once:v1',)
    if provider_block:
        binding += ('openrouter-vision:v1', provider_block)
    if config.backend == 'nous':
        binding += ('nous-vision:v1', wire_mode)
    if config.backend == 'anthropic':
        binding += ('anthropic-vision:v1', wire_mode)
    if config.backend == 'gemini':
        binding += ('gemini-vision:v1', wire_mode)
    if config.backend == 'ollama':
        binding += ('ollama-vision:v1', wire_mode)
    route_source = getattr(config, 'route_source', '')
    if route_source:
        if route_source not in {'auto:main', 'auto:override', 'auto:openrouter',
                                'auto:nous', 'auto:deepinfra'}:
            raise VisionPolicyUnavailable('invalid vision route source')
        binding += ('vision-auto:v1', route_source)
    identity = VisionIdentity(profile.id, policy, note[:500], warning, str(base), request_url, auth,
                              binding, empty_retries, provider_block, wire_mode=wire_mode,
                              prompt_cache_retention=config.prompt_cache_retention)
    try:
        findings = canonical_selection_findings(sg.evaluate([identity.selection_choice(config.model)]))
    except VisionPolicyUnavailable:
        raise
    except Exception as exc:
        raise VisionPolicyUnavailable('vision selection policy unavailable') from exc
    if findings:
        return replace(identity, binding=binding + ('vision-selection-findings:v1', *findings),
                       selection_findings=findings)
    return identity


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
            or ('' if frozen.provider in {'anthropic', 'gemini'} else
                authorization(backend.base_url, backend.api_key)) != frozen.authorization
            or getattr(backend, '_wire_mode', 'chat_completions') != frozen.wire_mode
            or (frozen.provider == 'openai-responses'
                and getattr(backend, '_prompt_cache_retention', '') != frozen.prompt_cache_retention)
            or (frozen.provider in ('openrouter', 'deepinfra', 'nous', 'ollama', 'anthropic', 'gemini', 'openai-responses')
                and getattr(backend, '_provider_id', '') != frozen.provider)
            or (frozen.provider not in ('openrouter', 'deepinfra', 'nous', 'ollama', 'anthropic', 'gemini', 'openai-responses') and getattr(backend, '_provider_id', ''))):
        raise VisionDestinationChanged('vision adapter destination changed')


@contextmanager
def _native_request_scope(config, backend, *, resolve_config, frozen, authorize=None, notice_purpose,
                          request_validity=None, cleared_findings=()):
    request_marker = object()

    def check():
        if request_validity is not None:
            request_validity()
        try:
            current = describe(resolve_config())
            if current.binding != frozen.binding:
                raise VisionDestinationChanged('vision configuration changed')
            if current.selection_findings != cleared_findings:
                findings = sg.evaluate([current.selection_choice(config.model)])
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
            def unique_pairs(pairs):
                result = {}
                for key, value in pairs:
                    if key in result:
                        raise ValueError('duplicate vision request field')
                    result[key] = value
                return result
            payload = json.loads(request.content, object_pairs_hook=unique_pairs if frozen.provider_block or frozen.provider in {"deepinfra", "nous", "ollama", "anthropic", "gemini", "openai-responses"} else dict)
            same_model = isinstance(payload, dict) and (
                ('contents' in payload and 'model' not in payload) if frozen.provider == 'gemini'
                else payload.get('model') == config.model)
            if frozen.provider_block:
                same_model = same_model and json.dumps(payload.get('provider'), sort_keys=True,
                                                       separators=(',', ':')) == frozen.provider_block
            if frozen.provider == 'openai-responses':
                same_model = (same_model and payload.get('store') is False
                              and payload.get('prompt_cache_retention') == frozen.prompt_cache_retention
                              and isinstance(payload.get('input'), list)
                              and 'tools' not in payload and 'messages' not in payload)
        except (ValueError, httpx.RequestNotRead):
            same_model = False
        if ((request.extensions.get('nerva_composer_vision_request') is request_marker) != marked
                or request.method != 'POST' or str(request.url) != frozen.request_url
                or not same_model
                or request.headers.get('Authorization', '') != frozen.authorization
                or request.headers.get('Cookie')):
            raise VisionDestinationChanged('vision physical request changed')
        if frozen.provider == 'nous' and (request.headers.get('x-api-key')
                or request.headers.get('proxy-authorization')
                or (frozen.wire_mode == 'anthropic_messages'
                    and request.headers.get('anthropic-version') != '2023-06-01')):
            raise VisionDestinationChanged('vision physical authentication changed')
        if frozen.provider == 'anthropic' and (
                request.headers.get('x-api-key') != config.api_key
                or request.headers.get('anthropic-version') != '2023-06-01'
                or request.headers.get('proxy-authorization')):
            raise VisionDestinationChanged('vision physical authentication changed')
        if frozen.provider == 'gemini' and (
                request.headers.get('x-goog-api-key') != config.api_key
                or request.headers.get('proxy-authorization')):
            raise VisionDestinationChanged('vision physical authentication changed')
        if frozen.provider == 'openai-responses' and (
                request.headers.get('x-api-key') or request.headers.get('x-goog-api-key')
                or request.headers.get('proxy-authorization')):
            raise VisionDestinationChanged('vision physical authentication changed')
        if recovery is not None:
            try:
                messages = payload.get('messages', [])
                image_bearing = any(
                    isinstance(message, dict) and isinstance(message.get('content'), list)
                    and any(isinstance(part, dict) and part.get('type') in {'image_url', 'image'}
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
    scope = (vision_retry_scope(backend, config.model, check, max_attempts=1 + frozen.empty_retries)
             if frozen.empty_retries or frozen.provider in {'nous', 'ollama', 'anthropic', 'gemini', 'openai-responses'} else nullcontext(None))
    with scope as recovery:
        final_hook_required = (recovery is not None or bool(frozen.provider_block)
                               or bool(cleared_findings) or frozen.provider in {'deepinfra', 'nous', 'ollama', 'anthropic', 'gemini', 'openai-responses'})
        if final_hook_required:
            backend.client.event_hooks['request'].append(last_request_hook)
        try:
            with physical_request_scope(check, request_check=request_check):
                yield check
                check()
        finally:
            if final_hook_required:
                backend.client.event_hooks['request'].remove(last_request_hook)


@contextmanager
def composer_request_scope(config, backend, *, resolve_config, remote_ack, principal, frozen=None,
                           cleared_findings=()):
    if getattr(principal, 'channel', None) != 'web':
        raise VisionPolicyUnavailable('composer vision requires an interactive web request')
    if not config.is_local and remote_ack is not True:
        raise VisionRemoteAckRequired('remote vision acknowledgment required')
    with _native_request_scope(config, backend, resolve_config=resolve_config,
                               frozen=frozen or describe(config), notice_purpose='composer_vision',
                               cleared_findings=cleared_findings) as check:
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
