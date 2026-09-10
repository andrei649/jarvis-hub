# Declarative extensions, and how one becomes callable

S1 (HA-4i) supplies the data-only authoring contract and read-only diagnostics.
**S2 adds the part that makes a declaration real:** an owner consents to exactly
what a descriptor declares, the declared surface is proved from inside the existing
acquisition sandbox, and only then do its tools appear on the tool surface.

The rule the whole design hangs on: **the host never imports third-party code, and
never trusts a declaration it has not seen the code make from inside the sandbox.**

What S2 still does not do: deliver lifecycle events (that is S3), bind a declared
*command* to the chat registry, hand extensions a `ctx` capability object, or let an
extension override a core command or a built-in tool. The acquisition pipeline
remains the only authority for signed packages, quarantine, approval, promotion and
revocation — an extension **is** an acquired package, so there is deliberately no
second store, no second signing key and no second sandbox it could arrive through.

## The four gates

An activation crosses all four, in order, and each refuses on its own:

| gate | refuses |
|---|---|
| **enabled** | the acquisition runtime is off |
| **consent** | the owner never agreed, or agreed to a *different* declared surface |
| **signature / attestation** | unsigned, unknown package, wrong sandbox image, wrong version, source bytes that moved since signing |
| **isolated registration** | the code registers a surface that is not the one declared |

Consent and the package signature are re-read on **every dispatch**, not remembered
from activation: withdrawing consent or swapping the package underneath a live
extension refuses the next call without anyone having to deactivate it first.

## Describe and check an extension

Save a UTF-8 JSON descriptor, for example `boats.json`:

```json
{
  "manifest_version": 1,
  "api_version": 1,
  "id": "boats",
  "version": "1.0.0",
  "capabilities": ["tools", "commands", "events.observe"],
  "tools": ["summarize"],
  "commands": ["boats_summary"],
  "events": ["tool.completed"],
  "requires": {"extensions": {}, "python": {}}
}
```

```console
nerva extensions doctor boats.json --json
nerva extensions doctor base.json boats.json
```

The doctor is offline and reads only the named descriptors plus installed Python
distribution metadata. Exit 0 means the declarations and exact dependencies check
out; it does not grant trust or enable execution. Exit 1 reports malformed input,
collisions, cycles, missing dependencies or version mismatches. Dependencies are
checked in this interpreter, not in any future sandbox image. Nothing is installed.

Both version fields must be integer 1. Every field in the example is required;
unknown fields, JSON duplicate keys, executable hooks, source paths and URLs are
refused. Files are capped at 64 KiB; a batch at 128 extensions; each declaration
or dependency category at 64 entries. Names use lowercase letters, digits and
underscores, start with a letter and contain at most 64 characters. Package versions
use `major.minor.patch` with an optional bounded prerelease/build suffix. Python
requirements use exact numeric versions with optional a/b/rc/post/dev suffixes;
range expressions and direct URLs are unsupported.

`boats.summarize` is the qualified tool declaration. Commands cannot collide with
the core command registry or another descriptor in the batch. Capabilities must
exactly match non-empty declaration categories. Only `command.completed`,
`session.started`, `session.ended` and `tool.completed` may be declared as events.
Declared events are still prospective: **no event is delivered to an extension**,
in S1 or S2. That is S3. Extension dependencies are exact versions, sorted before
dependents; cycles fail the batch, and missing or failed dependencies propagate to
dependents. `validate_registration` is what S2's activation compares the isolated
registration against — validating a descriptor still registers nothing and authorizes
no dispatch, so a clean `doctor` run is not permission.

## Inspect acquired packages

```console
nerva extensions list --json
```

This calls user-guarded `GET /api/plugins/extensions` using the normal CLI hub
configuration and user/admin credentials. Missing hub composition returns 503;
disabled acquisition or an uncomposed package store gets a named status. The endpoint
accepts no local paths. Reading never calls `ensure_promotion`, installs a package,
runs a backend or creates acquisition stores. The existing public `/plugins`
response does not expose this acquisition projection.

For `extensions list`, exit 0 means inspection succeeded, including explicitly
disabled/uncomposed states. Unreadable or oversized registries, failed active-package
integrity, unknown failure states and malformed responses return exit 1. Hub/auth
failures use the normal CLI connection and authorization exit codes. JSON output
preserves a valid diagnostic report even when its inspection failed.

An acquired entrypoint is projected as a declaration from its existing manifest.
Active records undergo the package store's existing signature/integrity check;
tampered and revoked records advertise no callable handlers. A row reads
`execution_available: true` with `callable_tools` filled in **only** when that record
is signature-verified *and* currently activated in this hub's runtime; anything else
still advertises nothing. Inspection reads an already-composed runtime and never
composes one. `signature_verified`
does not prove approval or sandbox availability: `approval_verified` remains false,
`quarantine_state` is `not_inspected`, and `reason` identifies the absent SDK or
failed integrity check. Package paths, source code, signatures, receipt content and
signing keys are not returned. The projection does not change persisted state.

The browser and mobile acquisition screens remain available for their existing
package lifecycle. A dedicated extension inspection UI is pending in
`docs/design/HUD_V2_REMAINING.md` and `mobile/PARITY.md`. No native UI injection,
install-from-Git surface or raw-shell lifecycle hook is included.

## Consent: agree to a surface, not to a name

```console
nerva extensions doctor boats.json          # what does it declare, and is it well formed
nerva extensions consent boats.json         # agree to exactly that
nerva extensions activate boats.json        # prove it in the sandbox; its tools go live
nerva extensions consent boats.json --revoke
```

Consent is recorded as the **SHA-256 of the declared surface** — capabilities, tools,
commands and events — not as a boolean against the extension id. Agreeing to "the
boats extension" would be agreeing to whatever boats declares next. So an update that
declares one more command reads as `changed`, with the difference, and is refused
until the owner agrees to the new document. The extension's *version* is deliberately
not in the digest: a bugfix that declares the same surface is the same agreement, and
re-asking on every patch is how an owner learns to click through a consent screen.

Consent defaults to off and **fails closed**: a missing, unreadable, oversized,
symlinked or wrong-version consent store reports `not_granted`. There is no "unknown"
state, because a runtime cannot act on one.

`--revoke` withdraws consent *and* takes the extension's tools off the surface in the
same call, with in-flight calls cancelled. The activation is dropped even if
unregistering fails — an extension the owner took back must not stay callable because
a removal raised.

## What an extension package looks like

An extension is a signed acquired package whose `main.py` exposes two functions:

```python
def register():
    # Declaring is data. There is no `ctx`, and no arguments: this function gets
    # nothing from the host, and every effect goes back through a governed kind.
    return {"tools": ["boats.summarize"], "commands": [], "events": []}


def call(tool, payload):
    return {"summary": payload["text"][:80]}
```

`register()` runs in the sealed container and must return **exactly** the manifest's
declared sets — qualified tool names (`<id>.<tool>`), commands and events. Declaring
one surface and registering another activates nothing; that mismatch is the attack the
sandbox round trip exists to catch, and it is why activation is not a file read.

`call(tool, payload)` receives the qualified name. The sandbox checks the name against
a fresh `register()` before calling, so a tool the extension no longer declares is
refused (exit 97, reported as `tool_not_declared`) even if the host's view were stale.
Anything the extension prints is swallowed; only the result envelope is read, so an
extension cannot forge a result by printing one.

## Isolation, and what is not proven here

The container is the acquisition profile's, unchanged: `--network none`,
`--cap-drop ALL`, `--read-only`, `no-new-privileges`, pinned image by sha256 digest,
bounded memory, pids and wall time. Nothing in the extension path relaxes it, and the
package must be attested to that exact image and config hash.

Extension tools reach the tool surface with `gated=False` and
`untrusted_output=True`. `gated=False` follows the acquired-capability precedent for
the same reason — a network-less, read-only, capability-less container is a contained
computation, and the human decision is the owner's consent and activation taken once,
not an approval prompt per call. `untrusted_output=True` is the part that matters every
call: what comes back is third-party content, so the tool loop fences it as DATA and
raises the turn's taint.

**Not verified in this repository's tests:** that any of this holds against a real
pinned Docker image. The runtime tests execute the real invocation scripts with the
real interpreter against real files, so the protocol is exercised — but the isolation
itself is the acquisition profile's, tested with the acquisition profile, and live
proof on a host with Docker is the owner's.
