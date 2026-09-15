"""Fixed xAI Responses policy with bounded, invocation-owned encrypted replay."""
import json
from dataclasses import replace

from .base import cloud_cap
from .egress import llm_async_client
from .provider_replay import (
    KEY,
    ProviderReplay,
    active_replay,
    projection,
    remember,
    validate_history,
)
from .provider_request import profile_with_declarations
from .providers import DEFAULT_REGISTRY
from .reasoning_effort import ReasoningEffortRefused
from .request_context import current_session, ensure_reasoning_active, selected_reasoning
from .responses import TIMEOUT, ResponsesBackend
from .responses_dialect import (
    MAX_TEXT,
    ResponsesRefused,
    encoded,
    identifier,
    input_items,
    parse_response,
    text,
)

XAI_PROFILE = DEFAULT_REGISTRY.get('xai')
GROK_LEVELS = XAI_PROFILE.reasoning_declarations


class XAIBackend(ResponsesBackend):
    supports_provider_replay = True
    error = "[xAI Responses error: request could not be completed]"

    def _accept_completion(self):
        ensure_reasoning_active()
        active_replay()
    endpoint = 'https://api.x.ai/v1/responses'

    def __init__(self, api_key, *, reasoning_effort='', effort_declarations=None, transport=None):
        self.api_key = api_key
        self.reasoning_effort = reasoning_effort
        self.profile = profile_with_declarations(XAI_PROFILE, effort_declarations, defaults=GROK_LEVELS)
        self._replay_owner = object()
        self.client = llm_async_client('xai', timeout=TIMEOUT, transport=transport,
                                      follow_redirects=False, trust_env=False)

    def context_window(self, model):
        # Only the currently documented exact model window is asserted.
        return 500000 if model == 'grok-4.6' else None

    def _payload(self, model, messages, max_tokens, temperature, tools=()):
        ensure_reasoning_active()
        if not isinstance(model, str) or model not in XAI_PROFILE.fallback_models:
            raise ResponsesRefused()
        validate_history(messages, owner=self._replay_owner, provider='xai', model=model)
        plain = input_items(messages, allow_provider_replay=True)
        native, offset = [], 0
        for message in messages:
            calls = message.get('tool_calls', [])
            count = (int(bool(message.get('content')) or not calls) + len(calls)
                     if message.get('role') != 'tool' else 1)
            envelope = message.get(KEY)
            native.extend(json.loads(envelope.items) if envelope is not None
                          else plain[offset:offset + count])
            offset += count
        payload = {'model': model, 'input': native, 'store': False,
                   'include': ['reasoning.encrypted_content'],
                   'max_output_tokens': min(cloud_cap(max_tokens), 32768), 'temperature': temperature}
        level, reason = self.profile.clamp_reasoning_effort(model, selected_reasoning(self.reasoning_effort))
        if reason == 'below-minimum':
            raise ReasoningEffortRefused()
        if level is not None:
            payload['reasoning'] = {'effort': level}
        if tools:
            payload['tools'] = [{'type': 'function', 'name': t.name, 'description': t.description,
                                 'parameters': t.input_schema, 'strict': False} for t in tools]
            payload['tool_choice'] = 'auto'
        encoded(payload)
        return payload

    def _parse_response(self, value, model):
        encoded(value)
        if not isinstance(value, dict) or not isinstance(value.get('output'), list):
            raise ResponsesRefused()
        rows = value['output']
        if len(rows) > 256:
            raise ResponsesRefused()
        native, ordinary, ids = [], [], set()
        for row in rows:
            if not isinstance(row, dict) or row.get('status', 'completed') != 'completed':
                raise ResponsesRefused()
            optional = {key: row[key] for key in ('id', 'status') if key in row}
            if 'id' in row:
                item_id = row['id']
                if not isinstance(item_id, str) or len(item_id) > 256:
                    raise ResponsesRefused()
                if item_id:
                    if item_id in ids:
                        raise ResponsesRefused()
                    ids.add(item_id)
            kind = row.get('type')
            if kind == 'reasoning':
                ciphertext = row.get('encrypted_content')
                if (not isinstance(ciphertext, str) or not ciphertext
                        or len(ciphertext.encode('utf-8')) > MAX_TEXT):
                    # Never retain or expose provider plaintext reasoning.
                    raise ResponsesRefused()
                for key, block_type in [('summary', 'summary_text'), ('content', 'reasoning_text')]:
                    blocks = row.get(key, [] if key == 'content' else None)
                    if not isinstance(blocks, list) or any(
                        not isinstance(block, dict) or block.get('type') != block_type
                        or not isinstance(block.get('text'), str) for block in blocks
                    ):
                        raise ResponsesRefused()
                native.append({'type': kind, **optional,
                               'summary': [], 'encrypted_content': ciphertext})
            elif kind == 'function_call':
                identifier(row.get('call_id'))
                identifier(row.get('name'))
                text(row.get('arguments'))
                ordinary.append(row)
                native.append({**optional, **{k: row[k] for k in ('type', 'call_id', 'name', 'arguments')}})
            elif kind == 'message':
                ordinary.append(row)
                native.append({'type': kind, **optional,
                               'role': row.get('role'), 'content': [
                                   {k: b[k] for k in ('type', 'text' if b.get('type') == 'output_text' else 'refusal')}
                                   for b in row.get('content', [])]})
            else:
                raise ResponsesRefused()
        turn = parse_response({**value, 'output': ordinary})
        if turn.tool_calls:
            envelope = ProviderReplay('xai', model, self._replay_owner,
                                      active_replay(required=True), current_session(),
                                      encoded(native), projection(turn.as_assistant_message()))
            turn = replace(turn, provider_replay=envelope)
        return turn

    async def generate_tool_turn(self, model, messages, tools, max_tokens=1024, temperature=0.7):
        active_replay(required=True)
        turn = await super().generate_tool_turn(model, messages, tools, max_tokens, temperature)
        ensure_reasoning_active()
        active_replay(required=True)
        if turn.provider_replay is not None:
            remember(turn.provider_replay)
        return turn

    async def _request(self, payload):
        active_replay()
        turn = await super()._request(payload)
        self._accept_completion()
        return turn
