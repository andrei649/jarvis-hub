# SEC-B4 Egress Boundary Redesign

## Freshness

| Field | Value |
| --- | --- |
| Goal | Close DNS-rebinding paths by making one transport-bound egress boundary authoritative. |
| Base SHA | `75e928114024869bae75ee77937974af9dda5db3` |
| Replaced branch | `fix/secb4-pinned-plugin-egress` at `abf2f2ffe6b458858f19034aedfb4a0757bab9a8` |
| Risk tier | R3 |
| Changed paths | Planning document only: this file. |
| Generation time | `2026-08-23T13:31:00+03:00` |
| Next action | Owner review, then tests-first replacement implementation. |
| Lease | none |

## Problem

Incremental SEC-B4 patches left multiple paths outside the intended pinning boundary:

- Research streaming invoked `PluginHTTPClient._get_client()` and bypassed the SNI-keyed pinned pool.
- Public validation admitted special non-global ranges such as carrier-grade NAT and benchmark ranges.
- `data:` browser navigation could start a real browser context and load HTTP(S) subresources outside a
  transport-bound proxy.
- Operator reality described a hermetic mapping as a passing browser transport proof.

These are architecture leaks. The correction is not another exception list.

## Decision

### One Plugin Egress Boundary

`PluginHTTPClient` becomes the only supported plugin/research HTTP transport. It exposes request and
stream operations that both require a `PinnedTarget` prepared by the same async validation flow.

`PinnedTarget` contains:

```text
logical_url     original URL used for policy and redirect semantics
dial_url        validated literal IPv4/IPv6 URL used by httpx
logical_host    original hostname for HTTP Host and TLS SNI
host_header     logical host plus explicit port when present
sni_hostname    logical host
pool_key        scheme, literal IP, port, logical SNI
```

All request, streaming, and redirect operations create or reuse a pool only by `pool_key`. Generic
`_get_client()` must not perform network I/O for an egress path. Research streaming calls the public
pinned streaming API; it may not access `_get_client()`.

Every redirect is manifest-checked, resolved, validated, and pinned independently. Cross-origin
redirects strip `Authorization`, `Cookie`, and `Proxy-Authorization`. POST-to-GET 301/302 redirects
strip the body and all entity headers.

### Address Policy

Public mode accepts only globally routable unicast addresses. It rejects private, loopback,
link-local, metadata, multicast, broadcast, unspecified, reserved, carrier-grade NAT, benchmark,
documentation, and mixed answer sets.

Explicit LAN mode accepts only loopback or RFC1918 addresses. It still rejects metadata,
link-local, multicast, broadcast, unspecified, IPv4-mapped metadata, public answers, and mixed
answer sets. `JARVIS_STRICT_EGRESS=0` can reduce a manifest warning but cannot reduce address safety.

DNS, empty-answer, parsing, and validation errors fail closed before a transport attempt.

### Browser Boundary

No real browser context or navigation is available without a future authenticated loopback CONNECT
proxy that dials validated addresses. This includes HTTP(S), `data:`, file-like, and other navigation
schemes, because any browser document can issue network subrequests.

The current release exposes a truthful unavailable/refused browser capability. It starts no
Playwright process, invokes no driver call, and produces no operator-reality success result. A future
proxy implementation must separately prove literal-IP dialing, logical Host/SNI preservation,
redirect/subresource coverage, and no bypass.

## Compatibility

- Existing callers use public `PluginHTTPClient` request or streaming APIs; direct `_get_client()`
  network use is removed from production callers.
- `trust_env=False` remains mandatory. Environment proxies are not silently trusted egress paths.
- Browser users receive an explicit unavailable/refused result rather than best-effort navigation.
- Non-network test/demo behavior is represented through an explicit NullBrowserDriver capability, not
  a browser navigation scheme exemption.

## Tests

All tests are hermetic: scripted DNS and recording transports only.

1. Request and research-stream paths with two logical HTTPS hosts sharing one IP use distinct pinned
   pools and preserve their own Host/SNI.
2. Public and LAN classifiers reject every listed unsafe range and permit only intended addresses.
3. Any second hostname resolution that changes to an unsafe answer produces no transport attempt.
4. Redirects repin each hop, limit to 20, and strip sensitive/entity headers according to method and
   origin changes.
5. Every browser navigation scheme fails unavailable/refused with zero Playwright starts or driver
   calls when no proxy is injected.
6. Operator reality records browser transport as unavailable, not as a passing real transport proof.

## Delivery

Create a replacement R3 branch from current `main`; do not amend or push the held SEC-B4 branch.
The builder, independent reviewer, and integrator are separate. The replacement is merged only after
exact-head evidence, two independent review stages, and integrator approval.
