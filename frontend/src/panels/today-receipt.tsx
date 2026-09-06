/* TODAY & RECEIPTS — the shareable "what Nerva did today" report and Proof-of-Action
   receipts (GET /api/report/today, POST /api/report/today/export,
   GET /api/report/receipt/{audit_id}; all user-guarded).

   The report is allow-listed and payload-free on the backend: task titles arrive
   already passed through the secret + PII scanners, and task payloads/results never
   exist in the response. This panel therefore renders what it receives and adds no
   "details" affordance — there is nothing more to fetch at this tier, by design.

   Honesty contract:
   · `empty:true` is rendered as the backend's own `reason` (e.g. "no autonomy decisions
     recorded on this day"), never as a row of zeros under a green chip; the chip is SEED
     whenever the queue source is missing.
   · An export is a governed effect (kernel kind report.export). The POST passes onErr
     and prints the refusal reason from the response body (`kernel_denied:…`,
     `approval_required`, `invalid_format`) — a refused export is never a silent no-op.
   · A receipt shows `verified` exactly as the backend computed it from the owner's
     hash chain: an unverified receipt is shown in amber with its reason, not hidden.

   NOTE: never spell a route path in this comment unless the panel calls it —
   tests/test_hud_v2_parity.py:_has_caller matches comment text as a caller. */
import React, { useState } from 'react';
import { apiGet } from '../api/client';
import { useApi, arr, mono, asLive, Card, State, Row, Tag, act, inpS } from '../panel-kit';

const TODAY_PATH = '/api/report/today';
const EXPORT_PATH = '/api/report/today/export';
const RECEIPT_PREFIX = '/api/report/receipt/';

const EM = '—';

const Note = ({ c, children }: { c?: any; children?: any }) => (
  <div style={{ fontSize: 10, lineHeight: 1.5, color: c || 'var(--ink-2)', padding: '3px 0 5px' }}>{children}</div>
);

const Head = ({ k }: { k: any }) => (
  <div style={{ ...mono, fontSize: 10, letterSpacing: '.08em', color: 'var(--ink-2)', marginTop: 10, marginBottom: 2 }}>{k}</div>
);

const Num = ({ n, k }: { n: any; k: any }) => (
  <div style={{ flex: 1, minWidth: 70 }}>
    <div style={{ fontSize: 22, color: 'var(--accent-light)', lineHeight: 1.1 }}>{n == null ? EM : String(n)}</div>
    <div style={{ ...mono, fontSize: 9, letterSpacing: '.08em', color: 'var(--ink-2)' }}>{k}</div>
  </div>
);

const STATUS_COLOR: Record<string, string> = {
  done: 'var(--green)',
  rejected: 'var(--amber)',
  failed: 'var(--red)',
};

const refusalText = (err: any) => {
  const reason = err?.body?.reason || err?.body?.error;
  if (reason) return `refused · ${String(reason)}`;
  return `refused · ${err?.status || 'error'}`;
};

export function TodayReceiptPanel() {
  const { d, e, loading, reload } = useApi(TODAY_PATH);
  const rep: any = d;
  const counts: any = (rep && rep.counts) || {};
  const ns: any = (rep && rep.north_star) || null;
  const actions: any[] = arr(rep, 'actions');
  const queueLive = !!(rep && rep.sources && rep.sources.queue === true);

  const [exportNote, setExportNote] = useState<string | null>(null);
  const [auditId, setAuditId] = useState('');
  const [receipt, setReceipt] = useState<any>(null);
  const [receiptErr, setReceiptErr] = useState<string | null>(null);

  // Governed effect: MUST carry onErr (panel-kit.tsx:93-97) — a kernel DENY answers
  // 403 and would otherwise read as success.
  const doExport = (format: 'json' | 'html') => act(EXPORT_PATH, { format },
    (r: any) => setExportNote(`exported ${format} · ${r?.path || 'ok'}`),
    (err: any) => setExportNote(refusalText(err)));

  const lookup = () => {
    const id = auditId.trim();
    setReceipt(null);
    setReceiptErr(null);
    if (!id) { setReceiptErr('enter an audit id (intent-log seq)'); return; }
    apiGet(RECEIPT_PREFIX + encodeURIComponent(id))
      .then((r) => setReceipt(r))
      .catch((err: any) => setReceiptErr(err?.status === 404 ? 'not found · no such entry'
        : err?.status === 400 ? 'bad audit id' : `receipt read failed · ${err?.status || 'error'}`));
  };

  const sub = rep ? (rep.empty ? `${rep.date} · empty` : `${rep.date} · ${counts.accepted ?? 0} accepted`) : null;

  return (
    <Card title="TODAY & RECEIPTS" live={asLive(d, queueLive)} sub={sub} onReload={reload}>
      <State e={e} loading={loading} n={rep ? 1 : 0} />

      {rep && rep.empty && (
        <Note c="var(--amber)">{rep.reason || 'nothing recorded for this day'}</Note>
      )}

      {rep && !rep.empty && (
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', padding: '6px 0' }}>
          <Num n={counts.accepted} k="ACCEPTED" />
          <Num n={counts.rejected} k="REJECTED" />
          <Num n={counts.night_shift} k="WHILE YOU SLEPT" />
          <Num n={counts.interrupts} k="INTERRUPTS" />
        </div>
      )}

      {rep && ns && (
        <Row>
          <span style={mono}>north-star</span>
          <span style={{ marginLeft: 'auto', display: 'flex', gap: 5, flexWrap: 'wrap' }}>
            <Tag>{ns.local_pct == null ? 'local: not measured' : `local ${ns.local_pct}%`}</Tag>
            <Tag>{ns.reject_rate == null ? 'reject: no decisions' : `reject ${ns.reject_rate}`}</Tag>
            <Tag c={ns.guardrails_ok ? 'var(--green)' : 'var(--amber)'}>{ns.guardrails_ok ? 'guardrails ok' : 'guardrail breach'}</Tag>
          </span>
        </Row>
      )}
      {rep && (
        <Row>
          <span style={mono}>model</span>
          <span style={{ marginLeft: 'auto' }}>
            <Tag>{rep.model && rep.model.name ? String(rep.model.name) : `${EM} not reported`}</Tag>
          </span>
        </Row>
      )}

      {actions.slice(0, 12).map((a, i) => (
        <Row key={a.task_id ?? i}>
          <span style={{ color: 'var(--accent-light)', flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{a.title}</span>
          <Tag>{a.kind}</Tag>
          {a.night ? <Tag c="var(--violet)">night</Tag> : null}
          <Tag c={STATUS_COLOR[a.status] || undefined}>{a.status}</Tag>
        </Row>
      ))}

      <div style={{ display: 'flex', gap: 6, marginTop: 8, alignItems: 'center' }}>
        <button className="tool-btn" onClick={() => doExport('json')} disabled={!rep}>export json</button>
        <button className="tool-btn" onClick={() => doExport('html')} disabled={!rep}>export card</button>
        {rep && rep.fingerprint && <Tag>{String(rep.fingerprint).slice(0, 12)}</Tag>}
      </div>
      {exportNote && (
        <Note c={exportNote.startsWith('refused') ? 'var(--amber)' : 'var(--ink-2)'}>{exportNote}</Note>
      )}
      <Note>
        Exports land under the local data root (reports/), never leave the machine, and cross the Action
        Kernel as report.export — a refusal is shown here with its reason.
      </Note>

      <Head k="PROOF-OF-ACTION RECEIPT" />
      <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
        <input
          aria-label="audit id"
          style={{ ...inpS, width: 90 }}
          placeholder="audit id"
          value={auditId}
          onChange={(ev) => setAuditId(ev.target.value)}
        />
        <button className="tool-btn" onClick={lookup}>verify</button>
      </div>
      {receiptErr && <Note c="var(--amber)">{receiptErr}</Note>}
      {receipt && (
        <div style={{ marginTop: 6 }}>
          <Row>
            <span style={mono}>#{String(receipt.audit_id)}</span>
            <span style={{ flex: 1, color: 'var(--ink)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{receipt.action}</span>
            {receipt.verified === true
              ? <Tag c="var(--green)">VERIFIED</Tag>
              : <Tag c="var(--amber)">{`UNVERIFIED${receipt.reason ? ' · ' + receipt.reason : ''}`}</Tag>}
          </Row>
          <Row>
            <span style={mono}>why</span>
            <span style={{ marginLeft: 'auto', color: 'var(--ink-2)', textAlign: 'right' }}>{receipt.why || EM}</span>
          </Row>
          <Row>
            <span style={mono}>decision</span>
            <span style={{ marginLeft: 'auto', display: 'flex', gap: 5 }}>
              <Tag>{receipt.decision && receipt.decision.verdict ? String(receipt.decision.verdict) : `${EM} no verdict`}</Tag>
              {receipt.decision && receipt.decision.tier != null && <Tag>tier {String(receipt.decision.tier)}</Tag>}
              <Tag c={receipt.signed ? 'var(--green)' : 'var(--amber)'}>{receipt.signed ? 'signed' : 'unsigned'}</Tag>
            </span>
          </Row>
          <Row>
            <span style={mono}>chain</span>
            <span style={{ marginLeft: 'auto', display: 'flex', gap: 5 }}>
              <Tag c={receipt.chain && receipt.chain.ok ? 'var(--green)' : 'var(--amber)'}>
                {receipt.chain && receipt.chain.ok ? 'chain ok' : 'chain broken'}
              </Tag>
              <Tag>{receipt.chain ? `${receipt.chain.entries} entries` : EM}</Tag>
              <Tag>{String(receipt.entry_hash || '').slice(0, 12)}</Tag>
            </span>
          </Row>
        </div>
      )}
      <Note>
        A receipt is one entry of the owner&rsquo;s own hash-chained, signed intent log, re-verified on read.
        Its free text has passed the same secret/PII scanners as the report.
      </Note>
    </Card>
  );
}
