# Provider test environment root-cause analysis

2026-11-13 UTC; read-only source/log/filesystem inspection. No production edits, guard invocation, chmod/chown, security settings, installations or tests were performed. Only this report was written. Input: `FULL-BACKEND-SUMMARY.json` and `/tmp/nerva-v70-full-backend.log`.

## Finding

The provider path guards reject the executor's actual `/tmp` ownership. The process UID/GID is 1000/1000. `/tmp` is UID/GID 65534/65534, mode 01777. It is sticky but owned by neither root (UID 0) nor the current process owner (UID 1000). This is a deterministic environment incompatibility with the existing guards, not evidence that their checks should be weakened.

`agents/core/llm/providers/packages.py:297` `_secure_root` opens every component with `O_DIRECTORY|O_NOFOLLOW`. Its `safe_ancestor` predicate accepts an ancestor if it is a directory and either is not group/world writable, or is sticky and owned by UID 0/current UID. Traversal fails at `/tmp` and raises `provider store root or ancestor is unsafe` at line 335, before reaching the test's private store. Final roots must additionally belong to the current UID and not be group/world writable. The function itself calls `fchmod` on a verified final directory, so this read-only audit deliberately did not call it as a probe.

`agents/core/llm/providers/hook_runtime.py:110` `_private_runtime_root` uses the same sticky-owner exception for writable ancestors and requires the final root to be current-UID owned and exactly mode 0700. `/tmp` therefore also causes `unsafe_runtime_root` before hook projection.

Actual inspected ancestor chain from a failing full-run test:

| Component | UID | Mode | Provider safe-ancestor predicate |
| --- | ---: | --- | --- |
| `/` | 65534 | 0755 | accepts; no group/world write |
| `/tmp` | 65534 | 01777 | **rejects; sticky owner is neither 0 nor 1000** |
| `/tmp/pytest-of-agent` | 1000 | 0700 | accepts |
| `/tmp/pytest-of-agent/pytest-535` | 1000 | 0700 | accepts |
| `…/popen-gw0` | 1000 | 0700 | accepts |
| `…/test_real_owner_selection_cas_0` | 1000 | 0700 | accepts |

These paths were present and not symlinks when inspected. The full-run log explicitly records the `/tmp/pytest-of-agent/pytest-535/popen-gw0/...` test paths. A private child underneath `/tmp` cannot fix this: every ancestor is checked.

Verified alternative chain:

| Component | UID | Mode | Predicate |
| --- | ---: | --- | --- |
| `/` | 65534 | 0755 | accepts |
| `/workspace` | 1000 | 0755 | accepts |
| `/workspace/scratch` | 1000 | 0755 | accepts |
| `/workspace/scratch/nerva-v70-integration` | 1000 | 0700 | accepts |

All alternative components are existing directories and not symlinks. Pytest can create its own 0700 disposable roots below this private directory. This selects an environment meeting the guard contract; it changes neither guards nor existing filesystem permissions.

## Failure accounting and limits

The original run recorded 36,678 cases: 36,217 passed, 108 skipped, 212 failed and 141 errored. Of 353 failures/errors, 346 belong to H361/H367 provider modules or the action-auth matrix. In that group 340 failure/error messages contain the provider unsafe-ancestor or unsafe-runtime-root diagnostics, including regex expectation failures that expose the unexpected guard refusal. Six remaining results in this group are downstream mismatches/timeouts/custom-endpoint 409 responses: their environmental attribution is plausible but requires a rerun.

The seven results outside that group are two G17 process-group death assertions, one native-Chrome orphan-reaping assertion, and four stale API-sweep checks. Do not classify those seven as fixed by moving temp roots. The parent is addressing generated API documentation separately. No rerun has been performed by this audit, so neither all 346 nor the full backend is claimed green.

## Legitimate focused rerun

Set both locations for the test subprocess:

- `--basetemp` controls pytest `tmp_path` and xdist worker roots.
- `TMPDIR` controls Python `tempfile` roots, including `tests/conftest.py:14`'s per-process `_PYTEST_DATA_ROOT` used for `JARVIS_HOME`/`JARVIS_KEY_DIR`. `--basetemp` alone does not move those separately allocated runtime roots.

Run from `/workspace/jarvis-hub`. The following is a proposed command, **not executed here**:

```bash
TMPDIR=/workspace/scratch/nerva-v70-integration .venv/bin/python -m pytest -q -n 0 \
  --basetemp=/workspace/scratch/nerva-v70-integration/provider-env-smoke-20261113 \
  tests/test_h361_provider_packages.py::test_full_snapshot_owner_approval_and_fresh_restart \
  tests/test_h361_provider_hook_runtime.py::test_actual_worker_imports_all_signed_members_and_keeps_hook_inputs_independent \
  'tests/test_action_auth_matrix.py::test_kernel_kinds_actually_invoke_kernel[plugin.load]' \
  'tests/test_action_auth_matrix.py::test_kernel_kinds_actually_invoke_kernel[provider.custom_endpoint]' \
  tests/test_h361_provider_hook_runtime.py::test_runtime_root_rejects_symlink_final_or_ancestor_and_public_parent
```

Use a fresh dedicated `--basetemp` child each run: pytest deletes/recreates that exact base, so never set it to the report directory, repository, or any directory containing evidence. The suggested child above was not created by this audit. The existing integration parent remains the private `TMPDIR`; tempfile creates uniquely named children. No installer or permission modification is needed.

After the smoke passes, rerun the failed provider/action-auth modules under the same environment with a new dedicated base, preserving complete logs/XML. Include the deliberate symlink/public-parent negative tests: their continued refusal confirms this is relocation rather than bypassing the safety contract. If only those modules recover, report that correction separately from the original full run; a focused rerun does not retroactively make the full run green. Investigate residual failures individually, especially process reaping and downstream timeout behavior.

No action was denied or left with an uncertain execution outcome. The remaining blocker is verification: the proposed valid-root rerun has not yet occurred in this audit.
