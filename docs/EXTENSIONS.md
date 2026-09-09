# Declarative extension inspection

Hermes HA-4i / S1 supplies a data-only authoring contract and read-only diagnostics.
It does not install extensions, import their Python, register executable handlers,
deliver lifecycle events or establish a usable isolated runtime. All reported
`callable_tools` and `callable_commands` are empty; `execution_available` is false.
The existing acquisition pipeline remains the authority for signed packages,
quarantine, approval, promotion and revocation. S2 mediated SDK dispatch and S3
observation delivery remain separate work.

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
These are prospective observation events; no event is emitted to an extension in
S1. Extension dependencies are exact versions, sorted before dependents; cycles
fail the batch, and missing or failed dependencies propagate to dependents.
`validate_registration` checks exact declared/registered sets for the future S2
boundary, but does not register handlers or authorize dispatch.

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
tampered and revoked records advertise no callable handlers. `signature_verified`
does not prove approval or sandbox availability: `approval_verified` remains false,
`quarantine_state` is `not_inspected`, and `reason` identifies the absent SDK or
failed integrity check. Package paths, source code, signatures, receipt content and
signing keys are not returned. The projection does not change persisted state.

The browser and mobile acquisition screens remain available for their existing
package lifecycle. A dedicated extension inspection UI is pending in
`docs/design/HUD_V2_REMAINING.md` and `mobile/PARITY.md`. No native UI injection,
install-from-Git surface or raw-shell lifecycle hook is included.
