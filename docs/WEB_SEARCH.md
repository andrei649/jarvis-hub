# Web search and page reading (`web_search` / `web_extract`)

The model can look things up with two ToolRPC tools: `web_search` (a query → titles, URLs and
snippets) and `web_extract` (up to five URLs → the clean text of each page — HTML, plain text or
PDF — never a model-written summary). Both are ungated, both declare their output **untrusted**:
the tool loop fences every result as data and marks the turn, so an action proposed after reading
the web queues for approval instead of running. The tools need the tool loop on
(`llm.tool_loop_enabled`, default off). Rows: H310 (contract), H537 (provider ABC, cache,
rescue vs policy block), H607 (configuration, verification, troubleshooting). Code:
`agents/core/plugins/web_providers.py`, `agents/core/plugins/websearch.py`,
`agents/core/web_tools.py`.

## Configuration priority

Read **per call** from the environment (no restart): the first rule that applies decides.

1. `JARVIS_WEB_PROVIDER_TIER` — `any` (default) · `free` · `paid`. Providers outside the pin can
   never answer, not even as a rescue. An unknown value refuses every search (`invalid_tier`).
2. `JARVIS_WEB_BACKEND` — a provider name (`tavily`, `searxng`, `duckduckgo`, or one a plugin
   registered) answers alone. If it is unknown, not configured or outside the tier pin, search
   answers `available: false` with `detail` = `unknown_backend` / `backend_not_configured` /
   `tier_pinned` — it never silently falls back to another provider.
3. `auto` (unset, the default) — the first eligible provider in the auto order below.
4. Rescue (`JARVIS_WEB_RESCUE`) — when the answering provider **fails** (network error, HTTP
   error status, unreadable answer), the next eligible **configured** provider is asked **once**.
   On by default for `auto`, off by default for a named backend (naming a backend is a choice
   about who sees your queries); `0` turns it off, `1` turns it on for a named backend too. A
   **policy block** (the manifest allowlist, the SSRF guard, the Action Kernel's e-stop) is never
   rescued and comes back as `reason: policy_blocked`. **The keyless DuckDuckGo fallback is not a
   rescue target** unless you set `JARVIS_WEB_RESCUE=1` *and* the caller is the interactive
   `web_search` tool: the research handler, the tech scout and the plugin gatherer (all
   `WebSearchPlugin.search()`) never rescue onto it, so a failing configured backend cannot leak
   their query to a third party you did not choose.

Keys: `TAVILY_API_KEY` (Tavily), `SEARXNG_URL` (your SearXNG; its host is added to the
`websearch` egress allowlist at boot). Both are read by `plugin_manager` at boot, as before.

### Self-hosted SearXNG

1. In the instance's `settings.yml` enable the JSON output format, or the provider gets an
   HTTP 403 (or an HTML page) back and the tool reports `provider_failed`:
   ```yaml
   search:
     formats:
       - html
       - json
   ```
   Restart the instance. `curl 'http://HOST:8080/search?q=test&format=json'` must return JSON.
2. Set `SEARXNG_URL=http://HOST:8080` (no trailing path; the hub appends `/search`). Its host is
   registered on the `websearch` egress allowlist at boot, so no manifest edit is needed.
3. Reach it by an **IP literal in a private range or `localhost`** (`http://192.168.1.20:8080`,
   `http://127.0.0.1:8080`). Those validate in LAN mode. A DNS name — a docker service name, an
   `.internal` host — is validated as public: a name that resolves to a private address is
   refused by the SSRF guard (`policy_blocked`), and one that does not resolve at all is a
   retryable `provider_failed`.
4. `python -m agents.core.plugins.web_providers` shows whether SearXNG is configured and would
   answer; it does not dial.

## Auto-detection table

| Order | Provider | Tier | Needs | Egress identity |
|---|---|---|---|---|
| 1 | `tavily` | paid | `TAVILY_API_KEY` | `websearch` (RESTRICTED: `api.tavily.com`) |
| 2 | `searxng` | free | `SEARXNG_URL` | `websearch` (+ the SearXNG host, registered dynamically) |
| 3… | plugin-registered | its own | its own `configured()` | its own manifest (RESTRICTED or LAN only) |
| last | `duckduckgo` | free | `beautifulsoup4` (keyless) | `websearch` (`html.duckduckgo.com`) |

The keyless DuckDuckGo fallback answers the interactive tool when nothing is configured, and never
counts as "configured": the HUD's honesty badge and unattended research tasks still read the plugin
as not set up, and (see rescue above) they never reach it by rescue either.
Local research (`acquisition/research.py`) is pinned to SearXNG with no rescue, whatever the
environment says.

### Adding a provider (first-party plugins)

Subclass `SearchProvider` and call `register_search_provider(...)`. Registration is refused for
an egress identity with no `plugin_gate` manifest, for a FULL-network or no-network manifest, and
for a name already taken; the three built-ins cannot be replaced or removed. Registration is a
**trusted in-process act**: the provider sees every query routed to it and a read-only view of the
two configured values (`tavily_api_key`, `searxng_url`) — not the plugin object, so not the
`webread` client — and may dial only through the `PluginHTTPClient` of its identity, so
its hosts are that manifest's allowlist (plus `register_dynamic_domain`), and every request
crosses SSRF pinning and the kernel's `plugin.egress` hook. Wrap each call in `classified(...)`
so a gate refusal becomes `PolicyBlock` and anything else — including a name that did not
resolve — `ProviderFailure`. Third-party
extensions cannot register: their sandbox has no network. `x_search` (a single-vendor xAI
feature) is deliberately not offered.

## What `web_extract` returns

- `url` (one page) or `urls` (1–5, duplicates folded); a sixth is `bad_args`.
- Each page is cut **head + tail** at `max_chars` (default 15,000, max 20,000) around an explicit
  `[... N chars omitted ...]` marker; `truncated: true` when anything was cut, `total_chars` is
  the page's length.
- One page never exceeds 40,000 bytes of text; several pages share one byte budget so the whole
  answer stays under the 100,000 bytes `web_extract` declares (`max_result_bytes`; Hermes counts
  chars, ToolRPC counts bytes); `web_search` declares 50,000 and fits its rows to it (trailing
  rows are dropped and counted in `omitted` when wide characters would push ten rows past it), so
  only `web_extract` raises the per-result context ceiling. On a small-context model the loop may still spill the answer.
- When a page was cut, its **full text** is written to the tool-result directory
  (`<data root>/workspace/tool_results/web_extract-<hash>.txt`, same retention as spilled tool
  results) and `footer` names the file. The footer names a `file_read(...)` call (and
  `read_with` carries it) only when `file_read` can open that path from this turn; otherwise it
  says so. Reading the file back is still tainted data.
- PDFs are read with the optional `pypdf` package in a worker thread, at most 200 pages; a PDF
  larger than the 2 MB read cap is refused as `too_large`, an encrypted or broken one as
  `url_refused`. At most two parses run at once and the rest of a call's PDFs **wait their
  turn** — but only inside the call's time budget. The tool loop cuts every tool call off at
  30 s (`tool_timeout`, which would throw away every page already read), so one `web_extract` call
  keeps its own deadlines under that: past **22 s** no PDF waits for a slot or keeps parsing, and
  past **26 s** any read still running is cancelled. Pages finished by then are returned; a PDF
  that did not fit answers `parser_busy` with a `retry` hint (ask for it alone in a later call,
  or use another source) and a page that was still downloading answers `fetch_failed` with the
  same kind of hint. So five ordinary PDFs in one call all read, and five very large ones read
  the first few and answer the rest `parser_busy` — they are never silently lost. A caller with no
  deadline (the gatherer, a script) keeps the standalone bounds: up to 90 s for a slot, 30 s per
  parse. The parse limit is checked between pages, so the worker stops at the next page boundary
  after it. A single page that hangs inside `pypdf` cannot be interrupted from Python and keeps
  its thread slot until it really ends: if both slots are held that way, further PDF reads
  answer `parser_busy`. The 2 MB / 200-page caps bound the work.
- **Known limits of the PDF reader (not built):** the memory `pypdf` uses to decompress a stream
  or extract one page is not bounded by Nerva (the 2 MB cap bounds the download, not what a
  crafted compressed stream expands to, and the size check runs between pages); install a
  current `pypdf` release, which carries its own decompression limits, and note that `pypdf` is
  in no requirements file here. A hard bound would be a killable subprocess with a memory
  rlimit; it is a separate execution path and is not built.
- The page cache (15 minutes, per server) keeps each page's head and tail, so a smaller cut is
  re-cut from the page itself, and a hit names a full-text file only while it still exists.
  Refusals are never cached. Repeat searches are cached the same 15 minutes in the plugin.

Refusal reasons, per page: `url_refused` (a gate, a non-text answer, or a name that does not
resolve — do not retry; the two are deliberately answered alike, because a different answer for
a private address would let a prompt-injected caller probe which internal host names exist), `fetch_failed` (a network error, a timeout, or a transient HTTP status:
408, 425, 429, 5xx — may be retried), `http_error` + `status` (any other HTTP error status: 404,
410, 401, 403, 451 — the server's settled answer, do not retry the same URL), `parser_missing` +
`missing` (install it), `parser_busy` (the PDF reader could not take that document in this call's
time, or hung documents hold it), `too_large`, `site_blocked` (`JARVIS_WEB_BLOCKED_DOMAINS`),
`secret_in_url`, `tainted_turn`. The status is checked before the media type, so a 503 that
answers in JSON is `fetch_failed`, not an unreadable page.

## Verification command

```bash
python -m agents.core.plugins.web_providers          # human-readable
python -m agents.core.plugins.web_providers --json   # for scripts
```

Offline: reads the same environment the hub reads and prints the selector, the tier pin, the
rescue setting, which provider would answer (and which would rescue it), each provider's
configured / tier / missing-package state, whether `beautifulsoup4` and `pypdf` are installed,
and the blocked sites. It never prints a key. Exit code 0 when some provider would answer, 1 when
none would. It does not dial anything — a live query is the tool itself (`nerva tools --untrusted`
shows what the loop fenced).

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `available: false`, `detail: backend_not_configured` | `JARVIS_WEB_BACKEND` names a provider whose key/URL is unset | set the key, or unset the selector |
| `detail: unknown_backend` | typo, or the plugin that registers it is not loaded | `python -m agents.core.plugins.web_providers` lists the names |
| `detail: tier_pinned` | the named provider is outside `JARVIS_WEB_PROVIDER_TIER` | change the pin or the backend |
| `detail: invalid_tier` | the tier value is not `any`/`free`/`paid` | fix the spelling |
| `detail: no_backend`, `missing: beautifulsoup4` | nothing configured and the keyless fallback cannot parse | `pip install beautifulsoup4`, or configure a backend |
| `reason: policy_blocked` | a gate refused: the host is outside the manifest allowlist (strict egress), or the kernel e-stop is engaged | check `nerva estop status`; register the host only if you mean it |
| `error: provider_failed`, `count: 0` | the provider failed and no rescue was allowed or the rescue failed too | check the network/CA (`JARVIS_CA_BUNDLE`), or allow `JARVIS_WEB_RESCUE=1` |
| `rescued_from: tavily` | Tavily failed once and the next provider answered | look at the hub log for the failure type |
| page `parser_missing`, `missing: pypdf` | a PDF and `pypdf` is not installed | `pip install pypdf` |
| page `too_large` | a PDF over the 2 MB read cap | download it and use the local-docs reader |
| page `url_refused` on a public site | non-text media, an egress refusal, or a name that does not resolve | do not retry; the log names the class (including `the name did not resolve`) |
| page `fetch_failed` | network error, a timeout, or HTTP 408/425/429/5xx | retry later |
| page `http_error`, `status: 404` (or 410/401/403/451) | the server's settled answer for that URL | do not retry the same URL; find another source |
| page `parser_busy` | the call's 22 s budget ran out before this PDF could be parsed (several large PDFs), or two earlier PDFs are hung inside `pypdf` | ask for it alone in a later call or read another source; a hung parse clears when it ends, or restart the hub |
| `provider_failed` on SearXNG, log `http_403` or `bad_body` | the instance does not serve the JSON format | enable `json` under `search.formats` (see Self-hosted SearXNG) |
| SearXNG `policy_blocked` on a docker/LAN name | a DNS name that resolves privately is validated as public | use the private IP literal or `localhost` in `SEARXNG_URL` |
| page `site_blocked` | the host is in `JARVIS_WEB_BLOCKED_DOMAINS` | remove it if that was not intended |
| `footer` says `file_read` cannot open the file | file tools are off (`JARVIS_FILE_TOOLS`), the turn was not offered `file_read`, or the scope refuses the path | turn the file tools on; the file is still on disk at the named path |
| `tainted_turn` | the turn already read untrusted content | search first, then read the URL exactly as returned |

## Not proven here

Every behaviour above is covered by offline tests (`tests/test_h310_web_parity.py`,
`tests/test_web_tools.py`, `tests/test_websearch.py`). No keyed Tavily or SearXNG query, no real
PDF with `pypdf` installed and no plugin-registered backend has been dialled live; those legs are
the owner's (`docs/OWNER_TASKS.md` P24).
