"""Parser-derived fish completions; optional real-shell tests never invoke Nerva."""
import argparse
import io
import os
import shutil
import subprocess

import pytest

from agents.cli.completion import completion_nodes, help_line
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


def raw_query(fish, tmp_path, parser, line, profiles_base=None, **env):
    """``complete -C`` output lines (``name<TAB>help``) for *line*."""
    script = tmp_path / 'nerva.fish'
    script.write_text(completion_script('fish', parser, profiles_base=profiles_base))
    syntax = subprocess.run([fish, '--no-config', '--no-execute', str(script)], capture_output=True, text=True, timeout=5)
    assert syntax.returncode == 0, syntax.stderr
    base = {k: v for k, v in os.environ.items() if k not in ('JARVIS_HOME', 'JARVIS_MEMORY_DIR', 'JARVIS_PROFILE')}
    result = subprocess.run([fish, '--no-config', '-c',
                            'source "$argv[1]"; source "$argv[1]"; complete -C "$argv[2]"',
                            str(script), line], capture_output=True, text=True, timeout=5,
                            env={**base, 'HOME': str(tmp_path), 'XDG_CONFIG_HOME': str(tmp_path), **env})
    assert result.returncode == 0, result.stderr
    return result.stdout.splitlines()


def query(fish, tmp_path, parser, line, profiles_base=None, **env):
    return {word.split('\t', 1)[0] for word in raw_query(fish, tmp_path, parser, line, profiles_base, **env)}


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


# ── H574: help text and profile names ────────────────────────────────────────

def test_fish_shows_each_commands_help_text(fish, tmp_path):
    parser = build_parser()
    lines = raw_query(fish, tmp_path, parser, 'nerva jobs ')
    helps = dict(completion_nodes(parser)[('jobs',)])
    assert {line.split('\t', 1)[0]: line.split('\t', 1)[1] for line in lines} == helps
    root = dict(line.split('\t', 1) for line in raw_query(fish, tmp_path, parser, 'nerva --pro'))
    assert 'JARVIS_PROFILE' in root['--profile']


def test_fish_help_text_cannot_execute_substitutions(fish, tmp_path):
    marker = tmp_path / 'injected'
    hostile = f"it's (touch {marker}) $(touch {marker}) \\"
    parser = argparse.ArgumentParser()
    parser.add_subparsers().add_parser('alpha', help=hostile)
    lines = raw_query(fish, tmp_path, parser, 'nerva al')
    assert lines == [f'alpha\t{help_line(hostile)}']
    assert not marker.exists()


def _profiles(tmp_path):
    home = tmp_path / 'home'
    home.mkdir()
    root = tmp_path / 'home-profiles'
    for name in ('work', 'lab-2', 'Bad!', 'default'):
        (root / name).mkdir(parents=True)
    (root / 'a-file').write_text('not a profile')
    (root / 'link').symlink_to(root / 'work')
    return home


def test_fish_completes_profile_names_then_the_command_path(fish, tmp_path):
    home = _profiles(tmp_path)
    parser = build_parser()
    env = {'JARVIS_HOME': str(home)}
    assert query(fish, tmp_path, parser, 'nerva -p ', **env) == {'default', 'lab-2', 'work'}
    assert query(fish, tmp_path, parser, 'nerva --profile wo', **env) == {'work'}
    (tmp_path / 'home-profiles' / 'later').mkdir()
    assert 'later' in query(fish, tmp_path, parser, 'nerva -p ', **env)
    root = {name for name, _ in completion_nodes(parser)[()]}
    assert query(fish, tmp_path, parser, 'nerva -p work ', **env) == root
    assert query(fish, tmp_path, parser, 'nerva --profile work jobs doc', **env) == {'doctor'}
    assert query(fish, tmp_path, parser, 'nerva --profile=work jobs doc', **env) == {'doctor'}
    assert query(fish, tmp_path, parser, 'nerva -p work jobs doctor ', **env) == set()


def test_fish_completes_the_profile_equals_form(fish, tmp_path):
    # Review round 3: `nerva --profile=<TAB>` listed nothing in fish (bash handles it).
    home = _profiles(tmp_path)
    parser = build_parser()
    env = {'JARVIS_HOME': str(home)}
    assert query(fish, tmp_path, parser, 'nerva --profile=', **env) == {
        '--profile=default', '--profile=lab-2', '--profile=work'}
    assert query(fish, tmp_path, parser, 'nerva --profile=w', **env) == {'--profile=work'}
    # only as the first word: after a verb it is not the root option
    assert query(fish, tmp_path, parser, 'nerva jobs --profile=', **env) == set()
    assert query(fish, tmp_path, parser, 'nerva -p work --profile=', **env) == set()


def test_fish_profile_root_falls_back_to_the_generated_install_root(fish, tmp_path):
    home = _profiles(tmp_path)
    parser = build_parser()
    assert query(fish, tmp_path, parser, 'nerva -p ', profiles_base=str(home)) == {'default', 'lab-2', 'work'}
    (tmp_path / 'other-profiles' / 'solo').mkdir(parents=True)
    assert query(fish, tmp_path, parser, 'nerva -p ', profiles_base=str(home),
                 JARVIS_MEMORY_DIR=str(tmp_path / 'other')) == {'default', 'solo'}
