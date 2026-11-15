"""Bounded command discovery advertises only usable namespaces for this caller."""

from types import SimpleNamespace

import pytest

from agents.core import settings_db
from agents.core.commands import Principal, build_default_registry
from tests.test_h026_skill_bundles import _hub, _md_skill, _write, isolated  # noqa: F401


async def pages(orch, *, channel="web", admin=True):
    principal = Principal(channel=channel, admin=admin, scope="dm")
    first = await orch.commands.dispatch('/commands', orch=orch, principal=principal)
    assert first.status == 'answered' and first.reply.startswith('Commands — page 1/')
    total = int(first.reply.splitlines()[0].split('/')[1].split()[0])
    result = [first.reply]
    for n in range(2, total + 1):
        page = await orch.commands.dispatch(f'/commands {n}', orch=orch, principal=principal)
        result.append(page.reply)
    return result


@pytest.mark.asyncio
async def test_owner_discovery_paginates_commands_and_readable_skills(tmp_path, monkeypatch):
    orch, seen = _hub(tmp_path, monkeypatch, _md_skill('weather'), _md_skill('notes'))
    settings_db.put_category('skills', {'disabled': ['notes']})
    found = await pages(orch)
    assert len(found) > 1 and all(len(p.splitlines()) <= 22 for p in found)
    text = '\n'.join(found)
    assert '/weather — skill' in text and '/notes — skill' not in text
    assert '/status' in text and '/commands' in text and seen.sent == []
    orch.checkpoints.close()


@pytest.mark.asyncio
async def test_guest_discovery_cannot_advertise_owner_skills_or_commands(tmp_path, monkeypatch):
    orch, seen = _hub(tmp_path, monkeypatch, _md_skill('weather'))
    settings_db.put_category('commands', {'user_allowed_commands': {'telegram': {'dm': ['commands']}}})
    text = '\n'.join(await pages(orch, channel='telegram', admin=False))
    assert '/help' in text and '/whoami' in text
    assert '/weather' not in text and '/pause' not in text and seen.sent == []
    orch.checkpoints.close()


@pytest.mark.asyncio
async def test_skill_discovery_respects_bundle_collision_and_telegram_spelling(tmp_path, monkeypatch):
    skill = _md_skill('athena only')
    orch, _ = _hub(tmp_path, monkeypatch, skill, _md_skill('weather'))
    _write(tmp_path, 'weather.yaml', 'name: Weather\nskills: [weather]\n')
    web = '\n'.join(await pages(orch))
    telegram = '\n'.join(await pages(orch, channel='telegram'))
    assert '/athena-only — skill' in web
    assert '/athena_only — skill' in telegram and '/athena-only — skill' not in telegram
    assert '/bundle weather — bundle' in web and '/weather — skill' not in web
    orch.checkpoints.close()


@pytest.mark.asyncio
async def test_telegram_skill_spelling_cannot_advertise_a_quick_command_collision(tmp_path, monkeypatch):
    orch, _ = _hub(tmp_path, monkeypatch, _md_skill('athena only'))
    settings_db.put_category('commands', {'quick_commands': {
        'athena_only': {'type': 'alias', 'target': '/help'}}})
    telegram = '\n'.join(await pages(orch, channel='telegram'))
    assert '/athena_only — quick alias' in telegram
    assert '/athena_only — skill' not in telegram
    orch.checkpoints.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('value', ['0', '-1', 'foo', '1 extra', '9999999'])
async def test_bad_page_returns_usage_without_running_model(value):
    registry = build_default_registry()
    orch = SimpleNamespace(commands=registry)
    result = await registry.dispatch('/commands ' + value, orch=orch, principal=Principal(admin=True))
    assert result.status == 'answered' and 'Usage: /commands [page]' in result.reply
