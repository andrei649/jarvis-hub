"""Unknown skill-shaped slash names stay commands rather than model messages."""

import pytest

from agents.core.commands import CommandRegistry, Principal


@pytest.mark.asyncio
@pytest.mark.parametrize("admin", [False, True])
async def test_unknown_hyphenated_slash_name_returns_command_notice(admin):
    result = await CommandRegistry().dispatch('/missing-skill instruction', orch=None,
                                               principal=Principal(channel='web', admin=admin))
    assert result is not None and result.status == 'unknown'
    assert result.name == 'missing-skill'
