# SEC-B4 — SSRF pinning and browser rebinding risk reduction

> Status: **DESIGN ONLY**. This document defines two separate security boundaries. It does not claim that browser DNS rebinding is eliminated unless a future transport can prove socket-level pinning.

## Goal

Harden the two audit surfaces without weakening existing policy:

1. `PluginHTTPClient`: resolve, validate and **dial the validated IP** for non-local HTTP(S) egress.
2. Governed Playwright: fail closed on invalid/private resolution and on observable resolution drift, while explicitly retaining the residual resolve→Chromium-connect window because Chromium owns the socket.

No runtime code, dependency, workflow, route, authority or release-readiness change is included in this PR.

## Security invariants

- Static manifest/egress policy remains authoritative and runs before transport.
- Public HTTP(S) egress is deny-by-default when DNS validation or pinning cannot be established.
- Private/local destinations are allowed only when an existing explicit policy grants local/private access; **manifest-less or untrusted callers never gain local/private access merely to preserve historical behavior**.
- Redirects and every new network hop are re-evaluated under the same policy.
- DNS failure, empty resolution, blocked/private resolution, SNI/Host mismatch, certificate failure or transport setup failure all fail closed.
- No new path may bypass Ultron, plugin policy, browser policy or existing audit controls.

## Current state

`resolve_and_validate` already resolves a hostname and rejects blocked/private addresses. The audit gap is at the connection boundary:

- `PluginHTTPClient` performs static policy checks, but its normal HTTP transport can resolve again when connecting.
- the Playwright guard validates before navigation, while Chromium performs its own later DNS/connect.

`websearch.fetch_page` is the in-repository reference for the stronger HTTP pattern: validate the host, connect to a validated IP, preserve the original Host header and preserve TLS server-name identity.

## Boundary A — PluginHTTPClient: real IP pinning

### Proposed transport

Add a small `PinnedSSRFTransport` below `PluginHTTPClient`.

Per request/hop:

1. Preserve the original URL hostname and port.
2. Run the existing static egress/manifest policy.
3. Determine whether explicit policy allows the requested local/private destination.
4. For public egress, call `resolve_and_validate(original_host)` once at the last practical point before the dial.
5. Reject on resolution error, empty result, or any blocked/private result.
6. Rewrite the connection target to one validated IP.
7. Preserve the original HTTP `Host` value.
8. Preserve the original TLS server name/SNI for HTTPS.
9. Let normal certificate verification validate the certificate against the original server name; certificate/SNI failure is fatal.
10. Repeat the full process for every redirected hop.

### Local/private policy

Local/private access must be explicit. The implementation must derive it from a trusted existing policy/manifest decision, not from absence of a manifest and not from a permissive fallback.

Examples that may qualify only when already explicitly allowed by policy include owner-configured LAN integrations such as Home Assistant/Homebridge or another declared local endpoint. `FULL` internet access does **not** imply private/LAN access.

### Failure semantics

The transport must raise a typed refusal before network I/O when:

- resolution fails;
- resolution is empty;
- a returned address is blocked/private without explicit local policy;
- pinning cannot be constructed safely;
- Host/SNI identity cannot be preserved;
- TLS certificate verification fails.

There is no `JARVIS_STRICT_EGRESS=0` escape hatch for the pinning/SSRF boundary.

### Required deterministic tests

1. Public host resolves once and the inner transport receives the validated IP.
2. Original Host header is preserved.
3. HTTPS SNI/server-name identity is preserved and certificate failure propagates.
4. Rebinding fake (`public` on validation, `private` on hypothetical second resolution) proves there is no second resolver call in the pinned transport.
5. Private/LAN target is refused without explicit local policy.
6. Explicitly allowed LAN target remains reachable without converting that allowance into a global bypass.
7. Redirect to blocked/private destination is refused.
8. DNS error/empty set fails before any inner transport call.

## Boundary B — Playwright: fail-closed risk reduction, not socket pinning

### Important limitation

A normal Playwright/Chromium navigation does not expose a repository-controlled socket transport where this code can guarantee that the IP validated by Python is the IP Chromium dials. Therefore a double-resolution check cannot honestly be described as closing the DNS-rebinding TOCTOU window.

Until a pinned browser transport/proxy/resolver seam is demonstrated, this boundary is **risk reduction** only.

### Proposed behavior

For every initial navigation, redirect and governed subresource:

1. Apply the existing browser/domain allowlist.
2. Resolve through `resolve_and_validate` immediately before navigation/request approval.
3. Reject on DNS error, empty result or blocked/private address.
4. Resolve a second time immediately before handing the URL to Chromium.
5. Reject if the validated address set changes.
6. Only then allow Chromium to proceed.

This catches observable rebinding and keeps failure fail-closed, but a residual race remains between the final validation and Chromium's actual connect.

### Local/private browser policy

Private/local browser navigation must never be allowed because a manifest is missing or because the historical path was permissive. It requires an explicit trusted policy decision naming the local/private scope. Otherwise the browser path refuses.

### Residual risk and promotion gate

The design must continue to report the residual resolve→connect race as open. SEC-B4 may be marked **risk reduced** after deterministic tests, but may be marked **TOCTOU closed** only after one of these is proven:

- a browser transport that dials the validated IP directly while preserving origin/TLS semantics;
- a trusted local proxy/resolver seam that performs the validated dial and cannot be bypassed by Chromium;
- an equivalent browser/network mechanism with reproducible socket-level evidence.

Any proxy solution must also define DNS ownership, CONNECT handling, SNI, certificate verification, redirect behavior, proxy bypass prevention and failure semantics. A MITM/private-CA design is not assumed or silently introduced.

### Required deterministic tests

1. Public stable resolution allows navigation.
2. Public→private or changed resolution between checks refuses navigation.
3. DNS failure/empty result refuses navigation.
4. Private/local destination refuses without explicit trusted policy.
5. Explicit allowed local scope is narrowly honored and does not permit arbitrary RFC1918/loopback destinations.
6. Redirect/subresource guards retain the same refusal semantics.
7. Tests and documentation explicitly assert that the browser result is `risk_reduced`, not `socket_pinned` or `toctou_closed`.

## Rollout / rollback

Implementation must remain in separate bounded PRs because the HTTP transport and browser path have different proof and rollback boundaries:

- **SEC-B4a — PluginHTTPClient pinned transport**: runtime/security change with pinning tests.
- **SEC-B4b — Playwright rebinding risk reduction**: browser-security change with residual-risk tests.

Either implementation can be reverted independently. This design PR itself is documentation-only and can be reverted with one commit.

## Acceptance for this design

This design is acceptable when it:

- distinguishes real HTTP IP pinning from browser risk reduction;
- keeps local/private access fail-closed unless explicitly trusted;
- defines DNS, Host, SNI and certificate failure semantics;
- does not claim deterministic browser tests prove socket-level pinning;
- leaves implementation, live-host proof and any authority change to later bounded PRs.
