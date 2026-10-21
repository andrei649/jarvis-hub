# CLI shell completion

The installed argparse tree generates command/subcommand completions for bash, zsh and fish. Scripts are printed to stdout by the offline completion command. Sourcing them does not invoke Nerva or connect to the hub.

For the current fish session:

```fish
nerva completion fish | source
```

To keep fish completion across sessions, the owner can save the generated script to fish's user completion directory:

```fish
mkdir -p ~/.config/fish/completions
nerva completion fish > ~/.config/fish/completions/nerva.fish
```

Regenerate a saved script after upgrading Nerva. Bash and zsh generation remains available through `nerva completion bash` and `nerva completion zsh`. The public Python helper `completion_script(shell)` rejects unsupported shell names instead of returning a different shell's script.

These completions cover the command tree, its help text and profile names (H574, below); not other option names, option values, file arguments or positional argument values. All three shells scope candidates to the exact command path and derive them recursively from live subparsers; synthetic deeper parser extensions and aliases are covered by tests. A leaf command or unknown path offers no sibling commands. Generated candidates are literal data, including command names containing shell metacharacters. Zsh uses `compadd -l -d displays --` so punctuation is not interpreted as an `_values` descriptor.

The earlier Fish slice used fish 4.9.3 in an isolated temporary runtime: syntax checks, actual `complete -C` output at every live subparser, partial prefixes, nested extensions, leaf behavior, repeated sourcing and substitution refusal. Tests use `fish --no-config` and never alter shell startup files. Environments without fish skip only the optional real-shell cases. No fish runtime is added to Nerva's product dependencies.

The 2026-10-10 Bash/Zsh correction executes the generated functions in those real shells, checks syntax, and covers current command paths, nested aliases, leaf/unknown paths and literal punctuation. The Zsh test captures `compadd` arguments instead of simulating an interactive editor. Current Fish script-generation tests pass; three real-Fish tests skip because that executable is absent in this environment. Historical Fish execution is not presented as a fresh run.

## Help text and profile names (H574)

The generator lives in `agents/cli/completion.py`; `agents.cli.nerva.completion_script` wraps it.

- **Help text.** Every command and root option carries its argparse `help`, folded to one printable line of at most 72 characters. Fish shows it with `complete -d`, zsh with `compadd -d` display strings, and bash in the listing it prints on a second <Tab> (`COMP_TYPE` 63) as `name  -- help`; what bash inserts is always the bare name, and a single match is never decorated. Every live command has help text (pinned by `tests/test_cli_shell_completion.py`).
- **Profile names.** `nerva -p NAME …` / `nerva --profile NAME …` selects an H689 profile for one invocation, exactly as `JARVIS_PROFILE=NAME` would (an invalid name is a usage error, exit 2); offline verbs then read that profile's data root, online verbs still reach `NERVA_HUB_URL`. After `-p`/`--profile` the scripts offer `default` plus every directory under `<install root>-profiles/` whose name is a valid profile name; symlinks and other entries are skipped. The shell lists that directory when you press <Tab>, so completion never runs `nerva` and a profile created later appears without regenerating the script. `$JARVIS_HOME`, then `$JARVIS_MEMORY_DIR`, set at completion time pick the install root, as `agents.core.paths.install_root` does; otherwise the root resolved when the script was generated is used. After the profile, completion continues at the verb. Values are completed after `-p NAME` / `--profile NAME` in all three shells and after `--profile=` in bash; a `--profile=NAME` word before the verb is skipped by all three.

All three shells are exercised for real (`bash`, `zsh -f`, `fish --no-config`) in `tests/test_cli_shell_completion.py` and `tests/test_cli_fish_completion.py`, including help text containing quotes, `$( )`, backticks and fish `( )` substitutions, which stays literal data.
