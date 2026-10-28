"""Portable checks for cmd.exe syntax errors in retained Windows launchers."""
import re
from pathlib import Path

import pytest


@pytest.mark.parametrize('name', ['INSTALL.bat', 'START.bat', 'UPDATE.bat', 'UNINSTALL.bat'])
def test_windows_launchers_have_no_empty_if_command_groups(name):
    # cmd.exe rejects an empty parenthesized IF body, including an opt-in branch.
    source = (Path(__file__).resolve().parents[1] / name).read_text(encoding='utf-8')
    empty_groups = list(re.finditer(r'(?im)^\s*if\b[^\r\n]*\(\s*\)', source))
    assert not empty_groups, (
        f'{name}: empty cmd.exe IF body at lines '
        f'{[source.count(chr(10), 0, match.start()) + 1 for match in empty_groups]}'
    )
