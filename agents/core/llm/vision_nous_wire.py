"""Nous native Messages image encoding and typed answer normalization."""

import base64
import binascii

from .native_response import normalized_vision_text
from .reasoning_effort import apply_anthropic


def messages_payload(compatible: dict) -> dict:
    messages = []
    system = []
    next_role = 'user'
    image_count = 0
    for message in compatible['messages']:
        content = message['content']
        if message['role'] == 'system':
            if messages or not isinstance(content, str):
                raise ValueError('invalid vision system message')
            system.append(content)
            continue
        role = message['role']
        if role != next_role:
            raise ValueError('invalid native vision role')
        if role == 'assistant' and (not isinstance(content, str) or not content):
            raise ValueError('invalid native vision assistant message')
        parts = [{'type': 'text', 'text': content}] if isinstance(content, str) else content
        if not isinstance(parts, list):
            raise ValueError('invalid native vision content')
        blocks = []
        for part in parts:
            if not isinstance(part, dict):
                raise ValueError('invalid native vision block')
            if part.get('type') == 'text' and isinstance(part.get('text'), str):
                blocks.append({'type': 'text', 'text': part['text']})
            elif (role == 'user' and part.get('type') == 'image_url'
                  and isinstance(part.get('image_url'), dict)):
                uri = part['image_url'].get('url')
                if not isinstance(uri, str):
                    raise ValueError('invalid native vision image')
                header, separator, data = uri.partition(',')
                mime = header.removeprefix('data:').removesuffix(';base64')
                if not separator or not header.startswith('data:') or not header.endswith(';base64') or mime not in {
                        'image/png', 'image/jpeg', 'image/gif', 'image/webp'} or not data:
                    raise ValueError('invalid native vision image')
                try:
                    base64.b64decode(data, validate=True)
                except (ValueError, binascii.Error):
                    raise ValueError('invalid native vision image') from None
                blocks.append({'type': 'image', 'source': {'type': 'base64', 'media_type': mime, 'data': data}})
                image_count += 1
            else:
                raise ValueError('invalid native vision block')
        if not blocks:
            raise ValueError('invalid native vision content')
        messages.append({'role': role, 'content': blocks})
        next_role = 'user' if role == 'assistant' else 'assistant'
    if next_role != 'assistant' or not image_count:
        raise ValueError('invalid native vision turn')
    payload = {**compatible, 'messages': messages}
    if system:
        payload['system'] = '\n\n'.join(system)
    apply_anthropic(payload, compatible['model'], '')
    return payload


def _blocks(payload):
    if (not isinstance(payload, dict) or 'error' in payload or payload.get('type') != 'message'
            or payload.get('role') != 'assistant' or not isinstance(payload.get('content'), list)
            or payload.get('stop_reason') not in (None, 'end_turn', 'max_tokens', 'stop_sequence')):
        raise ValueError('invalid native vision response')
    blocks = payload['content']
    for block in blocks:
        if not isinstance(block, dict) or block.get('type') not in {'text', 'thinking', 'redacted_thinking'}:
            raise ValueError('invalid native vision response')
        field = {'text': 'text', 'thinking': 'thinking', 'redacted_thinking': 'data'}[block['type']]
        if not isinstance(block.get(field), str):
            raise ValueError('invalid native vision response')
    return blocks


def messages_answer(payload) -> str:
    blocks = _blocks(payload)
    text = '\n\n'.join(normalized_vision_text(b['text']) for b in blocks if b['type'] == 'text').strip()
    if text:
        return text
    return '\n\n'.join(normalized_vision_text(b['thinking']) for b in blocks if b['type'] == 'thinking').strip()


def messages_empty(payload) -> bool:
    try:
        blocks = _blocks(payload)
    except ValueError:
        return False
    return payload.get('stop_reason') == 'end_turn' and all(
        b['type'] == 'text' and not b['text'].strip() for b in blocks)
