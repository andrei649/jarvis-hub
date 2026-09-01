/* TRUST OPS — three shipped trust/credential routes that had no client at all:

     · POST /api/security/spotlight        (user tier)  security.py:65
     · POST /api/secrets/broker/redact     (admin)      secrets.py:65
     · POST /api/admin/rotate-tokens       (admin)      admin.py:138

   Handlers read in full. What each one really does, and what this panel is therefore
   forbidden to imply:

   1. SPOTLIGHT IS NOT A SECOND OPINION. `spotlight(text, source)` (quarantine.py:70)
      calls the SAME `detect_injection()` over the SAME `_INJECTION_PATTERNS` list as
      the already-shipped INJECTION SCAN card (gap.tsx:633 → /api/security/scan-injection).
      The verdict half is byte-identical output from a byte-identical engine. What this
      route adds — and the only reason it is worth a surface — is `marked`: the
      delimiter-wrapped, DATAMARKED block a model would actually receive, plus the
      `source` label baked into it. The panel says so, so a matching verdict here can
      never be read as corroboration.

   2. AN EMPTY `injection_flags` IS NOT "CLEAN". It means only that none of the
      detector's built-in regexes matched. The shipped card renders "✓ clean — no
      injection patterns" in green; that wording is exactly what is not copied here.
      No route exposes `_INJECTION_PATTERNS`, so the panel also does not print how many
      patterns were tried — a hardcoded count would be frontend-invented backend state
      that silently rots the next time the list changes.

   3. `injection_flags` ARE RAW REGEX SOURCES, not phrases: `detect_injection` appends
      `pat.pattern` (quarantine.py:59). They are rendered verbatim in mono. Paraphrasing
      "you are now\b" into "impersonation attempt" would be the panel inventing a
      finding the backend never made.

   4. `marked` TRANSFORMS THE TEXT. `datamark` is `re.sub(r"\s+", "▁", text.strip())`,
      so every whitespace run — including newlines — becomes ▁. The block on screen is
      deliberately not the operator's input and is captioned as such.

   5. SPOTLIGHT CANNOT BE "UNAVAILABLE". It is a pure offline function: no orchestrator
      component, no LLM, no `require_component`, no 503 path. Its only handler refusal is
      400 {"error":"text required"}. So this panel never renders a component-unavailable
      state for it — that would be a condition the backend cannot produce.

   6. `source` DEFAULTS ONLY WHEN THE KEY IS ABSENT: `(body or {}).get("source",
      "untrusted")`. Sending `source: ""` is passed through and produces the literal
      wrapper `<<UNTRUSTED source=>>`. The key is therefore OMITTED when the input is
      blank, and the label shown afterwards is read back off the RESPONSE.

   7. REDACT IS EXACT-FULL-VALUE `str.replace` AND NOTHING MORE (secret_broker.py:113).
      No partial match, no entropy, no prefix, no pattern. So an unchanged result means
      "no stored secret VALUE appeared as an exact literal substring" — never "clean",
      never "safe to share". Worse, `_safe_get` SWALLOWS `SecretStoreError` (a wrong key
      or corrupted entry), logs a warning and returns None, so that secret is silently
      skipped and the 200 is indistinguishable from a full pass. The panel states this
      instead of implying coverage it cannot verify.

   8. THE REDACT RESPONSE IS ONE KEY: {"redacted": <str>}. No count, no list of which
      names matched, no flag. Anything more on screen would be invented.

   9. `{"names": []}` FROM GET /api/secrets/broker DOES NOT MEAN "no broker".
      `secret_broker_list` (secrets.py:47) answers `{"names": []}` both when
      `orch.secret_broker` is absent AND when it holds nothing — it has no 503 path at
      all. Only a 503 from a POST that is `require_component`-guarded proves absence,
      which is why the probe below exists: `POST {"text": ""}` runs the same guard,
      touches no state (redact("") compares every stored value against an empty string
      and returns ""), and separates "broker missing" from "broker empty". It is
      operator-initiated, never on mount, because a real POST lands in the global
      action-failure sink (client.ts:84).

  10. ROTATION IS DESTRUCTIVE AND CAN LOCK THIS BROWSER OUT. `token_store.rotate`
      deletes every issued token of the scope, writes a PERSISTENT `revoked:<scope>` row
      that supersedes JARVIS_<SCOPE>_TOKEN across restarts, then issues one new token
      whose raw value is returned exactly once (only its SHA-256 is stored). The warning
      is rendered BEFORE the control, the control is behind a typed strong-confirm, and
      the raw token is never auto-stored, auto-copied or logged.

  11. THE HANDLER SILENTLY COERCES BOTH FIELDS: an unknown scope becomes "admin"
      (`body.scope if body.scope in SCOPES else "admin"`) and any ttl_days <= 0 or null
      becomes None. So `scope` and `ttl_days` on screen are read FROM THE RESPONSE, never
      from the form. The scope control offers only the two real SCOPES ("admin", "user")
      so the coercion cannot bite, and the response is echoed anyway.

  12. THERE IS NO READ ROUTE FOR TOKEN STATE. `list_tokens()` is CLI-only
      (`python -m agents.core.security.token_store list`), so this panel shows no
      before/after inventory and claims none.

  13. NO KERNEL PATH ON ROTATE. Unlike /api/security/capabilities/issue, this handler
      never calls `_admin_kernel_denial`, so there is no 403 "kernel denied: …" here and
      the panel does not advertise one. Its only refusals are the admin guard's 401/403
      `detail` STRING and pydantic's 422 `detail` ARRAY. A sqlite failure surfaces as a
      non-JSON 500, where `err.body` is undefined and only `err.message` is true.

  14. The signed audit-action WRITE route is deliberately absent from this panel. Its path is
      spelled out only on its entry in tests/test_hud_v2_parity.py, never here: the parity
      matcher counts any literal occurrence in a client file as a caller, so naming it would
      fake a caller and let an unwired route leave the punch list. A HUD form that lets a
      human hand-type provenance into a tamper-evident intent log is worse than no control
      at all (BACKLOG.md:1383-1386).

   apiPost THROWS on 4xx/5xx and carries the parsed body on `err.body`, so every send
   below passes onErr and clears its success block first — otherwise the refusal branch
   would be dead code and a refused rotation could sit under a success line. */
import React, { useState } from 'react';
import { useApi, arr, mono, asLive, Card, State, Row, Tag, act, actA, inpS, taS, Json } from '../panel-kit';

const SPOTLIGHT_PATH = '/api/security/spotlight';
const BROKER_PATH = '/api/secrets/broker';
const REDACT_PATH = '/api/secrets/broker/redact';
const ROTATE_PATH = '/api/admin/rotate-tokens';

/* token_store.SCOPES — the only two values `rotate` accepts; anything else is silently
   rewritten to "admin" by the handler, so the control never offers a third. */
const SCOPES = ['admin', 'user'];

const HDR = { ...mono, fontSize: 10, letterSpacing: '.08em', color: 'var(--ink-3)', margin: '10px 0 4px' };
const NOTE = { ...mono, fontSize: 10, color: 'var(--ink-3)', marginTop: 4 };
const WARN = { ...mono, fontSize: 10, color: 'var(--amber)', marginTop: 4 };

/* The refusal, straight from the wire — nothing mapped, merged or renamed.
   `error`  STRING → the router spoke  ("text required", "secret broker not available")
   `detail` STRING → a guard spoke     ("admin token required", "admin disabled from network — …")
   `detail` ARRAY  → pydantic spoke    (422 field errors)
   neither         → non-JSON body (e.g. an unhandled 500): only the status and the
                     client's own message are known, and only those are shown. */
function Refusal({ err, path }: { err: any; path: string }) {
  const body = (err && err.body) || null;
  const routerErr = body && typeof body.error === 'string' ? body.error : null;
  const detail = body ? body.detail : null;
  const detailStr = typeof detail === 'string' ? detail : null;
  const detailList = Array.isArray(detail) ? detail : null;
  const quoted = routerErr != null || detailStr != null || detailList != null;
  return (
    <div role="alert" style={{ marginTop: 8, padding: 6, border: '1px solid var(--red)', borderRadius: 4 }}>
      <div style={{ ...mono, fontSize: 11, color: 'var(--red)' }}>
        refused · HTTP {(err && err.status) || 'error'} · POST {path}
      </div>
      {routerErr != null && <div style={{ ...mono, fontSize: 11, color: 'var(--ink-2)', marginTop: 4 }}>{routerErr}</div>}
      {detailStr != null && <div style={{ ...mono, fontSize: 11, color: 'var(--ink-2)', marginTop: 4 }}>{detailStr}</div>}
      {detailList != null && <Json v={detailList} max={140} />}
      {!quoted && (
        <>
          <div style={{ ...mono, fontSize: 11, color: 'var(--ink-2)', marginTop: 4 }}>
            {String((err && err.message) || 'request failed')}
          </div>
          <div style={NOTE}>the response carried no readable error/detail body — the status above is all that is known.</div>
          {body != null && <Json v={body} max={140} />}
        </>
      )}
    </div>
  );
}

export function TrustOpsPanel() {
  /* ── 1 · spotlight (user tier) ─────────────────────────────────────────── */
  const [spotText, setSpotText] = useState('');
  const [spotSource, setSpotSource] = useState('');
  const [spot, setSpot] = useState<any>(null);
  const [spotErr, setSpotErr] = useState<any>(null);
  const [spotBusy, setSpotBusy] = useState(false);

  const runSpotlight = () => {
    if (!spotText.trim() || spotBusy) return;
    setSpotBusy(true);
    setSpot(null);
    setSpotErr(null);
    const src = spotSource.trim();
    // the key is omitted when blank: sending source:"" would render `<<UNTRUSTED source=>>`
    // rather than letting the backend's own "untrusted" default apply.
    act(
      SPOTLIGHT_PATH,
      { text: spotText, ...(src ? { source: src } : {}) },
      (r) => { setSpot(r); setSpotBusy(false); },
      (e) => { setSpotErr(e); setSpotBusy(false); },
    );
  };

  const flags = spot ? arr(spot, 'injection_flags') : [];

  /* ── 2 · secret redact (admin) ─────────────────────────────────────────── */
  const broker = useApi(BROKER_PATH, true, true);
  const names = arr(broker.d, 'names');
  const [redText, setRedText] = useState('');
  const [red, setRed] = useState<any>(null);   // { probe, sent, out, raw }
  const [redErr, setRedErr] = useState<any>(null);
  const [redBusy, setRedBusy] = useState(false);

  const sendRedact = (probe: boolean) => {
    if (redBusy) return;
    const sent = probe ? '' : redText;
    if (!probe && !sent) return;
    setRedBusy(true);
    setRed(null);
    setRedErr(null);
    actA(
      REDACT_PATH,
      { text: sent },
      (r) => {
        const out = r && typeof r.redacted === 'string' ? r.redacted : null;
        setRed({ probe, sent, out, raw: r });
        setRedBusy(false);
      },
      (e) => { setRedErr(e); setRedBusy(false); },   // clears `red` above → a 503 can never sit under a result
    );
  };

  /* ── 3 · token rotation (admin, destructive) ───────────────────────────── */
  const [scope, setScope] = useState('admin');
  const [ttl, setTtl] = useState('');
  const [confirm, setConfirm] = useState('');
  const [rot, setRot] = useState<any>(null);
  const [rotErr, setRotErr] = useState<any>(null);
  const [rotBusy, setRotBusy] = useState(false);
  const [reveal, setReveal] = useState(false);
  const [stored, setStored] = useState('');

  const ttlRaw = ttl.trim();
  const ttlNum = ttlRaw === '' ? null : Number(ttlRaw);
  const ttlBad = ttlNum != null && !Number.isFinite(ttlNum);
  const rotateReady = confirm === scope && !ttlBad && !rotBusy;

  const rotate = () => {
    if (!rotateReady) return;
    setRotBusy(true);
    setRot(null);
    setRotErr(null);
    setReveal(false);
    setStored('');
    actA(
      ROTATE_PATH,
      { scope, ...(ttlNum != null && Number.isFinite(ttlNum) ? { ttl_days: ttlNum } : {}) },
      (r) => { setRot(r); setConfirm(''); setRotBusy(false); },
      (e) => { setRotErr(e); setRotBusy(false); },
    );
  };

  const storeToken = () => {
    if (!rot || typeof rot.token !== 'string') return;
    const key = rot.scope === 'user' ? 'hud.user_token' : 'hud.admin_token';
    try {
      localStorage.setItem(key, rot.token);
      setStored('stored in ' + key + ' — this browser only');
    } catch (e: any) {
      setStored('could not write localStorage: ' + String((e && e.message) || e));
    }
  };

  const anyLive = !!(spot || red || rot || broker.d);

  return (
    <Card title="TRUST OPS" live={asLive(anyLive)} sub={rot ? 'rotated · ' + String(rot.scope) : null}>
      <div style={{ ...mono, fontSize: 10, color: 'var(--ink-3)' }}>
        Three credential/trust routes that ship in the backend and had no caller: datamark
        untrusted content, scrub known secret values out of text, rotate an issued token scope.
      </div>

      {/* ─────────────── 1 · SPOTLIGHT ─────────────── */}
      <div style={HDR}>SPOTLIGHT · UNTRUSTED CONTENT (user tier)</div>
      <textarea
        style={taS}
        aria-label="untrusted text to spotlight"
        value={spotText}
        placeholder="paste the untrusted bytes — tool output, an email body, scraped web text…"
        onChange={(e) => setSpotText(e.target.value)}
      />
      <Row>
        <span style={{ ...mono, color: 'var(--ink-3)' }}>source</span>
        <input
          style={{ ...inpS, flex: 1 }}
          aria-label="source label"
          value={spotSource}
          placeholder="blank → the backend's own default: untrusted"
          onChange={(e) => setSpotSource(e.target.value)}
        />
        <button className="tool-btn" disabled={!spotText.trim() || spotBusy} onClick={runSpotlight}>SPOTLIGHT</button>
      </Row>
      <State e={null} loading={spotBusy} n={null} />
      {spotErr != null && <Refusal err={spotErr} path={SPOTLIGHT_PATH} />}
      {spot != null && (
        <div style={{ marginTop: 6 }}>
          <Row>
            {flags.length === 0
              ? <Tag c="var(--ink-3)">no pattern matched</Tag>
              : <Tag c="var(--red)">{flags.length} pattern(s) matched</Tag>}
            <span style={{ ...mono, color: 'var(--ink-2)' }}>suspicious: {String(spot.suspicious)}</span>
            <span style={{ ...mono, color: 'var(--ink-2)' }}>source: {String(spot.source)}</span>
          </Row>
          {flags.map((f, i) => (
            <Row key={i}>
              <span style={{ ...mono, color: 'var(--red)', wordBreak: 'break-all' }}>{String(f)}</span>
            </Row>
          ))}
          {flags.length === 0 && (
            <div style={NOTE}>
              no pattern matched — that means only that none of the detector's built-in regexes fired.
              It is not a verdict of safe, clean or injection-free, and no route exposes the pattern
              list, so this panel cannot tell you how many were tried.
            </div>
          )}
          <div style={{ ...mono, fontSize: 10, color: 'var(--ink-3)', marginTop: 8 }}>
            datamarked block — what a model receives. Every whitespace run (newlines included) is
            replaced by ▁, so this is a transform of your input, not your input.
          </div>
          <Json v={typeof spot.marked === 'string' ? spot.marked : spot} max={180} />
        </div>
      )}
      <div style={NOTE}>
        The flag verdict comes from the SAME H17.1 detect_injection() as the shipped INJECTION SCAN
        card — not a second opinion, not corroboration. What this route adds is the datamarked
        wrapper and the source label.
      </div>

      {/* ─────────────── 2 · SECRET REDACT ─────────────── */}
      <div style={HDR}>SECRET REDACT · admin</div>
      <State e={broker.e} loading={broker.loading} n={null} />
      {broker.e != null ? (
        <div style={WARN}>
          denominator unavailable — the name list could not be read ({String(broker.e)}). This panel
          does not know how many stored names a redaction would be compared against.
        </div>
      ) : broker.d != null ? (
        <div style={{ ...mono, fontSize: 10, color: names.length === 0 ? 'var(--amber)' : 'var(--ink-3)', marginTop: 4 }}>
          {names.length === 0
            ? 'GET /api/secrets/broker answered {"names": []} — nothing to compare against. That same answer is returned whether the broker is EMPTY or ABSENT (the GET has no 503 path), so it does not tell you which. Use the probe below.'
            : 'compared against ' + names.length + ' stored name(s): ' + names.map((n) => String((n && n.name) || n)).join(', ')}
        </div>
      ) : null}
      <textarea
        style={taS}
        aria-label="text to redact"
        value={redText}
        placeholder="paste a log line, trace or context blob to scrub"
        onChange={(e) => setRedText(e.target.value)}
      />
      <Row>
        <button className="tool-btn" disabled={!redText || redBusy} onClick={() => sendRedact(false)}>REDACT</button>
        <button className="tool-btn" disabled={redBusy} onClick={() => sendRedact(true)}>probe broker</button>
        <span style={{ ...mono, fontSize: 10, color: 'var(--ink-3)' }}>
          probe = POST {'{"text": ""}'} · changes nothing · 200 proves orch.secret_broker exists, 503 proves it does not
        </span>
      </Row>
      <State e={null} loading={redBusy} n={null} />
      {redErr != null && <Refusal err={redErr} path={REDACT_PATH} />}
      {red != null && red.out == null && (
        <div style={WARN}>
          the 200 response carried no `redacted` string — nothing is asserted about your text.
          <Json v={red.raw} max={120} />
        </div>
      )}
      {red != null && red.out != null && red.probe && (
        <div style={{ ...mono, fontSize: 11, color: 'var(--green)', marginTop: 6 }}>
          200 · the broker component is present (the empty probe passed require_component).
          This says nothing about how many secrets it holds.
        </div>
      )}
      {red != null && red.out != null && !red.probe && (
        <div style={{ marginTop: 6 }}>
          <Json v={red.out} max={160} />
          <div style={{ ...mono, fontSize: 11, marginTop: 4, color: red.out === red.sent ? 'var(--ink-3)' : 'var(--green)' }}>
            {red.out === red.sent
              ? 'unchanged — no stored secret value appeared as an exact literal substring of the text that was sent.'
              : 'changed — [REDACTED:<name>] marker(s) were substituted in.'}
          </div>
        </div>
      )}
      <div style={NOTE}>
        Exact full-value substring replacement only — no partial, prefix, entropy or pattern
        matching. And a secret whose value fails to decrypt is skipped SILENTLY by the broker
        (SecretStoreError → _safe_get returns None), so an unchanged 200 and a 200 that skipped
        half the store look identical from here. Unchanged never means safe to share.
      </div>

      {/* ─────────────── 3 · TOKEN ROTATION ─────────────── */}
      <div style={HDR}>TOKEN ROTATION · admin · DESTRUCTIVE</div>
      <div style={{ ...mono, fontSize: 10, color: 'var(--amber)', border: '1px solid var(--amber)', borderRadius: 4, padding: 6, marginTop: 4 }}>
        Rotating a scope DELETES every issued token of that scope and writes a persistent
        revoked:&lt;scope&gt; flag that supersedes JARVIS_ADMIN_TOKEN / JARVIS_USER_TOKEN across
        restarts. The token this browser is using (hud.admin_token / hud.user_token) stops working
        immediately — the next call of that tier will 401 unless you store the new one. There is no
        read route for token state (list_tokens is CLI-only), so this panel cannot show you a
        before/after inventory. Lockout recovery is offline, on the box:
        {' '}<span style={{ color: 'var(--ink-2)' }}>python -m agents.core.security.token_store rotate &lt;scope&gt;</span>.
        This is not reversible and the old token does not come back.
      </div>
      <Row>
        <span style={{ ...mono, color: 'var(--ink-3)' }}>scope</span>
        <select aria-label="rotation scope" style={{ ...inpS }} value={scope} onChange={(e) => { setScope(e.target.value); setConfirm(''); }}>
          {SCOPES.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        <input
          style={{ ...inpS, width: 150 }}
          aria-label="ttl days"
          value={ttl}
          placeholder="ttl days — blank = no expiry"
          onChange={(e) => setTtl(e.target.value)}
        />
      </Row>
      {ttlBad && <div style={WARN}>"{ttlRaw}" is not a number — the field is not sent. Clear it or type a positive number.</div>}
      {!ttlBad && ttlNum != null && ttlNum <= 0 && (
        <div style={WARN}>{ttlRaw} is not positive — the handler coerces any ttl_days &lt;= 0 to null (no expiry). The response below is the authority.</div>
      )}
      <Row>
        <input
          style={{ ...inpS, flex: 1 }}
          aria-label="type the scope to confirm"
          value={confirm}
          placeholder={'type "' + scope + '" to confirm'}
          onChange={(e) => setConfirm(e.target.value)}
        />
        <button
          className="tool-btn"
          aria-label="Rotate tokens for the selected scope"
          disabled={!rotateReady}
          onClick={rotate}
        >ROTATE {scope.toUpperCase()} TOKENS</button>
      </Row>
      <State e={null} loading={rotBusy} n={null} />
      {rotErr != null && <Refusal err={rotErr} path={ROTATE_PATH} />}
      {rot != null && (
        <div style={{ marginTop: 6 }}>
          <Row>
            <span style={{ ...mono, color: 'var(--ink-3)' }}>scope</span>
            <Tag c="var(--ink-2)">{String(rot.scope)}</Tag>
            <span style={{ ...mono, color: 'var(--ink-3)' }}>ttl_days</span>
            <Tag c="var(--ink-2)">{rot.ttl_days == null ? 'null · never expires' : String(rot.ttl_days)}</Tag>
          </Row>
          <div style={NOTE}>
            both read back off the response, not off the form — the handler silently rewrites an
            unknown scope to "admin" and any ttl_days &lt;= 0 to null.
          </div>
          {typeof rot.note === 'string' && (
            <div style={{ ...mono, fontSize: 11, color: 'var(--amber)', marginTop: 6 }}>{rot.note}</div>
          )}
          <Row>
            <button className="tool-btn" onClick={() => setReveal((v) => !v)}>{reveal ? 'hide token' : 'reveal token'}</button>
            <button className="tool-btn" onClick={storeToken}>store in this browser</button>
          </Row>
          <pre style={{ ...mono, fontSize: 11, userSelect: 'text', margin: '6px 0 0', padding: 8, background: 'var(--surface)', border: '1px solid var(--panel-line)', borderRadius: 4, color: 'var(--ink-2)', whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>
            {reveal ? String(rot.token) : '••••••••'}
          </pre>
          <div style={NOTE}>
            shown once — the store keeps only a SHA-256 hash. Nothing here is copied, logged or
            persisted for you; "store in this browser" writes hud.{rot.scope === 'user' ? 'user' : 'admin'}_token
            {' '}in THIS browser only, and every other client (the CLI included) still needs it pasted.
          </div>
          {stored !== '' && <div role="status" style={{ ...mono, fontSize: 10, color: 'var(--ink-3)', marginTop: 4 }}>{stored}</div>}
        </div>
      )}

      <div style={{ ...mono, fontSize: 10, color: 'var(--ink-3)', marginTop: 10 }}>
        POST {SPOTLIGHT_PATH} = user tier (X-User-Token) · GET {BROKER_PATH}, POST {REDACT_PATH} and
        POST {ROTATE_PATH} = admin tier (X-Admin-Token).
      </div>
      <div style={NOTE}>
        The signed audit-action write is deliberately not offered here: a form that lets a
        human hand-type provenance into a tamper-evident intent log is worse than no control
        at all.
      </div>
    </Card>
  );
}
