# Residency acknowledgment foundation

Goal: stop interpreting failed controller operations or active requests as confirmed
residency. Base: 98f24c76d256a6639378a5711c7c66c406dca3b4. Generated: 2026-09-15.
Head: source commit containing this plan. Next action: independent review.
Scope: model_manager.py, focused manager/Agent tests, this plan only.

## Approved design

Use an immutable ControllerAck(action, model_id) returned only after adapters
validate their concrete response. The manager requires this exact semantic receipt,
not truthiness. LM Studio requires status ok, kind lmstudio_control, matching
load_model/unload_model action and exact requested model, integer exit_code zero.
Resolved aliases are not accepted as the requested identity. Existing permission,
host-contract and disabled branches remain entirely inside the unchanged controller.
Ollama requires successful HTTP, object JSON, matching model, literal done true,
empty response and no error. Unload requires done_reason unload; load permits absent
or load reason, matching the documented empty-prompt response. No network retries.

Publish load tracking only after matching receipt. Retain old tracking until unload
receipt; stop replacement on refusal or exception. Cancellation propagates without
claiming the interrupted operation succeeded. Controller absence does not confirm.
Keep active reference counts separately from confirmed residents; unknown using()
entries disappear on final release and cannot create residency. Confirmed entries
mirror active references for existing introspection. Preserve default-off behavior,
public ensure/using contracts and best-effort ordinary generation.

This is acknowledgment accounting, not authoritative VRAM measurement. Existing
coarse estimates and no-evictable overcommit behavior are unchanged. Alias/canonical
identity coordination, production's LM Studio adapter versus other local providers,
the ensure/using gap, cross-process/external eviction and authoritative hardware
snapshots remain unsolved. No full image/LLM VRAM swap claim. Raw Ollama adapter is
not newly production-wired and obtains no new authority.

## RED/GREEN verification plan

Actual adapters: negative/malformed/mismatched acknowledgments, LM Studio gate
refusal, HTTP failure and semantic Ollama failure versus valid empty-prompt replies.
Actual manager: failed load no residency; refused/raised/cancelled unload retains
old accounting and does not load replacement; absent controller; nested/concurrent
unknown refs; acknowledged load while active; cancellation releases ref/lock.
Actual Agent synthesize continues generation after refusal, then releases unknown
protection. Existing default-off, LRU, generation and manager tests remain exercised.
Run focused pytest with repository guards, whole Ruff and Bandit baseline. No live
services, paid providers, dependency changes or full backend suite.

## Primary protocol evidence

Consulted 2026-09-15: https://docs.ollama.com/api/generate defines done as boolean
completion and keep_alive zero as immediate unload. Official maintained API examples
https://github.com/ollama/ollama/blob/main/docs/api.md#load-a-model show load with
empty response and done true (no reason); unload adds done_reason unload. These are
server acknowledgments, not proof of physical VRAM residency. LM Studio's actual
local adapter contract is agents/core/llm/lmstudio_control.py load_model/unload_model,
including canonical resolution, permission checks and structured _done results.

## Verification completed

The initial 23 actual adapter/manager regressions failed against the unchanged
implementation: /tmp/nerva-residency-red.log. After repair, 91 focused cases pass
(manager, new acknowledgment tests, LM Studio controller, Ollama controller):
/tmp/nerva-residency-final.log. Existing failed-unload test now asserts old state,
used bytes and no replacement, rather than merely asserting the attempted call.
Actual Agent synthesis proves refused management still produces its backend reply
and releases active protection without creating residency. Added tests exercise
concurrent unknown references becoming confirmed, cancellation, exact identities,
real LM Studio disabled/permission refusal and semantic malformed HTTP responses.

Command (repository pytest.ini retained):
`/tmp/nerva-python-runtime/bin/python3.12 /tmp/nerva-run-isolated.py "$PWD" /usr/bin/env TMPDIR=/private/tmp NERVA_PUBLIC_PROFILE=0 /Users/andrei649/Projects/nerva-hub/.venv/bin/python3.12 -m pytest tests/test_model_manager_ack.py tests/test_model_manager.py tests/test_lmstudio_control.py tests/test_ollama_control.py`

Whole Ruff (`-m ruff check agents scripts tests`) and Bandit 1.9.4 baseline
(`-m bandit -r agents scripts -q -b .bandit-baseline.json`) pass; logs
/tmp/nerva-residency-ruff.log and /tmp/nerva-residency-bandit.log. No live controller,
GPU, routing, protected policy, dependencies, global ledger or bundle changed.

## Independent review and integrated validation

Source 739a9915ae7ad584ba0f968722554570c576c722 cleared independent review with
91 guarded tests, plus root source review without findings. The same runtime source
was rebased onto final cloud-tool d530069b568ab3787a0b8592f096349372f383b7, yielding
source base 3b6571ca7c2b44dfc433bf5fb710b171fabd4b70. Assessment timestamp is UTC.

Full isolated backend: 11,624 collected; 11,598 passed, 25 skipped, one expected
failure, zero unexpected failures, 255.17 seconds. Actual logs/XML:
/tmp/nerva-residency-full.log and /tmp/nerva-residency-full.xml. Repository socket
and timeout guards remained active (including blocked Telegram connection attempts).
The explicit full-run PATH omitted Node, causing two JS snippet parse-check skips.
A supplemental run of tests/test_widget_and_skill_import_injection.py with Node
restored passes all 25 cases, including both skipped guards; logs/XML are
/tmp/nerva-residency-node-guards.log and /tmp/nerva-residency-node-guards.xml. These
supplemental passes do not change the recorded full-run pass/skip totals.

Full command used:
`/tmp/nerva-python-runtime/bin/python3.12 /tmp/nerva-run-isolated.py "$PWD" /usr/bin/env TMPDIR=/private/tmp NERVA_PUBLIC_PROFILE=0 PATH=/tmp/nerva-fish-runtime/fish/4.9.3/bin:/Users/andrei649/Projects/nerva-hub/.venv/bin:/usr/bin:/bin:/usr/sbin:/sbin /Users/andrei649/Projects/nerva-hub/.venv/bin/python3.12 -m pytest --junitxml=/tmp/nerva-residency-full.xml`

Final supplemental verification command (complete Node/fish PATH):
`/tmp/nerva-python-runtime/bin/python3.12 /tmp/nerva-run-isolated.py "$PWD" /usr/bin/env TMPDIR=/private/tmp NERVA_PUBLIC_PROFILE=0 PATH=/tmp/nerva-fish-runtime/fish/4.9.3/bin:/Users/andrei649/.local/bin:/usr/bin:/bin:/usr/sbin:/sbin /Users/andrei649/Projects/nerva-hub/.venv/bin/python3.12 -m pytest tests/test_widget_and_skill_import_injection.py --junitxml=/tmp/nerva-residency-node-guards.xml`

81 metadata checks pass (test_hermes_sprint_status, test_status_sync,
test_release_gate), /tmp/nerva-residency-metadata.log and .xml. Whole Ruff and
Bandit 1.9.4 baseline pass again after integration, logs
/tmp/nerva-residency-integrated-ruff.log and /tmp/nerva-residency-integrated-bandit.log.
status_sync --verify-test-count backend --test-result /tmp/nerva-residency-full.xml
confirms 11624. Generated status reuses frontend1326/mobile140 and routes501;
frontend/mobile suites were not rerun for this backend-only change. Hermes remains
121 equivalent/327 partial/94 missing/107 excluded/48 needing review. H515 stays
partial; only inspected new evidence was appended, with no blanket hash refresh.
