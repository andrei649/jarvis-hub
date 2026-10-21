# Local pilot check in the existing doctor

Updated: 2026-10-13 UTC.
Goal: one read-only prerequisite report for a local model and MCP memory pilot.
Implementation base: `26877eb4ddec7a405ba93105506b67a652efc943`.
Branch: `codex/shared-memory-mcp-read-hints-20261012`; the published commit and PR
identify the review revision. This is the second increment, preserving the
[MCP descriptor correction](2026-10-12-mcp-memory-read-interop.md).

## Behavior

```bash
python scripts/nerva.py doctor --local-pilot
python scripts/nerva.py doctor --local-pilot --json
```

The existing doctor already supplies reports, hub address resolution, bounded
HTTP requests, redirect refusal and credential handling. Its ordinary install
checks include a data-root write probe, and its command-center read may probe a
selected cloud provider. The new mode reuses the infrastructure and selects only
the reads needed for this pilot:

1. `/readyz`: the configured local hub is already running.
2. `/api/models/local`: the exact configured Ollama or LM Studio model has
   positive availability and residency metadata.
3. `/api/admin/settings/llm`: the stored `cloud_fallback` value is `never`.
4. MCP `tools/list` through `/api/mcp/server/rpc`: one unambiguous memory-search
   descriptor has literal `readOnlyHint: true` and a compatible basic `q` schema.

The hub must use loopback HTTP(S), without embedded credentials, query or
fragment. Admin metadata reads use the existing admin credential; MCP discovery
prefers the existing user credential. Redirects are refused and loopback requests
bypass HTTP proxies. No raw error body, endpoint payload or credential is printed.
Unknown, missing or incompatible evidence fails closed. A missing hub skips
dependent checks; an individual metadata failure does not hide other results.
The mode cannot be combined with `--smoke`.

No service is started, model downloaded, configuration written, memory queried
or text generated. There is no new route, registry, daemon, provider adapter or
dependency. Normal authentication audit and metadata-cache bookkeeping remains.
The inventory may probe already configured local-provider addresses; only the
doctor-to-hub connection is required to be loopback.

A successful report qualifies prerequisites only. Human and JSON output state
that inference, memory reading and agent-specific routing have not been tested.
The stored fallback setting can take up to 30 seconds to reach routing and does
not override explicitly cloud-bound agents. Runtime acceptance needs a
strict-local agent and a verified provider/model trace.

## Verification

Python 3.12.14 with the existing hash-locked dependencies:

```bash
python -m pytest tests/ --timeout=90 -q --tb=short --junitxml=backend-serial.xml
python scripts/status_sync.py --verify-test-count backend --test-result backend-serial.xml --json
```

One complete serial run of the final Python implementation recorded **25,589
cases: 25,527 passed, 58 skipped, one xfail, three failures and zero errors**.
Exit code: 1. Duration: 1,227.035 seconds. All 33 pilot cases and all 14 MCP
interoperability cases passed. The test-count guard returned
`actual=expected=25589`, `in_sync`. Source fingerprints matched the saved delivery
before and after the run. Subsequent publication edits only update documentation.

The three failures have the same identities and assertion messages as the clean
base reproduction, where browser host validation could not resolve `example.com`:

- `test_browser_kernel_gate::test_an_allowlisted_navigation_reaches_the_driver_once_a_transport_exists`
- `test_h15_1_browser_agent::test_preview_classifies_each_step`
- `test_h15_1_browser_agent::test_endpoint_check_and_preview`

No introduced regression was identified. No DNS override or security bypass was
added. This is a completed run with known failures, not an entirely passing suite.
Earlier focused/full runs are separate historical evidence and are not summed.

The pilot tests use synthetic responses and the real MCP descriptor without
executing the memory tool. Separate temporary loopback HTTP fixtures passed 16
scenarios: 302/307/308 redirects from each metadata endpoint sent nothing to the
other origin; loopback bypassed lowercase/uppercase HTTP proxy settings; only the
expected GET reads and MCP `tools/list` POST occurred; fallback was never written;
both successful and failed JSON reports retained false runtime-proof flags.
Those scenarios are not added to the backend suite count.

The actual local command returned exit 1 with `hub=fail/server_not_running` and
three skipped checks. No hub or model was started to change that result.
Ruff, `git diff --check`, Hermes report freshness and generated-status checks
passed. Frontend/mobile were unchanged and not rerun; their tracked counts
(2,177/359) and prior CI provenance were preserved. Remote CI is separate from
these local results and must be checked on the published PR commit.

## System76 pilot and rollback

The selected target is the **System76 laptop**. The local model actually installed
there remains unknown until access is available. No access, persistent connection
or operation of that computer is implied by this selection.

Next: review the draft PR, then run this command on System76 against its existing
hub/provider when authorized access is available. If prerequisites pass, verify
one synthetic response through a strict-local agent and one actual MCP memory
read. External-client compatibility and cross-machine synchronization remain
unproven. No alternative pilot host is awaiting selection.

Changed paths: `scripts/doctor.py`, `agents/cli/nerva.py`,
`tests/test_doctor_local_pilot.py`, `tests/test_nerva_cli.py`, this record, the
HA-1A backlog entry and the five generated status files. No HUD/mobile surface
or OpenAPI route changes. Rollback removes only the pilot mode, CLI flag and
associated tests/docs; preserve the separate MCP descriptor correction.
