"""Host-owned async bridge from signed package hooks to native wire guards.

No third-party class or callable enters the host profile. A prepared view belongs
to one exact model/message/context batch; ordinary synchronous use refuses.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, fields

from ..provider_request import (
    ProfileRequestRefused,
    _owned_json,
    prepare_profile_messages,
    profile_request_defaults,
)
from . import ProviderProfile


def _metadata(profile):
    return {item.name: getattr(profile, item.name) for item in fields(ProviderProfile)}


def _json(value, maximum=256 * 1024):
    return json.dumps(_owned_json(value, maximum=maximum), ensure_ascii=False,
                      allow_nan=False, sort_keys=True, separators=(',', ':'))


@dataclass(frozen=True)
class AdmittedProviderProfile(ProviderProfile):
    _hook_runtime: object = field(default=None, repr=False, compare=False)
    _package_hash: str = field(default='', repr=False)
    _home: str | None = field(default=None, repr=False)

    @classmethod
    def from_record(cls, record, runtime):
        if (type(record.profile) is not ProviderProfile
                or type(record.package_hash) is not str
                or re.fullmatch(r'[a-f0-9]{64}', record.package_hash) is None):
            raise ProfileRequestRefused('invalid admitted profile binding')
        return cls(**_metadata(record.profile), _hook_runtime=runtime,
                   _package_hash=record.package_hash, _home=record.home)

    def prepare_messages(self, messages):
        raise ProfileRequestRefused('admitted hooks require async preparation')

    def build_extra_body(self, **context):
        raise ProfileRequestRefused('admitted hooks require async preparation')

    def build_api_kwargs_extras(self, **context):
        raise ProfileRequestRefused('admitted hooks require async preparation')


@dataclass(frozen=True)
class _PreparedProfile(ProviderProfile):
    _model: str = field(default='', repr=False)
    _messages_json: str = field(default='', repr=False)
    _context_json: str = field(default='', repr=False)
    _result_json: str = field(default='', repr=False)

    def prepare_messages(self, messages):
        if _json(messages) != self._messages_json:
            raise ProfileRequestRefused('prepared hook message binding changed')
        return json.loads(self._result_json)['prepared_messages']

    def _context(self, context):
        if _json(context) != self._context_json:
            raise ProfileRequestRefused('prepared hook context binding changed')

    def build_extra_body(self, *, session_id=None, **context):
        self._context({'session_id': session_id, **context})
        return json.loads(self._result_json)['extra_body']

    def build_api_kwargs_extras(self, *, reasoning_config=None, **context):
        self._context({'reasoning_config': reasoning_config, **context})
        result = json.loads(self._result_json)['api_kwargs']
        return result['extra_body'], result['kwargs']

    def get_max_tokens(self, model):
        if model != self._model:
            raise ProfileRequestRefused('prepared hook model binding changed')
        return json.loads(self._result_json)['max_tokens']


async def prepare_admitted_profile(profile, *, model, messages, reasoning_config=None,
                                   session_id=None):
    """Await one isolated batch, then validate it with the native host guards."""
    if not isinstance(profile, AdmittedProviderProfile):
        return profile
    static = ProviderProfile(**_metadata(profile))
    sanitized = prepare_profile_messages(static, messages)
    original = _json(sanitized)
    context = {'model': model, 'session_id': session_id,
               'reasoning_config': _owned_json(reasoning_config)}
    frozen_context = _json(context)
    result = await profile._hook_runtime.evaluate(
        profile.id, package_hash=profile._package_hash, home=profile._home,
        model=model, messages=json.loads(original), reasoning_config=_owned_json(reasoning_config),
        session_id=session_id)
    result = _owned_json(result, maximum=512 * 1024)
    expected = {'prepared_messages', 'extra_body', 'api_kwargs', 'max_tokens',
                'reasoning_vocabulary'}
    if (type(result) is not dict or set(result) != expected
            or type(result['api_kwargs']) is not dict
            or set(result['api_kwargs']) != {'extra_body', 'kwargs'}):
        raise ProfileRequestRefused('invalid isolated profile result')
    declared = static.supported_reasoning_efforts(model)
    if result['reasoning_vocabulary'] != (list(declared) if declared is not None else None):
        raise ProfileRequestRefused('isolated profile reasoning declaration changed')
    prepared = _PreparedProfile(**_metadata(static), _model=model,
                                _messages_json=original, _context_json=frozen_context,
                                _result_json=_json(result, maximum=512 * 1024))
    prepare_profile_messages(prepared, sanitized)
    profile_request_defaults(prepared, model, session_id=session_id,
                             context={'reasoning_config': reasoning_config})
    return prepared
