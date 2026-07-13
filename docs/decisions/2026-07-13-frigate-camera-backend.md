# Camera backend decision: integrate Frigate

**Status:** accepted for H31
**Date:** 2026-07-13

## Decision

Jarvis integrates Frigate as the local detector and NVR. Jarvis will not implement an RTSP decoder,
recorder, video store, or object detector. The Jarvis source surface is read-only event metadata;
one private snapshot seam exists only inside the consent-bound privacy pipeline.

Optional ONVIF support is discovery and owner onboarding only. A discovered device must be mapped
to an owner-curated Frigate camera id before it can become a source. Jarvis never opens an ONVIF or
RTSP stream.

## Why

Frigate already owns the operationally difficult and security-sensitive video lifecycle: camera
protocols, reconnects, recording, retention, and detector acceleration. Rebuilding that lifecycle
would create a second NVR with weaker hardware support and a much larger privacy surface. The
integration lets Jarvis focus on governed local interpretation, retrieval, and house/monitor feeds.

## Security consequences

- The exact owner-configured origin must resolve entirely to loopback/LAN addresses on every call.
- The validated address is used as the connection target, with the original Host/SNI retained, so
  DNS rebinding cannot swap the checked address before connect.
- Redirects and non-identity content encodings are refused. Credentials are SecretBroker handles,
  injected only into the one pinned request and never forwarded to another host.
- Event and snapshot responses have independent received-byte ceilings. Missing or false
  `Content-Length` never bypasses the streaming counter.
- Polling requires an enabled source, live household consent gate, and a clear kill switch.
- The public source has no snapshot method. Raw bytes never enter tools, routes, capabilities,
  subscribers, logs, or audit.

## Rollback

Disable the Frigate source flag or revoke camera consent. This stops Jarvis polling and leaves
Frigate, camera configuration, and recordings untouched.
