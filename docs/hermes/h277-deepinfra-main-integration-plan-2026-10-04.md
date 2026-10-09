# H277 DeepInfra selected-main root integration

Generated2026-10-04. Goal remains local functional parity for all697 pinned
Hermes capabilities. Root checkout currently frozen at `e84f0922`; no real
source/test/evidence edit is permitted until the full22465 runner terminates
and all3,020 frozen paths are rehashed. Root alone integrates real files.

Reviewed prototype patch SHA-256:
`61025d505ced5d9a1cd9d621332e199f9c5edbddd9f357dafa7913559b59916b`.
Pinned provider declares DeepInfra own key and `/v1/openai` main chat. Preserve
existing explicit DeepInfra vision-role custom URLs and generic custom providers.
This unit supplies selected-main text/tool/native SSE and selected-main images;
it does not add default-model discovery, a catalog picker or live acceptance.

Source paths: new `agents/core/llm/deepinfra.py`, `hybrid_router.py`,
`vision_main.py`, `providers/__init__.py`, `agents/core/settings_db.py`;
tests: new `tests/test_h277_deepinfra_main.py`, narrow existing profile assertion
in `tests/test_h277_deepinfra_vision_roles.py`. No auxiliary/base/autonomy edits.

After the current full terminal receipt is locally committed:
1. Revalidate owned baseline hashes and whole `git apply --check` on current HEAD.
2. Save this pre-code plan in docs/hermes, apply only the new50-case test module,
   run root RED and inspect actual behavior failures separately from setup errors.
3. Apply five source files and the one necessary profile expectation. Run new
   cases, affected native images/router/provider policy/reasoning/usage/probe
   suites. Check exact own-key/body/URL guard and late-hook placement before final
   H513 egress, unknown-policy acknowledgement, local-only routes, no Gemini
   fallback for invalid explicit DeepInfra, stream timing/cancel/cleanup/finish.
4. Canonical base validation permits exact HTTPS host/path with optional trailing
   slash or :443 and canonicalizes; alternate paths/encoded/dot/query/fragment
   ambiguity refuse. The already reviewed generic custom-provider lane remains.
5. Ruff, baseline-aware Bandit, exact staged-file secret scan; source impact
   review updates only current inspected rows and localized docs/counts. Separate
   source commit/rollback unit. No remote publication or paid/live calls.

Rollback: reverse these seven source/test paths and accompanying scoped records,
then regenerate documented counts/status. Broader H277 remains partial. The
previous full22465 receipt will cover its unchanged source milestone only;
later DeepInfra source requires separate focused/integrated/full evidence.

Integration begins after verified full terminal and local records commit `9bfa085c`; the seven owned baseline paths still match the captured prototype source. Next action: root test-only RED, then bounded source integration.
