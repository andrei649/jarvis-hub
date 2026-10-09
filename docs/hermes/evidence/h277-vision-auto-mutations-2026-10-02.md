# H277 automatic image selection mutation receipt

Frozen source: `3ea6340551ddcb8901c434e192e571d2fd79f80b`.
Runner: `h277-vision-auto-mutations-2026-10-02.py`, using the existing
exact-commit archive harness. Python:
`/tmp/nerva-pr-python-20261001/bin/python` (3.12).
All provider transport in the selected tests was synthetic or mocked.

The first campaign on `aa3e20676bfa4ecc99855c5953896a74b621e8cf`
had 7 killed and 1 surviving mutant. The status test used a preselected Nous
model, so removing metadata preparation did not change its result. Added
`test_auto_status_prepares_deepinfra_catalog_before_review` to cover an
unselected model: GET prepares a scoped DeepInfra catalog and POST uses the
prepared model without a second catalog request.

The frozen rerun passed all **17 baseline tests** before and after mutations.
All **8/8 mutants were killed by test assertion failures**; there were zero
survivors and zero invalid cases. The probes covered role-key scope, explicit
endpoint precedence, selected-main precedence, role-model precedence, malformed
OpenRouter policy refusal, Nous-before-DeepInfra order, priority recheck after
an awaited preparation, and status catalog preparation.

The archive's **4,381 tracked regular files** matched their frozen hashes at
the end; no source file remained mutated. Source-scope SHA-256 values:

- `agents/core/llm/vision_auto.py`:
  `688600702b800343d703f53829a664f467584ab30e574599beb2c5de8a1c2970`
- `agents/core/routers/composer_vision.py`:
  `88fd263998952161ea79bf0bc964b4b72a683028aa4679dd5c8fddff98f49594`

The detailed JUnit, diffs, source manifest and logs are in the local
`/tmp/nerva-vision-auto-mutations-20261002-3ea6340551dd` directory. This
campaign establishes the selected guards' test sensitivity; it does not
establish live provider acceptance or complete Hermes H277 parity. The main
conversation's selected route is still not passed into the standalone image
composer, and the Hermes register remains 175/697 equivalent.
