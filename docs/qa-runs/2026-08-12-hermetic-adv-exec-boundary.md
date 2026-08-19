# ADV-038 external skill execution-boundary evidence

**Date:** 2026-08-12  
**Environment:** Windows, repository virtual environment  
**Scope:** Hermetic, no hardware or live service required

## Verdict

**FIXED-SINCE.** At the shipped default, unsigned external skill modules remain
discoverable but do not execute in-process. External provenance covers the owner skill
root, marketplace-installed packages, and imported sidecars. In-process loading remains
available to keyed HMAC-signed external skills and explicitly owner-approved generated
skills. Repository-bundled skill behavior is unchanged.

Marketplace extraction writes `EXTERNAL_SOURCE` after signature verification and removes
any package-supplied `OWNER_APPROVED_IN_PROCESS` marker. The generated-skill approval path
is the only path in this slice that writes that owner grant. The grant is accepted only
while the approved content still matches its integrity digest; any later source change
returns the skill to quarantine.

## Reproduction

The pre-fix regression tests failed because unsigned owner/imported module top-level code
reached `exec_module`, marketplace installs had no external marker, and owner approval had
no durable grant marker. After the fix:

```text
pytest targeted ADV-038 cases
5 passed

pytest skill signing, generated-skill quarantine/contract, user-home packaging,
marketplace/governance, and Hermes import suites
115 passed
```

One unrelated Starlette/httpx deprecation warning was emitted. No test was skipped.

## Boundary

This closes the automatic in-process import primitive. It does not claim that arbitrary
external Python is executed in a separate operating-system sandbox; blocked skills are
reported as sandboxed and retain no loaded module until a keyed signature or explicit
owner approval authorizes in-process loading.
