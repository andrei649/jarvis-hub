# Decision — multi-user readiness for 1.0 (H23.23)

> **Status: RATIFIED 2026-09-01 by owner — option (A).** Nerva 1.0 is single-user per install;
> per-user isolation stays a post-1.0 horizon that opens only when a design partner needs multiple
> distinct people on one shared install. This is the recorded default the H23.30 public-demo spec
> assumes — v1.0.0 itself is not tagged yet. The boundary notes "What (A) requires" asked for
> landed with the ratification (2026-09-01) in `SECURITY.md`, `docs/COMPATIBILITY.md`,
> `docs/THREAT_MODEL.md` and `docs/FAQ.md`. *(Original framing: recorded the decision the H23.23 row asked for —
> "accept single-user for 1.0 & document it, OR scope per-user isolation" — so it stopped
> blocking Lane A / A2; the owner made the final call.)*

## The question

The north-star metric is defined *"per active user"*, but the current build is **single-user by
construction**: one data root (`$JARVIS_HOME`), one settings DB, one memory subsystem, one auth
token pair (`X-User-Token` / `X-Admin-Token`) that gates by *presence*, not *identity*. There is
no per-user isolation of memory, sessions, canvas, or approvals.

Two ways to satisfy 1.0:
- **(A) Accept single-user for 1.0 and document the boundary.**
- **(B) Scope and build per-user isolation before 1.0.**

## Recommendation: (A) — ship 1.0 single-user, document it explicitly

**Rationale.**
- The product is a **personal** AI cabinet — one owner, their machine, their data. Single-user is
  the *intended* shape for the design-partner phase (Lane A/A7: recruit 1–3 partners, each on
  their **own** install). Each partner is already isolated by running a separate instance.
- Per-user isolation is a **large, security-sensitive** surface (per-user data roots, memory/
  session/canvas/approval partitioning, auth identity vs presence, quota-per-user). Building it
  pre-1.0 contradicts the year-one lesson — *don't add scope; the constraint is proof, not code*.
- The north-star "per active user" is measured **across installs** during the design-partner
  program, not across users on one host — so single-user does not block the metric.

**What (A) requires (small, doc-first):**
1. State the boundary in the trust docs: 1.0 is **single-user per install**; the token pair gates
   network exposure, not multi-tenant identity. (Add to `SECURITY.md` / `docs/PRIVACY.md`.)
2. Note it in `docs/COMPATIBILITY.md` supported-scope and the release notes.
3. Keep per-user isolation as a **post-1.0** roadmap item (below).

**When (B) becomes real (post-1.0 trigger):** a design partner needs multiple *distinct* people on
one shared install (household / small team). At that point scope: per-user data root + settings +
memory/session/canvas/approval partition + auth identity + per-user quotas + a migration from the
single-user layout. Tracked as a future horizon, not a 1.0 blocker.

## Consequence

- **A2 (72h soak) is unblocked:** soak the single-user install; record AUD-0/H23.23 against the
  documented single-user scope.
- No code change in this decision — it is a scope ratification + doc note. The doc notes land with
  this decision; the owner ratifies (or picks B) in `docs/OWNER_TASKS.md`.
