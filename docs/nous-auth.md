# Nous account setup in Nerva

The account lifecycle is implemented locally; Nous model inference is the next
integration dependency. Signing in does not change the selected model or enable
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
Profile names use1–64 ASCII letters/digits/underscores/hyphens, starting with a letter
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

## Remaining integration

The internal refresh-aware credentials API is ready for a native Nous consumer.
Tier-aware recommended vision models, welcome-model routing, Anthropic Messages,
automatic main → OpenRouter → Nous → DeepInfra selection, credential-pool breadth
and anonymous-account lifecycle remain unfinished. HUD/native account controls and
live provider acceptance are separate open work. Tests use synthetic credentials
and intercepted native HTTP transports; successful tests do not establish that an
OAuth client registration is accepted by the live provider.
