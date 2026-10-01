# ComfyUI authority recheck before publication

- Goal: close the dropped post-generation guard from the September 28 handover.
- Integration base: `c132949cd1a196d1a7a712b1fce043863a4be25f`.
- Implementation commit: `4dd279db33e2f1cd8dc151e2e5fbd415f56af1d9`.
- Generated: 2026-10-01.
- Changed source: `agents/core/media_backends/comfyui.py` and
  `agents/core/media_backends/registry.py`.

## Behavior

The ComfyUI provider previously discarded the runtime guard. An approval or kernel
decision revoked while the backend generated or downloaded an image could therefore
still publish a PNG and report success.

The provider now forwards the guard to the backend. After validated image bytes have
arrived, the backend rechecks its configuration fingerprint and the runtime authority.
The same check runs after temporary-file synchronization, immediately before the
existing atomic publication operation. A governance refusal becomes
`withheld_after_generation` with its original cause. A broken guard retains its
machinery failure reason. Neither case leaves a published PNG or temporary artifact.
Direct backend callers remain compatible through an optional keyword argument.

## Verification

Three regression cases failed before implementation: two post-download provider
guard cases and one final-publication case. After implementation, 366 focused tests
passed across the image backend, provider registry and runtime suites. Additional
signed-worker cases revoke the local-image gate at the real mocked `/view` response
under both off and enforce kernel modes. Scoped Ruff and whitespace checks passed.
An independent review inspected provider dispatch, runtime authority binding,
failure classification and atomic publication; it found no blocker.

Full repository verification is recorded in the pull request. Tests use synthetic
PNG data and mocked HTTP transport; no live ComfyUI or billed-provider call was made.

## Limits and continuation

H515 and H517 remain partial. Their existing VRAM orchestration, broader provider
integration and live-service acceptance gaps remain. The guard observes authority
after download and immediately before publication; it does not continuously cancel
generation or make external policy updates transactional with the filesystem link.
The historical worker comment describes the old review round; this note supersedes
its ComfyUI gap, without changing worker behavior.

Next action: continue HEQ-1 from the remaining capability contracts and unresolved
handover defects. Rollback: revert this PR's squash commit; doing so restores the
known publication-after-revocation defect.
