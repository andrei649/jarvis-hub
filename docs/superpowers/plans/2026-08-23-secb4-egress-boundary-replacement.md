# SEC-B4 Egress Boundary Replacement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace split plugin/browser egress paths with transport-bound pinned plugin I/O and a truthful unavailable browser boundary.

**Architecture:** Every plugin request and stream receives a `PinnedTarget` before network I/O, using a pool keyed by literal dial address and logical TLS identity. Browser navigation starts no browser context without a future proxy; the current capability is explicitly unavailable. Address classification is global-only in public mode and loopback/RFC1918-only in LAN mode.

**Tech Stack:** Python 3.12, httpx 0.28.1, FastAPI, pytest, pytest-socket, Playwright optional operator dependency.

---

### Task 1: Write Pinned Egress Contract Regressions

**Files:**
- Modify: `tests/test_http_client_ssrf_pinning.py`
- Modify: `tests/test_http_client.py`
- Modify: `tests/test_egress_audit_b3.py`
- Modify: `tests/test_h15_1_browser_agent.py`
- Modify: `tests/test_h28_playwright_driver.py`
- Modify: `tests/test_h28_operator_reality.py`

- [ ] **Step 1: Add a recording pinned-stream test before implementation**

```python
async def test_research_stream_uses_distinct_sni_pinned_pools_after_generic_client_init():
    client = PluginHTTPClient.for_plugin("websearch")
    await initialise_generic_research_stream(client)
    first = await client.open_pinned_stream("GET", "https://first.example/a")
    second = await client.open_pinned_stream("GET", "https://second.example/b")
    assert first.dial_url.host == second.dial_url.host == "203.0.113.10"
    assert first.pool_identity != second.pool_identity
    assert first.host_header == "first.example"
    assert second.sni_hostname == "second.example"
```

- [ ] **Step 2: Add address-classification regressions before implementation**

```python
@pytest.mark.parametrize("address", ["100.64.0.1", "198.18.0.1", "192.0.2.1", "::ffff:169.254.169.254"])
async def test_public_target_rejects_non_global_addresses_without_transport(address):
    resolver.answers = [address]
    with pytest.raises(PluginSSRFError):
        await client.get("https://logical.example/path")
    assert transport.requests == []

@pytest.mark.parametrize("address", ["fe80::1", "ff02::1", "::", "169.254.169.254"])
async def test_lan_target_rejects_unsafe_special_addresses_without_transport(address):
    resolver.answers = [address]
    with pytest.raises(PluginSSRFError):
        await lan_client.get("https://lan.example/path")
    assert transport.requests == []
```

- [ ] **Step 3: Add browser-unavailable regressions before implementation**

```python
@pytest.mark.asyncio
async def test_every_navigation_scheme_refuses_without_transport_proxy(driver):
    browser = GovernedBrowser(driver=driver, policy=BrowserPolicy(["allowed.example"]))
    for url in ("https://allowed.example/", "http://allowed.example/", "data:text/html,hi"):
        result = await browser.run_step({"action": "navigate", "url": url})
        assert result["status"] == "blocked"
        assert result["reason"] == "browser_transport_unavailable"
    assert driver.calls == []
```

- [ ] **Step 4: Run only the new nodes and verify RED**

Run:

```powershell
C:\Users\andrei649\Documents\GitHub\jarvis-hub\.venv\Scripts\python.exe -m pytest tests/test_http_client_ssrf_pinning.py tests/test_h15_1_browser_agent.py -q
```

Expected: failures because `open_pinned_stream`, global-only classification, and all-scheme browser
transport refusal do not yet exist.

### Task 2: Implement One Pinned Request And Stream Boundary

**Files:**
- Modify: `agents/core/http_client.py`
- Modify: `agents/core/acquisition/research.py`
- Test: `tests/test_http_client_ssrf_pinning.py`
- Test: `tests/test_http_client.py`

- [ ] **Step 1: Define the internal transport target and pool key**

```python
@dataclass(frozen=True, slots=True)
class PinnedTarget:
    logical_url: httpx.URL
    dial_url: httpx.URL
    host_header: str
    sni_hostname: str
    pool_key: tuple[str, str, int, str]
```

`dial_url` replaces the URL hostname with the validated literal address. `pool_key` is exactly
`(scheme, literal_ip, effective_port, logical_hostname)`.

- [ ] **Step 2: Prepare targets asynchronously and fail closed**

```python
async def _prepare_target(self, method: str, url: str) -> PinnedTarget:
    self._guard(method, url)
    logical_url = httpx.URL(url)
    addresses = await asyncio.to_thread(resolve_and_validate, logical_url.host, lan=self._allows_lan())
    if not addresses:
        raise PluginSSRFError("DNS validation produced no dialable address")
    return self._pinned_target(logical_url, addresses[0])
```

The implementation must reject resolver exceptions, empty answers, and validation errors before
creating a request. It must retain the logical host in `Host` and `sni_hostname` and set
`trust_env=False` for every pinned client.

- [ ] **Step 3: Route request and stream APIs through the same target**

```python
async def open_pinned_stream(self, method: str, url: str, **kwargs) -> PinnedStream:
    target = await self._prepare_target(method, url)
    return await self._open_target_stream(method, target, **kwargs)

async def request(self, method: str, url: str, **kwargs) -> httpx.Response:
    target = await self._prepare_target(method, url)
    return await self._request_target(method, target, **kwargs)
```

`_request_target` and `_open_target_stream` always select a client by `target.pool_key`; they never
call or reuse the generic `_get_client()` network pool. Public verb helpers call `request`.

- [ ] **Step 4: Replace research private-client streaming**

```python
async def fetch(self, url: str, pinned_ip: str) -> _PinnedResearchResponse:
    stream = await self.http_client.open_pinned_stream("GET", url, expected_ip=pinned_ip,
                                                        headers={"User-Agent": "Jarvis-GovernedResearch/1"})
    return _PinnedResearchResponse(response=stream.response, context=stream.context,
                                   circuit_breaker=self.http_client.circuit_breaker)
```

The public streaming API verifies `expected_ip` is among the current validated addresses. Remove
production access to `_get_client()` and private `_guard()` from research.

- [ ] **Step 5: Run request/stream tests and verify GREEN**

Run:

```powershell
C:\Users\andrei649\Documents\GitHub\jarvis-hub\.venv\Scripts\python.exe -m pytest tests/test_http_client.py tests/test_http_client_ssrf_pinning.py tests/test_egress_audit_b3.py -q
```

Expected: all tests pass; same-IP/different-SNI request and research-stream paths use distinct
pinned pool identities.

- [ ] **Step 6: Commit the transport boundary**

```powershell
git add agents/core/http_client.py agents/core/acquisition/research.py tests/test_http_client.py tests/test_http_client_ssrf_pinning.py tests/test_egress_audit_b3.py
```

### Task 3: Make Address Classification Explicitly Safe

**Files:**
- Modify: `agents/core/security/ssrf.py`
- Test: `tests/test_ssrf.py`
- Test: `tests/test_http_client_ssrf_pinning.py`

- [ ] **Step 1: Implement public and LAN address predicates**

```python
def _is_safe_public(address: ipaddress._BaseAddress) -> bool:
    return address.is_global and not address.is_multicast and not address.is_unspecified

def _is_safe_lan(address: ipaddress._BaseAddress) -> bool:
    address = _normalise_embedded_ipv4(address)
    return address.is_loopback or (
        isinstance(address, ipaddress.IPv4Address)
        and address in ipaddress.ip_network("10.0.0.0/8")
        or address in ipaddress.ip_network("172.16.0.0/12")
        or address in ipaddress.ip_network("192.168.0.0/16")
    )
```

Correct operator precedence with explicit helper branches. Metadata, link-local, multicast,
broadcast, unspecified, carrier-grade NAT, benchmark, documentation, and mixed answer sets return
an error in every mode.

- [ ] **Step 2: Run classifier regressions and verify GREEN**

Run:

```powershell
C:\Users\andrei649\Documents\GitHub\jarvis-hub\.venv\Scripts\python.exe -m pytest tests/test_ssrf.py tests/test_http_client_ssrf_pinning.py -q
```

Expected: all hostile scripted answers fail before transport and safe RFC1918/loopback LAN answers
remain pinned and usable.

- [ ] **Step 3: Commit the classifier**

```powershell
git add agents/core/security/ssrf.py tests/test_ssrf.py tests/test_http_client_ssrf_pinning.py
```

### Task 4: Close Browser Navigation Until a Real Proxy Exists

**Files:**
- Modify: `agents/core/browser_agent.py`
- Modify: `agents/core/browser_playwright.py`
- Modify: `agents/core/observability/operator_reality.py`
- Test: `tests/test_h15_1_browser_agent.py`
- Test: `tests/test_h28_playwright_driver.py`
- Test: `tests/test_h28_operator_reality.py`

- [ ] **Step 1: Make navigation unavailable before any browser driver call**

```python
if action == "navigate":
    return {
        "action": action,
        "status": "blocked",
        "reason": "browser_transport_unavailable",
    }
```

This check applies before URL parsing, policy lookup, approval, Playwright startup, or driver method
dispatch. It applies to every scheme. `NullBrowserDriver` stays available only for explicit test
capability injection, not navigation exemption.

- [ ] **Step 2: Make Playwright driver reject direct navigation too**

```python
async def navigate(self, *, url: str, **_kwargs):
    raise BrowserTransportUnavailable("transport-bound browser proxy is required")
```

The driver must not start a browser context for navigation while no real proxy is configured.

- [ ] **Step 3: Record unavailable browser transport truthfully in operator reality**

```python
ledger.unavailable(
    "browser_transport",
    "transport-bound browser proxy is not configured; no navigation proof is available",
)
```

Do not record a passing browser transport result and do not use a test-local mapping as production
transport evidence.

- [ ] **Step 4: Run browser and reality regressions**

Run:

```powershell
C:\Users\andrei649\Documents\GitHub\jarvis-hub\.venv\Scripts\python.exe -m pytest tests/test_h15_1_browser_agent.py tests/test_h28_playwright_driver.py tests/test_h28_operator_reality.py -q
```

Expected: every navigation scheme produces `browser_transport_unavailable`, zero Playwright starts,
and operator reality records unavailable rather than a false pass or failure.

- [ ] **Step 5: Commit the fail-closed browser boundary**

```powershell
git add agents/core/browser_agent.py agents/core/browser_playwright.py agents/core/observability/operator_reality.py tests/test_h15_1_browser_agent.py tests/test_h28_playwright_driver.py tests/test_h28_operator_reality.py
```

### Task 5: Run Exact-Head R3 Evidence and Independent Reviews

**Files:**
- Verify: every file changed in Tasks 2 through 4
- Review: PR body evidence receipt only

- [ ] **Step 1: Run the complete SEC-B4 regression matrix**

Run:

```powershell
C:\Users\andrei649\Documents\GitHub\jarvis-hub\.venv\Scripts\python.exe -m pytest tests/test_http_client.py tests/test_http_client_ssrf_pinning.py tests/test_plugin_egress.py tests/test_egress_audit_b3.py tests/test_egress_kernel_wave.py tests/test_ssrf.py tests/test_h15_1_browser_agent.py tests/test_h28_playwright_driver.py tests/test_h28_operator_reality.py -q
C:\Users\andrei649\Documents\GitHub\jarvis-hub\.venv\Scripts\python.exe -m ruff check agents/core/http_client.py agents/core/acquisition/research.py agents/core/security/ssrf.py agents/core/browser_agent.py agents/core/browser_playwright.py agents/core/observability/operator_reality.py
C:\Users\andrei649\Documents\GitHub\jarvis-hub\.venv\Scripts\python.exe scripts/check_ai_workflow_policy.py
git diff --check main...HEAD
```

Expected: all required tests pass except explicitly owner-opt-in live Playwright tests; Ruff, policy,
and diff checks pass.

- [ ] **Step 2: Obtain two independent reviews and a separate integrator decision**

Review checklist:

```text
Spec reviewer verifies every egress caller uses PinnedTarget and no direct generic stream remains.
Code-quality reviewer verifies pool key, redirect semantics, classifier boundaries, and browser truth.
Integrator verifies exact-head receipt, R3 role separation, and whether unavailable browser transport is acceptable release posture.
```

- [ ] **Step 3: Commit or amend nothing after evidence without rerunning it**

Expected: the evidence receipt references the final 40-character head, policy version, risk R3,
changed paths, commands/exit codes, producer/reviewer/integrator, known unavailable browser transport,
and `lease=none`.
