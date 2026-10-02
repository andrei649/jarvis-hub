"""Nous native Messages image encoding and typed answer normalization."""

from .native_response import normalized_vision_text
from .reasoning_effort import apply_anthropic


def messages_payload(compatible: dict) -> dict:
    messages = []
    system = []
    for message in compatible['messages']:
        content = message['content']
        if message['role'] == 'system':
            if not isinstance(content, str):
                raise ValueError('invalid vision system message')
            system.append(content)
            continue
        parts = [{'type': 'text', 'text': content}] if isinstance(content, str) else content
        blocks = []
        for part in parts:
            if part.get('type') == 'text':
                blocks.append({'type': 'text', 'text': part['text']})
            elif part.get('type') == 'image_url':
                uri = part['image_url']['url']
                header, separator, data = uri.partition(',')
                mime = header.removeprefix('data:').removesuffix(';base64')
                if not separator or not header.startswith('data:') or not header.endswith(';base64') or mime not in {
                        'image/png', 'image/jpeg', 'image/gif', 'image/webp'} or not data:
                    raise ValueError('invalid native vision image')
                blocks.append({'type': 'image', 'source': {'type': 'base64', 'media_type': mime, 'data': data}})
            else:
                raise ValueError('invalid native vision block')
        messages.append({'role': message['role'], 'content': blocks})
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
