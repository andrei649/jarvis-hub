# Review Queue — manual-testing + product-review checklist

> The running log of everything shipped during the autonomous run that needs your eyes.
> Walk this top-to-bottom during the full manual-test / product-review pass. The codebase
> is green and merged at every step; this is about the things automated checks **can't**
> prove.

## How each item is verified

- **Automated, every PR (gates the merge):** `pytest` (full suite), `ruff`, the
  route/action/capability **auth-matrices**, OpenAPI/route parity, SAST (bandit/semgrep) +
  secret-scan (gitleaks), hash-pinned deps.
- **Scratch simulation (where possible):** I also boot the app and hit real endpoints — and
  load HUD pages headless in a real browser (Chromium/Playwright) — in a throwaway scratch
  dir (never committed) to catch obvious runtime bugs. Noted per item.
- **⚠️ NEEDS YOU:** real LLM / real channel / live HUD pixels / GPU / owner secrets — the
  things only a human + real hardware can confirm.

## Owner-only — I cannot do these (also in `docs/OWNER_TASKS.md`)

- GPU runs — 0.18 Howard fine-tune / speculative decoding.
- Publishing — PyPI / Docker / GPG-signing (your secrets).
- Recruiting design partners; GitHub settings (branch protection, CodeQL enablement).

## Conventions

- **Risky/new behavior ships behind a default-off flag** (e.g. `JARVIS_ACTION_KERNEL`) so it
  changes nothing at runtime until you enable it during testing.

---

## Items (newest first)

### K4 — kill-switch + credential-quarantine syscalls
- **What:** `kernel/syscalls.py` — `halt()` / `release()` promote the existing `KillSwitch`
  to a kernel call, and `inject_guarded()` makes secret injection **quarantine-aware** (while
  halted, injection is forced blocked regardless of approval). Folds H23.3. Composes existing
  primitives; no behavior change until a caller uses it.
- **Verified (automated):** unit tests — halt→quarantine→release, injection blocked while
  halted even when approved, `kernel.authorize` denies new grants when halted, audit emitted.
- **⚠️ Needs you:** the **one-tap kill-switch HUD control** (frontend) is not built yet — this
  is the backend syscall only. (HUD comes in the productionization-tail phase.)
