# H23.24-H23.28 Tooling Cluster Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the five audit-derived release/tooling items as one coherent batch PR without changing runtime API behavior.

**Architecture:** Add four offline-first scripts plus one extension of `status_sync.py`. Keep network, process, SQLite, git, and filesystem readers injectable or isolated behind pure functions so tests stay hermetic; generate documentation from one machine-readable project-status object; make privacy and park-policy checks fail closed.

**Tech Stack:** Python 3.12 standard library, pytest, YAML registry input, GitHub Actions.

## Global Constraints

- No new HTTP routes and therefore no HUD/mobile parity changes.
- No conversation content in partner exports unless the operator explicitly selects a separate future lane; this batch has no such flag.
- Owner and market release gates are reported honestly and never auto-passed.
- Parked modules remain frozen until an explicit `unpark:` declaration names the matching phase or module.
- Update `BACKLOG.md` in the same feature commit; do not add scope beyond H23.24-H23.28.

---

### Task 1: H23.24 soak evidence collector

**Files:** Create `scripts/soak_report.py`; create `tests/test_soak_report.py`.

**Interfaces:** `collect_sample(fetch, ...) -> dict`, `summarize(samples) -> dict`, `render_report(...) -> str`, CLI writes JSONL samples plus a dated Markdown report.

- [ ] Add pure tests for duration parsing, outage capture, restart/growth/breach aggregation, log-signature redaction, torn JSONL recovery, and SQLite/WAL sizing.
- [ ] Run `python -m pytest tests/test_soak_report.py -q` and confirm failure because the script is absent.
- [ ] Implement the minimal injectable collector and renderer, then rerun the test file and Ruff.

### Task 2: H23.25 release gate

**Files:** Create `scripts/release_gate.py`; create `tests/test_release_gate.py`.

**Interfaces:** `run_gate(...) -> list[dict]`, `render(results) -> str`; CLI returns non-zero for any FAIL and supports `--skip-tests`/`--json`.

- [ ] Add tests for suite/snapshot semantics, status/link/version checks, owner ledger parsing, feedback evidence, rendering, and exit verdict.
- [ ] Run the focused tests red, restore the handoff implementation, then run focused tests and Ruff green.

### Task 3: H23.26 generated project status

**Files:** Modify `scripts/status_sync.py`, `tests/test_status_sync.py`, `README.md`, `NERVA.md`, `GO_LIVE_PLAN.md`, `STATUS.md`; create `project-status.json`.

**Interfaces:** `build_project_status(...) -> dict`, `apply_generated_snippets(path, text, status) -> str`; `--check` compares every generated artifact without rewriting.

- [ ] Add failing tests for agent counting, horizon roll-ups/open gates, deterministic JSON, marker-bounded snippets, and check-mode drift.
- [ ] Implement collectors for backend/frontend/mobile tests, route count, version, active agents, latest CI commit, and release gates.
- [ ] Insert stable generated markers in the three satellite docs, generate `project-status.json`, and verify idempotence.

### Task 4: H23.27 privacy-safe partner export

**Files:** Create `scripts/export_partner_feedback.py`; create `tests/test_export_partner_feedback.py`.

**Interfaces:** `build_packet(...) -> dict`, `render_markdown(packet) -> str`; CLI writes paired JSON and Markdown files chosen locally by the operator.

- [ ] Add failing tests for environment allowlisting, funnel/action/latency/NPS aggregation, north-star inclusion, absent-store degradation, JSON serializability, and conversation/credential exclusion.
- [ ] Implement read-only SQLite/API readers with bounded aggregate output and explicit privacy metadata.
- [ ] Run focused tests and Ruff green.

### Task 5: H23.28 park-list CI guard

**Files:** Create `scripts/park_guard.py`, `tests/test_park_guard.py`, `.github/workflows/park-guard.yml`.

**Interfaces:** `evaluate(changed_paths, declaration, policy) -> result`; CLI reads base/head refs and PR title/body inputs, returning non-zero on unauthorized parked-path changes.

- [ ] Add failing tests for all parked path families, unrelated changes, missing/mismatched declarations, phase aliases, and policy self-protection.
- [ ] Implement a data-driven phased policy and exact path matching; add the pull-request workflow with full-history checkout.
- [ ] Run focused tests and Ruff green.

### Task 6: Tracker sync, verification, and draft PR

**Files:** Modify `BACKLOG.md`, `STATUS.md`, and generated status artifacts from Task 3.

- [ ] Mark H23.24-H23.28 done with concrete files/tests, refresh generated counts, and inspect the complete diff for scope/privacy/security.
- [ ] Run all five focused test files, `python scripts/code_health.py` for touched Python, then the full offline suite.
- [ ] Commit the batch, push the designated branch, and open a draft PR with goal/non-goals/risk/tests/rollback and explicit final status.
