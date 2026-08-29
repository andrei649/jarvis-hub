# GAP-9 — Honesty-debt ledger (verified against `main` @ 69c7ab2c)

> Status: **research note** · dates 2026-08-09 · branch `nerva2/gap9-honesty-debt`
> Purpose: for each claim in `BACKLOG.md:577–583` (GAP-9), confirm or refute it against the
> actual code/docs, cite exact `file:line` evidence, grade severity, and propose the honest
> correction. **Read-only pass**: no files were edited except this one.

## Method

Every trace below was produced with read-only searches (`rg`/`Select-String`/`Get-ChildItem`)
and file reads on the worktree at `origin/main` @ `69c7ab2c`. Where a claim names an
*endpoint* or *package* that appears sanitized in `BACKLOG.md` (`/api/house/n`), the real
identifier was recovered from the code and is used here. All quoted text is verbatim.

## Summary

| # | Claim (BACKLOG.md) | Verdict | Severity | Honest correction |
|---|---|---|---|---|
| 1 | `/api/house/state.presence` structurally `[]` in every prod config | ✅ **CONFIRMED** | structural | Wire `PresenceInference` into a prod ingestion path, or stop advertising the field |
| 2 | ONVIF discovery needs undeclared `wsdiscovery` package | ✅ **CONFIRMED** | dependency | Declare `wsdiscovery` in a requirements file (or document the manual install) |
| 3 | Camera VLM leg needs a self-hosted VLM server | ✅ **CONFIRMED** | dependency | Document `JARVIS_VLM_URL`/`camera.vlm_endpoint` as an owner-hosted server (vLLM/llama.cpp) the repo does not ship |
| 4 | `environments/` is a policy plane that never executes; no SSH transport | ✅ **CONFIRMED** (with nuance) | structural | Note the policy/target machinery is unwired (helpers do execute); SSH is profile-only, no transport |
| 5 | Reality harness persists nothing (in-process registry, no artifact upload) | ✅ **CONFIRMED** | structural | State the in-process/ephemeral nature in the docs that present the V2 registry as verification |
| 6 | README voice stack lists engines no install path ships | ✅ **CONFIRMED** | over-promise | Rewrite `README.md:86` / `docs/FEATURES.md:67–68` to mark engines as manual/optional |

---

## Claim 1 — `/api/house/state.presence` is structurally always `[]`

**Verdict: CONFIRMED.**

**The route.** `GET /api/house/state` lives in the per-domain house router:
`agents/core/routers/house.py:316` `@router.get("/api/house/state", dependencies=[Depends(user_guard)])`.
The response's `presence` key is filled from the private store:

- `agents/core/routers/house.py:355` — `presence = _presence_view(runtime.private_store)`
- `agents/core/routers/house.py:333` — degraded path returns `"presence": []` verbatim
- `agents/core/routers/house.py:358` — private-store read failure also yields `presence = []`

`_presence_view` reads facts and keeps only the predicates
`presence_status`, `present_in`, `privacy_context`
(`agents/core/routers/house.py:214`); with no store it short-circuits to `[]`
(`agents/core/routers/house.py:240–242`). The store is `None` when the house brain is
disabled (`agents/core/routers/house.py:142` `private_store=None`), so even a disabled
config returns `[]`.

**The only writers.** The two predicates that produce a visible occupant
(`present_in`, `presence_status`) are written by exactly two store methods:

- `agents/core/house/private_store.py:435–443` — `record_presence(...) → predicate="present_in"`
- `agents/core/house/private_store.py:445–455` — `record_presence_state(...) → predicate="presence_status"`

**No production caller.** Those two store methods are invoked only from
`PresenceInference._persist` (`agents/core/house/presence.py:368` and `:388`), which is
called only from `PresenceInference.infer` (`presence.py:457`, defined at `presence.py:440`).
A repo-wide search for `PresenceInference` (`agents/core/house/presence.py:168`) shows the
class is instantiated in exactly two places outside `house/` itself:

- the reality-harness probe `_probe_graph_presence_privacy_purge`
  (`agents/core/observability/house_reality.py:514` `inference = PresenceInference(...)`,
  `:519` `inference.infer(...)`) — a self-check probe, not a production path;
- tests (`tests/test_h30_presence.py`).

The route tests feed facts through a `_PrivateStore` test double
(`tests/test_h30_house_routes.py:220–230`) and assert a **non-empty** presence projection
(`tests/test_h30_house_routes.py:236–252`), proving the view code works — but only when
facts already exist. In production no caller writes those facts, so the degraded-adapter
path (`"presence": []`, `tests/test_h30_house_routes.py:279`) is what actually serves.

**Contrast (not the same subsystem).** The *owner desk-presence* store
(`GET/POST /api/presence/owner`, `agents/core/routers/presence.py:35–59`; state in
`agents/core/autonomy/presence.py`) is deliberately separate — its docstring says so
(`agents/core/autonomy/presence.py:3–6`) — and it does have a production caller (the host
daemon). It does **not** feed `/api/house/state.presence`.

**Where the over-promise lives.** The field is a contract with no delivery path. The
nearest user-facing statements are roadmap, not delivery claims:
`NERVA_VISION.md:166` (ORIZONT 30 "House brain — Home Assistant graph, presence, governed
actuation") and `NERVA_VISION.md:419` (P2 "presence-aware delivery on ≥2 output surfaces"),
so there is no *false* user-facing sentence to correct — the endpoint schema itself is the
over-promise.

**Proposed correction (endpoint/doc contract, not this PR):**
- Either wire `PresenceInference` to a real ingestion source (e.g. HA `collect_events`
  events → `PresenceEvidence` → `infer`) so `presence` can be non-empty;
- or drop `"presence"` from the `/api/house/state` schema (both degraded and live shapes)
  until H30 ingestion exists, and replace the H30 route test's non-empty presence case
  (`tests/test_h30_house_routes.py:222–236`) with a `"reason": "presence_unwired"` contract.

---

## Claim 2 — ONVIF discovery needs the undeclared `wsdiscovery` package

**Verdict: CONFIRMED.**

**The import.** `agents/core/cameras/onvif.py:331`:

```python
from wsdiscovery.discovery import ThreadedWSDiscovery
```

This is the default discoverer loaded by `OnvifDiscoveryService`
(`onvif.py:235` `discoverer = self._discoverer or self._load_default_discoverer()`),
guarded by `except ImportError: return None` (`onvif.py:332–333`). When the package is
missing, discovery returns `status="unavailable", reason="onvif_dependency_missing"`
(`onvif.py:236–241`) — graceful, but the feature cannot work.

**The package is undeclared.** `rg "wsdiscovery"` matches nothing in
`requirements.txt`, `requirements-beta.txt`, `requirements-dev.txt`, or `pyproject.toml`
(exit 1). The install scripts install only `-r requirements-beta.txt`
(`INSTALL.bat:138`, `install.ps1:36`, `install.sh:25`), so a clean install never provides
`wsdiscovery`; the ONVIF discover route therefore always answers
`discovery_unavailable` on a stock install
(`agents/core/routers/cameras.py:177–185`).

**Where the over-promise lives.**
- `docs/design/HUD_V2_REMAINING.md:187` — "Admin-authenticated ONVIF discovery is
  onboarding-only" — presents discovery as a shipped HUD surface, but the discovery
  backend ships with zero install path for `wsdiscovery`.
- The 2026-07-25 gap analysis already flags the dependency
  (`docs/research/2026-07-25-nerva-vs-hermes-honest-gap-analysis.md`, Cameras row).

**Proposed correction for `docs/design/HUD_V2_REMAINING.md:187`:**
> "Admin-authenticated ONVIF discovery is onboarding-only; the discovery backend needs the
> **manually installed** `wsdiscovery` package — on a stock install the discover route
> returns `discovery_unavailable`."

---

## Claim 3 — the camera VLM leg needs a self-hosted VLM server

**Verdict: CONFIRMED.**

**Wiring.** The camera description leg is `LocalCameraVLM`
(`agents/core/cameras/vlm.py:83`). It is built in the camera runtime only when
`camera.vlm_enabled` is true (default **false**): `agents/core/cameras/runtime.py:367–370`
(`enabled=_boolean(_setting(orch, "camera.vlm_enabled", False))`). When enabled, the backend
is `VLMBackend(base_url=vlm_config.endpoint)` with default endpoint
`http://127.0.0.1:8000/v1` (`runtime.py:364–365`, `:373`). Otherwise a disabled stub is
used (`runtime.py:376` `LocalCameraVLM(vlm_config, generate=_disabled_generate)`).

**The server is external.** `VLMBackend`
(`agents/core/llm/vlm.py:95`) is an OpenAI-vision-compatible *client*: it POSTs
`/chat/completions` to `DEFAULT_VLM_BASE = "http://localhost:8000/v1"`
(`vlm.py:28`, `:123`). Nothing in the repo serves that endpoint. The module docstring says
so explicitly (`vlm.py:10–12`):

> "The model weights + GGUF build + 24GB GPU are the **host deployment seam**: point
> `JARVIS_VLM_URL` at a local vision server (vLLM / llama.cpp) and this adapter drives it."

The generic VLM route (`/api/vlm/describe`) makes the same requirement explicit
(`agents/core/routers/multimodal.py:48–54` — "Requires JARVIS_VLM_URL to point at a local
OpenAI-vision server").

**Where the over-promise lives.** The vision claims in
`NERVA_VISION.md:129–130` ("VLM eyes (`llm/vlm.py`, `/api/vlm/describe`)") are true as
*code-exists* statements but do not say the server is owner-hosted and not shipped;
`NERVA_VISION.md:391` (O31 "greenfield; `llm/vlm.py` for description") is roadmap and fine.
The code itself is honest (default-off, graceful `_disabled_generate`, 503 when
unconfigured).

**Proposed correction for `NERVA_VISION.md:129–130`** (append the seam):
> "…VLM eyes (`llm/vlm.py`, `/api/vlm/describe`) — **client only; requires an
> owner-hosted OpenAI-vision server (vLLM/llama.cpp) via `JARVIS_VLM_URL`**, screen
> grounding (`screen_grounding.py`), opt-in passive capture…"

---

## Claim 4 — `environments/` is a policy plane that never executes; no SSH transport exists

**Verdict: CONFIRMED, with one nuance.**

**The policy plane.** `agents/core/environments/targets.py:1–5` declares itself:

> "This module is a policy plane only. It never launches a subprocess, container, or SSH
> connection and deliberately accepts no command or payload content."

`default_targets()` (`targets.py:342–373`) and `backend_profiles()`
(`agents/core/environments/__init__.py:103–130`) are imported **only** inside the package
itself — no production module imports `TargetRegistry`, `default_targets`,
`TerminalTarget`, `TargetAuditChain`, or `backend_profiles`. The target-authorization
machinery (`TargetRegistry.authorize`, `targets.py:252–325`) is therefore never consulted
by any runtime path: it is dead policy that never executes.

**Nuance (the package is not entirely inert).** Some `environments/` helpers *do* execute
via the sandbox path: `scrub_child_env`/`prepare_python_child_env`
(`agents/core/sandbox.py`), `read_capped_stream`/`truncate_text`
(`agents/core/sandbox.py` + `agents/core/acquisition/sandbox_profile.py`), and
`file_rpc.FileRPCStore` (`agents/core/tool_rpc_runtime.py`). The honest statement is:
**the policy/target layer never executes; the env-scrubbing/output-capping helpers do.**

**No SSH transport.** Repo-wide `rg` for `paramiko|asyncssh|fabric` matches nothing in code
(only the 2026-07-25 gap analysis mentions them as *absent*). The only `ssh` strings in
code are descriptors, not a transport:
- `agents/core/environments/__init__.py:124–129` — `EnvironmentProfile(name="ssh",
  remote=True, supports_file_rpc=True)` (a capability *description*);
- `agents/core/environments/targets.py:355–362` — target `pi-house`, `backend="ssh"`,
  `enabled=False`;
- `agents/core/security_skills/pack.py:94` — `"ssh"` as a threat-intel keyword in
  ATT&CK metadata, unrelated to execution.

**Where the over-promise lives.**
- `NERVA_VISION.md:87` — "Execution topology — local, Docker, SSH, edge and optional cloud
  targets" (Atlas vision) lists SSH as a topology; the honest baseline later corrects it:
  `NERVA_VISION.md:104` — "execution environments (local/docker) merged (**no SSH transport
  exists**)". The vision section and baseline contradict; the baseline is right.
- `NERVA_VISION.md:371` — success metric S3: "local/docker/ssh targets with per-target
  policy **and** audit chain" (roadmap; fine as a target, not a delivery claim).

**Proposed correction for `NERVA_VISION.md:87`:** keep the aspirational topology but tag it:
> "Execution topology — local, Docker, SSH*, edge and optional cloud targets
> (*profile-only today; no SSH transport exists in-repo — see §3 honest baseline)"

---

## Claim 5 — the reality harness persists nothing (in-process registry, no artifact upload)

**Verdict: CONFIRMED — and the code is already self-honest about it.**

**In-process registry.** Harness verdicts are recorded into a module-level dict:
`agents/core/observability/capability_registry.py:55`
(`_VERIFICATIONS: dict[str, dict] = {}`), written by `record_verification`
(`:58–64`) and read back in `_apply_verification` (`:107–115`). The module states the
lifetime explicitly (`capability_registry.py:21–24`):

> "Records start at WIRED/SEAM on every boot. … Durable cross-process readiness remains
> V3's committed snapshot."

The harness itself says the same (`agents/core/observability/reality_harness.py:19–21`):

> "promotion here is **in-process** (the registry the live app/board reads is seeded fresh
> each boot). Persisting harness verdicts into a durable, committed readiness snapshot the
> deployed board reads is **V3** … — not this slice."

The promotion path is `_promote` → `record_verification`
(`reality_harness.py:126–133`), best-effort and in-memory.

**No artifact upload.** The scheduled reality lane
(`.github/workflows/reality.yml`) only checks out, installs, and runs
`pytest tests/test_reality_harness.py` — there is **no `actions/upload-artifact` step** and
no persistence side-effect anywhere in the workflow.

**Where the over-promise lives.** The readiness/verification statements in the vision doc
present the V2 registry as the verification mechanism without its ephemeral nature:
- `NERVA_VISION.md:46` — "the **Verification Fabric** (O24 — reality harness,
  SEAM→WIRED→VERIFIED→GA registry)";
- `NERVA_VISION.md:292` — "only the V1 reality harness promotes to VERIFIED".

Both are *true* as far as they go; the debt is that neither mentions the registry resets on
every boot, so a reader can reasonably conclude a green reality run is durable. The board
itself is honest (`harness_pending` flag, `capability_registry.py:489`).

**Proposed correction for `NERVA_VISION.md:46` (and `:292`):** append the lifetime:
> "the **Verification Fabric** (O24 — reality harness, SEAM→WIRED→VERIFIED→GA registry;
> **in-process, resets each boot — a durable committed readiness snapshot is V3, pending**)"

---

## Claim 6 — README's voice stack lists engines no install path ships

**Verdict: CONFIRMED.**

**The claim.** `README.md:86`:

> `- **Voice:** openWakeWord + faster-whisper + edge-tts / Kokoro`

**The engines are never installed by any shipped path.**
- `requirements.txt:32–35` — the voice block is fully commented out:
  `# openwakeword`, `# faster-whisper`, `# kokoro-onnx` (note `kokoro-onnx`, which differs
  from the README's "Kokoro").
- `requirements-beta.txt:43–57` — voice engines exist only as comments
  (`# pip install openwakeword pyaudio`, `# pip install faster-whisper torch`,
  `# pip install edge-tts`, `# pip install kokoro`, `# pip install pygame`).
- Install scripts install **only** `-r requirements-beta.txt`:
  `INSTALL.bat:138`, `install.ps1:36`, `install.sh:25`. `Select-String` for
  whisper/wakeword/edge/kokoro/voice/pyaudio over all three scripts returns **zero
  matches**.
- `requirements-dev.txt` contains no voice deps.

The runtime *code* for all four engines exists and imports lazily:
`agents/core/voice/stt.py:27` (`from faster_whisper import WhisperModel`),
`agents/core/voice/wake_word.py:14` (`import openwakeword`),
`agents/core/voice/tts.py:17` (`import edge_tts`) and `:23` (`import kokoro_tts`); missing
engines degrade to 503 with a manual-install hint (`docs/VOICE.md:48`, `:50–51`, `:173–174`)
and the HUD refuses to start the mic. So a stock install has **no** STT, **no** TTS.

**Where the over-promise lives.**
- `README.md:86` — presents the four engines as the shipped stack.
- `docs/FEATURES.md:67–68` — stronger: "voice — browser-mic loop (faster-whisper STT →
  edge-tts/Kokoro TTS) **ships today**"; the loop ships, but the server-side engines do not.
- `docs/VOICE.md` is honest (503-on-absence + manual `pip install` at `:173–174`).

**Proposed corrected sentence for `README.md:86`:**

> `- **Voice:** HUD browser-mic loop ships; server engines are optional/manual — STT
> faster-whisper, wake-word openWakeWord, TTS edge-tts / Kokoro (`pip install
> faster-whisper` / `edge-tts` / `kokoro`, see `docs/VOICE.md`) — not installed by any
> install path`

And for `docs/FEATURES.md:67–68`, change "ships today" to "the HUD loop ships today;
server-side STT/TTS engines are manual extras and degrade to 503 until installed".

---

## Unverifiable / not fully verifiable

None of the six claims was refuted. Two are *partially* qualified rather than fully
unverifiable:

- **Claim 4 nuance:** "policy plane that never executes" is strictly true only for the
  policy/target layer; the package's env-scrubbing/output-capping helpers execute via
  `sandbox.py` / `tool_rpc_runtime.py` (see claim 4). The no-SSH-transport half is fully
  confirmed.
- **Claim 5 nuance:** whether "no uploaded artifact" is a *debt* depends on reading
  `NERVA_VISION.md:46/292` as implying durability; the code and the CI workflow are already
  explicit about being in-process (see claim 5).

## Integrity notes

- No production code, tests, generated truth files, `BACKLOG.md`, or
  `PARALLEL_WORKFLOW.md` were modified. Only this document was created.
- Line numbers were captured on `origin/main` @ `69c7ab2c`; if `main` moves, re-verify the
  cited lines before acting on them.


---

## Resolution — 2026-08-29 (GAP-9 functional wave)

All five confirmed claims were closed by building the functional half rather than
re-hedging the docs (BACKLOG's 2026-08-28 recount asked for exactly this):

1. **Presence** — `agents/core/house/ingest.py` is the production writer
   (HA snapshot -> `PresenceInference`, default-off `house.presence_enabled` /
   `JARVIS_HOUSE_PRESENCE`); `/api/house/state` gained `presence_status`.
2. **ONVIF** — the missing `wsdiscovery` dependency now names its remedy at
   runtime (`onvif_dependency_missing` + `detail`); deliberately unlocked,
   same policy as the Playwright/pywinauto hosts.
3. **VLM** — `llm/vlm.py::resolve_vlm_config` makes a self-hosted server
   first-class (`JARVIS_VLM_BACKEND=lmstudio` on 1234/v1, or `custom`), with
   stable refusal reasons; `/api/vlm/status` reports config truth only.
4. **Environments** — `environments/execution.py::GovernedTargetRunner`
   executes through the target policy plane (docker-only, audit-before-spawn),
   reached via the gated `terminal_run` ToolRPC tool behind
   `JARVIS_TERMINAL_TARGETS`; local/ssh refuse with explicit
   not-implemented reasons.
5. **Reality harness** — `observability/reality_evidence.py` persists each run
   as `nerva.reality.run.v1` evidence (+ reality.yml artifact upload,
   14-day retention); promotion stays in-process-only per V3.

Doc corrections from the proposal above were applied in the same wave
(`docs/design/HUD_V2_REMAINING.md`, `docs/FEATURES.md`, `NERVA_VISION.md`).
