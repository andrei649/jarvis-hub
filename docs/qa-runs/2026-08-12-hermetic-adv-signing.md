# QA run - hermetic ADV skill-signing pass (chapter 15 section 15.3)

> **Scope:** the no-hardware skill-signing gate only: ADV-035 through ADV-037 and the
> SEC-B2 posture claim. This is not a full section 15.3 pass, does not clear ADV-038 through
> ADV-046, and does not clear the A1 / B0 owner-host gate. Agent: Codex, Max run
> `midnight-quill`. Sandbox: hermetic Windows checkout, no signing key, no owner data.

- **Build SHA:** `79982ba6` (branch `max/midnight-quill`)
- **Python:** 3.11.15 (environment fact only; this run makes no compatibility claim)
- **Probe:** `python scripts/qa_audit_probes.py signing --json` -> **CLOSED**
- **Focused regression:** `pytest tests/test_skill_signing.py tests/test_qa_audit_probes.py -q`
  -> **30 passed**

Verdict vocabulary follows chapter 15 section 15.0.2. The probe is only a lead, so every
closure below also has an independent throwaway-skill reproduction.

## ADV-035 - enforcement without a key

- **Verdict:** **FIXED-SINCE**. With `JARVIS_REQUIRE_SIGNED_SKILLS=1` and no
  `JARVIS_SKILL_SIGNING_KEY`, `require_signed()` raised `SkillSigningMisconfigured`.
- **Probe:** `enforcement_without_a_key_fails_closed: true`; verdict **CLOSED**.
- **CROSS:** the independent reproduction called the production function directly and recorded
  `enforced_without_key: refused`. The posture view remained readable and honest:
  `effective: false`, `integrity_only: true`, `misconfigured: true`.

## ADV-036 - attacker-computable digest is not authorship

- **Verdict:** **FIXED-SINCE for the signing claim**. A throwaway package could still compute its
  own unkeyed digest, but verification labelled it `integrity-only`, never `signed`.
- **CROSS:** after an ephemeral key was configured, that same attacker-generated artifact failed
  with `algo-mismatch`; re-signing with the key produced `hmac-sha256` and verified as `signed`.
- **Meaning:** the unkeyed digest remains a useful accidental-corruption check in advisory mode,
  but the enforcement path no longer accepts it as proof of origin.

## ADV-037 - keyed enforcement blocks unsigned code

- **Verdict:** **CONFIRMED**. With enforcement and an ephemeral key configured, an unsigned
  throwaway skill was registered as visible but `sandboxed: true`, with `module_loaded: false`.
- **CROSS:** the skill's module body raised if imported; discovery completed without executing it.
  The focused regression suite independently pins the same fail-closed path.

## Residual boundary

The broader section is not closed. At the shipped advisory default, an unsigned throwaway skill
still reproduced `module_loaded: true` and `sandboxed: false`. That is ADV-038's import-at-discovery
primitive, not the SEC-B2 unkeyed-signature defect. This run makes no claim about installer route
reachability, uninstall/rollback, signed-file coverage, or live listing labels (ADV-039 through
ADV-046). The next security slice should trace and close the imported/user-skill execution boundary
without breaking bundled skills.

## Summary

| Case | Chapter's broken signature | Current build |
|------|----------------------------|---------------|
| ADV-035 | enforcement proceeds with no key | **FIXED-SINCE** - startup/load refuses |
| ADV-036 | forged unkeyed artifact reads as signed | **FIXED-SINCE** - `integrity-only`; keyed host rejects it |
| ADV-037 | strict mode still executes unsigned code | **CONFIRMED closed** - visible, sandboxed, not imported |
| ADV-038 | advisory default imports unsigned module | **OPEN residual** - reproduced, outside SEC-B2 |
