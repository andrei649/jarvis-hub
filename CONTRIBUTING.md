# Contributing to Jarvis Hub

Thank you for your interest in contributing. This guide covers prerequisites, local setup, running the server and tests, and the branch/PR workflow.

---

## Prerequisites

- **Python 3.12** — other versions are not tested
- **LM Studio** or **Ollama** — at least one local inference backend must be running on port 1234 (LM Studio default) or 11434 (Ollama default)
- **Docker** (optional) — needed only if you want to run Qdrant, Neo4j, or n8n locally; see `docker-compose.yml`

---

## Setup

```bash
# 1. Clone the repo
git clone https://github.com/andrei649/jarvis-hub.git
cd jarvis-hub

# 2. Install dependencies
pip install -r requirements-beta.txt

# 3. Copy the example env file and fill in your values
cp .env.example .env
# Edit .env: set ANTHROPIC_API_KEY, GEMINI_API_KEY, TELEGRAM_BOT_TOKEN, etc.
# At minimum, set DEV_MODE=1 to skip keys that are not needed locally.

# 4. Configure models
# Ensure LM Studio is running with a model loaded on port 1234,
# OR Ollama is running with a model pulled (e.g. ollama pull gemma2).
```

---

## Run the server

```bash
python -m uvicorn agents.web:app --host 127.0.0.1 --port 8080
```

The HUD is at http://127.0.0.1:8080/ and the admin panel at http://127.0.0.1:8080/admin.

---

## Run tests

```bash
python -m pytest tests/ -q
# Expected: 909 passed
```

Tests are fully offline — no real LLM or network access required. All external backends are mocked.

---

## Code health (find improvements)

A single command runs the project's static-analysis toolchain — lint, formatting,
dead-code, and complexity hotspots — and prints a digest of improvement candidates:

```bash
pip install -r requirements-dev.txt    # one-time: installs ruff + vulture
python scripts/code_health.py          # full digest (never fails your shell)
python scripts/code_health.py --fix    # apply ruff's safe autofixes
python scripts/code_health.py --only lint     # run a single step
python scripts/code_health.py --strict        # exit 1 if any finding (gating)
```

- **Config is centralized** in `pyproject.toml` (`[tool.ruff]`, `[tool.vulture]`) so
  your editor, this script, and CI all agree on the rules.
- **It is advisory, not a gate** — consistent with "verde devreme peste perfecțiune".
  CI runs the same pass in `.github/workflows/code-health.yml` on every PR and weekly,
  publishing the digest to the run's job summary, but it never blocks a merge.
- Prefer fixing findings **in the files you already touch** rather than repo-wide sweeps
  (keeps diffs reviewable). Use `--fix` for the safe, mechanical ones.

---

## Branch and PR workflow

1. **Create a feature branch** from `main`:
   ```bash
   git checkout main && git pull origin main
   git checkout -b feat/my-feature
   ```
2. Make your changes. Keep commits focused and atomic.
3. Run the full test suite locally (`python -m pytest tests/ -q`) — CI must be green before merging.
4. **Open a Draft PR** early so others can see work in progress.
5. When ready, mark the PR as "Ready for review". A maintainer will review and merge.
6. Do not push directly to `main`.

---

## Code conventions

- Follow the patterns in `AGENTS.md` and `docs/ARCHITECTURE.md`.
- Do not modify `core/` modules without discussing the change in an issue first.
- All new endpoints go in `agents/web.py` — additive only, at the end of the file.
- New agents: add a `SOUL.md` under `agents/<id>/` and an entry in `agents/_system/agents.yaml`.
- New skills: create `skills/<name>/SKILL.md` + `skills/<name>/main.py`.

---

## Optional: Docker services (Qdrant, Neo4j, n8n)

```bash
docker compose up -d qdrant neo4j n8n
```

Then set the relevant env vars in `.env`:
- `VECTOR_BACKEND=qdrant` + `QDRANT_URL=http://localhost:6333`
- `NEO4J_URL=bolt://localhost:7687`
- `N8N_BASE_URL=http://localhost:5678`
