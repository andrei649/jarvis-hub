/* PAYMENTS — the H16.3 governed-payment broker's two uncalled admin surfaces:
   the mandate ledger (GET/POST /api/payments/mandates) and the payment request
   (POST /api/payments/request). Handlers: agents/core/routers/payments.py:49/59/64,
   broker logic agents/core/payments.py.

   What this panel is NOT, deliberately:

   1. It is not a way to pay anyone. `agents/core/payments.py` is a GOVERNANCE layer,
      not a processor: there is no rail (AP2/ACP/x402) wired, and `settle()` records
      the literal string "settled (no real rail)" (payments.py:319) while moving no
      money. Choosing a rail is an owner decision, so no settle control exists here
      and no wording on this panel implies a payment completed.
   2. It does not duplicate the payment lifecycle. approve / reject / settle already
      ship in TrustMode (modes.tsx:225-238) over the already-called GET /api/payments;
      re-reading that list here would be a second panel over a byte-identical payload.
      A created request is rendered from the POST response instead.
   3. It does not add a second party. The same X-Admin-Token that creates a request
      can approve it in the Trust queue — this panel adds a control surface, not a
      separate approver.

   Honesty notes specific to this router:

   * There is NO component guard on it (it imports only admin_guard + nocache_json) and
     the broker is built lazily with JsonStore swallowing a missing/corrupt file into {}
     (persistence/json_store.py:78). So no 503 "component unavailable" can ever be
     emitted, and this panel renders no such branch — it would be fiction. An empty
     `mandates` list therefore means exactly "no mandates", never "unavailable".
   * apiGet throws WITHOUT a body (api/client.ts:108), so a failed read can only be
     shown as its verbatim `GET /api/payments/mandates -> <status>`. The guard's own
     401/403 detail string is unreachable on a GET and is never guessed at.
   * apiPost DOES carry the parsed refusal body (client.ts:98-103), so both writes pass
     onErr and print the backend's own string: `error` for the 400s, the `detail` ARRAY
     for a 422, `reason` for a payment denial. Those three shapes are not interchangeable
     and are rendered separately.
   * `remaining` exists ONLY on the list route (list_mandates, payments.py:177). The
     create response does not carry it, so it is never computed here — after a create the
     list is reloaded and the number comes from the backend. */
import React, { useState } from 'react';
import { useApi, arr, mono, asLive, Card, State, Row, Tag, actA, inpS, Json } from '../panel-kit';

const MANDATES_PATH = '/api/payments/mandates';
const REQUEST_PATH = '/api/payments/request';

/* Denial codes are the backend's own, evaluated in DECLARED order with the first
   violation short-circuiting (automation_contracts.py:266-270; predicates declared at
   payments.py:76-84). The gloss below never SUBSTITUTES for a code — the code is always
   printed verbatim first — and an unrecognised code (e.g. a fail-closed
   "constraint_error:<name>") gets no gloss at all rather than an invented one. */
const CONTRACT_ORDER = [
  'unknown_mandate', 'mandate_expired', 'invalid_amount', 'currency_mismatch',
  'payee_not_allowed', 'over_per_payment_cap', 'over_total_cap',
];
const DENIAL_GLOSS: Record<string, string> = {
  unknown_mandate: 'no mandate with that id exists in the broker store.',
  mandate_expired: "the mandate's expires_at is in the past.",
  invalid_amount: 'amount was not a positive number (pydantic gt=0 normally answers 422 before this predicate is reached).',
  currency_mismatch: "the request currency does not match the mandate's stored currency.",
  payee_not_allowed: "the payee is not in the mandate's allowlist.",
  over_per_payment_cap: "amount is above the mandate's per_payment_cap.",
  over_total_cap: 'spent + amount would exceed the mandate’s total_cap.',
  kernel_denied: 'the Action Kernel refused it. The router (payments.py router:71) forwards only the code — the kernel’s own reason is dropped before it reaches this client, so nothing more can honestly be said here.',
};

const num = (v) => (Number.isFinite(Number(v)) ? String(Number(v)) : '—');
const stamp = (sec) => (Number.isFinite(Number(sec))
  ? new Date(Number(sec) * 1000).toISOString().slice(0, 19).replace('T', ' ') + 'Z'
  : '—');
const positive = (s) => Number.isFinite(Number(s)) && String(s).trim() !== '' && Number(s) > 0;

export function PaymentsPanel() {
  const { d, e, loading, reload } = useApi(MANDATES_PATH, true, true);   // admin-tier read
  const mandates = arr(d, 'mandates');
  const loaded = !!d && !e;

  const [selId, setSelId] = useState('');
  const sel = mandates.find((m) => m && m.id === selId) || null;

  // create-mandate form
  const [payees, setPayees] = useState('');
  const [perCap, setPerCap] = useState('');
  const [totCap, setTotCap] = useState('');
  const [currency, setCurrency] = useState('EUR');
  const [ttl, setTtl] = useState('');
  const [cNote, setCNote] = useState(null);
  const [cBusy, setCBusy] = useState(false);

  // request-payment form
  const [payee, setPayee] = useState('');
  const [amount, setAmount] = useState('');
  const [memo, setMemo] = useState('');
  const [rNote, setRNote] = useState(null);
  const [rBusy, setRBusy] = useState(false);

  const payeeList = payees.split(',').map((s) => s.trim()).filter(Boolean);
  const ttlBad = ttl.trim() !== '' && !positive(ttl);
  const canCreate = payeeList.length > 0 && positive(perCap) && positive(totCap) && !ttlBad && !cBusy;

  const selPayees = sel ? (Array.isArray(sel.payees) ? sel.payees : []) : [];
  const chosenPayee = selPayees.includes(payee) ? payee : (selPayees.length === 1 ? selPayees[0] : '');
  const canRequest = !!sel && !!chosenPayee && positive(amount) && !rBusy;

  /* A mandate is expired when now > expires_at — the SAME comparison the backend's
     `not_expired` predicate makes (payments.py:57-58). It is derived here, and labelled
     as derived; the backend remains the authority and answers `mandate_expired`. */
  const isExpired = (m) => !!(m && m.expires_at) && (Date.now() / 1000) > Number(m.expires_at);

  /* Shared refusal renderer for both writes. Three distinct shapes, never collapsed:
     400 -> the backend's `error` string (and `reason` for a denial), 422 -> FastAPI's
     `detail` ARRAY, everything else -> status + the guard's own detail or the throw
     message. Nothing is invented for a shape that did not arrive. */
  const refusal = (err) => {
    const status = err && err.status;
    const body: any = (err && err.body) || null;
    if (status === 422) {
      return { kind: 'err', text: 'refused · 422 · request rejected by validation', detail: (body && body.detail) };
    }
    if (status === 400 && body && body.error !== undefined) {
      return { kind: 'err', text: String(body.error), detail: undefined };
    }
    const cause = (body && (typeof body.detail === 'string' ? body.detail : body.error)) || (err && err.message) || 'refused';
    return { kind: 'err', text: `refused · ${status || '?'} · ${cause}`, detail: undefined };
  };

  const createMandate = () => {
    if (!canCreate) return;
    const body: any = {
      payees: payeeList,
      per_payment_cap: Number(perCap),
      total_cap: Number(totCap),
      currency: currency.trim(),
    };
    // Blank ttl => key OMITTED => backend default None => expires_at null => no expiry.
    if (ttl.trim() !== '') body.ttl_seconds = Number(ttl);
    setCBusy(true);
    setCNote(null);
    actA(MANDATES_PATH, body,
      (r: any) => {
        setCBusy(false);
        // The create response has no `remaining` key — reload so that number is the
        // backend's, never this panel's arithmetic.
        setCNote({ kind: 'ok', text: `mandate created · ${r && r.id} · ${num(r && r.total_cap)} ${r && r.currency} total, per-payment ≤ ${num(r && r.per_payment_cap)} · ${(r && Array.isArray(r.payees) ? r.payees : []).length} payee(s) · ${r && r.expires_at ? `expires ${stamp(r.expires_at)}` : 'no expiry'}` });
        reload();
      },
      (err) => { setCBusy(false); setCNote(refusal(err)); });
  };

  const requestPayment = () => {
    if (!canRequest || !sel) return;
    // mandate_id and currency come from the row the operator selected, and payee from
    // that mandate's own allowlist — a free-text payee or currency here would only
    // manufacture payee_not_allowed / currency_mismatch out of a UI choice.
    const body = {
      mandate_id: sel.id,
      payee: chosenPayee,
      amount: Number(amount),
      currency: sel.currency,
      memo,
    };
    setRBusy(true);
    setRNote(null);
    actA(REQUEST_PATH, body,
      (p: any) => {
        setRBusy(false);
        setRNote({
          kind: 'ok',
          // status is printed from the response, not assumed.
          text: `${p && p.id} · ${p && p.status} · ${num(p && p.amount)} ${p && p.currency} → ${p && p.payee}`,
          sub: `${p && p.memo ? `memo "${p.memo}" · ` : ''}recorded as a request awaiting approval. No money has moved and no rail was contacted; approve or reject it in the Trust queue.`,
        });
      },
      (err) => {
        setRBusy(false);
        const body: any = (err && err.body) || null;
        if (err && err.status === 400 && body && body.reason) {
          const code = String(body.reason);
          const known = DENIAL_GLOSS[code];
          setRNote({
            kind: 'err',
            text: `payment denied · ${code}`,
            // No gloss at all for a code this panel does not know (e.g. constraint_error:*).
            sub: known ? `backend code, verbatim. ${known}` : 'backend code, verbatim. This panel has no gloss for it and will not invent one.',
          });
          return;
        }
        setRNote(refusal(err));
      });
  };

  const note = (n) => (n ? (
    <div role="alert" style={{ ...mono, fontSize: 11, marginTop: 6, color: n.kind === 'err' ? 'var(--red)' : 'var(--green)' }}>
      <div>{n.text}</div>
      {n.sub ? <div style={{ color: 'var(--ink-3)', fontSize: 10, marginTop: 2 }}>{n.sub}</div> : null}
      {n.detail !== undefined && n.detail !== null ? <Json v={n.detail} /> : null}
    </div>
  ) : null);

  return (
    <Card
      title="PAYMENTS"
      live={asLive(d, mandates.length > 0)}
      sub={loaded ? `${mandates.length} mandate(s)` : null}
      onReload={reload}
    >
      {/* A read failure and an empty ledger are separate branches: a 401/403 here never
          renders as "0 mandates". apiGet throws without a body, so this string is all the
          panel can honestly know about the cause. */}
      <State e={e} loading={loading} n={loaded ? mandates.length : null} />

      {loaded && mandates.length === 0 && (
        <div style={{ ...mono, fontSize: 11, color: 'var(--amber)', padding: '4px 0' }}>
          no mandate authorized — the broker holds an empty allowlist, so every payment request is
          denied with the contract's first predicate, <b>unknown_mandate</b> (payments.py:77).
          This is a real empty ledger, not an outage: this router has no component guard and cannot
          report one.
        </div>
      )}

      {mandates.map((m, i) => (
        <Row key={(m && m.id) || i}>
          <span style={{ ...mono, color: 'var(--accent-light)' }}>{m && m.id}</span>
          <span style={{ display: 'flex', gap: 4, alignItems: 'center', flexWrap: 'wrap' }}>
            <Tag>{m && m.currency}</Tag>
            <Tag>per ≤ {num(m && m.per_payment_cap)}</Tag>
            <Tag>total {num(m && m.total_cap)}</Tag>
            <Tag>spent {num(m && m.spent)}</Tag>
            {/* `remaining` is added by list_mandates only — shown as — if absent, never computed. */}
            <Tag>remaining {m && Object.prototype.hasOwnProperty.call(m, 'remaining') ? num(m.remaining) : '—'}</Tag>
            {m && m.expires_at
              ? (
                <Tag c={isExpired(m) ? 'var(--red)' : undefined}>
                  {isExpired(m) ? 'expired ' : 'expires '}{stamp(m.expires_at)}
                </Tag>
              )
              : <Tag>no expiry</Tag>}
          </span>
          <span style={{ ...mono, fontSize: 10, color: 'var(--ink-3)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {(m && Array.isArray(m.payees) ? m.payees : []).join(' · ')}
          </span>
          <button
            className="tool-btn"
            style={{ marginLeft: 'auto' }}
            onClick={() => { setSelId(m && m.id); setPayee(''); setRNote(null); }}
            title="use this mandate for the request below"
          >{selId && m && selId === m.id ? 'selected' : 'select'}</button>
        </Row>
      ))}

      {mandates.some((m) => isExpired(m)) && (
        <div style={{ fontSize: 10, color: 'var(--ink-3)', marginTop: 4 }}>
          "expired" is derived here from <b>expires_at</b> vs this browser's clock — the same
          comparison the backend's not_expired predicate makes with the server's clock. The backend
          remains the authority and answers <b>mandate_expired</b>.
        </div>
      )}

      {/* ── create mandate (admin) ─────────────────────────────────────────────
          A genuine owner input: an allowlist of payees, two caps, a currency and an
          expiry. Nothing here is agent-produced. */}
      <div style={{ ...mono, fontSize: 9.5, letterSpacing: '.14em', color: 'var(--ink-3)', margin: '10px 0 2px' }}>
        AUTHORIZE A MANDATE (ADMIN)
      </div>
      <Row>
        <input
          value={payees}
          onChange={(ev) => setPayees(ev.target.value)}
          placeholder="payees, comma-separated (e.g. acme-gmbh, hetzner)"
          style={{ ...inpS, flex: 1, minWidth: 160 }}
        />
        <input value={perCap} onChange={(ev) => setPerCap(ev.target.value)} placeholder="per-payment cap" type="number" style={{ ...inpS, width: 110 }} />
        <input value={totCap} onChange={(ev) => setTotCap(ev.target.value)} placeholder="total cap" type="number" style={{ ...inpS, width: 90 }} />
        <input value={currency} onChange={(ev) => setCurrency(ev.target.value)} placeholder="EUR" maxLength={8} style={{ ...inpS, width: 60 }} title="max 8 chars; the backend uppercases it" />
        <input value={ttl} onChange={(ev) => setTtl(ev.target.value)} placeholder="ttl secs (blank = none)" type="number" style={{ ...inpS, width: 130 }} />
        <button className="tool-btn" onClick={createMandate} disabled={!canCreate}>
          {cBusy ? 'creating…' : 'create mandate'}
        </button>
      </Row>
      <div style={{ fontSize: 10, color: 'var(--ink-3)' }}>
        {payeeList.length > 0 ? `${payeeList.length} payee(s): ${payeeList.join(' · ')} — ` : 'at least one payee is required — '}
        a blank ttl omits the field, so expires_at is null and the mandate never expires.
        {ttlBad ? ' ttl must be a number greater than 0 (the backend declares gt=0).' : ''}
        {' '}The backend does <b>not</b> require per_payment_cap ≤ total_cap; it accepts whatever
        two positive numbers you give it.
      </div>
      {note(cNote)}

      {/* ── request a payment (admin) ──────────────────────────────────────────── */}
      <div style={{ ...mono, fontSize: 9.5, letterSpacing: '.14em', color: 'var(--ink-3)', margin: '10px 0 2px' }}>
        REQUEST A PAYMENT AGAINST A MANDATE (ADMIN)
      </div>
      {!sel ? (
        <div style={{ fontSize: 12, color: 'var(--ink-3)', padding: '4px 0' }}>
          select a mandate above — a request needs a mandate id, and this panel composes it from a
          row it actually fetched rather than from anything typed here.
        </div>
      ) : (
        <>
          <Row>
            <span style={{ ...mono, color: 'var(--ink-2)' }}>mandate {sel.id}</span>
            <Tag>currency {sel.currency}</Tag>
            <Tag>per ≤ {num(sel.per_payment_cap)}</Tag>
            <Tag>remaining {Object.prototype.hasOwnProperty.call(sel, 'remaining') ? num(sel.remaining) : '—'}</Tag>
            {isExpired(sel) && <Tag c="var(--red)">expired {stamp(sel.expires_at)}</Tag>}
          </Row>
          <Row>
            <select
              value={chosenPayee}
              onChange={(ev) => setPayee(ev.target.value)}
              style={{ ...inpS, minWidth: 140 }}
              title="payees allowed by this mandate"
            >
              <option value="">choose a payee…</option>
              {selPayees.map((p) => <option key={p} value={p}>{p}</option>)}
            </select>
            <input value={amount} onChange={(ev) => setAmount(ev.target.value)} placeholder="amount" type="number" style={{ ...inpS, width: 100 }} />
            <span style={{ ...mono, fontSize: 11, color: 'var(--ink-3)' }} title="not an input — taken from the selected mandate and sent as-is">
              {sel.currency}
            </span>
            <input value={memo} onChange={(ev) => setMemo(ev.target.value)} placeholder="memo (optional, ≤280)" maxLength={280} style={{ ...inpS, flex: 1, minWidth: 120 }} />
            <button className="tool-btn" onClick={requestPayment} disabled={!canRequest}>
              {rBusy ? 'requesting…' : 'request (pending)'}
            </button>
          </Row>
          <div style={{ fontSize: 10, color: 'var(--ink-3)' }}>
            Currency is not an input: the selected mandate's <b>{sel.currency}</b> is sent, so the UI
            cannot manufacture a currency_mismatch — the backend still denies one verbatim if it
            ever disagrees. The payee list is this mandate's own allowlist for the same reason.
            {positive(amount) && Number(amount) > Number(sel.per_payment_cap)
              ? ' The amount you entered is above the per-payment cap shown above; send it and the backend answers with its own denial code.'
              : ''}
          </div>
        </>
      )}
      {note(rNote)}

      {/* ── footer: every claim below is from the handler or the broker ───────── */}
      <div style={{ fontSize: 10, color: 'var(--ink-3)', marginTop: 8 }}>
        All three routes on this panel are admin-tier (X-Admin-Token): the mandate list read, the
        mandate create and the payment request (routers/payments.py:49/59/64).
        <br />
        <b>Nothing here pays anyone.</b> A 200 on the request route means a record with status
        "pending" exists — payments.py:239 hardcodes it and the module states there is no
        auto-approve at any amount. No payment rail is wired: settle() records the string
        "settled (no real rail)" (payments.py:319) and moves no money, and picking a rail is an
        owner decision — so there is no settle control here.
        <br />
        approve / reject / settle are not duplicated on this panel: they already ship in the Trust
        queue over GET /api/payments. Note that the same admin token that creates a request can
        approve it there — this panel adds a control surface, not a second party.
        <br />
        <b>spent</b> and <b>remaining</b> only move at settle (payments.py:313). Pending and
        approved payments reserve nothing, so two approved requests can together exceed
        <b> remaining</b>, and the second is auto-rejected at settle with reason over_total_cap
        (payments.py:306-312). Read <b>remaining</b> as "total_cap − settled spend", not as
        headroom.
        <br />
        Denial codes are the backend's, printed verbatim, in its evaluation order — first violation
        short-circuits: {CONTRACT_ORDER.join(' → ')}. A kernel refusal adds <b>kernel_denied</b>
        (its underlying reason is dropped by the router and is not shown), and a predicate that
        itself raises fails closed as constraint_error:&lt;name&gt;.
      </div>
    </Card>
  );
}
