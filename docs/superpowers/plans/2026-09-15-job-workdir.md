# Approved script-only job workdir implementation plan

**Goal:** Owner-authored `options.workdir` selects a real subprocess directory for scheduled Python scripts with `no_agent: true`, through the existing approved local terminal path.
**Base:** 6301356e. **Execution:** inline planning/TDD; independent source review before handoff. No global evidence, protected authority files, assets or publication.

Frozen H449 includes per-job workdir; upstream `31-automation.md:49` also includes project instruction loading and terminal/file/code context. This increment implements the script-only subprocess requirement at line235 and keeps broader model workdir support explicitly partial. H146 gains concrete advanced authoring. No process-wide `chdir`, instruction-file injection, model filesystem reach or sandbox mount mutation.

## Contract

- Optional workdir is a nonempty absolute string <=1024 characters, resolving to an existing directory inside current `JARVIS_TERMINAL_LOCAL_ROOTS` (default existing runtime workspace). Reject symlink components, missing/non-directory/outside paths, URLs and relative paths. Do not create directories or alter configured roots.
- Only `script` plus exact `no_agent: true` accepts this field. Reject monitor/model/reminder combinations instead of saving inert configuration. Omit field to clear it using existing replacement-options editing.
- Store canonical path; recheck at firing and freeze it as `terminal_run.args.cwd` alongside exact script source. Fresh task approval still applies. Existing approved argument comparison and terminal transport root/directory rechecks stay in force. A job edit does not rewrite an already proposed task; owner task approval sees its frozen cwd.
- A cwd constraint is not a filesystem sandbox for approved Python. Existing local-host opt-in, target policy, kernel, per-task human approval, scrubbed environment and subprocess timeout remain unchanged.
- CLI accepts --workdir with explicit complete --options, so edits cannot silently discard old script configuration. Empty --workdir removes the field from supplied options. UI provides script/no-agent/workdir authoring and shows the configured cwd; server validates every combination. Doctor reports invalid/missing workdir without repair.

## Steps

- [x] Validation helper and create/edit/clear tests: malformed inputs, scoped roots, canonical path, missing/symlink/outside paths, unsupported modes.
- [x] Script payload integration and real governed local subprocess tests: cwd/relative reads, two concurrent job directories, unchanged parent cwd, fresh denial/e-stop, frozen approved cwd and runtime disappearance refusal.
- [x] CLI/UI/doctor authoring and truthful outcome tests, including unsupported combinations and clear semantics.
- [x] Focused backend/frontend tests, both frontend typechecks, Ruff/Bandit, source-only commit and independent review. Record exact evidence here. Parent handles integration/bundle/global assessments.

Files: new `agents/core/autonomy/jobs_workdir.py`; narrow `jobs.py`, `jobs_scripts.py`, `jobs_health.py`; `agents/cli/nerva.py`; frontend job builder/jobs view; scoped tests and this plan. Existing environment/terminal authority modules should require no changes.


## Verification and limits

- Backend: 258 passed, one pre-existing Starlette/httpx warning. Command: `/tmp/nerva-python-runtime/bin/python -m pytest tests/test_job_workdir.py tests/test_job_scripts.py tests/test_jobs_doctor.py tests/test_jobs_edit.py tests/test_jobs_routes.py tests/test_nerva_cli.py tests/test_local_transport.py -o addopts='' -q`. New coverage: 22 workdir cases and two CLI cases.
- Frontend: all 1,316 default-suite tests passed with one worker (`npm test -- --maxWorkers=1 --reporter=json --outputFile=/tmp/nerva-job-workdir-frontend.json`), including one new authoring case. Focused Jobs suite: 18 passed. Both frontend TypeScript configurations passed.
- Whole-repository Ruff, Bandit1.9.4 against the existing baseline over relative `agents scripts`, and `git diff --check` passed.
- RED then GREEN: valid create/edit/clear and real concurrent subprocess cwd; CLI/workdir authoring and doctor status; UI controls; reviewer regression for contradictory unsupported-options text. Existing terminal approval and script lifecycle regressions also pass.
- The subprocess evidence uses the real governed runner/transport with temporary directories and a test kernel grant/approval decision; no production permission or channel action. Tests prove denial, e-stop, missing directories and symlink escapes refuse; approved tasks retain their frozen cwd after job edits. Parent process cwd remains unchanged.
- Workdir selection does not freeze directory contents/inodes or convert approved host Python into a filesystem sandbox. Existing terminal execution re-resolves the approved canonical path against current roots. Scripts require existing local-host opt-in and fresh task approval. Model instruction-file loading and terminal/file/code-execution workspace isolation remain unsupported.
- Source-only handoff; parent owns generated frontend assets, route/global evidence and publication.

## Integrated verification

Independent review cleared source d7cde62c: 235 backend checks including separate restart/frozen-cwd and changed-task-argument regressions, plus 18 Jobs UI checks. Root rebased only the source onto837d6d08 and regenerated the HUD at c3e6437d; all1,316 frontend checks, three TypeScript configurations and Vite passed. No terminal authority module changed. The integrated guarded backend run collected 11,484 cases: 11,460 passed, 23 skipped and one expected failure, with no unexpected failures (249.75 seconds, 58 warnings).

Release evidence used the product Python3.12 and `/tmp/nerva-run-isolated.py`, with `TMPDIR=/private/tmp`, the existing fish4.9.3 executable on PATH, and `/usr/bin/env NERVA_PUBLIC_PROFILE=0` before the product interpreter. Pytest.ini remained unchanged: timeout30s/thread and loopback-only socket guards were active. Command after the launcher: `/Users/andrei649/Projects/nerva-hub/.venv/bin/python3.12 -m pytest tests --junitxml=/tmp/nerva-job-workdir-integrated-guarded.xml`. Earlier interrupted runs with an addopts override or alternate interpreter are excluded from release evidence.

Hermes reports, status projections and backend-count verification pass. Release gate machine checks pass; existing owner/market gaps remain: live-model evaluation, B0 manual signoff and partner feedback, plus a missing soak-evidence warning. These are not credited by the code-only workdir tests. Only previously-current affected reviews H004/H523 were incidentally revalidated alongside H146/H449/H453/H684; no pre-existing stale review was blanket-refreshed.
