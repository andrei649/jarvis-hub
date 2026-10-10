# H004 — complete only the current command-tree node

Generated 2026-10-10 UTC. Base and initial head:
`9a5fdf298c6e63bcc38ddde4946c96998726f53e`; branch
`codex/h004-shell-completion-20261010`. Goal: close the frozen Bash/Zsh/Fish
command-tree completion contract. Local implementation only; no publication.

Bash and Zsh currently use only the first verb and offer its children in every
later argument position. They also flatten the parser to two levels. Derive
candidate sets recursively from the live argparse tree, keyed by the exact
command path before the current word. Complete only the children at that node;
leaf arguments and unknown paths yield no command candidates. Preserve Fish's
existing recursive behavior and the public command_tree compatibility API.
Quote parser metadata as literal shell text; generation must not execute it.

Implementation agent gpt-6-sol/high owns only agents/cli/nerva.py and a focused
tests/test_cli_shell_completion.py. Root owns design, integration and evidence.
No subdelegation. Other agents may read those paths after the writer declares
them stable. No concurrent edits to the integration worktree.

TDD: reproduce sibling suggestions after a leaf, and omitted third-level
subcommands using an injected argparse tree. Execute generated Bash and Zsh
completion functions with deterministic word/cursor vectors; cover root, nested,
partial prefix, leaf, unknown path, parser aliases and literal shell-sensitive
names. Validate real shell syntax. Run existing CLI and Fish-generation tests;
record any real-Fish skip because that executable is absent here. No expensive
full suite while the independent integration milestone is running.

Non-goals: option or argument-value completion, new commands, external shell
configuration, or changes to execution authority. Rollback reverts the generator
delta and focused regressions together; no runtime data migration is involved.

Results: all six new Bash/Zsh regressions fail on the original generator. The
fixed three-file CLI/Fish selection passes 116 cases and skips three real-Fish
cases because the executable is absent. Root review caught Zsh `_values`
descriptor parsing despite literal shell quoting; three Zsh cases reproduce the
issue before switching to `compadd --`. Final tests include colon, bracket,
leading-dash, quote and substitution-shaped names. The Zsh harness captures raw
compadd arguments; this is not a claim of interactive editor validation.
Independent final H004/CLI/skill-switch/lint tests pass 218 cases. Ruff and
whitespace checks pass. H329's known kernel re-enable gap remains partial;
H350's validated lint behavior is preserved. Fish generation is unchanged.

The earlier integration milestone is complete with its documented focused
fixture correction. Changed implementation paths remain exactly the CLI module
and new shell regression module. Next action: save this independently reversible
unit, integrate locally, refresh H004 and the two reviewed CLI collateral pins,
and run delivery/metadata guards. No second full backend suite is needed for
this isolated CLI delta after its focused and collateral checks.

Final integration correction: the Zsh completion function now explicitly returns
zero when a leaf/unknown path has no candidates. The committed test harness
calls it directly and checks process status; three cases reproduced the error
on integration commit `08bb5a5e`. Corrective commit `9f139e0d` passes the combined
five-file integrated selection: 222 passed and three real-Fish skips. The source
is frozen; remaining work is documentation/evidence synchronization only.

Independent review of the exact corrective commit also passes all six H004
cases, with no concrete defect; quoted candidate handling remains unchanged.
The final integration metadata guards pass 86 cases. No shell startup files or
external service were changed.
