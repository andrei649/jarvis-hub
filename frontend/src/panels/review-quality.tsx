/* REVIEW & QUALITY — three shipped, user-reachable routes that no client ever called:

     GET  /api/review/stats     agents/core/routers/review.py:25   (OPEN — no guard at all)
     GET  /api/quality/scores   agents/core/routers/quality.py:26  (user_guard)
     POST /api/review/flag      agents/core/routers/review.py:34   (user_guard)

   Why this is not a duplicate of a shipped surface. gap.tsx already ships ReviewPanel
   (:1691) and QualityPanel (:1486), and this panel deliberately overlaps neither:

     * ReviewPanel reads ONLY `/api/review/queue?status=pending` — a pending-filtered ITEM
       LIST from ReviewQueue.list(). It structurally cannot show total / reviewed /
       thumbs_up / thumbs_down / in_dataset, which come from a different store method
       (ReviewQueue.stats(), review_queue.py:139) over a different payload. The vote and
       promote-to-dataset controls live there and are NOT repeated here.
     * QualityPanel reads the aggregate `/api/quality` (avg_score, threshold, alerting) and
       owns the admin threshold-set control. Nothing anywhere renders the PER-REQUEST ring
       — its trace_ids, its individual scores, or its persona axis. That is section 2, and
       the threshold-set control is NOT repeated here.

   THE DEGENERATE-FORM RULING on POST /api/review/flag, which is the whole reason section 3
   looks the way it does. The `trace` body is agent-produced evidence: a cognition trace.
   A textarea asking the owner to hand-type or paste trace JSON would be a fake surface, and
   it is not built. The route survives only in one shape — a PICKER over the already-live
   GET /api/traces (analytics.py:277), sending the fetched summarized row back VERBATIM as
   `trace`. The genuine human inputs are the SELECTION and the free-text `reason`. With no
   fetched trace there is no honest body to send, so the button is disabled rather than
   typed into. There is deliberately no raw-JSON field anywhere on this panel.

   What this panel is not allowed to imply, checked against the handlers:

   1. `/api/review/stats` NEVER 503s. When get_orch() is falsy or orch.review_queue is None
      it answers 200 `{"stats": {}}` (review.py:27-30) — an EMPTY DICT, not zeros. That is
      reachable, not hypothetical: ComponentRegistry.register swallows a construction
      exception and sets the attribute to None (component_registry.py:33-44). Rendering that
      as "total 0 / pending 0" is the forbidden silent zero, so on that branch this panel
      prints NO rollup numbers at all and names the condition instead.
   2. `/api/quality/scores` answers 200 `{"scores": []}` BOTH when the ring is empty and when
      orch.quality is None (quality.py:30-32) — again never a 503. An empty list alone cannot
      distinguish "idle" from "not wired", so the panel refuses to guess and instead probes
      the open `/api/quality`: QualityMonitor.stats() always carries `n:int` when the monitor
      exists, so `typeof stats.n === 'number'` is an exact wired/not-wired test. That probe is
      READ-ONLY and contributes exactly two facts — qualityWired and stats.threshold. It
      re-renders neither the average nor the alert state (QualityPanel's job) and adds no
      control.
   3. No threshold, average or ring-window number is printed that no fetched payload carried.
      The threshold comes only from the probe's stats.threshold. The ring size (deque maxlen,
      DEFAULT_WINDOW=50) is exposed by NO route, so no capacity is ever shown — the panel says
      only what quality.py's own docstring says: an in-memory rolling signal, not durable
      history.
   4. THE IDEMPOTENCY TRAP. ReviewQueue.flag scans for an existing item with the same trace_id
      and, if found, returns THAT item unchanged — applying neither the new reason nor a new
      timestamp (review_queue.py:41-43) — while STILL answering `{"ok": true}`. So the
      operator's typed reason is never echoed back as if it had been stored: every field shown
      after a flag is read verbatim off the RETURNED item, and a mismatch between what was
      sent and what came back is called out as a write that did not happen.
   5. `item.score` is null by construction for anything flagged from GET /api/traces, because
      Tracer._summarize emits no `quality` key (tracer.py:100-120). Null renders "—", never 0.
      Likewise persona_score / soul_version / agent are ABSENT keys — not null — on every
      score entry whose trace carried no persona profile (quality.py:197-204), so they render
      nothing at all rather than 0 or "unknown".
   6. Neither the review queue nor the quality monitor has any enable/disable route, so this
      panel draws no toggle for either. The truthful statement is printed instead.
   7. THE CROSS-COMPONENT CONSEQUENCE. A threshold read off the quality monitor does NOT by
      itself mean a low score gets filed: cognition_trace.py:163 calls auto_flag only when
      orch.review_queue is not None, and quality / review_queue are two independent registry
      entries — either can be None while the other is up. So the auto-filing sentence is
      gated on the QUEUE evidence this panel already holds (section 1's `total`), not on the
      threshold, and it is denied outright in the queue-absent state instead of repeated.

   apiPost THROWS on every refusal here — 503 {"error": "review queue not available"}
   (require_component, review.py:36), 400 {"error": "trace required"} (review.py:44-45), and
   the guard's 401/403 — so `onErr` is MANDATORY on the flag control: without it act()'s own
   .catch swallows the refusal and the button reads as success. Each backend string is printed
   exactly as sent; the 503 and the 400 are never collapsed into one sentence.

   Tier: /api/review/stats is OPEN; the other three reads and the write are user_guard. There
   is no admin call on this panel — no actA, no useApi(..., true). */
import React, { useState } from 'react';
import { useApi, arr, mono, asLive, Card, State, Row, Tag, act, inpS, Json } from '../panel-kit';

const STATS_PATH = '/api/review/stats';          // open route
const SCORES_PATH = '/api/quality/scores?limit=50';
const TRACES_PATH = '/api/traces?limit=25';      // already a live caller (api/live.ts:381)
const PROBE_PATH = '/api/quality';               // availability probe ONLY
const FLAG_PATH = '/api/review/flag';

const num = (v) => (typeof v === 'number' && Number.isFinite(v) ? v : null);
const str = (v) => (typeof v === 'string' && v !== '' ? v : null);
const has = (o, k) => o != null && Object.prototype.hasOwnProperty.call(o, k);
const when = (v) => {
  const n = num(v);
  if (n == null) return null;
  try { return new Date(n * 1000).toLocaleString(); } catch { return String(v); }
};
const clock = (v) => {
  const n = num(v);
  if (n == null) return '—';
  try { return new Date(n * 1000).toLocaleTimeString(); } catch { return String(v); }
};

/* ReviewQueue.stats() keys, in the order the operator reads them. Every one is a plain
   integer straight off the payload — nothing here is derived, because thumbs_up+thumbs_down
   is NOT an identity with `reviewed` (items promoted before the current contract can carry
   verdict null), and printing a computed total would assert an invariant the store does not
   guarantee. */
const ROLLUP = [
  ['total', 'total'],
  ['pending', 'pending'],
  ['reviewed', 'reviewed'],
  ['thumbs_up', '\u{1F44D} thumbs up'],
  ['thumbs_down', '\u{1F44E} thumbs down'],
  ['in_dataset', 'in dataset'],
];

const label = { ...mono, fontSize: 9.5, letterSpacing: '.14em', color: 'var(--ink-3)', marginTop: 10 };
const note = { ...mono, fontSize: 10, color: 'var(--ink-3)', marginTop: 4 };
const amber = { ...mono, fontSize: 10.5, color: 'var(--amber)', marginTop: 4 };

export function ReviewQualityPanel() {
  const s = useApi(STATS_PATH);          // OPEN — no guard on this one (review.py:25)
  const q = useApi(SCORES_PATH);         // user_guard
  const t = useApi(TRACES_PATH);         // user_guard — feeds the flag picker
  const m = useApi(PROBE_PATH);          // OPEN — availability probe, no control drawn

  const [pickedId, setPickedId] = useState<any>(null);
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState<any>(null);   // {ok:true,item,sent} | {ok:false,status,msg,detail}

  const reloadAll = () => { s.reload(); q.reload(); t.reload(); m.reload(); };

  /* ── section 1 state ───────────────────────────────────────────────────── */
  const st = s.d && typeof s.d.stats === 'object' && s.d.stats ? s.d.stats : null;
  // The whole honesty hook for this route: {} means the component is absent, and only a
  // real integer `total` proves the store answered.
  const queueWired = !!st && typeof st.total === 'number';

  /* ── section 2 state ───────────────────────────────────────────────────── */
  const scores = arr(q.d, 'scores');
  const probe = m.d && typeof m.d.stats === 'object' && m.d.stats ? m.d.stats : null;
  const qualityWired = !!probe && typeof probe.n === 'number';
  const probeAnswered = !!m.d || !!m.e;
  const thr = probe ? num(probe.threshold) : null;   // the ONLY source of a threshold here

  /* ── section 3 state ───────────────────────────────────────────────────── */
  const traces = arr(t.d, 'traces');
  // 200-with-a-body degradation on the trace source (analytics.py:284). Backend-emitted,
  // shown verbatim. The 503 "not initialized" path reaches us as a status only — apiGet
  // attaches no body — so it surfaces through <State e=…/> instead.
  const tracerMsg = str(t.d && t.d.error);
  const picked = traces.find((x) => x && str(x.id) && String(x.id) === String(pickedId)) || null;

  const scoreByTrace = {};
  scores.forEach((e) => {
    const id = str(e && e.trace_id);
    if (id != null && num(e.score) != null) scoreByTrace[id] = e.score;
  });

  const submit = () => {
    if (!picked || busy) return;
    // Backend default when the key is omitted (review.py:47). Comparing the RETURNED
    // item.reason against this is what detects the idempotent no-op.
    const sent = reason.trim() || 'manual';
    setRes(null);
    setBusy(true);
    act(
      FLAG_PATH,
      { trace: picked, ...(reason.trim() ? { reason: reason.trim() } : {}) },
      (r) => {
        setBusy(false);
        setRes({ ok: true, item: r && r.item, sent, raw: r });
        s.reload();   // re-read the rollup rather than incrementing anything locally
      },
      (err) => {
        setBusy(false);
        const b = (err && err.body) || null;
        setRes({
          ok: false,
          status: err && err.status,
          msg: (b && str(b.error))
            || (b && typeof b.detail === 'string' ? b.detail : null)
            || (err && err.message)
            || 'request failed',
          detail: b && b.detail != null && typeof b.detail !== 'string' ? b.detail : null,
        });
      },
    );
  };

  const sub = !s.d ? null : queueWired ? `${num(st.pending) ?? '?'} pending` : 'queue component absent';
  const bothWired = queueWired && qualityWired;
  const settled = !!s.d && probeAnswered;

  return (
    <Card
      title="REVIEW & QUALITY"
      sub={sub}
      live={asLive(settled ? s.d : null, settled ? bothWired : undefined)}
      onReload={reloadAll}
    >
      {/* n={null}: a status card, never a list — "nothing yet" would be a lie here. */}
      <State e={s.e} loading={s.loading} n={null} />

      {/* ── 1 · QUEUE ROLLUP — GET /api/review/stats ───────────────────────── */}
      <div style={{ ...label, marginTop: 0 }}>QUEUE ROLLUP · /api/review/stats</div>

      {queueWired && (
        <>
          {ROLLUP.map(([k, lbl]) => (
            <Row key={k}>
              <span style={{ ...mono, color: 'var(--ink-2)' }}>{lbl}</span>
              <span style={{ marginLeft: 'auto', ...mono, color: 'var(--accent-light)' }}>
                {num(st[k]) != null ? st[k] : '—'}
              </span>
            </Row>
          ))}
          {arr(st, 'rubric_criteria').length > 0 && (
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 6 }}>
              <span style={{ ...mono, fontSize: 10, color: 'var(--ink-3)' }}>rubric:</span>
              {arr(st, 'rubric_criteria').map((c, i) => <Tag key={i} c="var(--ink-2)">{String(c)}</Tag>)}
            </div>
          )}
          <div style={note}>
            thumbs are counted among REVIEWED items only, and their sum need not equal
            `reviewed` — an item reviewed before the current contract can carry a null verdict —
            so no total is derived here.
          </div>
        </>
      )}

      {s.d && !queueWired && (
        <>
          <Row>
            <Tag c="var(--amber)">review queue not available</Tag>
          </Row>
          <div style={amber}>
            {STATS_PATH} answered {'{"stats": {}}'} — the component is absent; this is not a
            count of zero (the route never 503s).
          </div>
          <div style={note}>
            orch.review_queue is None whenever ReviewQueue construction raised: the component
            registry logs it and sets the attribute to None. No route turns it back on — that is
            an owner-side restart, so no toggle is drawn here.
          </div>
        </>
      )}

      {/* ── 2 · RECENT QUALITY SCORES — GET /api/quality/scores ────────────── */}
      <div style={label}>RECENT SCORES · /api/quality/scores</div>
      <State e={q.e} loading={q.loading} n={null} />

      {scores.slice(0, 8).map((e, i) => {
        const sc = num(e && e.score);
        const below = thr != null && sc != null && sc < thr;
        return (
          <Row key={(e && e.trace_id) || i}>
            <span style={{ ...mono, color: 'var(--ink-2)' }}>
              {str(e && e.trace_id) ? String(e.trace_id).slice(0, 12) : '(no trace id)'}
            </span>
            <span style={{ marginLeft: 'auto', display: 'flex', gap: 5, alignItems: 'center', flexWrap: 'wrap' }}>
              {has(e, 'persona_score') && (
                <Tag c="var(--ink-2)">
                  persona {num(e.persona_score) != null ? num(e.persona_score).toFixed(3) : 'null'}
                </Tag>
              )}
              {has(e, 'soul_version') && <Tag>soul {str(e.soul_version) || 'null'}</Tag>}
              {has(e, 'agent') && <Tag>{str(e.agent) || 'agent (empty)'}</Tag>}
              <Tag>{clock(e && e.ts)}</Tag>
              <Tag c={thr == null ? undefined : below ? 'var(--red)' : 'var(--green)'}>
                {sc != null ? sc.toFixed(3) : '—'}
              </Tag>
            </span>
          </Row>
        );
      })}

      {scores.length > 8 && (
        <div style={note}>showing 8 of {scores.length} returned (most recent first).</div>
      )}

      {q.d && scores.length === 0 && (
        !probeAnswered ? (
          <div style={note}>empty — checking {PROBE_PATH} to tell an idle ring from an absent monitor…</div>
        ) : m.e ? (
          <div style={amber}>
            empty — cannot tell an idle ring from an absent monitor ({PROBE_PATH} unreachable).
          </div>
        ) : qualityWired ? (
          <div style={note}>no scored requests in the ring yet.</div>
        ) : (
          <div style={amber}>
            quality monitor not wired (orch.quality is None) — the route answers 200
            {' '}{'{"scores": []}'} rather than 503, so this is not "quality is fine".
          </div>
        )
      )}

      <div style={note}>
        {thr != null
          ? `score colour uses threshold ${thr}, read from ${PROBE_PATH} (stats.threshold).`
          : `no colour: ${PROBE_PATH} reported no threshold, so no cutoff is asserted here.`}
        {' '}This ring is the in-memory live-quality signal, not durable history; its capacity is
        exposed by no route, so none is shown.
      </div>

      {/* AUTO-FILING IS NOT A PROPERTY OF THE THRESHOLD. cognition_trace.py:163 calls
          review_queue.auto_flag only inside `if getattr(orch, "review_queue", None) is not
          None:` — and `quality` and `review_queue` are two INDEPENDENT registry entries
          (orchestrator.py), so "monitor up, queue absent" is a reachable state, not a
          hypothetical. Gating this claim on `thr != null` alone printed "a turn below it is
          auto-filed" in exactly the state where nothing is filed at all, on the same card
          that had just said the queue component is absent. The claim is now made only when
          the rollup above proved the queue answered, denied when it proved it absent, and
          withheld when the rollup could not be read. */}
      {thr != null && (queueWired ? (
        <div style={note}>
          {`auto-filing runs only where the review queue component exists, and the rollup above shows it answering — so a turn scored below ${thr} on this path is filed with reason \`auto: score <score> < ${thr}\`.`}
        </div>
      ) : s.d ? (
        <div style={amber}>
          {`nothing is auto-filed at this cutoff: auto-filing runs only where the review queue component exists, and the rollup above reports it absent. A turn scoring below ${thr} still lands in this ring, but no review row is created for it.`}
        </div>
      ) : (
        <div style={note}>
          {`whether a turn below ${thr} is auto-filed depends on the review queue component, which the rollup above has not reported on, so nothing is claimed about it here.`}
        </div>
      ))}

      {/* ── 3 · FLAG A TRACE — POST /api/review/flag ───────────────────────── */}
      <div style={label}>FLAG A TRACE FOR REVIEW · POST /api/review/flag</div>
      <State e={t.e} loading={t.loading} n={null} />

      {tracerMsg && (
        <div style={amber}>
          {TRACES_PATH} answered 200 with error: {tracerMsg} — there is no trace to pick, so
          there is no honest body to POST and the control is disabled.
        </div>
      )}

      {traces.slice(0, 12).map((tr, i) => {
        const id = str(tr && tr.id);
        const sc = id != null ? scoreByTrace[id] : undefined;
        const sel = id != null && String(id) === String(pickedId);
        return (
          <Row key={id || i}>
            <button
              className="tool-btn"
              disabled={id == null}
              title={id == null ? 'this trace carries no id' : 'select this trace'}
              onClick={() => setPickedId(id)}
            >
              {sel ? '◉' : '○'}
            </button>
            <span style={{ fontSize: 11, color: sel ? 'var(--accent-light)' : 'var(--ink-2)' }}>
              {(str(tr && tr.text_preview) || '(no preview)').slice(0, 40)}
            </span>
            <span style={{ marginLeft: 'auto', display: 'flex', gap: 5, alignItems: 'center' }}>
              {str(tr && tr.route) && <Tag>{tr.route}</Tag>}
              {str(tr && tr.channel) && <Tag>{tr.channel}</Tag>}
              {typeof sc === 'number' && (
                <Tag c={thr != null && sc < thr ? 'var(--red)' : 'var(--ink-2)'}>{sc.toFixed(3)}</Tag>
              )}
            </span>
          </Row>
        );
      })}

      {t.d && traces.length === 0 && !tracerMsg && (
        <div style={note}>no traces recorded yet — nothing to flag.</div>
      )}

      <div style={{ display: 'flex', gap: 6, marginTop: 8, alignItems: 'center' }}>
        <input
          value={reason}
          onChange={(ev) => setReason(ev.target.value)}
          placeholder="reason (optional — backend default: manual)"
          style={{ ...inpS, flex: 1 }}
        />
        <button className="tool-btn" disabled={!picked || busy} onClick={submit}>
          {busy ? 'flagging…' : 'flag selected trace'}
        </button>
      </div>
      <div style={note}>
        The body is the fetched trace row sent back VERBATIM — a cognition trace is
        agent-produced evidence, so there is deliberately no field to type or paste one into.
        Your inputs are the selection above and the free-text reason.
        {picked ? ` Selected: ${String(picked.id).slice(0, 12)}.` : ' Nothing selected.'}
      </div>

      {res && res.ok && <FlagOutcome res={res} />}
      {res && !res.ok && <FlagFailure res={res} />}

      <div style={{ ...mono, fontSize: 10, color: 'var(--ink-3)', marginTop: 10, borderTop: '1px solid var(--panel-line)', paddingTop: 6 }}>
        {STATS_PATH} is unauthenticated; {SCORES_PATH.split('?')[0]}, {TRACES_PATH.split('?')[0]}{' '}
        and POST {FLAG_PATH} are user-tier (X-User-Token when the instance is network-exposed).
        No admin call on this panel. Voting, promote-to-dataset and the alert-threshold control
        live on the shipped REVIEW QUEUE and ANSWER QUALITY cards and are not repeated here.
      </div>
    </Card>
  );
}

/* The flag succeeded at the transport level — but "ok: true" does NOT mean a row was
   written. ReviewQueue.flag is idempotent per trace_id and returns the PRE-EXISTING item,
   with its original reason and original timestamp, still answering ok:true. So every field
   below is read off the RETURNED item, and the two facts that prove a no-op are called out:
   a reason that differs from the one sent, and a status other than "pending" (a freshly
   minted item is always pending with a null verdict). */
function FlagOutcome({ res }: { res: any }) {
  const item = res.item;
  if (!item || typeof item !== 'object') {
    return (
      <div role="alert" style={{ marginTop: 8, padding: 6, border: '1px solid var(--amber)', borderRadius: 4 }}>
        <div style={{ ...mono, fontSize: 10.5, color: 'var(--amber)' }}>
          the response carried no `item` — shown raw rather than interpreted.
        </div>
        <Json v={res.raw} />
      </div>
    );
  }
  const kept = str(item.reason) !== res.sent;
  const notPending = item.status !== 'pending';
  const preexisting = kept || notPending;
  const c = preexisting ? 'var(--amber)' : 'var(--green)';
  const sc = num(item.score);

  return (
    <div role="alert" style={{ marginTop: 8, padding: 6, border: `1px solid ${c}`, borderRadius: 4 }}>
      <div style={{ ...mono, fontSize: 10.5, color: c }}>
        {preexisting ? 'already queued' : 'flagged'} · item {str(item.id) || '(no id)'} · status{' '}
        {str(item.status) || '(none)'}
      </div>
      <div style={{ ...mono, fontSize: 10, color: 'var(--ink-2)', marginTop: 4 }}>
        trace_id {str(item.trace_id) || '(none)'} · reason: {str(item.reason) || '(null)'} · score{' '}
        {sc != null ? sc : '—'} · created {when(item.created_at) || '(none)'}
      </div>
      {sc == null && (
        <div style={note}>
          score is null: a trace summarized by GET /api/traces carries no `quality` key, so the
          store had nothing to record. Not a zero.
        </div>
      )}
      {kept && (
        <div style={{ marginTop: 4 }}>
          <Tag c="var(--amber)">already queued · reason kept: {str(item.reason) || '(null)'}</Tag>
          <div style={amber}>
            flag is idempotent per trace_id — a trace already in the queue returns its existing
            item unchanged, so the reason you typed ({res.sent}) was NOT applied and no new row
            was created.
          </div>
        </div>
      )}
      {notPending && !kept && (
        <div style={amber}>
          already queued · status {str(item.status)} — a newly flagged item is always "pending",
          so this row pre-dates your click and was returned unchanged.
        </div>
      )}
      {!preexisting && (
        <div style={note}>
          the reason above came back matching the one sent. That is consistent with a new row,
          but it cannot prove one: re-flagging a trace whose stored reason already equals yours
          returns the existing item and still answers ok:true, indistinguishably.
        </div>
      )}
    </div>
  );
}

/* apiPost throws on all three refusals plus the guard. Each backend string is printed as
   sent — "review queue not available" (503) and "trace required" (400) are distinct causes
   and are never collapsed into one sentence. */
function FlagFailure({ res }: { res: any }) {
  return (
    <div role="alert" style={{ marginTop: 8, padding: 6, border: '1px solid var(--red)', borderRadius: 4 }}>
      <div style={{ ...mono, fontSize: 10.5, color: 'var(--red)' }}>
        refused · HTTP {res.status != null ? res.status : '?'} · {res.msg}
      </div>
      <div style={{ ...mono, fontSize: 10, color: 'var(--ink-2)', marginTop: 4 }}>
        Nothing was flagged. The line above is the backend's own string, printed as sent.
      </div>
      {res.detail != null && <Json v={res.detail} />}
    </div>
  );
}
