# Gap-fill: Web dashboard "Keys" page — composed accessible names (round 0, area web-c)

Scope: this shard closes round-0 coverage gaps in the web dashboard's Keys page (`/env`) that exist
only as *composed* strings — labels the DOM/accessibility tree exposes by concatenating several
independently-i18n'd fragments, which no single-fragment entry in `web-c.md` reproduces. Two features
are documented here in full: (1) the **provider-group accordion header** in the "LLM Providers" card,
whose accessible name is `group name` + optional `Get key` link + `{count} key{s}` chip, and (2) the
**per-provider docs icon link** in the "Provider Logins (OAuth)" card, whose `title` is the runtime
template `Open ${p.name} docs` instantiated once per catalog provider.
Deliberately left to siblings: the per-key edit rows inside an expanded group (`web-c.env.var-row`,
`web-c.env.provider-group-row`), the OAuth card's buttons/badges/modal (`web-c.env.oauth-card`,
`web-c.env.oauth-providers`, `web-c.env.oauth-modal`), the Custom Keys card, and the non-provider
category cards — all already inventoried in `web-c.md`. The desktop app's twin i18n keys belong to
`desktop-b`.

### Keys → LLM Providers → provider-group accordion header (composed accessible name)  `id: gapfill-web-c-r0.env.provider-group-header`
- **Surface:** Web dashboard
- **Where:** `/env` (sidebar `KEYS`) → card "LLM Providers" (i18n `env.llmProviders`, anchor `#section-providers`) → each collapsible group row. The row is a `ListItem` with `onClick` and `aria-expanded`, so Playwright/AT report it as a **button** whose accessible name is the concatenation of every visible text node in the row. Live-crawl button names, verbatim and in render order (`hermes_inv/web_crawl/_env.json` → `states[0].buttons[35..50]`):
  1. `Nous Portal 1 key`
  2. `Anthropic 3 keys`
  3. `DashScope (Qwen) Get key 4 keys`
  4. `DeepSeek Get key 2 keys`
  5. `Gemini Get key 3 keys`
  6. `GLM / Z.AI Get key 4 keys`
  7. `Hugging Face Get key 2 keys`
  8. `Kimi / Moonshot Get key 4 keys`
  9. `MiniMax Get key 2 keys`
  10. `MiniMax (China) Get key 2 keys`
  11. `OpenCode Go Get key 2 keys`
  12. `OpenCode Zen Get key 2 keys`
  13. `OpenRouter Get key 1 key`
  14. `Xiaomi MiMo Get key 2 keys`
  15. `Upstage Solar Get key 2 keys`
  16. `Other Get key 59 keys`
- **What it does:** One clickable header per LLM vendor. Clicking it expands/collapses that vendor's environment-variable rows; the header itself advertises the vendor name, how many of its keys are configured, an optional outbound "Get key" link to the vendor's key console, and the total number of env vars in the group.
- **How it works:** `web/src/pages/EnvPage.tsx:386-424` (`ProviderGroupCard`'s header `ListItem`). Composition, left to right:
  - `ChevronDown` (expanded) or `ChevronRight` (collapsed) icon — `EnvPage.tsx:392-396`, `h-3.5 w-3.5 text-muted-foreground`.
  - Group label — `EnvPage.tsx:398-400`: `{group.name === "Other" ? t.common.other : group.name}`. All 15 named groups render their raw English name from the `PROVIDER_GROUPS` table (`EnvPage.tsx:48-70`, not translated); only the catch-all is routed through i18n `common.other` = "Other" (`web/src/i18n/en.ts:36`).
  - Optional success `Badge` `"{configuredCount} {t.common.set.toLowerCase()}"` — `EnvPage.tsx:401-405`; rendered only when `hasAnyConfigured` (at least one key in the group has `is_set`). On the inventory home no provider key is set, so no group shows it and the live names above contain no "N set" fragment.
  - Optional "Get key" link — `EnvPage.tsx:407-418`: `{t.env.getKey}` (i18n `env.getKey` = "Get key", `en.ts:499`) plus a 10 px `ExternalLink` icon, `href={keyUrl}`, `target="_blank" rel="noreferrer"`, `onClick={(e) => e.stopPropagation()}` so following it does not toggle the accordion. `keyUrl = apiKeys.find(([, info]) => info.url)?.[1]?.url ?? null` (`EnvPage.tsx:382`) — the URL of the **first** entry ending `_API_KEY`/`_TOKEN` that carries one. Nous Portal and Anthropic have no such URL, hence no "Get key" fragment in their names.
  - Key-count chip — `EnvPage.tsx:419-423`: `t.env.keysCount.replace("{count}", String(group.entries.length)).replace("{s}", group.entries.length !== 1 ? "s" : "")`. i18n `env.keysCount` = `"{count} key{s}"` (`en.ts:502`). The `{s}` placeholder is a hand-rolled English pluraliser: it resolves to `"s"` for every count except exactly 1, where it resolves to the empty string — which is why OpenRouter and Nous Portal read "1 key" (singular) and every other group reads "N keys".
- **Inputs / options — all 16 group rows, with the exact fragments that compose each name:**
  | # | Group label (verbatim) | Prefixes matched (`EnvPage.tsx:48-70`) | priority | "Get key" href | count chip |
  |---|---|---|---|---|---|
  | 1 | `Nous Portal` | `NOUS_` | 0 | none | `1 key` |
  | 2 | `Anthropic` | `ANTHROPIC_` | 1 | none | `3 keys` |
  | 3 | `DashScope (Qwen)` | `DASHSCOPE_`, `HERMES_QWEN_` | 2 | `https://modelstudio.console.alibabacloud.com/` | `4 keys` |
  | 4 | `DeepSeek` | `DEEPSEEK_` | 3 | `https://platform.deepseek.com/api_keys` | `2 keys` |
  | 5 | `Gemini` | `GOOGLE_`, `GEMINI_` | 4 | `https://aistudio.google.com/app/apikey` | `3 keys` |
  | 6 | `GLM / Z.AI` | `GLM_`, `ZAI_`, `Z_AI_` | 5 | `https://z.ai/` | `4 keys` |
  | 7 | `Hugging Face` | `HF_` | 6 | `https://huggingface.co/settings/tokens` | `2 keys` |
  | 8 | `Kimi / Moonshot` | `KIMI_` | 7 | `https://platform.moonshot.cn/` | `4 keys` |
  | 9 | `MiniMax` | `MINIMAX_` | 8 | `https://www.minimax.io/` | `2 keys` |
  | 10 | `MiniMax (China)` | `MINIMAX_CN_` | 9 | `https://www.minimaxi.com/` | `2 keys` |
  | 11 | `OpenCode Go` | `OPENCODE_GO_` | 10 | `https://opencode.ai/auth` | `2 keys` |
  | 12 | `OpenCode Zen` | `OPENCODE_ZEN_` | 11 | `https://opencode.ai/auth` | `2 keys` |
  | 13 | `OpenRouter` | `OPENROUTER_` | 12 | `https://openrouter.ai/keys` | `1 key` |
  | 14 | `Xiaomi MiMo` | `XIAOMI_` | 13 | `https://platform.xiaomimimo.com` | `2 keys` |
  | 15 | `Upstage Solar` | `UPSTAGE_` | 14 | `https://console.upstage.ai/api-keys` | `2 keys` |
  | 16 | `Other` (i18n `common.other`) | fallback — every `provider`-category key matching none of the prefixes above (`getProviderGroup`, `EnvPage.tsx:72-77`) | 99 (`getProviderPriority` default, `EnvPage.tsx:79-82`) | `https://console.x.ai/` (from `XAI_API_KEY`, the first "Other" API key with a URL) | `59 keys` |
  - Ordering: `EnvPage.tsx:822-829` sorts groups by `a.priority - b.priority`; "Other" gets 99 and therefore always renders last. Note that `MINIMAX_CN_` is listed **before** `MINIMAX_` in the prefix table (`EnvPage.tsx:62-63`) so the longer prefix wins the `startsWith` scan, while its priority (9) is higher than plain MiniMax's (8) — which is why the table row order and the render order differ for those two.
  - Interactions on the row: left-click anywhere except the "Get key" anchor toggles `expanded` (`setExpanded(!expanded)`, `EnvPage.tsx:388`); `aria-expanded` mirrors the state; hover style `hover:bg-primary/5`; each group starts collapsed (`useState(false)`, `EnvPage.tsx:364`). Clicking "Get key" opens the vendor console in a new tab and stops propagation.
  - The 59 keys behind `Other Get key 59 keys`, alphabetically: `ACTUAL_API_KEY`, `ACTUAL_BASE_URL`, `AI_GATEWAY_API_KEY`, `AI_GATEWAY_BASE_URL`, `ALIBABA_CODING_PLAN_API_KEY`, `ALIBABA_CODING_PLAN_BASE_URL`, `ALIBABA_CODING_PLAN_CN_BASE_URL`, `ALIBABA_TOKEN_PLAN_API_KEY`, `ALIBABA_TOKEN_PLAN_BASE_URL`, `ALIBABA_TOKEN_PLAN_CN_BASE_URL`, `ARCEEAI_API_KEY`, `ARCEE_BASE_URL`, `AWS_PROFILE`, `AWS_REGION`, `AZURE_FOUNDRY_API_KEY`, `AZURE_FOUNDRY_BASE_URL`, `CLAUDE_CODE_OAUTH_TOKEN`, `COMMANDCODE_ANTHROPIC_BASE_URL`, `COMMANDCODE_API_KEY`, `COMMANDCODE_BASE_URL`, `COPILOT_API_BASE_URL`, `COPILOT_GITHUB_TOKEN`, `DEEPINFRA_API_KEY`, `DEEPINFRA_BASE_URL`, `FIREWORKS_API_KEY`, `GH_TOKEN`, `GMI_API_KEY`, `GMI_BASE_URL`, `KILOCODE_API_KEY`, `KILOCODE_BASE_URL`, `LM_API_KEY`, `LM_BASE_URL`, `META_API_KEY`, `META_BASE_URL`, `META_MODEL_API_KEY`, `MODEL_API_KEY`, `NEBIUS_API_KEY`, `NEBIUS_BASE_URL`, `NEBIUS_TOKEN_FACTORY_API_KEY`, `NOVITA_API_KEY`, `NOVITA_BASE_URL`, `NVIDIA_API_KEY`, `NVIDIA_BASE_URL`, `OLLAMA_API_KEY`, `OLLAMA_BASE_URL`, `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `RAMP_ROUTER_API_KEY`, `RAMP_ROUTER_BASE_URL`, `ROUTER_API_KEY`, `STEPFUN_API_KEY`, `STEPFUN_BASE_URL`, `TOKENHUB_API_KEY`, `TOKENHUB_BASE_URL`, `TOKENPLAN_API_KEY`, `TOKENPLAN_BASE_URL`, `VERTEX_CREDENTIALS_PATH`, `XAI_API_KEY`, `XAI_BASE_URL`. It is by far the largest group — bigger than the other 15 combined (36) — because OpenAI, xAI, NVIDIA, Ollama, Bedrock/Vertex and every OpenAI-compatible router live there unnamed.
- **Outputs / side effects:** Purely local UI state (`expanded`) plus, for "Get key", a new browser tab at the vendor's console. Nothing is written to disk or to the server by the header itself; the writes happen in the key rows the header reveals.
- **Config / env:** Reads `GET /api/env` → `Record<string, EnvVarInfo>` where `EnvVarInfo = {is_set, redacted_value, description, url, category, is_password, tools[], advanced, channel_managed, provider, provider_label, custom}`. Only `category === "provider"` entries reach this card. The `advanced` flag is filtered by the page-level toggle (`EnvPage.tsx:809-812`), whose state defaults to **true** ("Show all providers by default", `EnvPage.tsx:615`), so the counts above are the *all-keys* counts; pressing "Hide Advanced" (i18n `env.hideAdvanced`) drops every `advanced: true` key and shrinks the chips (e.g. `Nous Portal` would lose its only key, `NOUS_BASE_URL`, and disappear entirely).
- **Edge cases / guards:** A group with exactly one key renders the singular chip (`1 key`), everything else the plural (`N keys`) — the `{s}` branch is English-only and other locales inherit the same two-form rule from their own `keysCount` string. Groups with no keys are never created (the map is built from present entries only), so an empty accordion is impossible. When no key in a group is set, the success "N set" badge is omitted entirely rather than showing "0 set". The `Other` label is the only group name that is translated; the other 15 stay English in every locale.
- **Rebuild notes:** Minimal spec — build `Map<groupName, entries[]>` by longest-prefix-wins over an ordered prefix table, sort by a hand-assigned priority with an unknown-group sentinel last, and render each header as `chevron + name + [count set badge] + [first-key-URL "Get key" link with stopPropagation] + "{n} key{s}"`. A better version would (a) expose the chip and badge to AT as `aria-label` on the button rather than relying on text concatenation, (b) use `Intl.PluralRules` instead of a `{s}` string splice so non-English locales pluralise correctly, and (c) split the 59-key "Other" bucket by the provider registry that already knows each key's vendor, instead of leaving two thirds of the page in a catch-all.

### Keys → Provider Logins (OAuth) → per-provider docs link (`Open <name> docs`)  `id: gapfill-web-c-r0.env.oauth-docs-link`
- **Surface:** Web dashboard
- **Where:** `/env` → card "Provider Logins (OAuth)" (anchor `#section-oauth`) → right-hand action cluster of each provider row → a ghost icon `Button` wrapping an `ExternalLink` glyph, inside `<a href={p.docs_url} target="_blank" rel="noopener noreferrer">`. It has no visible text, so its only accessible/tooltip name is the anchor's `title`, produced by the template `Open ${p.name} docs`. The eight live instances, verbatim:
  1. `Open Nous Portal docs`
  2. `Open ChatGPT or Codex Subscription docs`
  3. `Open Qwen (via Qwen CLI) docs`
  4. `Open MiniMax (OAuth) docs`
  5. `Open xAI Grok OAuth (SuperGrok / Premium+) docs`
  6. `Open GitHub Copilot (ACP) docs`
  7. `Open Anthropic API Key docs`
  8. `Open Anthropic OAuth: Required Extra Usage Credits to Use Subscription docs`
- **What it does:** Opens that provider's official documentation in a new tab so the operator can look up how to obtain or manage the credential before pressing "LOGIN" or copying the CLI command.
- **How it works:** `web/src/components/OAuthProvidersCard.tsx:217-227` renders the anchor only when `p.docs_url` is truthy; the `title` is built at `OAuthProvidersCard.tsx:223` as a template literal `` title={`Open ${p.name} docs`} `` — it is **not** i18n'd, so the string stays English in every locale and always interpolates the server-supplied provider name verbatim, punctuation and parentheses included. The provider list comes from `GET /api/providers/oauth`, served from `_OAUTH_PROVIDER_CATALOG` at `hermes_cli/web_server.py:11033-11117`; the same display names are reused by the CLI provider registry (`hermes_cli/providers.py:461` for the xAI entry).
- **Inputs / options — the eight anchors, their `title`, provider id and target URL (catalog order = render order):**
  1. `Open Nous Portal docs` — provider name "Nous Portal", id `nous` (`web_server.py:11035-11036`), href `https://portal.nousresearch.com`.
  2. `Open ChatGPT or Codex Subscription docs` — name "ChatGPT or Codex Subscription", id `openai-codex` (`web_server.py:11043-11044`), href `https://platform.openai.com/docs`.
  3. `Open Qwen (via Qwen CLI) docs` — name "Qwen (via Qwen CLI)", id `qwen-oauth` (`web_server.py:11051-11052`), href `https://github.com/QwenLM/qwen-code`.
  4. `Open MiniMax (OAuth) docs` — name "MiniMax (OAuth)", id `minimax-oauth` (`web_server.py:11059-11060`), href `https://www.minimax.io`.
  5. `Open xAI Grok OAuth (SuperGrok / Premium+) docs` — name "xAI Grok OAuth (SuperGrok / Premium+)", id `xai-oauth` (`web_server.py:11072-11073`), href `https://hermes-agent.nousresearch.com/docs/guides/xai-grok-oauth`.
  6. `Open GitHub Copilot (ACP) docs` — name "GitHub Copilot (ACP)", id `copilot-acp` (`web_server.py:11083-11084`), href `https://docs.github.com/en/copilot`.
  7. `Open Anthropic API Key docs` — name "Anthropic API Key", id `anthropic` (`web_server.py:11102-11103`), href `https://docs.claude.com/en/api/getting-started`.
  8. `Open Anthropic OAuth: Required Extra Usage Credits to Use Subscription docs` — name "Anthropic OAuth: Required Extra Usage Credits to Use Subscription", id `claude-code` (`web_server.py:11110-11111`), href `https://docs.claude.com/en/docs/claude-code`.
  - Interaction surface per anchor: mouse click / middle-click / Enter when focused (it is a real `<a>`, so keyboard-reachable in tab order and context-menu "Open link in new tab" works); hover shows the native `title` tooltip. No modifier-key behaviour is overridden and there is no `onClick` handler — unlike the "Get key" link in the LLM-Providers accordion, this anchor sits in a non-clickable row so it needs no `stopPropagation`.
- **Outputs / side effects:** Navigates a new browser tab to the documentation URL. `rel="noopener noreferrer"` severs `window.opener` and the referrer. No request to the Hermes server, no state change, nothing written to `~/.hermes`.
- **Config / env:** Nothing configurable — the names and URLs are hard-coded in `_OAUTH_PROVIDER_CATALOG` (`hermes_cli/web_server.py:11033`) and shipped to the browser as the `name` and `docs_url` fields of `GET /api/providers/oauth`.
- **Edge cases / guards:** The anchor is skipped entirely for any catalog entry with an empty/absent `docs_url` (all eight current entries have one, so all eight render). Because the title is an untranslated template, a localized dashboard still shows an English tooltip. Provider names are echoed straight into the `title` attribute — entry 8's name is a full sentence containing a colon, which produces the long tooltip "Open Anthropic OAuth: Required Extra Usage Credits to Use Subscription docs"; a longer or attacker-controlled name would grow the tooltip without limit (React escapes it, so it cannot break out of the attribute).
- **Rebuild notes:** Minimal spec — for each provider record with a `docs_url`, render `<a href target="_blank" rel="noopener noreferrer" title={"Open " + name + " docs"}><IconButton><ExternalLinkIcon/></IconButton></a>`. A better version would use an i18n'd `aria-label` (e.g. `oauth.openDocs` = "Open {provider} docs") instead of a bare `title`, so screen readers and non-English UIs get a translated name, and would keep the marketing-y long provider names out of tooltips by carrying a separate short `display_name` in the catalog.

## Handoffs
- `apps/desktop/src/i18n/en.ts:1673` `pendingRequests: count => \`Pending requests (${count})\`` and `:1675` `approvedUsers: count => \`Approved users (${count})\`` — the desktop app's function-style twins of the web pairing headings; belongs to `desktop-b`.
