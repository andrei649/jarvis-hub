/* SIGNAL GOVERNANCE — the Signal Layer → approval-inbox bridge (DRA-19), both of whose
   routes shipped user-reachable with no client that ever called them:

     GET  /api/signals/governance         agents/core/routers/signals.py:128
     POST /api/signals/governance/submit  agents/core/routers/signals.py:156

   Bridge: agents/core/signal_governance.py; constructed unconditionally in production
   (orchestrator.py:461, `SignalGovernanceBridge.from_env`).

   Why this is not a duplicate surface: gap.tsx's SignalRoutingPanel reads
   /api/signals/routed (the live feed, a different payload) and DecisionInboxPanel reads
   the admin /autonomy/tasks?status=blocked (task ROWS). Neither reports the bridge's
   enabled/flag/kind/pending status, and nothing in the HUD can submit a brief.

   What this panel is NOT allowed to imply, checked against the handlers:

   1. `enabled: false` is NOT an error and NOT a fault. It is the documented default:
      `from_env` reads JARVIS_SIGNAL_GOVERNANCE once, at orchestrator construction
      (signal_governance.py:74-78). The panel names the flag FROM THE PAYLOAD (`d.flag`)
      and words the state as a fact.
   2. There is NO route anywhere that sets or clears that flag, so this panel draws no
      toggle, switch or "turn on the bridge" control. The truthful statement — owner sets
      the env var and restarts Nerva — is printed instead.
   3. On the `available: false` branch the handler ships a hardcoded `pending: 0`
      (signals.py:141) alongside the reason. That zero is filler, not a measurement, so it
      is NEVER printed as a count; the panel says the count was not measured.
   4. Even on the available branch `pending` is not a total: `queue.pending_decisions()`
      defaults to limit=100 ORDER BY id ASC, and signals.py:143-147 collapses ANY read
      exception to 0 with only a server-side logger.warning. Both caveats are stated.
   5. Nothing submitted here is approved, executed, actioned or scheduled. Every queued
      task is enqueued then IMMEDIATELY transitioned to BLOCKED with
      decision='await_human_approval' (signal_governance.py:128-133); this bridge has no
      executor path at all.
   6. `skipped` merges two different causes — advisory (non-`requiresApproval`) items and
      contract-denied ones, whose reason reaches only the audit sink
      (signal_governance.py:99-118). The response carries no breakdown, so the number is
      printed bare and attributed to nothing.

   THE INVERTED apiPost TRAP, which is what makes this panel dangerous to write:
   /api/signals/governance/submit answers **200 for every refusal**, so refusals arrive in
   act()'s `then` branch, not onErr. `available: true` together with `status: "disabled"`
   is a real, reachable shape that queued NOTHING (signal_governance.py:95-96) — reading
   `available` alone as success would report a governance submission that never happened.
   The outcome is therefore classified in a fixed order: available===false → refused,
   status==='disabled' → refused, status==='ok' → the only success, anything else → the
   raw body verbatim rather than a guess. onErr is still mandatory and carries the
   401/403/500 path (err.body from client.ts failMutation).

   Both routes are user-tier (user_guard): act(), not actA(); useApi(..., admin=false). */
import React, { useState } from 'react';
import { useApi, mono, asLive, Card, State, Row, Tag, Btn, act, Json } from '../panel-kit';

const STATUS_PATH = '/api/signals/governance';
const SUBMIT_PATH = '/api/signals/governance/submit';

/* The three reasons the ROUTER itself emits (signals.py:140/169/176/182). Any other string
   is the sidecar plugin's own `status`, forwarded verbatim (signals.py:183-185). This list
   is used for ONE thing only — deciding whether to add the "the detail was dropped" note —
   and never to reword, translate or substitute for the reason, which is always printed
   exactly as the backend sent it. */
const ROUTER_REASONS = ['signal_governance_unavailable', 'signal_layer_plugin_unavailable'];

const str = (v) => (typeof v === 'string' && v !== '' ? v : null);
const int = (v) => (Number.isFinite(Number(v)) ? Number(v) : null);

export function SignalGovernancePanel() {
  /* user-tier read (user_guard) — admin=false, deliberately. */
  const { d, e, loading, reload } = useApi(STATUS_PATH);
  const [busy, setBusy] = useState(false);
  const [out, setOut] = useState<any>(null);   // { t: 'body', r } | { t: 'err', err }

  const loaded = !!d && !e;
  const available = loaded ? d.available === true : null;
  const enabled = loaded ? d.enabled === true : null;
  const flag = loaded ? str(d.flag) : null;    // rendered from the payload, never hardcoded
  const kind = loaded ? str(d.kind) : null;
  const note = loaded ? str(d.note) : null;
  /* Only meaningful when available === true. On the unavailable branch the handler's 0 is
     filler and must never reach the screen as a number. */
  const pending = available === true ? int(d.pending) : null;

  const sub = !loaded ? null
    : available !== true ? 'unavailable'
    : enabled ? `${pending == null ? '?' : pending} pending`
    : `disabled · ${pending == null ? '?' : pending} pending`;

  const submit = () => {
    if (busy) return;
    setOut(null);           // a stale success must never sit under a fresh attempt
    setBusy(true);
    act(
      SUBMIT_PATH,
      undefined,            // this route takes NO request fields at all
      (r) => {
        setBusy(false);
        setOut({ t: 'body', r });
        // Re-read rather than incrementing anything here: submitting is not idempotent.
        if (r && r.available === true && r.status === 'ok') reload();
      },
      (err) => { setBusy(false); setOut({ t: 'err', err }); },
    );
  };

  return (
    <Card
      title="SIGNAL GOVERNANCE"
      sub={sub}
      live={asLive(d, !!(loaded && available === true && enabled === true))}
      onReload={reload}
    >
      {/* n={null}: this is a status card, never a list — "nothing yet" would be a lie. */}
      <State e={e} loading={loading} n={null} />

      {/* ── Branch A · the bridge is not constructed ─────────────────────────── */}
      {loaded && available === false && (
        <>
          <Row>
            <Tag c="var(--red)">UNAVAILABLE</Tag>
            <span style={{ ...mono, color: 'var(--red)' }}>
              bridge unavailable · {str(d.reason) || '(the response carried no reason)'}
            </span>
          </Row>
          <div style={{ ...mono, color: 'var(--ink-2)', marginTop: 6 }}>
            pending not measured — on this branch the handler ships a hardcoded 0 beside the
            reason (signals.py:141), so there is no count to show.
          </div>
        </>
      )}

      {/* ── Branch B/C · the bridge exists; the flag decides ─────────────────── */}
      {loaded && available === true && (
        <>
          <Row>
            {enabled
              ? <Tag c="var(--green)">ENABLED</Tag>
              : <Tag c="var(--amber)">DISABLED</Tag>}
            <span style={{ ...mono, color: 'var(--ink-2)' }}>
              {pending == null ? 'pending unreadable' : pending}
              {kind ? ` × ${kind}` : ''} awaiting a human decision (BLOCKED in the decision inbox)
            </span>
          </Row>

          {!enabled && (
            <div style={{ ...mono, color: 'var(--amber)', marginTop: 6 }}>
              {flag
                ? `${flag} is not set — the bridge queues nothing until the owner sets it.`
                : 'the flag is not set — the bridge queues nothing until the owner sets it. (the response named no flag)'}
              <div style={{ color: 'var(--ink-3)', marginTop: 3 }}>
                This is the documented default state, not a fault. No route sets or clears
                it and the bridge reads the environment once when Nerva starts, so there is
                deliberately no toggle here: enabling it is an owner-side env change plus a
                restart.
              </div>
            </div>
          )}

          {note && (
            <div style={{ ...mono, color: 'var(--ink-3)', marginTop: 6 }}>{note}</div>
          )}

          {pending != null && pending > 0 && (
            <div style={{ ...mono, color: 'var(--ink-3)', marginTop: 6 }}>
              A disabled bridge can still report a non-zero count — those are items left
              over from an earlier enabled run, still sitting in the inbox.
            </div>
          )}
        </>
      )}

      {/* ── The submit control ───────────────────────────────────────────────── */}
      <Row>
        <span style={{ ...mono, color: 'var(--ink-3)' }}>
          submit the sidecar's live world brief (GET /briefs/world, fetched server-side)
        </span>
        <Btn onClick={submit}>{busy ? 'submitting…' : 'submit brief → inbox'}</Btn>
      </Row>
      <div style={{ ...mono, color: 'var(--ink-3)', marginTop: 4 }}>
        Nothing is typed here: the route takes no request body. The recommendations come
        from the Signal Layer sidecar's own brief, and every accepted item lands BLOCKED —
        nothing is approved, executed or scheduled by this control.
      </div>
      {loaded && available === true && enabled === false && (
        <div style={{ ...mono, color: 'var(--amber)', marginTop: 4 }}>
          the bridge is off — a submit returns status:disabled and queues nothing.
        </div>
      )}

      {out && out.t === 'body' && <SubmitOutcome r={out.r} flag={flag} />}
      {out && out.t === 'err' && <SubmitFailure err={out.err} />}

      <div style={{ ...mono, color: 'var(--ink-3)', marginTop: 8, borderTop: '1px solid var(--panel-line)', paddingTop: 6 }}>
        user-tier read and write (user_guard) — nothing on this panel is admin. `pending` is
        counted over the queue's first 100 pending decisions (limit=100, id ASC), and a
        failed read is collapsed to 0 server-side, so it is a lower bound, not a total.
      </div>
    </Card>
  );
}

/* Every refusal from this route is a 200 with a body, so the classification order below is
   the whole safety property: `available` is checked first, then `status === 'disabled'`,
   and only `status === 'ok'` may render as success. */
function SubmitOutcome({ r, flag }: { r: any; flag: string | null }) {
  const box = (c: string, children: any) => (
    <div role="alert" style={{ marginTop: 8, padding: 6, border: `1px solid ${c}`, borderRadius: 4 }}>{children}</div>
  );

  // (1) no bridge / no sidecar plugin / fetch_failed / the sidecar's own status.
  if (!r || r.available === false) {
    const reason = str(r && r.reason);
    const dropped = reason == null || ROUTER_REASONS.indexOf(reason) === -1;
    return box('var(--red)', (
      <>
        <div style={{ ...mono, color: 'var(--red)' }}>
          refused · {reason || '(the response carried no reason)'}
        </div>
        <div style={{ ...mono, color: 'var(--ink-2)', marginTop: 4 }}>
          Nothing was queued. The string above is the backend's own reason, printed as sent.
        </div>
        {dropped && (
          <div style={{ ...mono, color: 'var(--ink-3)', marginTop: 4 }}>
            The router forwards only this status — the sidecar's `error` detail (which holds
            the failed path) and its `provider` are dropped before the response, so nothing
            more can honestly be said about the cause here.
          </div>
        )}
      </>
    ));
  }

  // (2) available:true AND status:disabled — the shape that must never read as success.
  if (r.status === 'disabled') {
    return box('var(--amber)', (
      <>
        <div style={{ ...mono, color: 'var(--amber)' }}>
          disabled · nothing queued{flag ? ` · ${flag} is not set` : ' · the governance flag is not set'}
        </div>
        <div style={{ ...mono, color: 'var(--ink-2)', marginTop: 4 }}>
          The request reached the bridge and the bridge declined to queue anything. Not a
          transport failure, and not a submission.
        </div>
      </>
    ));
  }

  // (3) the one success branch.
  if (r.status === 'ok') {
    const queued = int(r.queued);
    const skipped = int(r.skipped);
    const ids = Array.isArray(r.task_ids) ? r.task_ids : [];
    return box('var(--green)', (
      <>
        <div style={{ ...mono, color: 'var(--green)' }}>
          queued {queued == null ? '?' : queued} · skipped {skipped == null ? '?' : skipped}
        </div>
        {ids.length > 0 && (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 4 }}>
            {ids.map((id, i) => <Tag key={i} c="var(--ink-2)">#{String(id)}</Tag>)}
          </div>
        )}
        {queued === 0 && (
          <div style={{ ...mono, color: 'var(--ink-2)', marginTop: 4 }}>
            brief carried no actionable recommendations — nothing was queued.
          </div>
        )}
        {str(r.note) && <div style={{ ...mono, color: 'var(--ink-2)', marginTop: 4 }}>{str(r.note)}</div>}
        {skipped != null && skipped > 0 && (
          <div style={{ ...mono, color: 'var(--ink-3)', marginTop: 4 }}>
            {skipped} not queued — the response carries no breakdown, so no cause is
            attributed to that number here.
          </div>
        )}
        <div style={{ ...mono, color: 'var(--ink-3)', marginTop: 4 }}>
          Each id above is BLOCKED with decision=await_human_approval, waiting in the
          decision inbox. A per-item enqueue failure is swallowed server-side and simply
          shrinks `queued`, with nothing surfaced in this response.
        </div>
      </>
    ));
  }

  // (4) anything else — shown raw rather than collapsed into a guess.
  return box('var(--amber)', (
    <>
      <div style={{ ...mono, color: 'var(--amber)' }}>
        unrecognised response · status {str(r.status) || '(none)'} — printed as received,
        with no interpretation.
      </div>
      <Json v={r} />
    </>
  ));
}

/* The 401/403/500 path. Refusal BODIES never reach here (they are 200s), so anything that
   does is a transport-level failure and is shown as one, with the status visible. */
function SubmitFailure({ err }: { err: any }) {
  const b = (err && err.body) || null;
  const line =
    b && typeof b.reason === 'string' ? b.reason
    : b && typeof b.detail === 'string' ? b.detail
    : b && b.detail != null && typeof b.detail !== 'string' ? null
    : (err && err.message) || 'request failed';
  return (
    <div role="alert" style={{ marginTop: 8, padding: 6, border: '1px solid var(--red)', borderRadius: 4 }}>
      <div style={{ ...mono, color: 'var(--red)' }}>
        submit failed · HTTP {(err && err.status) || '?'} · POST {SUBMIT_PATH}
      </div>
      {line != null && <div style={{ ...mono, color: 'var(--ink-2)', marginTop: 4 }}>{line}</div>}
      {b && b.detail != null && typeof b.detail !== 'string' && <Json v={b.detail} />}
      <div style={{ ...mono, color: 'var(--ink-3)', marginTop: 4 }}>
        The request did not reach the bridge — nothing was queued.
      </div>
    </div>
  );
}
