/* SUPPORT & VOICE — the diagnostic issue bundle (admin) and the Wyoming satellite probe.

   Two shipped, user-reachable reads that no client called:
     · GET /api/support/bundle  (admin_guard — agents/core/routers/support.py:21 →
       agents/core/support_bundle.py:build_bundle)
     · GET /api/voice/wyoming   (no guard — agents/core/routers/wyoming.py:29)

   Why this is not a fourth re-chart of panels that already exist. Three of the bundle's
   six sections overlap shipped surfaces (capabilities → CapabilityLadderPanel,
   posture.system_profile → SystemProfilePanel, posture.hardened → PosturePanel). The
   bundle's distinct operator value is the thing none of them provides: ONE attachable
   artifact a design partner can paste into a support request, plus per-section
   availability and audit-chain integrity in a single answer. So the panel renders the
   raw JSON and a copy control, and keeps the per-section rows to what the bundle adds
   (route count, egress tallies, audit event counts + chain state) or to availability.

   HONESTY CONTRACT — every clause below is a defect this panel is written to avoid.

   1. THE ADMIN GUARD'S WORDS NEVER REACH US. admin_guard (agents/web.py:_admin_guard)
      answers 401 detail "admin token required" or 403 detail "admin disabled from
      network — …", but apiGet (frontend/src/api/client.ts) throws BEFORE reading the
      error body: only `GET /api/support/bundle -> 401|403` exists client-side. So this
      panel prints useApi's own message through <State/> and never quotes those detail
      strings — printing them would be inventing a body we did not receive.

   2. `posture.product_posture` IN THE BUNDLE IS COMPUTED FROM DEFAULTS, NOT FROM THE BOX.
      support_bundle._posture() calls product_posture.snapshot() with NO argument, so
      flat={} → raw_name/name are always "off", valid is always true, and every wave-1
      flag reads {value:false, source:"default"} whatever the owner selected. (The LIVE
      one, agents/core/routers/security.py:358, passes orch._runtime_settings.) Presenting
      this as the live posture would be a lie, so the row carries a permanent
      "defaults-only" tag and points at GET /api/security/posture instead. This is stated
      as the panel's own code-verified note — the backend emits no such warning.

   3. A SECTION THAT FAILED IS NEVER A ZERO. Each of the six sections is assembled
      defensively and degrades to the literal {"error": "unavailable"}; they fail
      INDEPENDENTLY. Those render amber with the backend's own word, never 0 / empty.

   4. `egress.clean` IS `not violations`, so it is true when NOTHING WAS MEASURED. An
      empty plugins map renders grey "no egress recorded yet", and a zero external total
      renders "no external calls recorded" — never a green "clean / local-first" badge
      earned by an empty sample. Green only when a violation could have been seen.

   5. AUDIT CHAIN: `chain_ok`/`chain_broken_at` are set inside contextlib.suppress, so an
      ABSENT chain_ok means "not verified in this bundle", not "ok". And chain_ok:true
      over window 0 is a trivially-verified empty chain — the same precedent as
      AuditAnchorsPanel ("nothing to check" is not "checked").

   6. meta.version is added under suppress(Exception) and CAN BE ABSENT → "version not
      reported". Never a made-up version.

   7. WYOMING: `enabled` (the setting) and `listening` (a real loopback connect) were
      once conflated — the owner saw enabled:true with nothing listening. They are three
      separate rows here (enabled / listening / reachable) and are never merged. The
      backend's `note` is the honest headline and is rendered VERBATIM; when listening is
      true the note is "" and this panel renders NOTHING in its place.

   8. NO WYOMING TOGGLE, ON PURPOSE. Verified by grep: nothing in product code constructs
      WyomingServer (the only construction is the hermetic reality probe in
      agents/core/observability/house_reality.py), and voice.wyoming_enabled /
      voice.wyoming_port are read only by this one handler and are not registered settings
      keys — so no shipped route can turn it on. A toggle would produce enabled:true with
      nothing listening: exactly the conflation the backend comment exists to kill. The
      panel states the truth instead.

   9. The probe is 127.0.0.1-only with a 0.2s timeout, so listening:false means "nothing
      answered on loopback", not "nothing is running anywhere".

  10. The copy control never claims success it did not get: a rejected writeText renders
      the rejection, and a browser without navigator.clipboard is said to be without it.

   Both routes are GETs; there is nothing to hand-type, so the degenerate-form test does
   not bite and no POST surface exists here. */
import React, { useState } from 'react';
import { useApi, mono, asLive, Card, State, Row, Tag, Json } from '../panel-kit';

/* The single error literal every bundle section degrades to. Returned verbatim so the
   panel renders the backend's own word and never a synonym of its own. */
function sectionError(v: any): string | null {
  if (v && typeof v === 'object' && !Array.isArray(v) && typeof v.error === 'string') return v.error;
  return null;
}
type SecState = { kind: 'ok' | 'error' | 'absent'; text?: string };
function secState(v: any): SecState {
  if (v === undefined || v === null) return { kind: 'absent' };
  const err = sectionError(v);
  if (err !== null) return { kind: 'error', text: err };
  if (typeof v !== 'object') return { kind: 'absent' };
  return { kind: 'ok' };
}
const num = (v: any) => (typeof v === 'number' && Number.isFinite(v) ? String(v) : '—');
const RIGHT: React.CSSProperties = { marginLeft: 'auto', display: 'flex', gap: 5, alignItems: 'center', flexWrap: 'wrap' };
const FOOT: React.CSSProperties = { ...mono, fontSize: 9.5, color: 'var(--ink-3)', lineHeight: 1.5, marginTop: 8 };

function SupportBundleCard() {
  const { d, e, loading, reload } = useApi('/api/support/bundle', true, true);   // admin-tier read
  const [copy, setCopy] = useState<{ ok: boolean; msg: string } | null>(null);

  const posture = d && typeof d.posture === 'object' && d.posture ? d.posture : null;
  const sections: Array<[string, any]> = [
    ['posture.hardened', posture ? posture.hardened : undefined],
    ['posture.product_posture', posture ? posture.product_posture : undefined],
    ['posture.system_profile', posture ? posture.system_profile : undefined],
    ['capabilities', d ? d.capabilities : undefined],
    ['egress', d ? d.egress : undefined],
    ['audit', d ? d.audit : undefined],
  ];
  const states = sections.map(([name, v]) => [name, secState(v)] as [string, SecState]);
  const okCount = states.filter(([, s]) => s.kind === 'ok').length;

  const meta = d && typeof d.meta === 'object' && d.meta ? d.meta : null;
  const caps = d ? d.capabilities : undefined;
  const capsErr = sectionError(caps);
  const eg = d ? d.egress : undefined;
  const egErr = sectionError(eg);
  const au = d ? d.audit : undefined;
  const auErr = sectionError(au);
  const pp = posture ? posture.product_posture : undefined;
  const ppErr = sectionError(pp);

  const plugins = eg && !egErr && typeof eg.plugins === 'object' && eg.plugins ? eg.plugins : null;
  const pluginNames = plugins ? Object.keys(plugins) : [];
  const violations: string[] = eg && !egErr && Array.isArray(eg.local_only_violations) ? eg.local_only_violations : [];
  const extTotal = eg && !egErr ? eg.external_egress_total : undefined;

  const auWindow = au && !auErr && typeof au.window === 'number' ? au.window : null;
  const auCounts: Array<[string, any]> = au && !auErr && typeof au.recent_event_counts === 'object' && au.recent_event_counts
    ? Object.entries(au.recent_event_counts).sort((a: any, b: any) => Number(b[1]) - Number(a[1]))
    : [];
  const chainOk = au && !auErr ? au.chain_ok : undefined;

  const doCopy = () => {
    const text = JSON.stringify(d, null, 2);
    const cb: any = typeof navigator !== 'undefined' ? (navigator as any).clipboard : undefined;
    if (!cb || typeof cb.writeText !== 'function') {
      setCopy({ ok: false, msg: 'clipboard unavailable in this browser — select the JSON above and copy it by hand' });
      return;
    }
    Promise.resolve(cb.writeText(text)).then(
      () => setCopy({ ok: true, msg: `copied · ${text.length} chars` }),
      (err: any) => setCopy({ ok: false, msg: `copy failed · ${(err && err.message) || String(err)}` }),
    );
  };

  return (
    <Card
      title="SUPPORT BUNDLE"
      live={asLive(d, d && okCount === 6)}
      sub={d ? `${okCount}/6 sections` : null}
      onReload={reload}
    >
      {/* On 401/403 this is useApi's own message ("GET /api/support/bundle -> 403").
          The guard's `detail` never reaches the client, so it is never printed. */}
      <State e={e} loading={loading} n={d ? 1 : 0} />
      {d && (
        <>
          <Row>
            <span style={mono}>build</span>
            <span style={RIGHT}>
              {meta && typeof meta.version === 'string' && meta.version
                ? <Tag c="var(--ink-2)">v{meta.version}</Tag>
                : <Tag c="var(--ink-3)">version not reported</Tag>}
              <Tag>py {(meta && meta.python) || '—'}</Tag>
              <Tag>{(meta && meta.platform) || '—'}</Tag>
            </span>
          </Row>
          <Row>
            <span style={mono}>generated</span>
            <span style={RIGHT}>
              <Tag>{(meta && meta.generated_at) || '—'}</Tag>
              <Tag>{typeof d.routes === 'number' ? `${d.routes} routes` : 'routes —'}</Tag>
            </span>
          </Row>

          <Row>
            <span style={mono}>sections</span>
            <span style={RIGHT}>
              {states.map(([name, s]) => (
                <Tag key={name} c={s.kind === 'ok' ? 'var(--ink-2)' : 'var(--amber)'}>
                  {s.kind === 'ok' ? name : s.kind === 'error' ? `${name} · error: ${s.text}` : `${name} · absent from bundle`}
                </Tag>
              ))}
            </span>
          </Row>

          <Row>
            <span style={mono}>capabilities</span>
            <span style={RIGHT}>
              {capsErr !== null ? <Tag c="var(--amber)">error: {capsErr}</Tag> : (
                <>
                  <Tag c="var(--ink-2)">{num(caps && caps.total)} total</Tag>
                  {caps && typeof caps.by_state === 'object' && caps.by_state
                    ? Object.entries(caps.by_state).map(([k, v]: any) => <Tag key={k}>{k} {String(v)}</Tag>)
                    : null}
                  {caps && caps.harness_pending === true
                    ? <Tag c="var(--amber)">harness_pending — nothing VERIFIED/GA yet</Tag>
                    : null}
                </>
              )}
            </span>
          </Row>

          <Row>
            <span style={mono}>egress</span>
            <span style={RIGHT}>
              {egErr !== null ? <Tag c="var(--amber)">error: {egErr}</Tag> : (
                <>
                  <Tag c="var(--ink-2)">external {num(extTotal)}</Tag>
                  <Tag>model {num(eg && eg.model_egress_total)}</Tag>
                  <Tag>{pluginNames.length} plugin(s)</Tag>
                  {violations.length > 0
                    ? <Tag c="var(--red)">local-only violation: {violations.join(', ')}</Tag>
                    : pluginNames.length === 0
                      /* `clean` is `not violations` → true over an empty sample. Nothing
                         was measured, so nothing is proven. */
                      ? <Tag c="var(--ink-3)">no egress recorded yet — nothing measured</Tag>
                      : typeof extTotal === 'number' && extTotal > 0 && eg.clean === true
                        ? <Tag c="var(--green)">no local-only violations</Tag>
                        : <Tag c="var(--ink-3)">no external calls recorded — nothing to violate</Tag>}
                </>
              )}
            </span>
          </Row>

          <Row>
            <span style={mono}>audit</span>
            <span style={RIGHT}>
              {auErr !== null ? <Tag c="var(--amber)">error: {auErr}</Tag> : (
                <>
                  <Tag c="var(--ink-2)">window {auWindow === null ? '—' : auWindow} event(s)</Tag>
                  {auCounts.slice(0, 4).map(([k, v]) => <Tag key={k}>{k} {String(v)}</Tag>)}
                  {chainOk === false
                    ? <Tag c="var(--red)">chain broken @ #{au.chain_broken_at ?? '?'}</Tag>
                    : chainOk === true
                      ? (auWindow && auWindow > 0
                        ? <Tag c="var(--green)">chain verified over {auWindow} row(s)</Tag>
                        : <Tag c="var(--ink-3)">no events in window — a zero-row chain verifies trivially</Tag>)
                      : <Tag c="var(--amber)">chain not verified in this bundle</Tag>}
                </>
              )}
            </span>
          </Row>

          <Row>
            <span style={mono}>product posture (in bundle)</span>
            <span style={RIGHT}>
              {ppErr !== null ? <Tag c="var(--amber)">error: {ppErr}</Tag> : (
                <>
                  <Tag c="var(--ink-2)">{(pp && (pp.name || pp.raw_name)) || '—'}</Tag>
                  {pp && pp.label ? <Tag>{pp.label}</Tag> : null}
                  <Tag c="var(--amber)">defaults-only — not this box</Tag>
                </>
              )}
            </span>
          </Row>

          <Row>
            <span style={mono}>attachable artifact</span>
            <span style={RIGHT}>
              <button className="tool-btn" onClick={doCopy} aria-label="copy the bundle JSON">copy bundle JSON</button>
            </span>
          </Row>
          {copy && (
            <div style={{ ...mono, fontSize: 10, marginTop: 4, color: copy.ok ? 'var(--green)' : 'var(--red)' }}>
              {copy.msg}
            </div>
          )}
          {/* Rendered in full so it can be selected by hand even when the clipboard is
              unavailable — the artifact IS the point of this route. */}
          <Json v={d} max={260} />
        </>
      )}
      <div style={FOOT}>
        GET /api/support/bundle · admin-tier read (X-Admin-Token from <code>hud.admin_token</code>); a 401/403
        here comes from the admin guard, and the client throws before reading the guard&apos;s body, so only the
        status is shown above. Allow-list bundle: aggregates only — never raw config, secrets, message content
        or audit previews. Each section is assembled defensively, so a failed source reports
        <code> {'{"error":"unavailable"}'} </code> instead of crashing the bundle, and the six fail independently.
        The product-posture section is computed from CODE DEFAULTS — support_bundle.py calls
        product_posture.snapshot() with no runtime settings — so it can read <code>off</code> on a box whose
        product.posture is set; the live one is GET /api/security/posture.
      </div>
    </Card>
  );
}

function WyomingCard() {
  const { d, e, loading, reload } = useApi('/api/voice/wyoming');   // open read: the route declares no guard
  const flag = (v: any, onTrue: string, onFalse: string, falseColor: string) => (
    <Tag c={v === true ? 'var(--green)' : falseColor}>{v === true ? onTrue : onFalse}</Tag>
  );
  return (
    <Card
      title="WYOMING VOICE SATELLITE"
      live={asLive(d, d && d.reachable === true)}
      sub={d ? `port ${num(d.port)} · v${d.version || '—'}` : null}
      onReload={reload}
    >
      <State e={e} loading={loading} n={d ? 1 : 0} />
      {d && (
        <>
          {/* Three separate truths. They are never merged: `enabled` is a setting,
              `listening` is a measurement, `reachable` is both. */}
          <Row>
            <span style={mono}>enabled (setting voice.wyoming_enabled)</span>
            <span style={RIGHT}>{flag(d.enabled, 'true', 'false', 'var(--ink-3)')}</span>
          </Row>
          <Row>
            <span style={mono}>listening (measured · loopback connect)</span>
            <span style={RIGHT}>{flag(d.listening, 'true', 'false', 'var(--amber)')}</span>
          </Row>
          <Row>
            <span style={mono}>reachable (enabled AND listening)</span>
            <span style={RIGHT}>{flag(d.reachable, 'true', 'false', 'var(--red)')}</span>
          </Row>
          <Row>
            <span style={mono}>protocol</span>
            <span style={RIGHT}>
              <Tag>{d.protocol || '—'}</Tag>
              <Tag>v{d.version || '—'}</Tag>
              <Tag>role {d.role || '—'}</Tag>
              <Tag>port {num(d.port)}</Tag>
            </span>
          </Row>
          {/* The backend's own headline, verbatim. When listening is true it is "" and
              nothing is rendered here — no invented "all good". */}
          {typeof d.note === 'string' && d.note
            ? <div style={{ ...mono, fontSize: 10.5, color: 'var(--amber)', marginTop: 6, lineHeight: 1.5 }}>{d.note}</div>
            : null}
        </>
      )}
      <div style={FOOT}>
        GET /api/voice/wyoming · open read (the router is included with no guard). No enable/start control here
        on purpose: nothing in the product constructs or starts WyomingServer — the only construction is the
        hermetic reality probe — and <code>voice.wyoming_enabled</code> is not a registered settings key, so no
        shipped route can turn it on; a toggle would just re-create the enabled-true/nothing-listening
        conflation. The probe connects to 127.0.0.1:&lt;port&gt; with a 0.2s timeout, so a listener bound to
        another interface would also read listening:false.
      </div>
    </Card>
  );
}

export function SupportVoicePanel() {
  return (
    <>
      <SupportBundleCard />
      <WyomingCard />
    </>
  );
}
