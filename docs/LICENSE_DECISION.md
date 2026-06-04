# License decision — Jarvis Hub

> Status: **✅ DECIDED 2026-06-04 — Apache-2.0**, to be applied **just before v1.0.0** (staying **MIT** until release). · prepared 2026-06-04
> Context: GTM research (`docs/research/2026-06-04-privacy-first-gtm.md`) + plan (`docs/GTM_PLAN.md`).
> Decide this **before** accepting outside contributions — relicensing is trivial now (solo author),
> hard once community PRs land under the current license.

## Decision (2026-06-04)

**Apache-2.0**, chosen adoption-first — the moat is brand + hosted convenience + community, not a
restrictive license. **Deferred until just before the v1.0.0 release** (stay on MIT for now so nothing
changes mid-development); tracked in the [v1.0 launch checklist](../GO_LIVE_PLAN.md#v10-launch-checklist).
When it's time, the change is small: swap `LICENSE` → Apache-2.0, add `TRADEMARKS.md` (protect the
"Jarvis Hub" name), add a CLA note in `CONTRIBUTING.md`, and flip the README license badge.

## What the choice has to satisfy
1. **Genuinely OSI open-source is non-negotiable.** The ICP (privacy-first individuals on HN / r/LocalLLaMA / r/selfhosted) over-indexes on open source and treats "source-available" relicenses as rug-pulls. Open-source = auditable is the *whole wedge*.
2. **Monetization is hosted convenience, not gated core.** Open-core: free self-host, paid **Hosted Pro** (managed sync/relay/backups). We are *not* gating core local features — so the license doesn't have to protect in-repo "pro" code.
3. **Solo dev, pre-traction.** Adoption matters more than defense — for now.

## Options

| Option | Stops a SaaS clone? | Adoption / trust | Notes |
|---|---|---|---|
| **MIT** (current) | ❌ none | ★★★ max, frictionless | Anyone (incl. a cloud provider) can host a closed competitor. |
| **Apache-2.0** | ❌ none | ★★★ + explicit patent grant | The "professional permissive" standard (Jan, LocalAI, Home Assistant). Trivial switch from MIT. |
| **AGPL-3.0 + CLA + commercial dual-license** | ✅ strong (network copyleft) | ★★ (AGPL spooks some enterprises) | **Khoj's exact model** for this niche; self-hosters are fine with it; the CLA lets you sell a commercial exception. |
| **Source-available (BSL / SSPL / FSL)** | ✅ strongest | ✗ **damages the wedge** | HN / r/selfhosted treat these as rug-pulls (HashiCorp / Redis / Elastic backlash). **Avoid.** |
| **Permissive + branding clause** (Open WebUI-style) | ◐ brand only | ★★ | Stops white-label clones at scale, but the added clause is itself debated as non-OSI. |

## Recommendation

**✅ CHOSEN — Apache-2.0 + a `TRADEMARKS.md` brand policy + a lightweight CLA.**
- Maximizes the adoption + trust the wedge depends on; the patent grant makes it the credible permissive default.
- The **moat is brand + hosted convenience + community + shipping speed**, not a restrictive license — consistent with the convenience-based pricing the research validated.
- The **trademark policy** stops clones passing off as "Jarvis Hub"; the **CLA** keeps the door open to dual-license later.

**Alternative — AGPL-3.0 + CLA + commercial dual-license** — choose this *if* protecting a future hosted tier from a cloud-provider clone matters more *now* than enterprise adoption. Proven by Khoj for local-first personal AI.

**The deciding question:** do you fear a cloud provider cloning your hosted tier (→ **AGPL + dual**) more than any friction to adoption / enterprise use (→ **Apache**)? For a pre-traction solo project chasing *individual* adoption, lean **Apache-2.0 + trademark + CLA**, and tighten later via the CLA if needed.

## The actual change is small once you pick
- **Keep MIT:** do nothing.
- **Apache-2.0:** swap `LICENSE`, add `TRADEMARKS.md` + a CLA note in `CONTRIBUTING.md`.
- **AGPL + dual:** swap `LICENSE` to AGPL-3.0, add a `COMMERCIAL-LICENSE.md` offer + CLA.

Tell me which and I'll prepare it in a follow-up PR.
