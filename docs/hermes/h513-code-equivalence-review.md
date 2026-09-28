# H513 frozen-contract review

Generated 2026-09-27. Base/head bd2bb70ead1b493043a335e77713fc42c47d4013
plus local sprint changes. Decision: accepted as code-equivalent to the frozen H513 contract.
Goal: review the exact existing inventory contract without adding requirements or
removing accepted product scope. The final camera milestone passed 19,194 backend tests with 35 skips and
1,822 frontend tests, with typecheck/build/scoped security scans green. Next action:
continue the remaining Hermes queue; preserve the independent product gaps below.

## Contract and implementation

The immutable inventory row H513 names three policy behaviors: restrict tools to
their intended surfaces, persist an operator acknowledgment for unattended use of
training-permitted provider tiers while retaining the warning, and control runtime
dependency installation. Its original Nerva decision explicitly accepts existing
surface/kernel controls and hash-pinned dependencies with no runtime provider
installation as the safer equivalent; the missing behavior is provider data policy,
durable acknowledgment and security-posture presentation. The inventory row and
all 697 identities remain unchanged.

| Frozen requirement | Reviewed implementation and evidence |
| --- | --- |
| Surface restrictions | `agents/core/tool_profiles.py` resolves the offered set from agent, surface and principal, narrows per-agent patterns and fails closed; the tool runtime refuses calls outside the resolved set. Existing snapshot/runtime tests remain in the full suite. |
| Provider data-handling metadata | Provider profiles and `agents/core/llm/data_handling.py` resolve actual backend/model/account policy, including substitutions and off-loopback local profiles. Unknown remains conservative; inspecting metadata does not make a model request. |
| Durable unattended acknowledgment | The admin-only route writes configuration-bound HMAC scopes after audit, re-resolves after blocking audit, validates the finite maps and fails closed on unavailable/corrupt state. Generic settings/import/reset cannot create grants. |
| Warning survives acknowledgment | Actual routed and independently guarded role dispatch logs/records the warning; responsive Security Posture retains policy warning and independent allow/revoke controls. No grant suppresses that warning. |
| Fresh runtime enforcement | Routed/tool-loop/cache/auxiliary clients and implemented native judge/vision/camera paths recheck at physical dispatch and retries. Role scopes are independent; camera additionally checks the original household privacy lease. |
| No surprise dependency installation | Existing pinned dependency/lockfile workflow remains unchanged; this slice adds no runtime installer, dependency or service. |

The routed, judge, interactive vision, Telegram and camera snapshots record the
incremental implementations. The camera milestone runs the complete backend and
frontend suites after focused regressions and independent review. Source hashes
are immutable snapshots, not later refreshed claims about an old run.

## Separate work remains in the project

These items are not declared delivered and are not removed from the overall Nerva
objective. They do not change the frozen H513 server policy acceptance contract:

- Remote embedding support/consent is outside the approved local-only embedding
  adapter. Unsupported destinations perform no semantic-model I/O and retain the
  explicit hash fallback. Durable stored-vector provenance/re-embedding is a
  separate data-lifecycle migration, not repaired by the scoped request/cache work.
- The presence explanation seam and standalone native screen-locator builder have
  no verified production caller. Their existence is not credited as live features.
- Native mobile consent/warning controls remain a client integration gap recorded
  in `mobile/PARITY.md`; responsive Trust is not proof of native-device parity.
- Camera provisioning is still incomplete: the standard settings API cannot create
  the undeclared camera keys. H31 owner setup and real configured-camera acceptance
  remain open; a guarded inference path is not a complete camera product.
- Provider/account terms and live configured-provider behavior are not certified
  by offline tests. The original build queue allows unknown policy when terms are
  uncertain, so uncertainty is represented in the product and requires explicit
  owner acknowledgment for unattended use. No new vendor guarantee is asserted.

Code equivalence is distinct from live acceptance and from completing the entire
697-capability project. This review grants no credit to another inventory row.

Final milestone evidence: [camera integration](evidence/h513-camera-integration-2026-09-27.json).
