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
   status==='disabled' → refused, status==='ok'/'partial' → recognised (partial means some
   recommendations were queued and some were DROPPED), anything else → the
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
        if (r && r.available === true && (r.status === 'ok' || r.status === 'partial')) reload();
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

          {/* Only the DISABLED branch needs this: with the flag unset the bridge queues
              nothing, so a non-zero count would otherwise look like a contradiction. It
              says only that, and attributes the items to nothing — the response carries
              no timestamps and no provenance, so "left over from an earlier run" would
              be an invented cause. On the ENABLED branch the row above is already the
              whole truth and this note would be a lie about the live queue. */}
          {!enabled && pending != null && pending > 0 && (
            <div style={{ ...mono, color: 'var(--ink-3)', marginTop: 6 }}>
              The bridge queues nothing while the flag is unset, so this count is of items
              already in the inbox — the response does not say when, or by what, they were
              queued.
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
   and only `status === 'ok'` or `'partial'` is recognised — `partial` still renders the
   queued ids, but its `failed` block says plainly what was lost. */
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
  if (r.status === 'ok' || r.status === 'partial') {
    const queued = int(r.queued);
    const skipped = int(r.skipped);
    const ids = Array.isArray(r.task_ids) ? r.task_ids : [];
    const failed = int(r.failed);
    const failures = Array.isArray(r.failures) ? r.failures : [];
    // A `partial` run LOST work. Framing it green would make a dropped recommendation read
    // as a success with a footnote, so the whole box takes the amber of what happened.
    const lost = failed != null && failed > 0;
    const tone = lost ? 'var(--amber)' : 'var(--green)';
    return box(tone, (
      <>
        <div style={{ ...mono, color: tone }}>
          queued {queued == null ? '?' : queued} · skipped {skipped == null ? '?' : skipped}
          {lost ? ` · failed ${failed}` : ''}
        </div>
        {ids.length > 0 && (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 4 }}>
            {ids.map((id, i) => <Tag key={i} c="var(--ink-2)">#{String(id)}</Tag>)}
          </div>
        )}
        {/* queued 0 used to have two indistinguishable producers — an empty brief, and a
            brief whose every enqueue raised into a swallowed `except` that incremented
            NEITHER counter. The bridge now counts failures separately and returns them, so
            the cause can be stated instead of hedged. */}
        {queued === 0 && failed === 0 && (
          <div style={{ ...mono, color: 'var(--ink-2)', marginTop: 4 }}>
            Nothing was queued and nothing failed — the brief carried no actionable
            recommendations.
          </div>
        )}
        {/* `failed` ABSENT is not `failed: 0`. A response without the key came from a bridge
            that could not separate the two producers of queued:0, so the honest answer there
            is still the hedge — the panel does not upgrade an unknown into a verdict. */}
        {queued === 0 && failed == null && (
          <div style={{ ...mono, color: 'var(--ink-2)', marginTop: 4 }}>
            Nothing was queued, and this response does not say why: it carries no `failed`
            count, so an empty brief and a run whose queue writes all raised are
            indistinguishable here.
          </div>
        )}
        {failed > 0 && (
          <div style={{ ...mono, color: 'var(--red)', marginTop: 4 }}>
            {failed} recommendation{failed > 1 ? 's were' : ' was'} DROPPED — the bridge tried
            to queue {failed > 1 ? 'them' : 'it'} and failed, so {failed > 1 ? 'they are' : 'it is'}{' '}
            not waiting in the decision inbox and no one will be asked to approve{' '}
            {failed > 1 ? 'them' : 'it'}.
            {failures.map((f: any, i: number) => (
              <div key={i} style={{ color: 'var(--ink-2)', marginTop: 2 }}>
                {String((f && f.label) ?? '—')} — {String((f && f.error) ?? 'no reason given')}
              </div>
            ))}
          </div>
        )}
        {str(r.note) && <div style={{ ...mono, color: 'var(--ink-2)', marginTop: 4 }}>{str(r.note)}</div>}
        {skipped != null && skipped > 0 && (
          <div style={{ ...mono, color: 'var(--ink-3)', marginTop: 4 }}>
            {skipped} not queued — these were either non-actionable or refused by the
            recommendation contract. That split is not in the response, so it is not guessed
            here; failures are counted separately above and are never folded into this number.
          </div>
        )}
        {/* "Each id above" is only true when there ARE ids, and the swallow caveat is
            already carried by the queued-0 line, so neither is printed unconditionally. */}
        {ids.length > 0 && (
          <div style={{ ...mono, color: 'var(--ink-3)', marginTop: 4 }}>
            Each id above is BLOCKED with decision=await_human_approval, waiting in the
            decision inbox. A per-item enqueue failure is reported separately as `failed`
            rather than silently shrinking this list.
          </div>
        )}
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
