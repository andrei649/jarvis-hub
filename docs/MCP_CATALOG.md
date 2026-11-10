# MCP servers: the catalog, installing, and signing in

Nerva can talk to MCP servers (tools other programs and services offer). Since G9 (2026-11-10)
you can pick one from a reviewed catalog instead of typing its details, install it after reading
exactly what will run, and sign in to a remote server that uses OAuth. Rows: H549 (catalog,
install, deep link), H550 (OAuth sign-in), H692 (sign-in when the browser and the hub are on
different machines).

## Where

- **HUD:** Console → Interop → **MCP Servers** (`/v2/console/mcp`). Your servers, each with its
  transport, how it signs in, which of its secrets are set (names only), connect, disconnect,
  remove, sign in and sign out; below, the catalog with a search.
- **CLI:** `nerva mcp catalog [--search Q]`, `nerva mcp install <name> [--as NAME] [--input K=V]
  [--yes]`, `nerva mcp login <server> [--port N] [--no-browser]`. All need the admin token.
- **Routes (admin):** `GET /api/admin/mcp/catalog?q=`, `POST /api/admin/mcp/catalog/preview`,
  `POST /api/admin/mcp/catalog/install`, `GET|DELETE /api/admin/mcp/{name}/oauth`,
  `POST /api/admin/mcp/{name}/oauth/start`, `POST /api/admin/mcp/{name}/oauth/callback` (relay).
  The browser returns to `GET /api/oauth/mcp/callback` (no token on a redirect; see below).

## The catalog

66 manifests from Hermes Agent's `optional-mcps/` (pin `9c0560f8`), vendored byte-identical as
data under `agents/vendor/hermes/optional-mcps/` with a `MANIFEST.json` row each
(`scripts/hermes_vendor.py mcp-catalog`, see `docs/hermes/ADOPT_LANE.md` → slice 5). Nerva
re-reads each file against its row every time the catalog is listed: a file whose bytes differ
is listed as `tampered` and cannot be installed. Each entry also shows `future_manifest` (a newer
manifest version), `invalid` or `unsupported` (a bootstrap step such as `git clone` + commands,
which Nerva does not run) with the reason. At this pin all 66 are remote HTTP servers: 56 use
OAuth (n8n also asks for your instance's URL at install), 10 need no account.

## Installing

1. **Preview.** The hub builds the plan: what will run (`spawn on this hub: <command line>` for a
   local server, `connect over HTTPS to <url>` for a remote one), the environment it gets, the
   names of the secrets it needs, the trust tier (`read-only`: only tools the server marks
   read-only can be called; change it later), the tool filter the manifest suggests, and the
   vendor's notes. The plan has a digest.
2. **Confirm.** The HUD's Install button stays off until you tick "I have read what will run";
   the CLI asks `Install it? [y/N]` (`--yes` is that answer for a script you read). The install
   request carries the plan's digest: if anything that would run differs from what you saw, the
   hub answers `plan_changed` with the new plan and installs nothing.
3. **Secrets.** Typed once (password field; the CLI reads them without echo), stored encrypted in
   the hub's secret store as `mcp.secret.<server>.<NAME>`, given only to that server (its spawn
   environment, or a header template such as `Bearer ${MCP_X_API_KEY}`), never written to the
   server config, never shown again, and deleted when you remove the server. The secret broker
   treats these names as internal: no `{{secret:…}}` handle reaches them.
4. **Nothing starts.** An installed server connects (a local one is spawned) only when you press
   connect. A remote server needs `JARVIS_MCP_HTTP_CLIENT=1` on the hub, as before.

An install goes through the same path as adding a server by hand: refused in safe mode, for a
name the load set holds, when an administrator pinned `mcp.servers` (managed configuration, 409
`managed`, audited), under the emergency stop, and for a name already in use (never overwritten:
install under another name). Every install writes an `mcp.install` row to the intent log (command
or URL, environment names, secret names, digest; never a value). Writes must come from Nerva's own
page (a cross-site request is refused, a non-JSON body is 415), because the admin guard trusts
loopback on a default install.

## Install links

`/v2/console/mcp?install=<catalog name>` opens the install card for a catalog entry.
`/v2/console/mcp?link=<name>&config=<base64 JSON>` opens it for a vendor's server that is not in
the catalog (`{"command": …, "args": […], "env": {…}}` or `{"url": …}`, at most 32 KB). A link is
inert: it only fills the card you then read and confirm. A link's environment **values are
dropped**: each name becomes a secret you type, so a link cannot plant a value; names that steer
an interpreter (`PATH`, `NODE_OPTIONS`, `LD_PRELOAD`, `PYTHONPATH` …) and any `headers` are
refused. The card says the server is not from the reviewed catalog.

## Signing in (OAuth)

For a remote server that requires it (`auth: oauth`), press **sign in** (or `nerva mcp login`).

- **Discovery.** The server's protected-resource metadata (RFC 9728) names its authorization
  server; the metadata's `resource` must be the server's own origin. The authorization server's
  metadata (RFC 8414 or OpenID) must name itself as issuer. Endpoints must be https (http only to
  a loopback or private address literal). A server that lists PKCE methods must offer S256.
- **Who Nerva is.** Dynamic client registration (RFC 7591) when the server offers it, as a public
  client, remembered per redirect address; otherwise a client the manifest pins, or one you set
  when you add the server (`oauth: {client_id, scope, client_secret}`; the secret goes to the
  secret store).
- **The flow.** Authorization code with PKCE (S256), a random state and the server URL as the
  RFC 8707 resource. At most 8 sign-ins wait at once, each for 5 minutes.
- **Tokens.** In the secret store (`mcp.oauth.<server>.*`), never in settings or the config. The
  access token is sent only to the server's own origin (a mismatch refuses the connect,
  `token_origin_mismatch`), refreshed a minute before it expires, and refreshed once when the
  server answers 401 mid-session (other calls refused with the same token wait for that refresh
  and reuse it; the refused call is retried once, safe because a 401 means nothing ran). A failed
  refresh (`invalid_grant`) asks you to sign in again. **Sign out** and **remove** revoke the
  tokens at the server (RFC 7009, best effort) and delete them.
- **Audit.** Each sign-in writes `mcp.oauth.sign_in` to the intent log (server, issuer, scope,
  expiry, how it came back); sign-out writes `mcp.oauth.sign_out`. Never a token.
- **E-stop.** Engaged, it refuses starting a sign-in, redeeming a callback and refreshing.

### When the browser is not on the hub's machine (H692)

The browser has to come back somewhere after you approve. Three ways, none of which lets anyone
but you finish your sign-in:

1. **Back to the hub** (the HUD's default): the redirect is the hub's own address as your browser
   reached it, `…/api/oauth/mcp/callback`. A redirect carries no admin token, so the start also set
   an HttpOnly cookie on that path holding a random **binding**; the hub redeems the code only
   with the waiting state and that binding, compared in constant time, once. A browser without
   the cookie gets "this sign-in was not started from this browser" and the sign-in keeps waiting.
2. **A loopback relay** (`nerva mcp login`): the CLI listens once on `127.0.0.1:<port>` on your
   machine, passes `http://127.0.0.1:<port>/callback` as the redirect, and relays only `code` and
   `state` (with the binding from the start) to the hub. It closes on the first return, Ctrl-C or
   after five minutes. Only the hub exchanges the code.
3. **Paste** (HUD): when the browser cannot reach the hub's address, paste the address it ended
   on; the panel relays its code and state with the binding.

The redirect is always either the hub's own callback route or a loopback address with a port of
1024 or more and a short plain path (no query, fragment or user info). The hub never redirects
anywhere itself, so the callback is not an open redirect.

## Limits

- No probe and tool checklist right after install: connect, then narrow tools with the trust tier
  and filters.
- No `nerva://` link registered with the operating system; install links are HUD addresses.
- No Client ID Metadata Document identity, no pinned loopback ports for a first-login exact match,
  no token-endpoint user-agent override.
- The catalog's `suggest` keywords and hosts are listed but do not drive suggestions in chat.
- The Gmail/Calendar/Spotify connectors keep their fixed loopback redirect; the relay serves MCP
  sign-in.
- Tested against a fake authorization server and a fake MCP server only; no live sign-in was made.
