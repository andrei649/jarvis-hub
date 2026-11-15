"""The actual streamed/non-streamed turn never lets a bundle shadow a command."""

import pytest

from tests.test_h026_skill_bundles import (
    _hub,
    _md_skill,
    _say,
    _write,
    isolated,  # noqa: F401 — shared isolated bundle/skill stores
)


@pytest.mark.asyncio
@pytest.mark.parametrize('stream', [False, True])
@pytest.mark.parametrize('name,text', [('h', '/h'), ('nerva', '/nerva help')])
async def test_bundle_cannot_shadow_alias_or_platform_fallback(tmp_path, monkeypatch, stream, name, text):
    orch, seen = _hub(tmp_path, monkeypatch, _md_skill('weather'))
    _write(tmp_path, f'{name}.yaml', f'name: {name}\nskills: [weather]\n')
    reply, notices = await _say(orch, text, stream=stream)
    assert not seen.sent, 'a registered command was sent to the model as a bundle'
    assert '/help' in reply
    assert not any('bundle' in n.lower() for n in notices)


@pytest.mark.asyncio
@pytest.mark.parametrize('stream', [False, True])
async def test_explicit_bundle_keeps_access_to_a_colliding_name(tmp_path, monkeypatch, stream):
    orch, seen = _hub(tmp_path, monkeypatch, _md_skill('weather'))
    _write(tmp_path, 'h.yaml', 'name: h\nskills: [weather]\n')
    await _say(orch, '/bundle h', stream=stream)
    assert len(seen.sent) == 1
    assert 'skill bundle' in seen.sent[0]


@pytest.mark.asyncio
@pytest.mark.parametrize('stream', [False, True])
async def test_invalid_quick_command_still_reserves_its_name(tmp_path, monkeypatch, stream):
    from agents.core import settings_db
    orch, seen = _hub(tmp_path, monkeypatch, _md_skill('weather'))
    _write(tmp_path, 'weather.yaml', 'name: weather\nskills: [weather]\n')
    original = settings_db.get_value
    monkeypatch.setattr(settings_db, 'get_value', lambda category, key, default=None:
                        {'weather': {'invalid': True}} if (category, key) == ('commands', 'quick_commands')
                        else original(category, key, default))
    reply, notices = await _say(orch, '/weather', stream=stream)
    assert 'Invalid quick-command configuration' in reply
    assert not seen.sent
