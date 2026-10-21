"""The hub's own file tools and terminal are never rooted in the workspace's company data (NWS-17).

The default roots are disjoint from ``<data>/business`` (tests/test_workspace_integration_
purge.py), but an operator could still set ``JARVIS_FILE_ROOTS`` or
``JARVIS_TERMINAL_LOCAL_ROOTS`` to the workspace directory, to the data root that contains
it, or to a folder under it — and the owner's personal assistant could then read the
company database and documents; the pilot guide asking operators not to was the only
control. Now such a root is dropped, with one warning per root, whatever its spelling
(``..``, a symlink); when none is left the default root applies, and every other root is
kept exactly as configured.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import pytest

from agents.core.environments import local_transport
from agents.core.environments.local_transport import LocalHostTransport
from agents.core.file_tools import FileScope
from agents.core.workspace import config
from tests.support.workspace_fixtures import ws  # noqa: F401  (ws is a fixture)

FILE_ROOTS = "JARVIS_FILE_ROOTS"
TERMINAL_ROOTS = "JARVIS_TERMINAL_LOCAL_ROOTS"


@pytest.fixture(autouse=True)
def fresh_warnings(monkeypatch):
    """A new process: no root warned about yet."""
    monkeypatch.setattr(config, "_warned_hub_roots", set(), raising=False)


def _file_roots(monkeypatch, value: str) -> list[Path]:
    monkeypatch.setenv(FILE_ROOTS, value)
    return list(FileScope.from_env().roots)


def _terminal_roots(monkeypatch, value: str) -> list[Path]:
    monkeypatch.setenv(TERMINAL_ROOTS, value)
    return [Path(root) for root in local_transport.default_roots()]


def _readers(monkeypatch):
    return {FILE_ROOTS: lambda value: _file_roots(monkeypatch, value),
            TERMINAL_ROOTS: lambda value: _terminal_roots(monkeypatch, value)}


def _guard_warnings(caplog) -> list[str]:
    return [record.getMessage() for record in caplog.records
            if record.levelno == logging.WARNING and "Nerva Workspace data directory"
            in record.getMessage()]


@pytest.mark.parametrize("setting", [FILE_ROOTS, TERMINAL_ROOTS])
@pytest.mark.parametrize("which", ["business", "data root", "files folder", "dotdot", "symlink"])
def test_a_root_that_reaches_company_data_is_dropped_for_the_default(ws, tmp_path, monkeypatch,
                                                                     caplog, setting, which):
    business = config.workspace_dir()
    (business / "files").mkdir(exist_ok=True)
    link = tmp_path / "shortcut"
    link.symlink_to(business, target_is_directory=True)
    root = {"business": business, "data root": ws.data_dir, "files folder": business / "files",
            "dotdot": f"{ws.data_dir}/workspace/../business", "symlink": link}[which]
    default = (ws.data_dir / "workspace").resolve()
    with caplog.at_level(logging.WARNING):
        roots = _readers(monkeypatch)[setting](str(root))
    assert [r.resolve() for r in roots] == [default], (which, roots)
    [warning] = _guard_warnings(caplog)
    assert setting in warning and str(business.resolve()) in warning


@pytest.mark.parametrize("setting", [FILE_ROOTS, TERMINAL_ROOTS])
def test_other_roots_are_kept_in_order_and_each_drop_is_logged_once(ws, tmp_path, monkeypatch,
                                                                    caplog, setting):
    first, second = tmp_path / "proiecte", tmp_path / "acte"
    first.mkdir()
    second.mkdir()
    business = config.workspace_dir()
    value = f"{first},{business},{second}"
    read = _readers(monkeypatch)[setting]
    with caplog.at_level(logging.WARNING):
        for _ in range(3):
            assert [r.resolve() for r in read(value)] == [first.resolve(), second.resolve()]
    assert len(_guard_warnings(caplog)) == 1


@pytest.mark.parametrize("setting", [FILE_ROOTS, TERMINAL_ROOTS])
def test_the_warning_says_what_the_dropped_root_keeps_out_and_claims_no_more(
        ws, monkeypatch, caplog, setting):
    """The line an operator reads states the terminal's limit (review REV-POLISH-03).

    It used to say the hub's "file tools and terminal never reach company data" — but the
    terminal's roots bound only its working directory: an approved ``cat ../business/…``
    still runs (PILOT_GUIDE §13, §18).
    """
    config.workspace_dir()
    with caplog.at_level(logging.WARNING):
        _readers(monkeypatch)[setting](str(ws.data_dir))
    [warning] = _guard_warnings(caplog)
    assert "never" not in warning and "so this root is ignored" in warning
    if setting == TERMINAL_ROOTS:
        assert "the terminal's working directory stays outside company data" in warning
        assert "a path inside an approved command" in warning
        assert "governed by the terminal's approval" in warning
    else:
        assert "the file tools stay outside company data" in warning
        assert "terminal" not in warning
    assert "PILOT_GUIDE §13" in warning


def test_an_unrelated_root_is_kept_unchanged(ws, tmp_path, monkeypatch, caplog):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    config.workspace_dir()
    with caplog.at_level(logging.WARNING):
        assert _file_roots(monkeypatch, str(elsewhere)) == [elsewhere.resolve()]
        assert _terminal_roots(monkeypatch, str(elsewhere)) == [elsewhere]
    assert _guard_warnings(caplog) == []


def test_the_terminal_built_from_the_env_cannot_run_inside_company_data(ws, tmp_path,
                                                                        monkeypatch):
    business = config.workspace_dir()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.setenv(TERMINAL_ROOTS, f"{ws.data_dir},{elsewhere}")
    transport = LocalHostTransport.from_env()
    assert [Path(root) for root in transport.roots] == [elsewhere.resolve()]
    assert transport.resolve_cwd(business) is None
    assert transport.resolve_cwd(elsewhere) == elsewhere.resolve()


def test_the_file_tools_refuse_a_company_file_even_with_the_data_root_configured(ws,
                                                                                monkeypatch):
    from agents.core.file_tools import FileScopeError

    database = config.workspace_dir() / "workspace.db"
    database.write_bytes(b"")
    monkeypatch.setenv(FILE_ROOTS, str(ws.data_dir))
    with pytest.raises(FileScopeError):
        FileScope.from_env().resolve(str(database))


def test_nothing_is_dropped_while_no_company_data_can_exist(ws, monkeypatch, caplog):
    """Workspace off and never used: the owner's roots stay exactly as configured."""
    monkeypatch.setenv("NERVA_WORKSPACE", "0")
    assert not (ws.data_dir / config.DATA_DIRNAME).exists()
    os.makedirs(ws.data_dir, exist_ok=True)
    with caplog.at_level(logging.WARNING):
        assert _file_roots(monkeypatch, str(ws.data_dir)) == [ws.data_dir.resolve()]
        assert _terminal_roots(monkeypatch, str(ws.data_dir)) == [ws.data_dir]
    assert _guard_warnings(caplog) == []
    (ws.data_dir / config.DATA_DIRNAME).mkdir()      # a workspace that was used, now off
    assert _file_roots(monkeypatch, str(ws.data_dir)) == [(ws.data_dir / "workspace").resolve()]
