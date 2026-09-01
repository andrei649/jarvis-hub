/* AUTONOMY CONTROL — the four autonomy-surface routes that ship in the backend and had
   no client at all. Handlers read in full: agents/core/routers/autonomy.py (status:158,
   observer status:172, observer run:186, suggestions:364, call:114), the queue helpers
   agents/core/autonomy/queue.py:1653/1669, the observer agents/core/autonomy/observer.py:252
   and the broker agents/core/autonomy/call_broker.py:207-287.

   What this panel deliberately does NOT do:

   1. It does not resolve decisions. `pending_decisions` is rendered read-only; accept /
      reject / defer is POST /autonomy/tasks/{id}/decision and already ships in
      DECISION INBOX (gap.tsx:2719). Duplicating it here would be a second control over
      the same route, not a new capability.
   2. It does not apply an autonomy raise. NOTHING in the backend consumes a suggestion
      row: there is no per-(agent,kind,risk_tier) raise endpoint. The nearest control,
      POST /autonomy/policy, is agent-WIDE and already lives in AGENT AUTONOMY
      (gap.tsx:2831) — wiring a row to it would widen far more than the suggested class.
      So the rows carry the backend's own `suggestion` string and no button.
   3. It does not dial anyone. POST /api/autonomy/call only builds a tier-2
      (`_RISK_TIER = 2`, kind `call.outbound`) ASK task and enqueues it; the dialing
      happens later, in CallBroker.execute, after an approval — and even then an
      unresolved provider secret leaves NullCallClient returning
      status:"deferred" / reason:"call_credential_not_configured" (call_broker.py:137-156).

   Honesty notes specific to these handlers:

   * /autonomy/status, /autonomy/observer, /autonomy/observer/run and
     /autonomy/preferences/suggestions each fail closed with 503 {"error": "not
     initialized"} when get_orch() is falsy. apiGet throws BEFORE reading the body
     (api/client.ts:108), so a failed read can only be shown as its verbatim
     `GET <path> -> <status>`; every number on this panel is rendered inside a
     `sd && ...` guard built from a NON-errored read, so a 503 can never fall through
     to a zero.
   * apiPost DOES carry the parsed refusal body (client.ts failMutation), so both writes
     pass onErr. The observer run has TWO distinct 503 bodies — "not initialized" and
     "observer not initialized" — and the call route has ten-plus distinct `reason`
     strings. They are printed verbatim, never mapped onto one friendly sentence.
   * The interrupt budget shown here is the SAME pair /autonomy/interrupts already feeds
     to DECISION INBOX; it is labelled as such. The genuinely unrendered parts of
     /autonomy/status are the per-status census and the `proposed` half of the pending
     list (queue.py:1653 — a status=blocked filter never returns those).
   * `ok: true` from /api/autonomy/call does NOT mean queued: with no orchestrator the
     route builds a throwaway CallBroker with enqueue=None (autonomy.py:123-126) and
     answers 200 {ok:true, queued:false} — a preview, nothing enqueued. The panel
     branches on `queued`, not on the status code. */
import React, { useState } from 'react';
import { useApi, arr, mono, asLive, Card, State, Row, Tag, act, actA, inpS, taS, Json } from '../panel-kit';

const STATUS_PATH = '/autonomy/status';
const OBSERVER_PATH = '/autonomy/observer';
const OBSERVER_RUN_PATH = '/autonomy/observer/run';
const SUGGESTIONS_PATH = '/autonomy/preferences/suggestions';
const CALL_PATH = '/api/autonomy/call';

/* Presentation order only — taken from the queue's own _TRANSITIONS machine
   (queue.py). A status with zero rows is ABSENT from stats() (GROUP BY status), so
   nothing here invents a 0 for a status the backend did not return; unknown keys are
   appended untouched. */
const STATUS_ORDER = ['proposed', 'blocked', 'deferred', 'approved', 'running', 'done', 'failed', 'rejected', 'quarantined'];

/* Mirrors call_broker._CREDENTIAL (call_broker.py:52-55). No route lists the providers,
   so this list can drift; on an `unknown_provider` refusal the backend's own
   `supported` array is printed instead of this one. */
const PROVIDERS = [
  { id: 'twilio', credential: 'twilio_auth_token' },
  { id: 'telnyx', credential: 'telnyx_api_key' },
];

const amber = { color: 'var(--amber)', fontSize: 11 };
const note = { color: 'var(--ink-3)', fontSize: 10.5, lineHeight: 1.5, margin: '4px 0 0' };
const head = { ...mono, fontSize: 10, letterSpacing: '.08em', color: 'var(--ink-3)', margin: '10px 0 4px' };

/* The ONLY thing a failed apiGet carries is `GET <path> -> <status>`; the guard's own
   detail string is unreachable on a GET. So the hint names the handler branch that
   produces that status, and nothing else. */
const readHint = (msg, on503) => {
  const s = String(msg || '');
  if (/-> 503$/.test(s)) return on503;
  if (/-> 401$/.test(s)) return 'admin_guard: 401 "admin token required" — set the X-Admin-Token in the HUD. Unreachable, not empty.';
  if (/-> 403$/.test(s)) return 'admin_guard: 403 — no admin credential is configured and the caller is not localhost. Unreachable, not empty.';
  return null;
};

const ORCH_503 = 'the route\'s single 503 branch: {"error": "not initialized"} — get_orch() is falsy, so the orchestrator (and with it the queue, the budget and the preference store) is not up. Unavailable, NOT zero.';

export function AutonomyControlPanel() {
  const status = useApi(STATUS_PATH, true, true);            // admin-tier read
  const obs = useApi(OBSERVER_PATH, true, true);             // admin-tier read
  const sug = useApi(SUGGESTIONS_PATH, true, true);          // admin-tier read

  /* useApi keeps the last good payload when a later reload fails, so every renderer
     below reads the ERROR-FREE projection: a 503 blanks the numbers instead of leaving
     a stale census standing next to an offline line. */
  const sd: any = status.e ? null : status.d;
  const od: any = obs.e ? null : obs.d;
  const gd: any = sug.e ? null : sug.d;

  const stats: Record<string, any> = (sd && sd.stats) || {};
  const statKeys = Object.keys(stats);
  const ordered = [
    ...STATUS_ORDER.filter((k) => statKeys.includes(k)),
    ...statKeys.filter((k) => !STATUS_ORDER.includes(k)),
  ];
  const total = ordered.reduce((n, k) => n + (Number(stats[k]) || 0), 0);
  const pending = arr(sd, 'pending_decisions');
  const remaining = sd ? sd.interrupt_budget_remaining : null;
  const perDay = sd ? sd.interrupt_budget_per_day : null;

  // ── observer run ──
  const [run, setRun] = useState<any>(null);
  const [runErr, setRunErr] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const sample = () => {
    setBusy(true); setRun(null); setRunErr(null);
    actA(OBSERVER_RUN_PATH, {},
      (r) => { setRun(r || {}); setBusy(false); status.reload(); obs.reload(); },
      (err) => { setRunErr(err); setBusy(false); });
  };
  const summary = run && run.summary;
  const runUnhealthy = arr(summary, 'unhealthy');

  // ── governed call request ──
  const [to, setTo] = useState('');
  const [provider, setProvider] = useState('twilio');
  const [reason, setReason] = useState('');
  const [agent, setAgent] = useState('');
  const [message, setMessage] = useState('');
  const [res, setRes] = useState<any>(null);
  const [callErr, setCallErr] = useState<any>(null);
  const [callBusy, setCallBusy] = useState(false);
  const canCall = to.trim() !== '' && message.trim() !== '' && !callBusy;
  const request = () => {
    setCallBusy(true); setRes(null); setCallErr(null);
    const body: any = { to: to.trim(), message, provider, reason: reason.trim() };
    if (agent.trim()) body.agent = agent.trim();
    act(CALL_PATH, body,
      (r) => { setRes(r || {}); setCallBusy(false); status.reload(); },
      (err) => { setCallErr(err); setCallBusy(false); });
  };
  const cred = (PROVIDERS.find((p) => p.id === provider) || {} as any).credential;

  const suggestions = arr(gd, 'suggestions');
  const tierColor = (n) => (n >= 3 ? 'var(--red)' : n === 2 ? 'var(--amber)' : 'var(--ink-3)');

  return (
    <Card
      title="AUTONOMY CONTROL"
      live={asLive(!!sd)}
      sub={sd ? `${total} task(s) in the queue · ${pending.length} awaiting a decision` : null}
      onReload={() => { status.reload(); obs.reload(); sug.reload(); }}
    >
      {/* ── S1 · queue census + interrupt budget ─────────────────────────── */}
      <div style={head}>QUEUE CENSUS · GET {STATUS_PATH}</div>
      <State e={status.e} loading={status.loading} n={sd ? 1 : 0} />
      {status.e && readHint(status.e, ORCH_503) && (
        <div style={amber}>{readHint(status.e, ORCH_503)}</div>
      )}
      {sd && ordered.length === 0 && (
        <div style={{ color: 'var(--ink-3)', fontSize: 11 }}>
          queue empty · stats {'{}'} — no rows in the tasks table. A true zero, not an outage.
        </div>
      )}
      {sd && ordered.length > 0 && (
        <Row>
          <span style={{ display: 'flex', gap: 5, flexWrap: 'wrap', alignItems: 'center' }}>
            {ordered.map((k) => (
              <Tag key={k} c={k === 'blocked' || k === 'proposed' ? 'var(--amber)' : k === 'failed' || k === 'quarantined' ? 'var(--red)' : 'var(--ink-3)'}>
                {k} {stats[k]}
              </Tag>
            ))}
          </span>
          <span style={{ ...mono, marginLeft: 'auto', color: 'var(--ink-2)' }}>{total} total</span>
        </Row>
      )}
      {sd && (
        <>
          <Row>
            <span style={{ ...mono, color: 'var(--ink-2)' }}>interrupt budget</span>
            <span style={{ marginLeft: 'auto' }}>
              <Tag c={remaining === 0 ? 'var(--amber)' : 'var(--ink-3)'}>
                {remaining == null ? '—' : String(remaining)} / {perDay == null ? '—' : String(perDay)} interrupts left today
              </Tag>
            </span>
          </Row>
          <div style={note}>
            Not new: this pair is the same budget GET /autonomy/interrupts already feeds to DECISION INBOX
            (that route additionally reports <code>used</code>). Shown here because it is the ceiling the call
            request below is checked against. The genuinely unrendered halves of this route are the per-status
            census above and the <code>proposed</code> rows below.
          </div>
          <div style={head}>AWAITING A DECISION · {pending.length} row(s)</div>
          {pending.length === 0 && (
            <div style={{ color: 'var(--ink-3)', fontSize: 11 }}>nothing blocked or proposed.</div>
          )}
          {pending.slice(0, 8).map((t: any, i: number) => (
            <Row key={t.id ?? i}>
              <span style={{ ...mono, color: 'var(--ink-2)' }}>#{t.id} · {t.title || t.kind || 'task'}</span>
              <span style={{ marginLeft: 'auto', display: 'flex', gap: 5, alignItems: 'center' }}>
                <Tag c={t.status === 'proposed' ? 'var(--amber)' : 'var(--ink-3)'}>{t.status}</Tag>
                {typeof t.risk_tier === 'number' && <Tag c={tierColor(t.risk_tier)}>tier {t.risk_tier}</Tag>}
                {t.agent && <Tag>{t.agent}</Tag>}
                {t.origin && <Tag>{t.origin}</Tag>}
              </span>
            </Row>
          ))}
          {pending.length > 8 && (
            <div style={note}>{pending.length - 8} more not shown (the route itself caps at 100).</div>
          )}
          <div style={note}>
            Read-only here. This list is <code>status IN ('blocked','proposed')</code> — the <code>proposed</code>{' '}
            rows never appear under a <code>status=blocked</code> filter. Resolving one is
            POST /autonomy/tasks/{'{id}'}/decision, which is DECISION INBOX's shipped control, not this panel's.
          </div>
        </>
      )}

      {/* ── S2 · proactive OS observer ────────────────────────────────────── */}
      <div style={head}>OS OBSERVER · POST {OBSERVER_RUN_PATH}</div>
      {obs.e && (
        <>
          <div style={amber}>observer state unavailable · {obs.e}</div>
          {readHint(obs.e, ORCH_503) && <div style={amber}>{readHint(obs.e, ORCH_503)}</div>}
        </>
      )}
      {od && (
        <Row>
          <span style={{ display: 'flex', gap: 5, alignItems: 'center', flexWrap: 'wrap' }}>
            {od.probes != null && <Tag>{od.probes} probe(s)</Tag>}
            {od.tracked != null && <Tag>{od.tracked} signal(s) tracked</Tag>}
            {arr(od, 'unhealthy').length > 0
              ? <Tag c="var(--amber)">{arr(od, 'unhealthy').length} unhealthy</Tag>
              : od.probes != null && <Tag c="var(--green)">all tracked signals healthy</Tag>}
          </span>
        </Row>
      )}
      {od && od.enabled === false && od.reason && (
        <div style={amber}>
          observer disabled · reason: {String(od.reason)} — orch.observer is None, so a manual run answers
          503 {'{"error": "observer not initialized"}'} too.
        </div>
      )}
      {od && od.enabled === false && !od.reason && (
        <div style={amber}>
          setting system.observer_enabled = false — that flag gates ONLY the scheduled pass
          (autonomy_coordinator.py:268-271). A manual run below still samples.
        </div>
      )}
      {od && arr(od, 'unhealthy').map((u: any, i: number) => (
        <Row key={(u && u.key) || i}>
          <span style={{ ...mono, color: 'var(--amber)' }}>{u && u.key}</span>
          <span style={{ ...mono, color: 'var(--ink-2)' }}>{u && u.detail}</span>
          {u && u.severity && <span style={{ marginLeft: 'auto' }}><Tag c="var(--amber)">{u.severity}</Tag></span>}
        </Row>
      ))}
      <Row>
        <span style={{ ...mono, color: 'var(--ink-3)' }}>sample the host now (admin)</span>
        <button className="tool-btn" style={{ marginLeft: 'auto' }} disabled={busy} onClick={sample}>
          {busy ? 'sampling…' : 'sample now'}
        </button>
      </Row>
      {busy && (
        <div style={{ color: 'var(--ink-3)', fontSize: 11 }}>
          sampling… every probe is a live TCP connect (Qdrant, Neo4j, n8n, LM Studio, Ollama) — this can take
          several seconds against a box where they are down.
        </div>
      )}
      {runErr && (
        <div style={{ color: 'var(--red)', fontSize: 11 }}>
          run refused · HTTP {String(runErr.status ?? '?')}
          {runErr.body && runErr.body.error != null
            ? <> · {String(runErr.body.error)}</>
            : <> · {String(runErr.message || 'refused')}</>}
          {!runErr.body && <div style={note}>no JSON body on the response — the throw message is all there is.</div>}
        </div>
      )}
      {run && !summary && (
        <>
          <div style={amber}>200 OK, but the response carried no `summary` object — nothing to count.</div>
          <Json v={run} />
        </>
      )}
      {summary && (
        <>
          <Row>
            <Tag>sampled {summary.sampled}</Tag>
            <Tag c={Number(summary.findings) > 0 ? 'var(--amber)' : 'var(--ink-3)'}>findings {summary.findings}</Tag>
            <Tag c={Number(summary.submitted) > 0 ? 'var(--amber)' : 'var(--ink-3)'}>submitted {summary.submitted}</Tag>
            {runUnhealthy.length > 0 && <span style={{ marginLeft: 'auto', ...mono, color: 'var(--amber)' }}>{runUnhealthy.join(' · ')}</span>}
          </Row>
          {Number(summary.submitted) > 0 && (
            <div style={amber}>
              {summary.submitted} finding(s) submitted to the autonomy queue as task(s). Where each one landed is
              the risk policy's call, not this panel's — the census above was reloaded, read it there.
            </div>
          )}
        </>
      )}
      <div style={note}>
        This is a WRITE: observe() samples, debounces, then submits each finding through the autonomy worker.
        It does not consult system.observer_enabled — that flag only gates the scheduled pass — so the button
        is never disabled by it.
      </div>

      {/* ── S3 · autonomy-raise suggestions ──────────────────────────────── */}
      <div style={head}>AUTONOMY-RAISE SUGGESTIONS · GET {SUGGESTIONS_PATH}</div>
      <State e={sug.e} loading={sug.loading} n={gd ? 1 : 0} />
      {sug.e && readHint(sug.e, ORCH_503) && <div style={amber}>{readHint(sug.e, ORCH_503)}</div>}
      {gd && suggestions.length === 0 && (
        <div style={amber}>
          0 suggestions — and this endpoint cannot tell you which of the two causes it is: either no class
          cleared the bar (≥ 4 samples AND ≥ 0.8 approval, risk_tier 1–2 only), or the preference store has no
          DB connection and suggest_autonomy_raise() returned [] at preferences.py:132. Both are HTTP 200
          {' {"suggestions": []}'}.
        </div>
      )}
      {gd && suggestions.map((s: any, i: number) => (
        <div key={i}>
          <Row>
            <span style={{ ...mono, color: 'var(--ink-2)' }}>{s.agent} · {s.kind}</span>
            <span style={{ marginLeft: 'auto', display: 'flex', gap: 5, alignItems: 'center' }}>
              <Tag c={tierColor(s.risk_tier)}>tier {s.risk_tier}</Tag>
              <Tag>approval_rate {String(s.approval_rate)} over {s.samples} sample(s)</Tag>
            </span>
          </Row>
          <div style={{ ...mono, fontSize: 10.5, color: 'var(--ink-3)', padding: '0 0 4px' }}>{s.suggestion}</div>
        </div>
      ))}
      {gd && (
        <div style={note}>
          Advisory only, and there is no button on purpose: NO endpoint applies a per-(agent, kind, risk_tier)
          raise. The nearest control, POST /autonomy/policy, sets one agent's mode AUTO/ASK/OFF for everything
          that agent does — it already lives in AGENT AUTONOMY, and using it here would widen far more than the
          suggested class. The bar (≥ 4 samples, ≥ 0.8 approval, tiers 1–2) is the module default and the route
          accepts no override; approval_rate is the backend's plain AVG(approved), printed as it was rounded.
        </div>
      )}

      {/* ── S4 · governed outbound-call request ──────────────────────────── */}
      <div style={head}>REQUEST A GOVERNED CALL · POST {CALL_PATH}</div>
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center', margin: '2px 0 6px' }}>
        <input style={{ ...inpS, flex: '1 1 150px' } as any} maxLength={40} placeholder="to (number, ≤ 40 chars)"
          value={to} onChange={(ev) => setTo(ev.target.value)} />
        <select style={inpS as any} value={provider} onChange={(ev) => setProvider(ev.target.value)}>
          {PROVIDERS.map((p) => <option key={p.id} value={p.id}>{p.id}</option>)}
        </select>
        <input style={{ ...inpS, flex: '1 1 150px' } as any} maxLength={200} placeholder="reason (optional, ≤ 200)"
          value={reason} onChange={(ev) => setReason(ev.target.value)} />
        <input style={{ ...inpS, flex: '0 1 120px' } as any} maxLength={40} placeholder="agent (optional)"
          value={agent} onChange={(ev) => setAgent(ev.target.value)} />
      </div>
      <textarea style={taS as any} maxLength={2000} placeholder="message to be spoken on the call (≤ 2000 chars)"
        value={message} onChange={(ev) => setMessage(ev.target.value)} />
      <Row>
        <span style={{ ...mono, color: 'var(--ink-3)' }}>
          {to.trim() === '' || message.trim() === '' ? 'to + message are required by the broker' : `provider ${provider} · credential ${cred}`}
        </span>
        <button className="tool-btn" style={{ marginLeft: 'auto' }} disabled={!canCall} onClick={request}>
          {callBusy ? 'requesting…' : 'request approval'}
        </button>
      </Row>
      <div style={note}>
        Nothing dials here, ever. This queues a tier-2 (<code>call.outbound</code>) ASK task that lands in the
        decision inbox; the call is placed later, in CallBroker.execute, only after an approval — and only if the
        provider secret ({cred}) resolves. With no secret the default NullCallClient returns
        status:"deferred" · reason:"call_credential_not_configured". No route on this panel reports whether that
        secret exists, so this states the condition rather than guessing which side of it this instance is on.
      </div>
      {res && res.queued === true && (
        <div style={{ color: 'var(--green)', fontSize: 11, marginTop: 6 }}>
          queued for approval · task #{String(res.task_id)} · kind {String(res.kind)}
          <div style={{ ...mono, color: 'var(--ink-2)' }}>{String(res.title || '')}</div>
          {res.preview && (
            <div style={{ display: 'flex', gap: 5, alignItems: 'center', flexWrap: 'wrap', marginTop: 4 }}>
              <Tag c={tierColor(res.preview.risk_tier)}>tier {String(res.preview.risk_tier)}</Tag>
              <Tag c={res.preview.irreversible ? 'var(--red)' : 'var(--ink-3)'}>{res.preview.irreversible ? 'irreversible' : 'reversible'}</Tag>
              <Tag c={res.preview.requires_approval ? 'var(--amber)' : 'var(--ink-3)'}>{res.preview.requires_approval ? 'approval required' : 'auto-approvable'}</Tag>
            </div>
          )}
          {res.preview && res.preview.summary && (
            <div style={{ ...mono, color: 'var(--ink-3)', fontSize: 10.5 }}>{String(res.preview.summary)}</div>
          )}
        </div>
      )}
      {res && res.queued !== true && (
        <div style={{ marginTop: 6 }}>
          <div style={amber}>
            NOT queued — the broker had no enqueue sink (no orchestrator, or no autonomy queue), so
            autonomy.py:123-126 built a throwaway CallBroker and this 200 is a PREVIEW ONLY. Nothing was
            enqueued, nobody will be called, and pressing again will not change that.
          </div>
          <Json v={res.preview || res} />
        </div>
      )}
      {callErr && (
        <div style={{ marginTop: 6 }}>
          <div style={{ color: 'var(--red)', fontSize: 11 }}>
            refused · HTTP {String(callErr.status ?? '?')}
            {callErr.body && callErr.body.reason != null
              ? <> · reason: {String(callErr.body.reason)}</>
              : (!callErr.body || (callErr.body.detail === undefined && callErr.body.reason === undefined))
                ? <> · {String(callErr.message || 'refused')}</>
                : null}
            {callErr.body && callErr.body.kind != null && <> · kind {String(callErr.body.kind)}</>}
          </div>
          {callErr.body && Array.isArray(callErr.body.supported) && (
            <div style={{ ...mono, fontSize: 10.5, color: 'var(--ink-2)' }}>supported: {callErr.body.supported.join(' · ')}</div>
          )}
          {callErr.body && Array.isArray(callErr.body.missing) && (
            <div style={{ ...mono, fontSize: 10.5, color: 'var(--ink-2)' }}>missing: {callErr.body.missing.join(' · ')}</div>
          )}
          {callErr.body && callErr.body.detail !== undefined && <Json v={callErr.body.detail} />}
          <div style={note}>
            The broker's reasons are distinct code paths and are printed exactly as sent —
            unknown_provider from the provider guard and unknown_provider from the contract are not the same
            refusal, and neither is rewritten here.
          </div>
        </div>
      )}

      <div style={{ ...note, borderTop: '1px solid var(--panel-line)', paddingTop: 6, marginTop: 8 }}>
        admin reads: {STATUS_PATH} · {SUGGESTIONS_PATH} · {OBSERVER_PATH} (X-Admin-Token) ·
        admin write: POST {OBSERVER_RUN_PATH} · user-tier write: POST {CALL_PATH}.
      </div>
    </Card>
  );
}
