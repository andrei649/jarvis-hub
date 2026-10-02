# Nous account setup in Nerva

The account lifecycle and explicit Nous image route are implemented locally.
Signing in alone does not select a vision provider, change the main model or enable
cloud routing. No live Nous login or provider registration has been verified here.

## Connect an account

Configure `JARVIS_NOUS_CLIENT_ID` on the hub with a public OAuth client identifier
registered for this application. The source reference uses its own `hermes-cli`
registration; Nerva does not silently reuse that identity or invent a working ID.
Without this setting, login explains the missing configuration before any request.

Use an owner-authenticated hub connection, normally `JARVIS_ADMIN_TOKEN` with the
existing `NERVA_HUB_URL` settings:

```sh
python -m agents.cli.nerva auth nous login --profile default
python -m agents.cli.nerva auth nous status --profile default --json
python -m agents.cli.nerva auth nous logout --profile default
```

Login prints the Portal verification link and user code, then polls at the provider's
interval. Complete authorization in your own browser. Ctrl-C stops waiting; the
pending flow expires without changing an existing account. Status is local and
makes no network request. Logout clears that profile's local credentials and pending
flow; it does not revoke the account at the provider. Other profiles remain intact.
Profile names use 1–64 ASCII letters/digits/underscores/hyphens, starting with a letter
or digit. Access tokens, refresh tokens and private device codes remain on the hub.

## Endpoints and persistence

Default Portal: `https://portal.nousresearch.com`. Set `JARVIS_NOUS_PORTAL_URL` only
for a deliberate operator override. Credentials and pending flows are bound to the
issuing Portal and configured client ID; changing either requires a new login.
`JARVIS_NOUS_INFERENCE_BASE_URL` is a runtime endpoint override. Network-returned
inference URLs are restricted to the canonical inference/welcome hosts. Remote HTTP,
URL credentials/query/fragment and redirects are rejected; loopback development
HTTP is supported for explicit overrides.

State is encrypted with Nerva's existing SecretStore cipher in a dedicated
`security/nous-auth.sqlite3` under the configured Nerva data root. Its cipher key
material follows the existing `JARVIS_SECRET_KEY`/restricted local key-file contract.
No files under `.hermes`, shared Hermes auth stores or other profiles are imported.
Transactions serialize refresh across processes; an already rotated usable peer
token is adopted instead of redeeming a single-use refresh token twice. Explicit
terminal OAuth rejection quarantines the dead account credentials; rate limits,
edge challenges and temporary transport failures retain them for a later attempt.
JWT parsing checks usability metadata only; the provider validates signatures.

Owner routes are `GET /api/oauth/nous/status?profile=NAME` and
`POST /api/oauth/nous/login`, `/poll`, `/logout`. POST bodies accept a profile;
poll additionally requires the login_id returned by login. Responses are no-store
and never return account credentials. No public endpoint returns prepared inference
credentials or permits manual refresh-token injection.

## Select Nous for images

Set `JARVIS_ROLE_VISION_PROVIDER=nous`. `JARVIS_ROLE_VISION_PROFILE` chooses the
logged-in account, defaulting to `default`. An explicit
`JARVIS_ROLE_VISION_MODEL` pins the model on the normal inference endpoint. Without
one, composer status discovers the Portal's public vision recommendation and saves
the selection under the encrypted profile; the welcome endpoint uses
`nous/welcome`. A known free account uses only the free recommendation. Paid or
unknown entitlement tries paid then free, and an absent recommendation falls back
to `google/gemini-3.6-flash`.

The account owns its inference endpoint and bearer credential. Set
`JARVIS_NOUS_INFERENCE_BASE_URL` only as a deliberate account endpoint override.
Any `JARVIS_ROLE_VISION_BASE_URL` must exactly match the prepared endpoint;
`JARVIS_ROLE_VISION_KEY` must remain empty. A separate role key cannot silently
replace OAuth. `JARVIS_NOUS_ANTHROPIC_WIRE=chat` is the default. Setting `native`
uses Anthropic Messages only for `anthropic/*` models. `auto` and invalid values
currently stay on chat/completions; the wire choice is part of the reviewed image
destination.

`GET /api/vlm/composer/status` may prepare credentials and fetch recommendation
metadata; `refresh_catalog=true` refreshes the public catalog without forcing an
OAuth token rotation. Normal credential preparation can refresh an unusable token.
Image POSTs and role/policy reads use the prepared local selection and never
refresh OAuth or discover a replacement model. A selection expires on logout,
account or configuration drift, or credential expiry. Remote image sends still
need the existing destination, training and cost confirmations. Local-only image
consumers remain local, and inherited Nous video is unavailable until its own
adapter exists.

Automatic main → OpenRouter → Nous → DeepInfra selection, credential-pool breadth,
anonymous-account lifecycle, HUD/native account controls and live provider acceptance
remain separate open work. Tests use synthetic credentials and intercepted native HTTP transports;
successful tests do not establish that an OAuth client registration is accepted
by the live provider.
