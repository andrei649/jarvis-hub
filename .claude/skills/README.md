# Jarvis dev-skills (BACKLOG H22.7)

Repo-specific **developer** skills for coding assistants (Claude Code, opencode,
Gemini CLI) — distinct from the runtime *agent* capabilities in the top-level
`skills/` directory. They encode jarvis conventions so an assistant follows them
without re-deriving the rules each session.

## Format (superpowers convention)
Each `<name>/SKILL.md` has YAML frontmatter:
- `name` — the skill id.
- `description` — **starts with "Use when…"** and lists *triggering conditions*;
  it must NOT summarize the workflow (the assistant acts on the description, then
  reads the body only when triggered).

Bodies use progressive disclosure and stay short (<200 words for hot skills).

## Skills here
| Skill | Triggers on |
|-------|-------------|
| `jarvis-load-context` | start of any task — what to read instead of the ~2M-token repo |
| `jarvis-add-route` | adding/moving an HTTP endpoint (per-domain router + parity re-seed) |
| `jarvis-write-test` | writing/fixing a pytest test (sys.path bootstrap, offline fakes) |
| `jarvis-add-plugin` | adding a third-party integration (concurrent gatherer spec) |

## Pairing with obra/superpowers (optional, host action)
These complement the [superpowers](https://github.com/obra/superpowers) pipeline
(brainstorm → plan → subagent-driven dev → TDD → review). Install it once per
machine to get that pipeline across assistants:

```
/plugin install superpowers@claude-plugins-official
```

The plugin install is a per-developer host action — it is not vendored here.
