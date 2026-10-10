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

These completions cover the command tree, not option names, option values, file arguments or positional argument values. All three shells scope candidates to the exact command path and derive them recursively from live subparsers; synthetic deeper parser extensions and aliases are covered by tests. A leaf command or unknown path offers no sibling commands. Generated candidates are literal data, including command names containing shell metacharacters. Zsh uses `compadd --` so punctuation is not interpreted as an `_values` descriptor.

The earlier Fish slice used fish 4.9.3 in an isolated temporary runtime: syntax checks, actual `complete -C` output at every live subparser, partial prefixes, nested extensions, leaf behavior, repeated sourcing and substitution refusal. Tests use `fish --no-config` and never alter shell startup files. Environments without fish skip only the optional real-shell cases. No fish runtime is added to Nerva's product dependencies.

The 2026-10-10 Bash/Zsh correction executes the generated functions in those real shells, checks syntax, and covers current command paths, nested aliases, leaf/unknown paths and literal punctuation. The Zsh test captures `compadd` arguments instead of simulating an interactive editor. Current Fish script-generation tests pass; three real-Fish tests skip because that executable is absent in this environment. Historical Fish execution is not presented as a fresh run.
