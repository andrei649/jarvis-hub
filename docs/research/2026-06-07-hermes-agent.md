# Hermes / `hermes-agent` — research: what it is, and why our importer is broken against it

> Date 2026‑06‑07 · Goal: ground‑truth what `NousResearch/hermes-agent` actually is in 2026, verify
> whether `agents/core/skills/importer.py` (`import_from_hermes`) still works against the live repo,
> and decide what to mine. Grounded in **direct GitHub API + raw‑source fetches** (not memory — the
> repo post‑dates the Jan‑2026 model cutoff) cross‑checked by 5 fan‑out search agents.
>
> **Headline:** `hermes-agent` is **real, MIT, and one of the most active agent projects on GitHub**
> (created 2025‑07‑22, ~185.7k★, pushed 2026‑06‑07). But our importer is pointed at a layout and file
> format that **no longer exist there** — `import_from_hermes()` 404s on every real skill today, and
> even if it didn't, `loader.py` would never load the result. This is a **latent‑broken feature**, not
> a working one. The good news: the fix aligns us with an *open* standard (agentskills.io `SKILL.md`),
> not anything Hermes‑proprietary.

## 1. What `hermes-agent` actually is (VERIFIED via GitHub API)

Two different Nous projects share the "Hermes" name; we must not conflate them.

| | `NousResearch/hermes-agent` | `NousResearch/Hermes-Function-Calling` (legacy) |
|---|---|---|
| What | "The agent that grows with you" — self‑hosted autonomous agent product | Reference inference code for Hermes‑2‑Pro JSON tool calling |
| Created | 2025‑07‑22 | 2024 |
| Activity | `pushed_at` **2026‑06‑07**, release **v0.16.0** (2026‑06‑05), ~10.9k commits | last commit **2025‑12‑22** (~6 mo stale) |
| Stars | **~185,676** | ~1.4k |
| License | **MIT** ("Copyright (c) 2025 Nous Research") | **MIT** ("Copyright (c) 2024 Nous Research") |
| Skills? | **Yes** — `skills/` tree, agentskills.io‑compatible | **No** — single self‑recursive function‑call loop |

Verified directly: `https://api.github.com/repos/NousResearch/hermes-agent` returned
`id 1024554267, created_at 2025-07-22, stargazers_count 185676, forks 31917, open_issues 19034,
license MIT, default_branch main, description "The agent that grows with you"` — confirmed by a second
independent org‑repos API fetch (same star count + `pushed_at`).

**Architecture / capabilities** (from README + docs; runtime internals are Nous's own description, not
code‑audited by us):
- Multi‑channel gateway: Telegram, Discord, Slack, WhatsApp, Signal, Email, CLI + a desktop app.
- Model‑agnostic: Nous Portal, OpenRouter (200+), NVIDIA NIM, GLM/z.ai, Kimi, MiniMax, HF, OpenAI, "your own endpoint" — switch with `hermes model`, no code change.
- **Self‑improving "learning loop":** writes/refines reusable skill documents from experience; procedural memory; a "Skills Hub"; natural‑language cron.
- **Multi‑agent primitive:** `delegate_tool` spawns an isolated subagent (own conversation + terminal); concurrent delegation capped by `delegation.max_concurrent_children` (default 3); `execute_code` runs sandboxed Python that calls Hermes tools over a Unix‑socket RPC (secrets not readable).
- **OpenClaw migration path:** `hermes claw migrate` → `~/.hermes/skills/openclaw-imports/` (same `SKILL.md` lineage we analysed in `2026-06-05-openclaw-feature-analysis.md`).

## 2. The real skill format — and why our importer misses it (VERIFIED from source)

**Live layout is three‑level and uses `SKILL.md`, not a manifest file:**
```
skills/<category>/<skill-name>/
  ├── SKILL.md        # required — YAML frontmatter + markdown instructions
  ├── templates/  references/  scripts/  assets/   # optional
```
Categories in‑repo: `apple, autonomous-ai-agents, creative, data-science, devops, email, github,
media, mlops, note-taking, productivity, red-teaming, research, smart-home, social-media,
software-development, …` (each has a `DESCRIPTION.md`; actual skills are one level deeper).

**A real `SKILL.md` frontmatter** (verbatim, `skills/github/github-issues/SKILL.md`):
```yaml
---
name: github-issues
description: "Create, triage, label, assign GitHub issues via gh or REST."
version: 1.1.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [GitHub, Issues, Project-Management, Bug-Tracking, Triage]
    related_skills: [github-auth, github-pr-workflow]
---
# (markdown body = the prompt/instructions)
```
Documented frontmatter fields: `name, description, version, author, platforms` + under
`metadata.hermes`: `tags, category, related_skills, requires_toolsets, fallback_for_toolsets,
required_environment_variables, required_credential_files, config`. There is **one** JSON‑ish file —
a global `~/.hermes/skills/.bundled_manifest` (skill→content‑hash for update drift detection) — but it
is **not** a per‑skill manifest and declares no tools/prompt/command/agents.

### What `importer.py` assumes (and how each assumption fails)

`agents/core/skills/importer.py` (`HERMES_REPO="NousResearch/hermes-agent"`, `HERMES_SKILLS_PATH="main/skills"`):

| Importer assumption | Reality | Result |
|---|---|---|
| Skills are flat: `main/skills/<name>/` | Three‑level: `main/skills/<category>/<name>/` | wrong path depth |
| File is `manifest.json` / `manifest.yaml` / `<name>.json` / `<name>.yaml` | File is `SKILL.md` (YAML frontmatter) | all 4 candidate URLs **404** |
| Schema has `tools, prompt, command, agents` | Frontmatter has `author, license, platforms, metadata.hermes.*`; prompt is the markdown **body** (no `prompt`/`command`/`agents` keys; tools ≈ `requires_toolsets`) | empty/garbage fields even if fetched |

Net: `import_from_hermes(<any real skill>)` exhausts its 4 URL candidates → hits the GitHub `contents`
API fallback (which lists category dirs, not a manifest) → returns **`False`** ("not found"). The
feature is **broken for the current repo**.

### Second, independent break: importer ↔ loader mismatch (local)

Even if the fetch succeeded, `_save_skill()` writes `skills/<name>/manifest.json` — but our own
`agents/core/skills/loader.py:_load_skill()` **only reads `SKILL.md`** (and via a *Markdown‑heading*
convention — `# name`, `> desc`, `**Version:**`, `## Commands` — **not** YAML frontmatter). So imported
skills are never discovered/loaded regardless of the fetch. Two formats diverge three ways:

| | hermes-agent (real) | importer.py writes | loader.py reads |
|---|---|---|---|
| File | `SKILL.md` | `manifest.json` | `SKILL.md` |
| Schema | YAML frontmatter | JSON manifest | Markdown headings |

## 3. The Hermes tool‑calling format (stable across model generations)

Worth knowing even though it's separate from the agent repo — it's the same ChatML scheme from Hermes
2 Pro → Hermes 4.3, so an agent loop built once works across sizes:
- Tools declared in the system prompt inside `<tools>…</tools>` as OpenAI‑style JSON‑schema function objects.
- Model emits `<tool_call>{"name":…,"arguments":{…}}</tool_call>`; results returned in a `tool` role inside `<tool_response>…</tool_response>`. ChatML tokens `<|im_start|>/<|im_end|>`. These are single special tokens in the Llama‑3‑based Hermes models.
- JSON mode embeds a schema in `<schema>…</schema>`. Tooling: vLLM has a Hermes tool‑call parser, llama.cpp supports the format, Ollama exposes tool calling for `hermes3`.

**Model family (context):** Hermes 2 Pro (Mistral 7B / Llama‑3 8B, 2024) → Hermes 3 (Llama 3.1
8B/70B/405B + 3.2 3B, Aug 2024, 128K ctx) → **Hermes 4** (14B=**Qwen3‑14B**, 70B/405B=Llama‑3.1, Aug
2025, toggleable `<think>` hybrid reasoning, ~131K ctx) → **Hermes 4.3 36B** (ByteDance Seed‑OSS‑36B,
Dec 2025, trained on Nous's Psyche network; GGUF + LM Studio listing; fits ~24 GB at Q4). Note: Hermes
4 14B is **Qwen3‑based**, not Llama — a common mis‑statement.

## 4. Licensing — safe to vendor? (VERIFIED LICENSE files)

- **`hermes-agent` code/skills = MIT** (raw LICENSE confirmed). **`Hermes-Function-Calling` = MIT.** Both safe to vendor into our project with attribution preserved (keep a `THIRD_PARTY_LICENSES` entry: "Nous Research, MIT").
- A few Nous repos have **no license** (`hermes-agent-self-evolution`, `autoreason`) → all‑rights‑reserved, **do not vendor**.
- **Model weights** are a separate matter: Apache‑2.0 for Hermes 2 Pro (Mistral); **Meta Llama Community License** for all Llama‑based Hermes (2 Pro Llama‑3, all Hermes 3, Hermes 4 70B/405B) — "Built with Llama" + naming + AUP + 700M‑MAU clauses. This governs *weights/derivatives*, not skill text files we author. Not relevant to vendoring `SKILL.md` files (those are MIT in‑repo).

→ **Vendoring individual MIT `SKILL.md` skills from `hermes-agent` is safe** with attribution.

## 5. Maintenance & 2026 fit

- `hermes-agent`: **aggressively maintained** (releases every few days). A good bet *as a skill source* — and a better one because its skills are **portable `SKILL.md` (agentskills.io)**, the standard now read by ~32 tools (Claude Code, Codex/Gemini CLI, Copilot, Cursor, Goose, Cline, OpenCode, and hermes‑agent itself; published by Anthropic 2025‑12‑18).
- `Hermes-Function-Calling`: **legacy / maintenance‑only.** The prompt‑template approach is superseded by native tool‑calling in modern open models + **MCP** (de‑facto interop standard; ~16–17k servers; adopted by OpenAI/Google/MS/AWS). Even Nous's own agent uses MCP + agentskills.io, not the old templates. **Don't build new work on it.**
- Local tool‑calling model picks (2026, indicative benchmarks): **Qwen3‑Coder/Qwen3 30–32B** or **Gemma 4 27B** (Q4_K_M+) lead; **Hermes 4 14B / 4.3 36B** are solid uncensored options with toggleable reasoning but not the tool‑calling leaders.

## 6. Implications for jarvis‑hub (actionable)

1. **Treat `import_from_hermes` as broken, not working.** STATUS.md / repo_export claim "✅ Skills Import (hermes)"; in reality it returns `False` for every current skill. Either fix it or mark it accurately (truth‑in‑docs, cf. H7.8). Worth a **BUG** entry. *(No live test catches this — `test_skills_api.py` mocks the importer.)*
2. **Rewrite the importer around `SKILL.md`, not `manifest.json`.** Concretely: walk the 3‑level tree (`contents/skills` → category → skill), fetch `SKILL.md`, parse YAML frontmatter, and **save it as `SKILL.md`** (not `manifest.json`) so `loader.py` can discover it.
3. **Reconcile the two local SKILL.md dialects.** Our `loader._parse_manifest` reads Markdown headings; hermes‑agent (and the agentskills.io standard) use **YAML frontmatter**. Teach the loader to parse frontmatter (fall back to the heading style) — this also future‑proofs us for *any* agentskills.io source (OpenClaw, Claude Code skills, etc.), not just Hermes. This is the highest‑leverage change: it turns the importer from "one broken source" into "any standard skill repo."
4. **Map fields honestly:** frontmatter `requires_toolsets`→our `requires`; markdown body→the skill prompt/instructions; there is no `command`/`agents` in Hermes skills, so synthesize/default rather than expect them.
5. **Add a real integration test** (recorded fixture of a live `SKILL.md`) so the next upstream layout change is caught, not silently shipped as "✅".
6. **Strategic framing:** don't bet on "Hermes format" — bet on **`SKILL.md` + MCP**. We already speak `SKILL.md` natively and have many MCP servers wired; aligning the importer to the open standard is the durable move. Hermes 4.3 36B is a reasonable *optional* local model, not a backbone.

**Sources:** `https://api.github.com/repos/NousResearch/hermes-agent` · `https://api.github.com/orgs/NousResearch/repos` · `github.com/NousResearch/hermes-agent` (+ `/tree/main/skills`, `skills/github/github-issues/SKILL.md`, LICENSE) · `github.com/NousResearch/Hermes-Function-Calling` (LICENSE, `prompt_assets/sys_prompt.yml`) · `hermes-agent.nousresearch.com/docs` · HF `NousResearch/Hermes-{2-Pro,3,4-14B,4-70B,4-405B,4.3-36B}` cards · Hermes 3/4 tech reports (arXiv 2408.11857, 2508.18255) · agentskills.io (Anthropic, 2025‑12‑18) · modelcontextprotocol.io 2026 roadmap · vLLM/llama.cpp/Ollama tool‑calling docs · internal: `agents/core/skills/{importer,loader}.py`, `docs/research/2026-06-05-openclaw-feature-analysis.md`.
