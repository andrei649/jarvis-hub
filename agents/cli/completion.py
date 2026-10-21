"""Shell completion for ``nerva`` — generated from the live argparse tree (H004, H574).

``nerva completion bash|zsh|fish`` prints a script that completes:

* **command paths** — each parser node offers only its own children, so a parser
  extension appears without touching this file;
* **help text** — each command (and each root option) carries its argparse ``help``:
  fish shows it with ``-d``, zsh with ``compadd -d``, and bash in the listing it prints
  on a second <Tab> (``COMP_TYPE`` 63), never in what it inserts;
* **profile names** — after the root ``-p``/``--profile`` option, the profiles that
  exist on disk (``<install root>-profiles/<name>``, the H689 layout ``agents.core.paths``
  resolves) plus ``default``. The shell lists the directory itself at completion time:
  completing never runs ``nerva``, and a profile created later appears without
  regenerating the script. ``$JARVIS_HOME``/``$JARVIS_MEMORY_DIR`` are honoured at
  completion time as ``install_root`` honours them; otherwise the root resolved when the
  script was generated is used.

Every name, help line and path is emitted as quoted literal data, never as shell code.
Stdlib-only on purpose: completion must work without the hub's dependencies.
"""

from __future__ import annotations

import argparse
import os
import re
import shlex

SHELLS = ("bash", "zsh", "fish")
#: The profile-name rule ``agents.core.paths._PROFILE_RE`` enforces, as a shell regex.
PROFILE_RE = "^[a-z0-9][a-z0-9_-]{0,31}$"
HELP_CHARS = 72

_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]+")


def help_line(text: object) -> str:
    """One printable line of help: whitespace collapsed, controls dropped, bounded."""
    if not isinstance(text, str) or text == argparse.SUPPRESS:
        return ""
    line = " ".join(_CONTROL.sub(" ", text).split())
    if len(line) > HELP_CHARS:
        line = line[:HELP_CHARS - 1].rstrip() + "…"
    return line


def _children(node: argparse.ArgumentParser) -> dict[str, tuple[argparse.ArgumentParser, str]]:
    """name → (child parser, help) for every subcommand of *node*, aliases included."""
    out: dict[str, tuple[argparse.ArgumentParser, str]] = {}
    for action in node._actions:
        if not isinstance(action, argparse._SubParsersAction):
            continue
        helps = {}
        for choice in action._choices_actions:
            child = action.choices.get(choice.dest)
            if child is not None:
                helps[id(child)] = help_line(choice.help)
        for name, child in action.choices.items():
            out[name] = (child, helps.get(id(child), ""))
    return out


def completion_nodes(parser: argparse.ArgumentParser) -> dict[tuple[str, ...], tuple[tuple[str, str], ...]]:
    """Each parser node's exact command path → its children as ``(name, help)``, sorted."""
    nodes: dict[tuple[str, ...], tuple[tuple[str, str], ...]] = {}

    def walk(node: argparse.ArgumentParser, path: tuple[str, ...]) -> None:
        children = _children(node)
        if not children:
            return
        nodes[path] = tuple((name, children[name][1]) for name in sorted(children))
        for name in sorted(children):
            walk(children[name][0], (*path, name))

    walk(parser, ())
    return nodes


def completion_paths(parser: argparse.ArgumentParser) -> dict[tuple[str, ...], tuple[str, ...]]:
    """Each parser node's exact command path and its immediate child names."""
    return {path: tuple(name for name, _ in kids) for path, kids in completion_nodes(parser).items()}


def root_options(parser: argparse.ArgumentParser) -> tuple[tuple[str, str], ...]:
    """The root parser's option strings with their help, in declaration order."""
    out = []
    for action in parser._actions:
        if action.option_strings and not isinstance(action, argparse._SubParsersAction):
            for option in action.option_strings:
                out.append((option, help_line(action.help)))
    return tuple(out)


def profile_options(parser: argparse.ArgumentParser) -> tuple[str, ...]:
    """The root option strings that take a profile name (``dest == "profile"``), if any."""
    for action in parser._actions:
        if action.dest == "profile" and action.option_strings:
            return tuple(action.option_strings)
    return ()


def default_profiles_base() -> str:
    """The install root the script falls back to when ``$JARVIS_HOME`` is unset at completion."""
    from agents.core.paths import install_root  # stdlib-only module

    env = {key: value for key, value in os.environ.items()
           if key not in ("JARVIS_HOME", "JARVIS_MEMORY_DIR", "JARVIS_PROFILE")}
    try:
        return str(install_root(env))
    except RuntimeError:
        return ""


def _words(names) -> str:
    """An array of literal shell words, never code or a split completion string."""
    return " ".join(shlex.quote(name) for name in names)


# ── bash ─────────────────────────────────────────────────────────────────────

def _bash(parser: argparse.ArgumentParser, base: str) -> str:
    nodes = completion_nodes(parser)
    options = root_options(parser)
    profile = profile_options(parser)

    def assign(kids) -> str:
        return (f"candidates=({_words(n for n, _ in kids)}); "
                f"helps=({_words(h for _, h in kids)})")

    lines = [
        '# nerva bash completion — generated from the parser tree; eval "$(nerva completion bash)"',
        "_nerva() {",
        '    local cur="${COMP_WORDS[COMP_CWORD]}" o=0 i n width line',
        "    local -a candidates=() helps=() names=() descs=()",
        "    COMPREPLY=()",
    ]
    if profile:
        arms = "|".join(shlex.quote(opt) for opt in profile)
        lines += [
            "    # the root profile option comes before the verb: skip it and its value",
            "    while (( o + 1 < COMP_CWORD )); do",
            '        case "${COMP_WORDS[o+1]}" in',
            f"            {arms})",
            '                if [[ "${COMP_WORDS[o+2]}" == "=" ]]; then',
            "                    (( o + 3 < COMP_CWORD )) || break; o=$((o + 3))",
            "                else",
            "                    (( o + 2 < COMP_CWORD )) || break; o=$((o + 2))",
            "                fi ;;",
            "            *) break ;;",
            "        esac",
            "    done",
            "    if (( COMP_CWORD - o >= 2 )) && case \"${COMP_WORDS[o+1]}\" in "
            f"{arms}) true ;; *) false ;; esac; then",
            '        [[ "$cur" == "=" ]] && cur=""',
            f"        local base={shlex.quote(base)} re={shlex.quote(PROFILE_RE)} d",
            '        if [[ -n "${JARVIS_HOME:-}" ]]; then base="$JARVIS_HOME"',
            '        elif [[ -n "${JARVIS_MEMORY_DIR:-}" ]]; then base="$JARVIS_MEMORY_DIR"; fi',
            '        base="${base/#\\~/$HOME}"',
            '        while [[ "$base" == */ && "$base" != / ]]; do base="${base%/}"; done',
            "        candidates=(default)",
            '        for d in "$base-profiles"/*/; do',
            '            d="${d%/}"',
            '            [[ -d "$d" && ! -L "$d" ]] || continue',
            '            n="${d##*/}"',
            '            [[ "$n" =~ $re && "$n" != default ]] && candidates+=("$n")',
            "        done",
            "    elif (( COMP_CWORD - o == 1 )); then",
        ]
    else:
        lines.append("    if (( COMP_CWORD - o == 1 )); then")
    lines += [
        '        if [[ "$cur" == -* ]]; then',
        f"            {assign(options)}",
        "        fi",
        f"        candidates+=({_words(n for n, _ in nodes.get((), ()))}); "
        f"helps+=({_words(h for _, h in nodes.get((), ()))})",
        "    elif (( COMP_CWORD - o == 2 )); then",
        '        case "${COMP_WORDS[o+1]}" in',
    ]
    for path, kids in sorted(nodes.items()):
        if len(path) == 1:
            lines.append(f"            {shlex.quote(path[0])}) COMPREPLY=(); {assign(kids)} ;;")
    lines.append("        esac")
    for path, kids in sorted(nodes.items()):
        if len(path) < 2:
            continue
        checks = " && ".join(
            f'[[ "${{COMP_WORDS[o+{i}]}}" == {shlex.quote(part)} ]]' for i, part in enumerate(path, 1)
        )
        lines += [
            f"    elif (( COMP_CWORD - o == {len(path) + 1} )) && {checks}; then",
            f"        {assign(kids)}",
        ]
    lines += [
        "    fi",
        '    for i in "${!candidates[@]}"; do',
        '        [[ "${candidates[i]}" == "$cur"* ]] || continue',
        '        names+=("${candidates[i]}"); descs+=("${helps[i]-}")',
        "    done",
        '    COMPREPLY=("${names[@]}")',
        "    # help text only in the listing (second <Tab>), never in what is inserted",
        '    if (( ${#names[@]} > 1 )) && [[ "${COMP_TYPE-}" == 63 ]]; then',
        "        width=0",
        '        for n in "${names[@]}"; do (( ${#n} > width )) && width=${#n}; done',
        "        COMPREPLY=()",
        '        for i in "${!names[@]}"; do',
        '            if [[ -n "${descs[i]}" ]]; then',
        "                printf -v line '%-*s  -- %s' \"$width\" \"${names[i]}\" \"${descs[i]}\"",
        '                COMPREPLY+=("$line")',
        "            else",
        '                COMPREPLY+=("${names[i]}")',
        "            fi",
        "        done",
        "    fi",
        "}",
        "complete -F _nerva nerva",
    ]
    return "\n".join(lines) + "\n"


# ── zsh ──────────────────────────────────────────────────────────────────────

def _zsh(parser: argparse.ArgumentParser, base: str) -> str:
    nodes = completion_nodes(parser)
    options = root_options(parser)
    profile = profile_options(parser)

    def assign(kids) -> str:
        return (f"candidates=({_words(n for n, _ in kids)}); "
                f"helps=({_words(h for _, h in kids)})")

    lines = [
        "#compdef nerva",
        "# nerva zsh completion — generated from the parser tree",
        "_nerva() {",
        "    local o=0 i n width d",
        "    local -a candidates=() helps=() displays=()",
    ]
    if profile:
        arms = "|".join(shlex.quote(opt) for opt in profile)
        eq_arms = "|".join(shlex.quote(opt + "=") + "*" for opt in profile if opt.startswith("--"))
        skip = [f"            {arms}) (( o + 3 < CURRENT )) || break; o=$((o + 2)) ;;"]
        if eq_arms:
            skip.append(f"            {eq_arms}) o=$((o + 1)) ;;")
        lines += [
            "    # the root profile option comes before the verb: skip it and its value",
            "    while (( o + 2 < CURRENT )); do",
            '        case "${words[o+2]}" in',
            *skip,
            "            *) break ;;",
            "        esac",
            "    done",
            "    if (( CURRENT - o == 3 )) && case \"${words[o+2]}\" in "
            f"{arms}) true ;; *) false ;; esac; then",
            f"        local base={shlex.quote(base)} re={shlex.quote(PROFILE_RE)}",
            '        if [[ -n "${JARVIS_HOME:-}" ]]; then base="$JARVIS_HOME"',
            '        elif [[ -n "${JARVIS_MEMORY_DIR:-}" ]]; then base="$JARVIS_MEMORY_DIR"; fi',
            '        base="${base/#\\~/$HOME}"',
            '        while [[ "$base" == */ && "$base" != / ]]; do base="${base%/}"; done',
            "        candidates=(default)",
            '        for d in "$base-profiles"/*(N/); do',
            '            [[ -L "$d" ]] && continue',
            '            n="${d:t}"',
            '            [[ "$n" =~ $re && "$n" != default ]] && candidates+=("$n")',
            "        done",
            "    elif (( CURRENT - o == 2 )); then",
        ]
    else:
        lines.append("    if (( CURRENT - o == 2 )); then")
    lines += [
        '        if [[ "${words[CURRENT]}" == -* ]]; then',
        f"            {assign(options)}",
        "        fi",
        f"        candidates+=({_words(n for n, _ in nodes.get((), ()))}); "
        f"helps+=({_words(h for _, h in nodes.get((), ()))})",
    ]
    for path, kids in sorted(nodes.items()):
        if not path:
            continue
        checks = " && ".join(
            f'[[ "${{words[o+{i}]}}" == {shlex.quote(part)} ]]' for i, part in enumerate(path, 2)
        )
        lines += [
            f"    elif (( CURRENT - o == {len(path) + 2} )) && {checks}; then",
            f"        {assign(kids)}",
        ]
    lines += [
        "    fi",
        "    (( ${#candidates[@]} )) || return 0",
        "    width=0",
        '    for n in "${candidates[@]}"; do (( ${#n} > width )) && width=${#n}; done',
        "    for (( i = 1; i <= ${#candidates[@]}; i++ )); do",
        '        if [[ -n "${helps[i]-}" ]]; then',
        '            displays+=("${(r:width:)candidates[i]}  -- ${helps[i]}")',
        "        else",
        '            displays+=("${candidates[i]}")',
        "        fi",
        "    done",
        '    compadd -l -d displays -- "${candidates[@]}"',
        "    return 0",
        "}",
        '_nerva "$@"',
    ]
    return "\n".join(lines) + "\n"


# ── fish ─────────────────────────────────────────────────────────────────────

def _fish_quote(value: str) -> str:
    # fish single quotes recognize only escaped backslashes and single quotes.
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def _fish(parser: argparse.ArgumentParser, base: str) -> str:
    quote = _fish_quote
    profile = profile_options(parser)
    longs = [opt for opt in profile if opt.startswith("--")]
    skip = ""
    if profile:
        skip = "\n".join([
            "    while test (count $words) -ge 1",
            f"        if contains -- $words[1] {' '.join(quote(o) for o in profile)}",
            "            test (count $words) -ge 2; or break",
            "            set -e words[1..2]",
            *([f"        else if string match -q -- {' '.join(quote(o + '=*') for o in longs)} $words[1]",
               "            set -e words[1]"] if longs else []),
            "        else",
            "            break",
            "        end",
            "    end",
        ])
    lines = [
        "# nerva fish completion — generated from the live parser tree",
        "# Current session: nerva completion fish | source",
        "function __nerva_words",
        "    set -l words (commandline -opc)",
        "    set -e words[1]",
        *([skip] if skip else []),
        "    # printf with no arguments would still print one empty line, i.e. one empty word",
        "    test (count $words) -gt 0; and printf '%s\\n' $words",
        "    return 0",
        "end",
        "function __nerva_complete_path",
        "    set -l words (__nerva_words)",
        "    test (count $words) -eq (count $argv); or return 1",
        "    for word in $argv",
        '        test "$words[1]" = "$word"; or return 1',
        "        set -e words[1]",
        "    end",
        "    return 0",
        "end",
        "complete -c nerva -f",
    ]
    if profile:
        lines += [
            "function __nerva_complete_profile",
            "    set -l words (__nerva_words)",
            f"    test (count $words) -eq 1; and contains -- $words[1] {' '.join(quote(o) for o in profile)}",
            "end",
            "function __nerva_profiles",
            f"    set -l base {quote(base)}",
            '    if test -n "$JARVIS_HOME"',
            "        set base $JARVIS_HOME",
            '    else if test -n "$JARVIS_MEMORY_DIR"',
            "        set base $JARVIS_MEMORY_DIR",
            "    end",
            "    set base (string replace -r '^~(?=/|$)' $HOME -- $base)",
            "    set base (string replace -r '(?<=.)/+$' '' -- $base)",
            "    echo default",
            "    for dir in $base-profiles/*/",
            "        set -l dir (string replace -r '/$' '' -- $dir)",
            "        test -L $dir; and continue",
            "        set -l name (string replace -r '.*/' '' -- $dir)",
            f"        string match -qr -- {quote(PROFILE_RE)} $name; and test $name != default; and echo $name",
            "    end",
            "end",
            "complete -c nerva -n __nerva_complete_profile -a '(__nerva_profiles)' -d profile",
        ]
    root = _fish_quote("__nerva_complete_path")
    for option, text in root_options(parser):
        if option.startswith("--"):
            flag = f"-l {quote(option[2:])}"
        elif len(option) == 2:
            flag = f"-s {quote(option[1:])}"
        else:
            flag = f"-o {quote(option[1:])}"
        lines.append(f"complete -c nerva -n {root} {flag} -d {quote(text)}")

    def walk(node: argparse.ArgumentParser, path: tuple[str, ...]) -> None:
        condition = "__nerva_complete_path" + "".join(" " + quote(part) for part in path)
        children = _children(node)
        for name in sorted(children):
            child, text = children[name]
            # -a, -n and -d are evaluated by fish later; quote metadata at both the
            # definition and completion stages, never as shell code.
            lines.append(f"complete -c nerva -n {quote(condition)} -a {quote(quote(name))}"
                         f" -d {quote(text)}")
            walk(child, (*path, name))

    walk(parser, ())
    return "\n".join(lines) + "\n"


def completion_script(shell: str, parser: argparse.ArgumentParser, *,
                      profiles_base: str | None = None) -> str:
    """The completion script for *shell* over *parser*.

    *profiles_base* is the install root whose ``-profiles`` sibling holds the profiles
    (default: :func:`default_profiles_base`, resolved now).
    """
    if shell not in SHELLS:
        raise ValueError(f"unsupported completion shell: {shell!r}")
    base = default_profiles_base() if profiles_base is None else profiles_base
    return {"bash": _bash, "zsh": _zsh, "fish": _fish}[shell](parser, base)


__all__ = [
    "HELP_CHARS", "PROFILE_RE", "SHELLS", "completion_nodes", "completion_paths",
    "completion_script", "default_profiles_base", "help_line", "profile_options", "root_options",
]
