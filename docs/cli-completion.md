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

These completions cover the command tree, not option names, option values, file arguments or positional argument values. Fish candidates are scoped to the exact command path and derived recursively from live subparsers; synthetic deeper parser extensions are covered by tests. Generated candidates are literal data, including command names containing shell metacharacters.

Verification for this slice used fish 4.9.3 in an isolated temporary runtime: syntax checks, actual `complete -C` output at every live subparser, partial prefixes, nested extensions, leaf behavior, repeated sourcing and substitution refusal. Tests use `fish --no-config` and never alter shell startup files. Environments without fish skip only the optional real-shell cases. No fish runtime is added to Nerva's product dependencies.
