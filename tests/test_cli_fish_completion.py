"""Parser-derived fish completions; optional real-shell tests never invoke Nerva."""
import argparse
import io
import os
import shutil
import subprocess

import pytest

from agents.cli.nerva import Context, build_parser, completion_script, main


def test_cli_accepts_fish_completion_without_a_hub():
    out = io.StringIO()
    assert main(['completion', 'fish'], context=Context(environ={}, out=out, err=io.StringIO())) == 0
    assert 'complete -c nerva' in out.getvalue()


@pytest.mark.parametrize('shell', ['', 'powershell', 'Fish'])
def test_public_generator_rejects_unknown_shell(shell):
    with pytest.raises(ValueError, match='shell'):
        completion_script(shell)


@pytest.fixture
def fish():
    binary = shutil.which('fish')
    if not binary:
        pytest.skip('fish is not installed; generated script still has parser tests')
    return binary


def query(fish, tmp_path, parser, line):
    script = tmp_path / 'nerva.fish'
    script.write_text(completion_script('fish', parser))
    syntax = subprocess.run([fish, '--no-config', '--no-execute', str(script)], capture_output=True, text=True, timeout=5)
    assert syntax.returncode == 0, syntax.stderr
    result = subprocess.run([fish, '--no-config', '-c',
                            'source "$argv[1]"; source "$argv[1]"; complete -C "$argv[2]"',
                            str(script), line], capture_output=True, text=True, timeout=5,
                            env={**os.environ, 'HOME': str(tmp_path), 'XDG_CONFIG_HOME': str(tmp_path)})
    assert result.returncode == 0, result.stderr
    return {word.split('\t', 1)[0] for word in result.stdout.splitlines()}


def nodes(parser, path=()):
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            yield path, set(action.choices)
            for name, child in action.choices.items():
                yield from nodes(child, (*path, name))


def test_every_live_command_path_completes_exactly(fish, tmp_path):
    parser = build_parser()
    for path, expected in nodes(parser):
        assert query(fish, tmp_path, parser, 'nerva ' + ' '.join(path) + ' ') == expected
    assert query(fish, tmp_path, parser, 'nerva jobs doctor ') == set()
    assert query(fish, tmp_path, parser, 'nerva jobs doc') == {'doctor'}


def test_generated_fish_recurses_into_parser_extensions(fish, tmp_path):
    parser = argparse.ArgumentParser()
    top = parser.add_subparsers().add_parser('new-verb')
    child = top.add_subparsers().add_parser('nested')
    child.add_subparsers().add_parser('leaf')
    assert query(fish, tmp_path, parser, 'nerva new-verb nested ') == {'leaf'}
    assert query(fish, tmp_path, parser, 'nerva new-verb wrong ') == set()


def test_fish_command_names_cannot_execute_substitutions(fish, tmp_path):
    marker = tmp_path / 'injected'
    parser = argparse.ArgumentParser()
    parser.add_subparsers().add_parser(f"literal'(touch {marker})")
    query(fish, tmp_path, parser, 'nerva ')
    assert not marker.exists()
