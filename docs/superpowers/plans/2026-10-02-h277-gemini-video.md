# H277 Native Gemini Video Implementation Plan

> **For agentic workers:** use superpowers:subagent-driven-development task-by-task. Parent owns integration and commits.

**Goal:** Send the approved video's actual bytes through a native Gemini adapter while preserving authority and existing-provider compatibility.
**Architecture:** Pure protocol codec, then narrow role/identity/runtime integration; existing consent storage, signed task and HTTPX transport remain authoritative.
**Tech Stack:** Python3.12, existing HTTPX and pytest; no dependency additions.
**Spec:** [Native Gemini design](../../hermes/h277-gemini-video-design-2026-10-02.md).

## Global Constraints

- Local only; no push/merge/deploy, live model calls or credential imports.
- Python: `/tmp/nerva-pr-python-20261001/bin/python`; retain repository pytest guards.
- At most two Sol High implementers. No shared writers or subdelegation.
- Existing providers retain exact no-chain HMAC/scope/result compatibility.
- One actual send per candidate; whole-chain authority and180/65/60/35-second budgets remain.
- Native serialized request <20,000,000bytes; supported MIME values match the spec.
- H277 remains partial; preserve all accepted follow-up work.

## Review Focus

- Mixed chain with over-limit native payload: no earlier compatible send before refusal (Task2).
- x-goog-api-key injected into compatible request, or Bearer injected into Gemini: refuse (Task2).
- Remote Gemini cannot borrow a primary/local or global Gemini key/grant (Task2).
- Thought-only or safety-blocked successful response must not disclose/fail over (Task1/2).
- MOV/AVI/MKV names must not silently become MP4; unsupported native MIME refuses at intake (Task1/2).

## Task1: Pure native codec and MIME declarations

Files: create `agents/core/llm/video_native.py`, `tests/test_h277_video_native.py` only.
Interfaces (no environment/store/client I/O):
- `GEMINI_VIDEO_BASE`, `GEMINI_VIDEO_MAX_REQUEST_BYTES=20_000_000`, `VIDEO_MIME` from spec.
- `VideoNativeRefused(ValueError)` with sanitized messages.
- `gemini_request_url(base_url: str, model: str) -> str`; empty base selects constant.
- `gemini_video_mime(mime: str) -> str`; accept only supported declared MIME, reject Matroska/unknown.
- `gemini_video_body(prompt: str, data_url: str) -> dict`; validate base64/MIME, produce exact native shape, bound compact UTF8 JSON size with ensure_ascii=False.
- `gemini_video_answer(payload: object) -> str`; implement spec's candidate/finish/safety/thought rules.

- [ ] Write red tests for canonical/default/custom URLs and unsafe path/model inputs; extension/MIME table; exact native bytes; invalid data URLs/base64 and actual request-size boundary; thought exclusion, safety/finish/structure/empty rejection.
- [ ] Run new test file and preserve expected missing-helper failure.
- [ ] Implement pure codec without importing video_policy/model_roles or introducing cycles.
- [ ] Run codec tests and scoped Ruff; freeze and report exact red/green evidence for parent review.

## Task2: Resolver, identity and signed native dispatch

Depends on Task1 interface freeze. Files: `agents/core/llm/model_roles.py`, `video_routes.py`, `video_policy.py`, `agents/core/video_analysis.py`; new `tests/test_h277_video_gemini.py`; narrowly update old provider-inventory assertions in video/role tests only when newly false.

- [ ] Add red resolver/signed-worker tests for Gemini primary/default/custom base, fallback in both orders, finite independent consent and no global/vision key inheritance.
- [ ] Add red actual-wire assertions for x-goog-api-key-only credentials, native inline_data content/MIME, fresh credentials/config/consent/cleanup changes, no authority bypass.
- [ ] Permit Gemini only on video role; choose video-only default base. Parser validates Gemini model/URL via Task1, keys stay fixed-slot. Keep existing primary branches byte-compatible.
- [ ] Build Gemini identity with native URL/raw scoped key and extra protocol/header binding fields; expose a per-identity request-header property while preserving existing authorization field and old tuple format. Physical validation checks both possible credential headers and actual Gemini request bytes <20,000,000, including a whitespace-inflation regression.
- [ ] Use pure native MIME at intake; validate all native payload sizes after materialization before any lane/client. Build fresh native body per attempt, parse native successful response with helper, retain failure categories/limits/cleanup. Add Gemini compact-notice legend without exceeding200characters.
- [ ] Correct general MIME table by importing Task1's declaration; add signed tests for MOV/AVI and native MKV refusal. Test mixed-chain over-limit denial before primary transport.
- [ ] Run new Gemini tests and all video/model-role/consent/signed-media regressions, scoped Ruff and diff check. Freeze for parent review; do not stage or commit.

## Task3: Integration, evidence and next action

Parent owns `.env.example`, `docs/FLAGS.md`, Hermes design/report/assessment, BACKLOG, mobile/HUD gap records when applicable, generated status and local handover.

- [ ] Review producer/consumer interfaces and security-sensitive diffs; obtain one bounded independent review, fix concrete findings red-first.
- [ ] Document key/base/MIME/size rules and unresolved larger-upload/live/provider gaps. Re-read affected ledger evidence only; no blanket hash restamps or parity promotion.
- [ ] Commit coherent code, update generated counts/reports, then freeze an exact commit and run full backend once. Fix actual failures and verify source stability. Frontend is unchanged: retain previous1838-test/typecheck/build proof and verify its source hashes.
- [ ] Scan changed source/docs/tests, save honest exact-source receipt, commit local handover and continue the full goal.
