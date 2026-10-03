# H277 smart terminal checkpoint verification

Generated UTC: 2026-10-03T07:45:35.208011+00:00.
Base / preceding HEAD: `326d21edb3795f892b2080f4f27c928abce36cf5`.
Branch: `codex/h277-provider-discovery-20261002`.
Delivery: local commit only; runtime flags remain unchanged.

**Execution Plan:**

Implement default-off strict guardian verdicts for one terminal task, bind the queue receipt to exact arguments and current policy, consume the real typed mediation handoff and satisfy only the ordinary terminal ASK in AUTO. Verify kernel refusals, revocation, owner override and manual Docker compatibility. Reproduce and fix the stale writer inventory, then rerun the complete backend suite. Two Sol/high agents performed owned implementation and bounded read-only review; no subdelegation.

**Files Modified:**

48 changed paths including this report; seven generated asset renames are listed by their new names.

| Path | Rationale |
|---|---|
| [.env.example](../../../.env.example) | Default-off owner smart policy and deny controls. |
| [BACKLOG.md](../../../BACKLOG.md) | Record this partial delivery and the native mobile gap. |
| [GO_LIVE_PLAN.md](../../../GO_LIVE_PLAN.md) | Dependent generated status/count report; no new completion credit. |
| [HERMES_STATUS.md](../../../HERMES_STATUS.md) | Dependent generated status/count report; no new completion credit. |
| [NERVA.md](../../../NERVA.md) | Dependent generated status/count report; no new completion credit. |
| [README.md](../../../README.md) | Dependent generated status/count report; no new completion credit. |
| [STATUS.md](../../../STATUS.md) | Dependent generated status/count report; no new completion credit. |
| [agents/core/autonomy/advisory_judgements.py](../../../agents/core/autonomy/advisory_judgements.py) | Default advisory compatibility plus post-storage hook. |
| [agents/core/autonomy/approval_judge.py](../../../agents/core/autonomy/approval_judge.py) | Named guardian transport and live binding checks. |
| [agents/core/autonomy/queue.py](../../../agents/core/autonomy/queue.py) | Atomic exact-task guardian verdicts and signed one-operation receipts. |
| [agents/core/autonomy/smart_approvals.py](../../../agents/core/autonomy/smart_approvals.py) | Strict verdict, trusted policy and bounded untrusted command projection. |
| [agents/core/autonomy/task_approval_judge.py](../../../agents/core/autonomy/task_approval_judge.py) | Queue review, receipt verification and worker promotion effects. |
| [agents/core/autonomy/worker.py](../../../agents/core/autonomy/worker.py) | Trusted receipt callback forwarding and machine approval verification. |
| [agents/core/autonomy_coordinator.py](../../../agents/core/autonomy_coordinator.py) | Typed production intake, exact actor/origin/request and durable authority. |
| [agents/core/environments/execution.py](../../../agents/core/environments/execution.py) | Kernel-aware terminal actuation and post-await current-request checks. |
| [agents/core/kernel/__init__.py](../../../agents/core/kernel/__init__.py) | Ordinary terminal ASK can be satisfied by trusted sealed proof only in AUTO. |
| [agents/core/kernel/binding.py](../../../agents/core/kernel/binding.py) | Optional trusted callback through the existing mediation bridge. |
| [agents/core/llm/vision_review.py](../../../agents/core/llm/vision_review.py) | Import-only lint correction; review bodies unchanged. |
| [agents/core/orchestrator_bindings.py](../../../agents/core/orchestrator_bindings.py) | Refresh 14 existing writer positions, preserving names and columns. |
| [agents/web/v2/assets/gap-TGrKP9cD.js](../../../agents/web/v2/assets/gap-TGrKP9cD.js) | Regenerated HUD bundle from verified React source. |
| [agents/web/v2/assets/index-B5j19wTW.js](../../../agents/web/v2/assets/index-B5j19wTW.js) | Regenerated HUD bundle from verified React source. |
| [agents/web/v2/assets/modes-BN2JG_jf.js](../../../agents/web/v2/assets/modes-BN2JG_jf.js) | Regenerated HUD bundle from verified React source. |
| [agents/web/v2/assets/modes2-Hg8e7MEl.js](../../../agents/web/v2/assets/modes2-Hg8e7MEl.js) | Regenerated HUD bundle from verified React source. |
| [agents/web/v2/assets/modes3-C_78SV1Q.js](../../../agents/web/v2/assets/modes3-C_78SV1Q.js) | Regenerated HUD bundle from verified React source. |
| [agents/web/v2/assets/modes4-DCal2S2C.js](../../../agents/web/v2/assets/modes4-DCal2S2C.js) | Regenerated HUD bundle from verified React source. |
| [agents/web/v2/assets/modes_world-FSOgGdv5.js](../../../agents/web/v2/assets/modes_world-FSOgGdv5.js) | Regenerated HUD bundle from verified React source. |
| [agents/web/v2/index.html](../../../agents/web/v2/index.html) | Regenerated HUD bundle from verified React source. |
| [docs/ARCHITECTURE.md](../../../docs/ARCHITECTURE.md) | Document separate advisory and sealed terminal authority. |
| [docs/HERMES_CAPABILITIES.md](../../../docs/HERMES_CAPABILITIES.md) | Dependent generated status/count report; no new completion credit. |
| [docs/design/HUD_V2_REMAINING.md](../../../docs/design/HUD_V2_REMAINING.md) | Record delivered guardian UI and remaining parity. |
| [docs/hermes/assessment.json](../../../docs/hermes/assessment.json) | Re-read current affected rows, preserve verdicts and inherited stale rows. |
| [docs/hermes/evidence/h277-local-vision-mutations-2026-10-02.py](../../../docs/hermes/evidence/h277-local-vision-mutations-2026-10-02.py) | Import-spacing lint only; historic mutation selectors unchanged. |
| [docs/hermes/evidence/h277-smart-terminal-mutations-2026-10-03.json](../../../docs/hermes/evidence/h277-smart-terminal-mutations-2026-10-03.json) | Exact-source isolated authority mutation harness and receipt. |
| [docs/hermes/evidence/h277-smart-terminal-mutations-2026-10-03.py](../../../docs/hermes/evidence/h277-smart-terminal-mutations-2026-10-03.py) | Exact-source isolated authority mutation harness and receipt. |
| [docs/hermes/evidence/h277-smart-terminal-verification-2026-10-03.md](../../../docs/hermes/evidence/h277-smart-terminal-verification-2026-10-03.md) | This source-bound verification report and complete changed-path list. |
| [docs/hermes/evidence/h277-vision-auto-mutations-2026-10-02.py](../../../docs/hermes/evidence/h277-vision-auto-mutations-2026-10-02.py) | Import-spacing lint only; historic mutation selectors unchanged. |
| [docs/hermes/h277-smart-terminal-plan-2026-10-03.md](../../../docs/hermes/h277-smart-terminal-plan-2026-10-03.md) | Design, corrections, boundaries, resources and next action. |
| [frontend/src/gap.tsx](../../../frontend/src/gap.tsx) | Guardian DENY/ESCALATE and pending labels with owner controls. |
| [frontend/src/test/decision-inbox-panel.test.tsx](../../../frontend/src/test/decision-inbox-panel.test.tsx) | Three new guardian rendering regressions. |
| [mobile/PARITY.md](../../../mobile/PARITY.md) | Record native guardian labels/configuration as an open gap. |
| [project-status.json](../../../project-status.json) | Dependent generated status/count report; no new completion credit. |
| [tests/test_h277_smart_approval_policy.py](../../../tests/test_h277_smart_approval_policy.py) | Behavior-level smart policy, CAS, receipt, actuation or real-kernel regression. |
| [tests/test_h277_smart_judge.py](../../../tests/test_h277_smart_judge.py) | Behavior-level smart policy, CAS, receipt, actuation or real-kernel regression. |
| [tests/test_h277_smart_kernel.py](../../../tests/test_h277_smart_kernel.py) | Behavior-level smart policy, CAS, receipt, actuation or real-kernel regression. |
| [tests/test_h277_smart_terminal_actuation.py](../../../tests/test_h277_smart_terminal_actuation.py) | Behavior-level smart policy, CAS, receipt, actuation or real-kernel regression. |
| [tests/test_h277_smart_terminal_integration.py](../../../tests/test_h277_smart_terminal_integration.py) | Behavior-level smart policy, CAS, receipt, actuation or real-kernel regression. |
| [tests/test_h277_smart_terminal_queue.py](../../../tests/test_h277_smart_terminal_queue.py) | Behavior-level smart policy, CAS, receipt, actuation or real-kernel regression. |
| [tests/test_h277_vision_main.py](../../../tests/test_h277_vision_main.py) | Import order only; test bodies unchanged. |

**Verification Results:**

- Final backend: `python -m pytest tests --junitxml=...`, exit 0; **21,509 passed, 34 skipped, 1 xfailed**, 67 warnings, 1,126.01 seconds. Collected count **21,544**.
- New smart tests: **137 passing**; broad authority/terminal regression: **725 passing**. Corrective inventory/vision regression: **148 passing**.
- Authority mutations: **11/11 assertion-killed**, zero invalid or surviving mutants; restored 137-case baseline passed and all 14 mutation source/test hashes still match. [Exact receipt](h277-smart-terminal-mutations-2026-10-03.json).
- Full frontend: **1,884 tests across 207 files**, exit 0; TypeScript and HUD production build pass. Existing large-chunk build warning remains.
- Legacy HUD coverage suite: **233 tests across 27 files**, **69.75% line coverage**, above its configured 60% threshold. This does not measure Python or React-v2 line coverage; no Python coverage threshold/instrumentation is configured in the current runtime.
- Repository-wide Ruff and whitespace checks pass. Graft wiring rebuilt/check passed: 47,798 nodes across 2,715 files; deep semantic layer not built.
- Source remained frozen throughout final backend execution: all 21 source/test hashes captured during the run match its completed source.
- Earlier full run: 21,508 passed, one failure in exact orchestrator writer positions, 34 skipped and one expected failure. Reproduced isolated before fixing all 14 positions (+89); this earlier run is not presented as green. A still earlier run was interrupted for the real-kernel correction and is not a complete-suite result.
- Actual kernel/production bridge, SQLite queue and task executor run in process. Guardian HTTP and final process sink are mocked; existing local/SSH transport regressions are included. No live model, mobile-device or new real-Docker acceptance claim.

**Remaining Risks:**

- H277/H485 remain partial. Broader shell/script pre-escalation, same-turn model feedback, session denial warning, observer hooks, native mobile and live provider acceptance remain open. A next-turn denial warning can use the authenticated server-minted chat session/principal; it does not establish Hermes same-turn parity.
- Legacy manually approved Docker still lacks the terminal.exec kernel hop added to the smart path. Owner-edited/reblocked tasks stay manual; unchanged-digest nonapproval is retained; shell detection is bounded rather than a full interpreter.
- Global Bandit 1.9.4 baseline scan has **three pre-existing findings** in unchanged nous_auth.py (B101 lines 452/584 and B105 line 506), zero scan errors and no finding on this increment’s changed authority files. The global SAST gate is red; no baseline was weakened.
- Static parity remains **182 equivalent / 264 partial / 63 missing / 188 needs_review** out of 697 (26.1%). This checkpoint receives no new equivalence credit. GitHub CI and deployment are unverified here.

Source hashes (SHA-256; verification excludes the self-referential report):

```json
{
  "agents/core/autonomy/advisory_judgements.py": "a5798d26fa0908e0f93b1a064cf327cdc2919f85fb85edda1bde9231064f11dd",
  "agents/core/autonomy/approval_judge.py": "cd0647a0d4a133c0ea8b7650dbd2fbb95dbd3d3ce454bc84f9e10712f60f7dcc",
  "agents/core/autonomy/queue.py": "0408913c9e22f0827629e60af342190bac3b58edbb9dfeb0d56d637d60a5052d",
  "agents/core/autonomy/smart_approvals.py": "988da9e441cf82e0ae9b3060bbe34e78137deb05748cd78d8851f032ffdb1008",
  "agents/core/autonomy/task_approval_judge.py": "4764fc4967bd7163f45ae47eb0ea77507b626188efe51350825bf29125af3106",
  "agents/core/autonomy/worker.py": "d78b2565904b9c8ffd46886746b9ae1647222fd771f0d9079bf0df16bc70b685",
  "agents/core/autonomy_coordinator.py": "6c2fa59028faf70a19b5f2d755fb35ab330be6479cc970ff5779e567abb732b1",
  "agents/core/environments/execution.py": "fc3c0f6a48fe01ff33484eddc49fd64ff37e9c56613006f8557300c719215204",
  "agents/core/kernel/__init__.py": "cb4d5fee72c3ccb7c105fa5f9a4c006617123e66779ab93666b5be894e4aab30",
  "agents/core/kernel/binding.py": "696792a324375816d52628ee7ac2a6486ac7f27ea606f4f9554ca9d62f17c782",
  "agents/core/llm/vision_review.py": "876094c36c1da103c20d3a21e3d13c9a2d479580de87f85440cc36ee483b1d44",
  "agents/core/orchestrator_bindings.py": "23101990a4f729cedd4de8607ef4574166aba00702270d7f03de4daf883d6343",
  "frontend/src/gap.tsx": "aa887c5ad295c2fa8cf12ad3ca827bf7ec8d6a7403bf2c26f87f905849451654",
  "frontend/src/test/decision-inbox-panel.test.tsx": "20716b5315ba8f361d7f891e4b59aba81368cdb5a217652681f363c861d54577",
  "tests/test_h277_smart_approval_policy.py": "1402497d600a5446e8c60d9e1be15846733cb68a630f6fbcfba0ff3c2e94be21",
  "tests/test_h277_smart_judge.py": "c40d8bd66770c09a5f98710ccb6dfa5160327d8aee27f3d170b20b73ce98e352",
  "tests/test_h277_smart_kernel.py": "0a443ff6eaba5e28995e11339aabb09dfd9360961d21f181a4e4dd5adedbc3ce",
  "tests/test_h277_smart_terminal_actuation.py": "89635fc743c2356c428d7ab360e981131a133716ea94c95267d12eea6732e1fa",
  "tests/test_h277_smart_terminal_integration.py": "96983f0e7c0b296125f53eae7272130d8d92b470b9e04220348ac8234adab5e4",
  "tests/test_h277_smart_terminal_queue.py": "85775e3c0f34eae4980b56726a87c3da7f0090c3e20aec0e98647877a340dff8",
  "tests/test_h277_vision_main.py": "d22f1c605ce44b16e7a1fadcbb202cdca9c9ed624e41f2c679eba4a881ebb58a"
}
```
