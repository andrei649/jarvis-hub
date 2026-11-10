# Plan for the 112 `missing` Hermes rows (64 to build, 48 skip)

Base: jarvis-hub `90bb0f1` (2026-11-10). Upstream: hermes-agent `9c0560f8`. Sources: the frozen inventory
`docs/research/2026-09-07-hermes-absorption-ledger.json`, `docs/hermes/assessment.json`,
`scripts/hermes_status.py`, `runtime/hermes/gateway-catalog.json` and `runtime/hermes/rpc-policy.json`.
Line counts exclude tests. **Fan-in** is the number of distinct internal Hermes modules a file imports,
counted with `ast` (`agent.*`, `tools.*`, `gateway.*`, `hermes_cli.*`, `hermes_state*`, `hermes_constants`,
`utils`, …).

## 0. Three facts that change the plan

1. **Where the 64 come from.** `hermes_status.py summary` reports 112 missing. Only 57 have a review.
   The other 55 have **no review at all**: the reader defaults them to `missing` from their 2026-09-07
   `nerva_state`. 112 − 48 skip = 64. Only 9 of the 64 were assessed as missing (H023, H040, H086, H173,
   H543, H545, H597, H658, H668). The other 55 (marked † below) carry a two-month-old baseline, and
   code has landed since then:
   - `/btw` exists (`agents/core/commands.py:54`, H414), which bears on H669.
   - Telegram `sendVoice` exists (`channels/telegram.py:1826`), and so do inbound voice and photo (H108).
     This bears on H528 and H070.
   - `JARVIS_PROFILE` named profiles exist (`paths.py:143`, H689 equivalent), which bears on H250.
   - The web chat has a `clarify` path (`agents/web.py:1599`), which bears on H316.
   - `nerva approvals` exists (`agents/cli/nerva.py:285`), which bears on H226.
   - Skill `required_environment_variables` is parsed (`skills/frontmatter.py:271`), which bears on H342.
   - Kanban worktrees were adapted from Hermes (`kanban/workspaces.py`), which bears on H402 and H474.
   - Tauri has a `global_shortcut` flag (`desktop/src-tauri/src/main.rs:23`), which bears on H179.
   - The Adopt slice 3 skills catalog (H336) bears on H335.

   **Step 1 of any build order is to re-assess these rows. Writing code comes after.**
2. **The Run lane is narrower than the 2026-11-10 proposal assumes.** The sidecar exposes only Hermes's
   headless `/api/ws` JSON-RPC (262 methods: 87 at tier 0, 15 at tier 2, 160 at tier 3).
   `RUNTIME_INTEGRATION.md` states that REST, PTY, SPA and plugin-HTTP routes are refused. So
   `hermes acp` (stdio), the `api_server` platform (`/v1/chat/completions`), `hermes mcp serve`, the
   messaging-platform adapters (Telegram, SMS, …), the Electron desktop and the Ink TUI are **not
   reachable**. Run only covers features whose effect is an RPC method. That means these rows:
   /btw, /loop, context breakdown, clarify, the MCP catalog and OAuth, rooms and peers, and what the
   skip rows below say.
3. **Two upstream sources are gone at `9c0560f8`.** `hermes sync` (H040) has no code upstream. The
   browser-controller broker (H086) is gone too: `browser.controller.{register,heartbeat,result,detach}`
   were removed in this pin's contract diff, and no Python references remain. Neither row can be
   adopted or run. Each is native-only, and should be re-scoped against current upstream.

## 1. Feature groups (64 rows → 22 groups)

Lane key: **Own** is native code. **Adopt** is vendored upstream text behind `agents/vendor/hermes_compat`.
**Run** is the sidecar RPC, named methods with tiers. "Own+Adopt" means a native core plus vendored leaf
files. The **Sec** column marks groups that need adversarial review (approvals, exec, credentials,
egress, memory).

| # | Group | Rows | Lane | Upstream files (lines · fan-in) | Nerva files touched | Size | Sec | Depends on |
|---|---|---|---|---|---|---|---|---|
| G1 | Operator-pinned (managed) config | H249†, H267†, H629† (duplicates of one feature) | Own | `hermes_cli/managed_scope.py` 188 · 5 (reference only: imports `config_backend`, `secret_scope`) | new `agents/core/managed_scope.py`; `agents/core/env_config.py`; `agents/core/settings_db.py`; `agents/core/routers/admin.py` (settings PUT refusal); `agents/cli/nerva.py` (config set/unset) | S–M | yes (policy floor read by the `config.write` kind) | none (H248/H266 layering exists) |
| G2 | Session commands: /plan, /loop, /btw fork | H668, H460†, H578† (H460 and H578 are duplicates), H669† | Own+Adopt | `agent/plan_prompt.py` 71 · **0** (Adopt as is); `hermes_cli/loops.py` 738 · 2 (`config`, `goals`): cadence and digest backoff can be adopted with a 2-shim compat; `agent/side_question*.py` 614 · 4–13 (do not adopt). Run: `prompt.btw` (t2), `session.control` (t3) + `session.control.update` | `agents/core/commands.py`; `agents/core/slash_access.py`; `agents/core/kernel/` (plan-mode: refuse non-read kinds while active); `agents/core/heartbeat.py` (H577 seam); `agents/core/memory/conversation.py` (snapshot for the /btw fork); vendor + compat | M (H669 is S after re-assessment: /btw already native) | yes for H668 (kernel mode) | none |
| G3 | Context meter | H412† | Own | `agent/context_breakdown.py` 364 · 5 (tied to Hermes's system prompt; reference only). Run: `session.context_breakdown` (t0), sidecar sessions only | `agents/core/context_compressor.py` (expose the policy object); new route in `agents/core/routers/sessions.py`; `frontend/src/panels/mission-canvas.tsx` + new meter; `/context` in `commands.py` | M | no | G2 (`commands.py`: same builder or after G2) |
| G4 | Clarify tool + governance prompts | H316†, H226† | Own+Adopt | `tools/clarify_tool.py` 224 · 3 (`agent.redact`, `tools.human_input_hooks`, `tools.registry`: all have compat targets in the plan); `tools/clarify_gateway.py` 319 · 5 (do not adopt). Run: server requests `clarify`, `secret`, `sudo` + `clarify.lock`, `request.answer`, `approval.respond` (t3) | `agents/web.py` (existing `on_clarify`); `agents/core/tool_rpc.py`; `agents/cli/nerva.py` (approvals exist; add clarify/secret answers); HUD card | S–M after re-assessment | yes (answers are untrusted input; secret goes to the broker) | none |
| G5 | Project verification + coding posture | H023, H405†, H406† | Own+Adopt | `agent/verify/recipes.py` 296 · **0**, `environment.py` 48 · 1 (Adopt); `runner.py` 264 · 2 (replace: it spawns processes); `agent/verification_evidence.py` 805 · 4, `verification_stop.py` 244 · 8, `agent/coding_context.py` 592 · 4 (reference, or Adopt with `runtime_cwd`/`subprocess`/`config` shims) | new `agents/core/verify/` (runner through `terminal.exec` / `environments/execution.py`, evidence table); prompt context tier (H406 snapshot); `agents/core/environments/targets.py`; vendor tree | L (M without verify-on-stop) | yes (host execution) | execution-target transports (H023) |
| G6 | MCP client protocol + resilience | H552†, H556† | Own (+Adopt `tools/mcp_schema_cache.py` 109 · 2) | `tools/mcp_tool_handlers.py` 887 · 17, `mcp_tool_discovery.py` 950 · 12, `mcp_tool_health.py` 297 · 5 (reference only) | `agents/core/mcp/client.py` (`connect_all` is a serial loop today, `:842`); resource/prompt utility tools in `agents/core/mcp/`; injection scan on resource text | M + M | yes for H552 (untrusted resource text) | none |
| G7 | MCP sampling / elicitation | H553† | Own (+Adopt the rate-limit core of `tools/mcp_tool_sampling.py` 333 · 6 if shims cover `auxiliary_client`/`approval_prompt`) | as listed | `agents/core/mcp/client.py` (initialize callbacks); `agents/core/kernel/budget.py`; approval queue | M | yes (spends the owner's budget) | G6 (same file: same builder) |
| G8 | Tool search (progressive disclosure) | H585† | Own | `tools/tool_search.py` 649 · 9, `tool_search_catalog.py` 336 · 3, `tool_search_validation.py` 265 · 4 (reference; BM25 is replaceable) | `agents/core/tool_rpc.py`; `agents/core/autonomy_coordinator.py:433-677`; new `agents/core/tool_search.py` | M | yes (`tool_call` must unwrap before `kernel.authorize`) | MCP tools exposed to the model loop |
| G9 | MCP install catalog + client OAuth | H549†, H550†, H692† | Own + Adopt data | `optional-mcps/` 66 reviewed manifests (Adopt as data, like `SKILLS_CATALOG.json`); `hermes_cli/mcp_catalog.py` 858 · 12; `tools/mcp_oauth*.py` 2 620 · 4–6 (reference: `hermes_constants`, `pm`, `mcp_tool`). Run: `mcp.catalog` (t0), `mcp.servers.add`, `mcp.servers.oauth.{start,poll,callback,cancel}` (t3), sidecar servers only | `agents/core/routers/mcp.py`; `agents/core/routers/oauth.py`; `agents/core/plugins/oauth.py` (PKCE exists); `agents/core/secrets_vault.py`; `scripts/hermes_vendor.py` catalog | L | yes (an install is a new trust root; tokens) | H548 operator surface (partial, exists) |
| G10 | Nerva's MCP server: inbox + approvals | H559† | Own | `agent/transports/hermes_tools_mcp_server.py` 165 · 2 (different shape; reference) | `agents/core/mcp/server.py` (ROUTE_TOOL_ALLOWLIST / MUTATING_ROUTE_ALLOWLIST); `agents/core/routers/mcp.py` | M | **yes** (answering an approval over MCP) | per-identity MCP tokens (H558 residual) |
| G11 | Editor agent over ACP | H542†, H543, H544†, H545 | Own+Adopt | `acp_adapter/` 22 files, 6 726 · 84: **not adoptable as a whole** (`server.py` 1 155 · 32, `session.py` 597 · 11). Leaves to adopt: `permissions.py` 153 · 2, `edit_approval.py` 244 · 4, `modes.py` 18 · 0, `elicitation.py` 71 · 0. Not reachable via Run | new `agents/core/acp/` (stdio server over the orchestrator); `agents/core/mcp/client.py` (session-scoped registry, H545); approval-queue mapping (`allow_always` → `permission.grant`); new dependency `agent-client-protocol` | **L–XL** | **yes** | **owner decision**: contradicts skip H056 (same feature) |
| G12 | OpenAI-compatible inbound API | H560†, H614† (duplicates) | Own | `gateway/platforms/api_server.py` 4 111 · 69 (reference only) | new `agents/core/routers/openai_compat.py`; `agents/core/routers/_deps.py` (bearer → identity); `agents/core/action_origin.py` (taint at the boundary); `agents/core/identity_manifest.py` | M–L | yes | none. It is not the credential-lending proxy of H376/H565/H584 |
| G13 | Browser sign-in for a networked Nerva | H509† | Own | reference: Hermes web_server session token | `agents/web.py:119-215` guards; `agents/core/routers/_deps.py`; reuse the design of `agents/core/workspace/auth.py` | L | **yes** | G12 (`_deps.py`: sequence after G12); H510 host-header guard |
| G14 | A2A outbound (call peers as tools) | H562† | **Adopt** | `plugins/platforms/a2a/tools.py` 361 · 3, `protocol.py` 491 · 2, `security.py` 259 · 6 (`proxy_bypass`, `redact`, `secret_scope`, `_shared`, `config`, `hermes_constants`). Uses `urllib.request`, so a compat urllib routed to `PluginHTTPClient` replaces today's `urllib_refused` | `agents/core/a2a.py` (peer `url`); new `agents/vendor/hermes_compat/{a2a_shared,urllib}.py`; plugin manifest + egress allowlist; vendor tree + `MANIFEST.json` | M | yes (sends owner data off-box; `plugin.egress`) | inbound A2A (H561, partial) |
| G15 | Channel reliability | H081†, H100†, H116† | Own | `gateway/delivery_ledger.py` 564 · 5, `dead_targets.py` 104 · 2, `plugins/platforms/telegram/` 38 files 11 318 · 75, `telegram_held_inbound.py` (reference only) | `agents/core/channels/telegram.py` (offset kept only in memory, `:308`; no backoff); `channels/manager.py`; `channels/outbound.py`; `agents/core/channel_inbox.py`; new delivery-ledger table | L | yes for H116 (backfill must re-enter gating) | adapter descriptor |
| G16 | Channel media + SMS | H070†, H528†, H098† | Own (+Adopt `tools/audio_container.py` 56 · **0**) | `gateway/media_policy.py` 120 · 2, `media_fetch.py` 120 · 6, `plugins/platforms/sms/adapter.py` 359 · 8 (needs `gateway.platforms.*` shims, more compat than writing it natively) | `channels/telegram.py`; new `channels/sms.py` (Twilio HMAC-SHA1 webhook); `agents/core/kernel/registry.py` (SMS kind, or reuse `call.outbound`); delivery-path allowlist | M (H070/H528 likely S–M after re-assessment) | yes (file egress, paid SMS, webhook auth) | G15 (`telegram.py`: same builder) |
| G17 | Owner hooks | H080†, H408† | Own | `gateway/hooks.py` 168 · 4, `run_inbound_hooks.py` 302 · 14, `agent/shell_hooks.py` 858 · 10 (reference) | new `agents/core/hooks/`; `agents/core/extensions/`; `plugin_gate.py`; kernel `permission.grant` + `terminal.exec` | M + M | **yes (highest)** | **owner decision**: H408 duplicates skip rows H021, H163 and H514 |
| G18 | Worktrees, delegation durability, reviewer | H402†, H474†, H401†, H404† | Own (+Adopt the prompt text of `agent/review_engine.py` 195 · 2) | `hermes_cli/worktree_ops.py` 1 231 · 17, `tools/async_delegation.py` 1 467 · 15 (reference only) | `agents/core/subagents.py`; `agents/core/kanban/workspaces.py` (extract the shared worktree helper); `agents/core/autonomy/queue.py` (durable rows) | L (H402+H474 M, H401 L, H404 S–M) | yes (writes to disk; reviewer must be read-only) | H400 (partial, landed) |
| G19 | Video generation | H516† | **Adopt** (provider ABC + plugins) | `agent/video_gen_provider.py` 289 · 4, `video_gen_registry.py` 45 · 2, `plugins/video_gen/` 4 files 1 164 · 10 (`fal_common`, `xai_http`, `managed_tool_gateway`, `runtime_provider`); `tools/video_generation_tool.py` 376 · 7 (replace). No video RPC in the catalog | `agents/core/creative/video_pipeline.py`; `media.generate` kind; media serving (H523); compat `provider_base`/`secret_scope`; vendor tree | M–L | moderate (cost/egress: reuses the reviewed image path) | image-provider seam H515 (exists) |
| G20 | Skills distribution | H025†, H335†, H342†, H040 | Own (+Adopt `tools/skills_hub_sources.py` 430 · 2 for the trust-ranked source router) | `hermes_cli/skills_hub.py` 1 731 · 24, `tools/skills_hub*.py` (~2 000 · 6–8) reference; **no upstream for H040** | `agents/core/skills/importer.py`, `marketplace.py`, `frontmatter.py` (H342 already parses), skills router; secret broker | H342 S, H025 M, H335 **XL** (most is now H336 catalog: re-assess), H040 L (no source) | yes (taps are trust roots) | H336 (partial) |
| G21 | Ops surfaces: files, channel config, restart/update | H142†, H151†, H160†, H173, H624† | Own | `hermes_cli/web_server_files.py` 560 · 10, `update_cmd.py` 1 954 · 33, `update_cmd_check.py` 327 · 14 (reference only) | new `agents/core/routers/files.py`; channel-config routes + `routers/secrets.py` broker; `agents/core/routers/ops.py` (restart/update actions, streaming log); `repo.sync` / `host.control` kinds; HUD panels | L (3 sub-branches: files M, channel config M, update L) | **yes** (credential denylist, irreversible update) | backup create/verify (exists); H171 for the desktop half of H173 |
| G22 | Desktop shell (Tauri) | H171†, H179†, H181†, H183†, H186†, H203†, H690† | Own (Hermes is Electron TS; nothing to adopt; not reachable via Run) | `apps/desktop/…` reference; `hermes_cli/macos_tcc_anchor.py` 367 · 3 | `desktop/src-tauri/src/main.rs` + new Rust modules; `frontend/src`; installer packaging | **XL total** (H186 alone XL, H171 L, H179 S, others M) | yes for H183 (link installs an MCP server) and H203 (import = `skill.install`) | owner decision 2 (desktop out of native scope?); H183 needs G9 |

Groups that are left over or must be re-scoped:

| Rows | Note |
|---|---|
| H224†, H226† (terminal client) | H226 is mostly covered by `nerva approvals` plus G4. H224 assumes a full-screen TUI that Nerva does not have. The proposal's decision 2 would take it out of native scope. **L if built.** |
| H250†, H203† (profiles) | H250 is mostly delivered by H689 (`JARVIS_PROFILE`): re-assess. What remains is `?profile=` on config routes, a HUD switcher, and the export/import bundle (H203). Own, M. Touches `paths.py` and `routers/admin.py`, which collides with G1, so sequence it after G1. |
| H366† (sign in with a Claude/ChatGPT subscription) | Own, L, security. `hermes_cli/auth.py` 2 423 · 33 and `auth_codex.py` 1 132 · 14 cannot be adopted. Reuse the Nous device flow (`agents/core/llm/nous_auth.py`) and the Codex image auth. **Owner decision: provider terms of service** on using consumer-subscription OAuth in a third-party app. |
| H597 (LSP diagnostics) | `agent/lsp/` 14 files 4 042 · 24. `client.py` 862 · 6 and `protocol` could be adopted. **L.** It contradicts skips H055 and H564 (same feature): resolve that first. If built, start with pyright only as a governed child process. |
| H658 (remote room member) | Own: `agents/core/node_mesh.py`, `agents/core/security/capability.py`. Reference: `gateway/hosted_room_peer.py` 562 · 7. **L**, adversarial review. Run alternative between Hermes instances only: `groups.peer.{invite,register,revoke}` (t3). |
| H086 (browser broker, `keep`) | The upstream source is gone (see §0). Re-scope against `browser.manage` (t3) / Nerva's `browser.step`, or mark it superseded. |
| H040 (device sync) | No upstream code. Lowest value per effort of the 64. Defer. |

## 2. Recommended build order

Parallel lanes have disjoint files. The shared hotspots are `agents/cli/nerva.py`, `commands.py`,
`mcp/client.py`, `channels/telegram.py`, `subagents.py` and `routers/_deps.py`. Each hotspot belongs to
exactly one builder per wave.

| Wave | Builder A | Builder B | Builder C | Builder D |
|---|---|---|---|---|
| **0** (no code, highest value per effort) | Re-assess the 55 unreviewed rows with `hermes_status.py write`. Expect about 10 to move to `partial`: H669, H528, H070, H316, H226, H250, H342, H335, H179, H402/H474. Resolve the duplicates (H460=H578, H560=H614, H249=H267=H629) and the decision conflicts (H056↔H542–545, H055/H564↔H597, H021/H163/H514↔H408). | | | |
| **1** (S–M, high value) | G1 managed scope (`managed_scope.py`, `env_config.py`, `settings_db.py`, `routers/admin.py`, owns `nerva.py` this wave) | G2 → G3 /plan, /loop, /btw fork, /context (owns `commands.py`, kernel plan-mode) | G6 → G7 MCP client resources, resilience, sampling (owns `mcp/client.py`) | G14 A2A outbound, Adopt (`a2a.py`, compat urllib, vendor) |
| **2** (M) | G4 clarify + prompts (`web.py`, `tool_rpc.py`; takes `nerva.py` from A) | G5 verify + coding posture (new `core/verify/`, vendor `agent/verify/`) | G9 MCP catalog + OAuth (`routers/mcp.py`, `routers/oauth.py`, `plugins/oauth.py`) | G19 video gen, Adopt (vendor, `creative/video_pipeline.py`) |
| **3** (M–L) | G12 OpenAI-compatible API → G13 browser sign-in (owns `_deps.py`, `web.py` guards) | G15 → G16 channels (owns `channels/*`) | G18 worktrees, delegation, reviewer (owns `subagents.py`, `kanban/workspaces.py`) | G8 tool search (`tool_rpc.py` after G4, `autonomy_coordinator.py`); then G10 MCP server approvals (`mcp/server.py`) |
| **4** (L/XL or owner-gated) | G21 ops surfaces (files → channel config → update) | G20 skills distribution (H342, H025 first; H335 after re-assessment) | G11 ACP (if the owner overrides H056) | G17 hooks (if the owner overrides H021/H163/H514); H366, H597, H658, G22 desktop, H224 after owner decisions |

Wave 1 and 2 already include the rows whose Hermes code can be adopted cleanly: `plan_prompt.py`
(fan-in 0), `verify/recipes.py` (0), `audio_container.py` (0), the a2a tools (2–6), the video provider
ABC (2–4), `clarify_tool.py` (3) and `loops.py` (2). The large upstream subsystems are references only:
`acp_adapter` (84), `api_server` (69), the telegram plugin (75), `profiles` (32), `update_cmd` (33),
`auth` (33) and `skills_hub` (24).

**Honest size of the 64.** The inventory's own effort field gives 2 S (H086, H545), 46 M, 14 L (H070,
H100, H171, H366, H401, H405, H509, H516, H542, H550, H556, H560, H597, H624) and 2 XL (H186, H335).
Grouped, the real heavyweights are G11 ACP (L–XL), G22 desktop (XL total), G21 ops surfaces (L) and
G15 channel reliability (L). Wave 0 should move about 10 rows to `partial` and shrink several M rows
to S.

## 3. The 48 `skip` rows: is `excluded` honest?

All 48 are currently counted as missing, because the owner directive of 2026-09-27 reopened every
former exclusion (`scope_reopenings`, 107 entries; `excluded: 0`). The verdicts:

- **Keep**: `excluded` is honest by design.
- **Keep, sidecar**: excluded natively, but the pinned sidecar already exposes it, so it could count as
  `available (sidecar)` if the owner takes decision 1.
- **Defer**: honest only as "deferred (audience or effort)", not "by design".
- **Reconsider**: the rationale is stale or contradicted elsewhere in the ledger.

| Row | Feature | Verdict | Why |
|---|---|---|---|
| H032 | Mixture-of-agents presets | Keep, sidecar | Multiplies spend on a local box. The sidecar has MoA (`moa.*` notifications). |
| H050 | Restricted operator shell | Keep | The kernel makes an allowlist shell redundant. |
| H054 | Drive the owner's logged-in browser | Keep | Hands over every live session cookie. |
| H055 | Install/manage language servers | **Reconsider** | Contradicts H597 (copy). Decide once for all three LSP rows. |
| H056 | Serve to editors over ACP | **Reconsider** | Contradicts H542–H545 (copy, same feature). |
| H077 | /fast, /codex-runtime, /topup | Keep | Vendor commerce, against %-local. |
| H087 | Scale-to-zero | Keep | Hosted-billing feature; the box is always on. |
| H102 | DoH fallback-IP transport | Keep | Breaks hostname-based egress gating. |
| H110 | Discord voice presence | Keep | Community product; local voice covers the owner's room. |
| H123 | DingTalk/Feishu/WeCom/Yuanbao | Defer | Audience, not design. The sidecar does not run Hermes messaging adapters, so no Run option. |
| H124 | IRC/LINE/SimpleX/Mattermost/Raft/Buzz | Defer | Same as H123. |
| H125 | iMessage via a BlueBubbles sidecar | Keep | Needs a second always-on macOS runtime with full disk access. |
| H127 | Matrix E2EE | **Reconsider → Defer** | The rationale is weak. E2EE protects against the homeserver, not against Nerva. This is effort, not anti-thesis. |
| H128 | Platform administration tools | Keep | Irreversible third-party effects outside the owner's use. |
| H149 | Swappable memory provider | Keep | Memory is the integrated pillar under `kg.write` mediation. |
| H163 | Event-triggered shell hooks | **Reconsider** | Contradicts H408 (copy) and H080. One owner decision for H021/H163/H514/H408. |
| H166 | Third-party dashboard extensions | Keep | Same-origin JavaScript can forge approvals. |
| H213 | Pane tiling + `apply_layout` | Keep | Product: a designed HUD. |
| H214 | Desktop pet | Keep, sidecar | Brand. `pet.*` RPCs exist; exposing them is a brand choice, not parity. |
| H215 | Native context menu / spellcheck | Keep | The webview and OS already provide it. |
| H233 | Hot-loaded TUI widget SDK | Keep | Unsandboxed agent-authored code. |
| H238 | Pet system (TUI) | Keep, sidecar | As H214. |
| H239 | Hosted wallet / top-up | Keep | No hosted metering to top up. `billing.*` / `subscription.*` exist in the sidecar but serve Nous's storefront: do not count them. |
| H292 | Human-typing pacing | Keep | Honesty posture. |
| H324 | Native third-party platform tools | Keep | Same as H128. |
| H341 | Inline shell in skill bodies | Keep | Actively incompatible: reading a skill would execute code. |
| H348 | LLM skill consolidation | **Reconsider → Defer** | The "12 skills" premise is stale since the Adopt slice 3 catalog (H336). Still low value. |
| H365 | Bedrock/Vertex/Azure credentials | **Reconsider** | "Single-owner house brain" no longer holds for the Nerva Workspace B2B pilot. Tie it to D1–D3. |
| H371 | Buy credits / subscription | Keep | Storefront for Nous. |
| H376 | Lend provider credentials to local apps | Keep | Credential lending outside the kernel. Distinct from G12 (H560/H614). |
| H384 | Another agent CLI as a backend | Keep | A foreign loop runs tools that Nerva does not authorize. |
| H489 | Approve-everything (yolo) | Keep | Conflicts with the approval model. |
| H496 | Per-identity credential isolation | **Reconsider** | The single-principal premise is broken by the multi-user Workspace pilot (`agents/core/workspace/`). It may become a must-have for B2B. |
| H546 | Copilot as a model backend over ACP | Keep | Same as H384. |
| H564 | Semantic errors after an edit (LSP) | **Reconsider** | Duplicate of H597 (copy). |
| H565 | Third-party apps ride the owner's subscription | Keep | Credential lending. |
| H568 | Middleware that rewrites tool calls | Keep | Approval cards would describe arguments that were changed after review. |
| H572 | Custom UI in the desktop app/dashboard | Keep | Same as H166. Electron is the wrong stack. |
| H582 | `x_search` | **Reconsider (Adopt, S)** | `tools/x_search_tool.py` 342 · 3 (`config`, `registry`, `xai_http`). It fits the Adopt lane exactly like Exa/Brave/Parallel: opt-in, owner key, `plugin.egress`. |
| H584 | Subscription as an OpenAI proxy | Keep | Same as H565. |
| H587 | Nous tool gateway | Keep | A hosted pass-through for every query. |
| H590 | Mascot reacting to agent state | Keep, sidecar | As H214. |
| H609 | Hand turns to the Codex app-server | Keep | Effects outside the kernel. |
| H627 | Android host | Keep | One governed host; phones are clients. |
| H628 | Nix fleet deployment | Keep | Fleet operator, not the product's user. |
| H638 | Desktop-shell extension API | Keep | The Tauri shell is a window, not an app platform. |
| H657 | Room failover to a surviving host | Keep, sidecar | Single host by design. `groups.replicate/promote/demote` (t3) exist between Hermes hosts only. |
| H662 | Second browser engine + real-profile snapshot | Keep | No screenshots means no visual grounding. The real-profile half is the same as H054. |

**Summary.** 32 rows are honestly `excluded`, and 5 more are excluded natively but available through
the sidecar (H032, H214, H238, H590, H657). 2 should be labelled deferred rather than excluded
(H123, H124). 9 need an owner decision or a fix:
- four are contradictions with copy rows (H055, H056, H163, H564);
- two have premises the B2B pilot broke (H365, H496);
- two should drop to deferred: H348 (stale premise) and H127 (weak rationale);
- one is a cheap Adopt (H582).
