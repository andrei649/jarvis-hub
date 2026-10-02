# H277 local auxiliary temperature recovery

Base: `cd2aa666ed0a690e9bf9138747b95c15ffe9ee37`; branch
`codex/h277-auxiliary-recovery-20261002`. Pinned Hermes:
`59b2aeef6c7a3ecbb2625a54c66111a56eb64e3e`. Generated 2026-10-02.

Five real nonstreaming auxiliary producers (title, recall rewrite, review,
acquisition capability and acquisition draft) can recover a structured local
LM Studio HTTP400 rejection of temperature. The initial requested temperature
is unchanged; the single repair omits that field and deliberately uses the
provider default. Model, messages, token caps and Qwen /no_think stay fixed.
The existing model-unloaded retry composes in either order, at most three sends.
No other parameter, credential, provider or global model selection is changed.

The scope binds the exact backend object and model and closes inherited references.
Every physical send remains inside H513 authorization, including revocation that
the backend catches and converts to a degraded reply. Ordinary chat, tool turns
(including an ambient auxiliary scope), streamed compression and other adapters
do not gain this temperature recovery. Error classification uses bounded structured
HTTP400 data, refuses a conflicting parameter and does not inspect arbitrary
exception strings. The new detector adds no body logging; existing bounded final
backend diagnostics remain unchanged.

Verification before source freeze: five actual-producer tests failed without the
implementation, then passed. Final focused union: **612 passed**, zero failures,
errors or skips, including32 new cases. JUnit:
`/tmp/nerva-h277-parameter-green-union-20261002.xml`; red JUnit:
`/tmp/nerva-h277-parameter-red-20261002.xml`. Scoped Ruff and diff checks passed.
Independent bounded source review found no blocker; reviewer did not rerun tests.
Full-backend integration is recorded separately after a clean commit freeze.

No live model/provider call or coverage-percentage measurement. H277 remains
partial: SDK credentials, other parameter/provider recovery, route capability
cache, discovery, empty-output and progress recovery, additional consumers and
broader video/native-client work remain. This batch stays local; no publication,
merge, deployment or personal-profile import. Rollback this branch's coherent
feature changes; preserve the base and historical evidence.
