/* WRITEBACK & DIGEST — two shipped, user-tier routes that no client ever called.

   Handlers read in full before writing a line of this:
     * GET  /api/integrations/writeback  — agents/core/routers/integrations.py:43
     * POST /api/integrations/writeback  — agents/core/routers/integrations.py:53
       (governance layer: agents/core/writeback.py, WriteBackBroker.request)
     * POST /api/digest/run              — agents/core/routers/tools.py:57
       (engine: agents/core/digest.py, build_default_aggregator / DigestAggregator.run)

   The five things this panel refuses to say, each pinned to the source that would
   have made it a lie:

   1. "It was written to Notion / GitHub / Calendar." POST /api/integrations/writeback
      performs ZERO network I/O. It validates against _CATALOG, evaluates
      WRITEBACK_DRAFT_CONTRACT and — at most — enqueues an ask-tier task
      (writeback.py:437-449). The external call happens later in
      WriteBackBroker.execute, only for an already-APPROVED task, and even then an
      unconfigured host answers {"status":"deferred", reason
      "writeback_credential_not_configured"} (NullWriteBackClient) — an outcome this
      route cannot observe. So the queued line says "held for approval", never "sent".

   2. "queued" as a synonym for success. The 200 body has TWO shapes and the
      difference is the whole point of this card: with an enqueue sink bound
      (autonomy_coordinator.py:783) it is {ok:true, queued:true, task_id, …}; with no
      sink it is {ok:true, queued:false, …payload} — validation + dry-run only,
      writeback.py:435-437, nothing in any queue and nothing that will ever run.
      queued:false is rendered AMBER and says so in words.

   3. "The credential is configured." The GET returns only the secret's NAME
      (writeback.py:_CREDENTIAL) and the POST only the "{{secret:…}}" handle
      (SecretBroker.reference). No route in this lane reports whether that secret
      exists, so this panel states that limit instead of guessing, and offers no
      "configure credential" control — there is no route for one.

   4. "The write-back rail is live because the catalog loaded." It is not evidence:
      integrations.py:47-49 falls back to a throwaway `WriteBackBroker()` when the
      orchestrator is absent and returns the byte-identical static catalog. The LIVE
      chip is therefore driven ONLY by a POST's own `queued` field, and stays absent
      until one has come back.

   5. digest count 0 as "no results". DigestSource.fetch swallows EVERY exception and
      returns [] (digest.py:104-110), and parse_feed returns [] for a malformed or
      hostile feed and when defusedxml is missing (digest.py:66-76). The response
      carries no per-source status, so 0 means "nothing matched" OR "all the feeds
      failed" and the panel says exactly that.

   Refusal handling: apiPost THROWS on 4xx and carries the parsed body on the error
   (api/client.ts failMutation → err.status / err.body / err.message). Both writes here
   pass onErr and print the backend's own words — `reason` verbatim
   (unknown_target_action | missing_fields | invalid_kind | credential_ref_mismatch |
   contract_error | enqueue_failed | a free-form Action-Kernel deny string) plus its
   missing/required/supported arrays, with the whole body dumped as JSON underneath so
   FastAPI's {"detail":[…]} and JARVIS-INTERNAL-001 arrive intact. Nothing is
   paraphrased and no two causes are collapsed into one sentence. (The shipped
   SafeCommsDraftPanel's `reason: err?.message` prints "POST … -> 422" instead of the
   cause; that bug is deliberately not copied.)

   Tier: both routes are Depends(user_guard). No actA, no useApi(…, true) in this file. */
import React, { useState } from 'react';
import { useApi, arr, mono, asLive, Card, State, Row, Tag, act, inpS, taS, Json } from '../panel-kit';

/* Plain literals — this is what the HUD parity gate matches, and what the operator
   can grep back to the router. */
const WRITEBACK_PATH = '/api/integrations/writeback';
const DIGEST_PATH = '/api/digest/run';

const AMBER = 'var(--amber)';
const GREEN = 'var(--green)';
const INK3 = 'var(--ink-3)';

/* WIDGET hints only — never a source of field NAMES. Every input this panel renders is
   generated from the selected entry's own `required`/`optional` arrays as returned by
   the GET, so a catalog change reaches the form without a frontend edit.
   `LIST_FIELDS` mirrors writeback.py:_LIST_FIELDS (the broker coerces a bare string to a
   ONE-element list, which would silently turn "bug, urgent" into a single label — so the
   panel splits on commas itself and labels the input as doing that).
   `PROSE_FIELDS` is writeback.py:_LONG_FIELDS plus notion's `text`, and only decides
   textarea-vs-input. */
const LIST_FIELDS = new Set(['labels', 'assignees', 'attendees']);
const PROSE_FIELDS = new Set(['content', 'body', 'description', 'text']);

const Head = ({ k, note }: { k: any; note?: any }) => (
  <div style={{ marginTop: 12, marginBottom: 4 }}>
    <div style={{ ...mono, fontSize: 10, letterSpacing: '.08em', color: 'var(--accent-light)' }}>{k}</div>
    {note && <div style={{ fontSize: 10, color: INK3, marginTop: 2, lineHeight: 1.45 }}>{note}</div>}
  </div>
);
const Note = ({ c, children }: { c?: any; children?: any }) => (
  <div style={{ fontSize: 10.5, lineHeight: 1.5, color: c || INK3, marginTop: 6 }}>{children}</div>
);
const Right = ({ children }: { children?: any }) => (
  <span style={{ marginLeft: 'auto', display: 'flex', gap: 5, alignItems: 'center', flexWrap: 'wrap' }}>{children}</span>
);
const listOf = (v: any): any[] => (Array.isArray(v) ? v : []);

export function WritebackDigestPanel() {
  /* ── governed write-back ─────────────────────────────────────────────────── */
  const { d, e, loading, reload } = useApi(WRITEBACK_PATH);
  const targets = arr(d, 'targets');

  const [choice, setChoice] = useState('');
  const [vals, setVals] = useState<Record<string, string>>({});
  const [agent, setAgent] = useState('pepper');
  const [wbOut, setWbOut] = useState<any>(null);
  const [wbErr, setWbErr] = useState<any>(null);
  const [sending, setSending] = useState(false);

  const keyOf = (t: any) => `${t && t.target}:${t && t.action}`;
  const selectedKey = choice || (targets[0] ? keyOf(targets[0]) : '');
  const selected = targets.find((t: any) => keyOf(t) === selectedKey) || targets[0] || null;
  const required = selected ? listOf(selected.required) : [];
  const optional = selected ? listOf(selected.optional) : [];
  /* Mirrors the broker's own _present rule (writeback.py:103-110) on the required keys,
     so the routine "missing_fields" 422 is prevented rather than explained away after
     the fact. Every OTHER refusal still reaches the operator verbatim. */
  const ready = !!selected && required.every((k: any) => (vals[k] || '').trim() !== '');

  const pick = (v: string) => { setChoice(v); setVals({}); setWbOut(null); setWbErr(null); };
  const setVal = (k: string, v: string) => setVals((p) => ({ ...p, [k]: v }));

  const queue = () => {
    if (!selected || !ready || sending) return;
    const fields: Record<string, any> = {};
    for (const name of [...required, ...optional]) {
      const raw = (vals[name] || '').trim();
      if (!raw) continue;
      fields[name] = LIST_FIELDS.has(name)
        ? raw.split(',').map((s) => s.trim()).filter(Boolean)
        : raw;
    }
    setSending(true);
    act(
      WRITEBACK_PATH,
      {
        target: selected.target,
        action: selected.action,
        fields,
        agent: agent.trim() || 'pepper',
        source: 'hud.writeback_panel',
      },
      (r: any) => { setWbOut(r); setWbErr(null); setSending(false); if (r && r.queued === true) setVals({}); },
      (err: any) => { setWbOut(null); setWbErr(err); setSending(false); },
    );
  };

  /* The ONLY honest evidence about the approval queue this lane can obtain: the GET is
     identical with and without an orchestrator, so the chip stays absent until a POST
     has reported its own `queued`. */
  const sinkKnown = !!wbOut && typeof wbOut.queued === 'boolean';
  const live = asLive(sinkKnown, sinkKnown && wbOut.queued === true);

  /* ── topic digest ────────────────────────────────────────────────────────── */
  const [topic, setTopic] = useState('');
  const [limit, setLimit] = useState('10');
  const [sources, setSources] = useState<string[] | null>(null);   // learned from run #1
  const [sel, setSel] = useState<string[]>([]);
  const [res, setRes] = useState<any>(null);
  const [dErr, setDErr] = useState<any>(null);
  const [running, setRunning] = useState(false);

  const limitN = Number(limit);
  const limitOk = Number.isInteger(limitN) && limitN >= 1 && limitN <= 50;   // tools.py:51 ge=1 le=50
  /* sources:[] is FALSY in `names = names or list(SOURCE_TEMPLATES)` (digest.py:180) — an
     empty array silently runs ALL five feeds. So an empty selection disables the button
     instead of being sent. */
  const noneSelected = sources !== null && sel.length === 0;
  const canRun = limitOk && !noneSelected && !running;
  const toggle = (n: string) => setSel((p) => (p.includes(n) ? p.filter((x) => x !== n) : [...p, n]));

  const runDigest = () => {
    if (!canRun) return;
    const body: any = { topic: topic.trim(), limit: limitN };
    if (sources !== null) body.sources = sel;   // never [] — canRun forbids it
    setRunning(true);
    act(
      DIGEST_PATH,
      body,
      (r: any) => {
        setRes(r); setDErr(null); setRunning(false);
        /* Learn the real catalog from the backend's own echo (there is no GET that
           lists digest.SOURCE_TEMPLATES), once, on the first run. */
        const echoed = arr(r, 'sources');
        if (sources === null && echoed.length) { setSources(echoed as string[]); setSel(echoed as string[]); }
      },
      (err: any) => { setRes(null); setDErr(err); setRunning(false); },
    );
  };

  const items = arr(res, 'items');
  const sub = [
    d ? `${targets.length} write actions` : null,
    res ? `digest ${res.count} items` : null,
  ].filter(Boolean).join(' · ') || null;

  return (
    <Card title="WRITEBACK & DIGEST" live={live} sub={sub} onReload={reload}>
      <Head
        k="GOVERNED WRITE-BACK"
        note="GET/POST /api/integrations/writeback — the allowlist of external writes, and the front door that turns one into an ask-tier task."
      />
      <State e={e} loading={loading} n={targets.length} />

      {targets.map((t: any, i: number) => (
        <Row key={t.kind || i}>
          <span style={{ ...mono, color: 'var(--accent-light)' }}>{t.label || `${t.target}.${t.action}`}</span>
          <Right>
            <Tag>{t.kind || `${t.target}.${t.action}`}</Tag>
            {t.credential && <Tag>needs {t.credential}</Tag>}
            <Tag>req: {listOf(t.required).join(', ') || '—'}</Tag>
          </Right>
        </Row>
      ))}

      {d && (
        <Note>
          `credential` is only the NAME of the secret the executor resolves at approval time
          (SecretBroker.reference &rarr; {'{{secret:…}}'}); this panel cannot see whether it is configured.
          The catalog is also served identically with no orchestrator bound (integrations.py:47-49),
          so a successful read here proves nothing about the approval queue behind it.
        </Note>
      )}

      {selected && (
        <>
          <div style={{ display: 'grid', gridTemplateColumns: 'minmax(140px,1.4fr) minmax(80px,.6fr)', gap: 6, marginTop: 8 }}>
            <select aria-label="write-back action" value={selectedKey} onChange={(ev) => pick(ev.target.value)} style={inpS}>
              {targets.map((t: any) => (
                <option key={t.kind || keyOf(t)} value={keyOf(t)}>{t.label || `${t.target}.${t.action}`}</option>
              ))}
            </select>
            <input value={agent} onChange={(ev) => setAgent(ev.target.value)} placeholder="agent" style={inpS} />
          </div>

          {/* Inputs generated from THIS entry's required/optional arrays — no field name
              is hardcoded anywhere in this file. */}
          <div style={{ display: 'grid', gap: 6, marginTop: 6 }}>
            {[...required.map((n: any) => [n, true] as const), ...optional.map((n: any) => [n, false] as const)].map(([name, req]) => {
              const hint = LIST_FIELDS.has(name)
                ? `${name} · ${req ? 'required' : 'optional'} · comma-separated list`
                : `${name} · ${req ? 'required' : 'optional'}`;
              return PROSE_FIELDS.has(name)
                ? <textarea key={name} value={vals[name] || ''} onChange={(ev) => setVal(name, ev.target.value)} placeholder={hint} style={{ ...taS, minHeight: 52 }} />
                : <input key={name} value={vals[name] || ''} onChange={(ev) => setVal(name, ev.target.value)} placeholder={hint} style={inpS} />;
            })}
          </div>

          <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginTop: 6, flexWrap: 'wrap' }}>
            <button className="tool-btn" disabled={!ready || sending} onClick={queue}>queue write-back</button>
            <span style={{ fontSize: 10, color: INK3 }}>
              {ready ? 'validates, then holds it for your approval — no external call happens here' : 'every required field must be filled'}
            </span>
          </div>
        </>
      )}

      {wbOut && wbOut.queued === true && (
        <div role="alert">
          <div style={{ ...mono, fontSize: 10.5, color: GREEN, marginTop: 8 }}>
            queued for approval · task #{String(wbOut.task_id)} · {String(wbOut.kind || '')}
          </div>
          <Note>
            Held as an ask-tier task. NOTHING has been written to {String((selected && selected.target) || 'the external system')} —
            the API call runs later, in WriteBackBroker.execute, only after you approve it, and an unconfigured
            host defers it instead (a result this route never reports back).
          </Note>
          {wbOut.preview && wbOut.preview.summary && (
            <div style={{ ...mono, fontSize: 10, color: INK3, marginTop: 4 }}>{String(wbOut.preview.summary)}</div>
          )}
          <Json v={wbOut.preview} />
        </div>
      )}

      {wbOut && wbOut.queued === false && (
        <div role="alert">
          <div style={{ ...mono, fontSize: 10.5, color: AMBER, marginTop: 8 }}>
            validation-only preview — no approval queue is attached, nothing was queued
          </div>
          <Note c={AMBER}>
            The broker had no enqueue sink (writeback.py:435-437), so this request was validated and
            previewed and then discarded. There is no task to approve and nothing will ever run.
            The sanitized payload the backend built is below, verbatim.
          </Note>
          <Json v={wbOut} />
        </div>
      )}

      {wbOut && typeof wbOut.queued !== 'boolean' && (
        <div role="alert">
          <div style={{ ...mono, fontSize: 10.5, color: AMBER, marginTop: 8 }}>
            unrecognised 200 body — neither queued:true nor queued:false; shown as received
          </div>
          <Json v={wbOut} />
        </div>
      )}

      {wbErr && (
        <div role="alert">
          <div style={{ ...mono, fontSize: 10.5, color: AMBER, marginTop: 8 }}>
            refused ({String(wbErr.status || '?')}){wbErr.body && wbErr.body.reason ? ` · ${String(wbErr.body.reason)}` : ''}
          </div>
          {wbErr.body && Array.isArray(wbErr.body.missing) && (
            <div style={{ ...mono, fontSize: 10, color: AMBER }}>missing: {wbErr.body.missing.join(', ')}</div>
          )}
          {wbErr.body && Array.isArray(wbErr.body.required) && (
            <div style={{ ...mono, fontSize: 10, color: INK3 }}>required: {wbErr.body.required.join(', ')}</div>
          )}
          {wbErr.body && Array.isArray(wbErr.body.supported) && (
            <div style={{ ...mono, fontSize: 10, color: INK3 }}>supported: {wbErr.body.supported.join(', ')}</div>
          )}
          {/* The backend's own body, untouched — covers the free-form Action-Kernel deny
              reason, FastAPI's {"detail":[…]} and the JARVIS-* error envelopes. */}
          <Json v={wbErr.body != null ? wbErr.body : wbErr.message} />
        </div>
      )}

      <Note>
        user tier · POST validates against the allowlist and (when a queue is attached) enqueues an
        ask-tier task; the external API call happens only after you approve it, and the credential is
        injected at that moment.
      </Note>

      {/* ── digest ───────────────────────────────────────────────────────────── */}
      <Head
        k="TOPIC DIGEST"
        note="POST /api/digest/run — fetches public RSS/Atom feeds server-side and ranks them by weight × idea-reality. No GET exists, so nothing runs until you ask."
      />

      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(140px,1fr) 80px', gap: 6 }}>
        <input value={topic} onChange={(ev) => setTopic(ev.target.value)} maxLength={200} placeholder="topic (optional, max 200)" style={inpS} />
        <input value={limit} onChange={(ev) => setLimit(ev.target.value)} type="number" min={1} max={50} placeholder="limit" style={inpS} />
      </div>

      {sources === null ? (
        <Note>
          The source list is not hardcoded here and no route lists it — the first run omits `sources`
          (which the backend reads as all built-ins) and the chips below are built from the `sources`
          array that run echoes back.
        </Note>
      ) : (
        <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap', marginTop: 6 }}>
          {sources.map((n) => (
            <button
              key={n}
              className="tool-btn"
              aria-pressed={sel.includes(n)}
              onClick={() => toggle(n)}
              style={{ opacity: sel.includes(n) ? 1 : 0.45 }}
            >
              {n}
            </button>
          ))}
        </div>
      )}

      <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginTop: 6, flexWrap: 'wrap' }}>
        <button className="tool-btn" disabled={!canRun} onClick={runDigest}>{running ? 'running…' : 'run digest'}</button>
        {!limitOk && <span style={{ fontSize: 10, color: AMBER }}>limit must be a whole number 1–50 (the route&rsquo;s own ge/le bounds)</span>}
        {noneSelected && <span style={{ fontSize: 10, color: AMBER }}>select at least one source — an empty list would silently run all of them</span>}
        {limitOk && !noneSelected && !res && !dErr && <span style={{ fontSize: 10, color: INK3 }}>not run yet</span>}
      </div>

      {dErr && (
        <div role="alert">
          <div style={{ ...mono, fontSize: 10.5, color: AMBER, marginTop: 8 }}>
            request failed ({String(dErr.status || '?')}) — this is a refusal, not an empty digest
          </div>
          <Json v={dErr.body != null ? dErr.body : dErr.message} />
        </div>
      )}

      {res && (
        <div style={{ marginTop: 8 }}>
          <div style={{ ...mono, fontSize: 10, color: INK3 }}>
            {String(res.count)} items · sources composed: {arr(res, 'sources').join(', ') || '—'}
            {res.topic ? ` · topic "${String(res.topic)}"` : ' · no topic'}
          </div>
          {res.count === 0 && (
            <Note c={AMBER}>
              0 items · this endpoint reports no per-source errors: a feed that failed, timed out or was
              blocked returns silently empty (digest.py DigestSource.fetch swallows every exception;
              parse_feed returns [] on a malformed feed or a missing defusedxml). So this is either
              &ldquo;nothing matched&rdquo; or &ldquo;a fetch failed&rdquo; — the response cannot tell you which.
              Server logs (jarvis.digest) have the reason.
            </Note>
          )}
          {items.map((it: any, i: number) => (
            <Row key={(it && it.link) || (it && it.title) || i}>
              {it && it.link
                ? <a href={String(it.link)} target="_blank" rel="noreferrer noopener" style={{ ...mono, color: 'var(--accent-light)' }}>{String(it.title || it.link)}</a>
                : <span style={{ ...mono, color: 'var(--accent-light)' }}>{String((it && it.title) || '—')}</span>}
              <Right>
                {it && it.source && <Tag>{String(it.source)}</Tag>}
                {it && it.reality != null && <Tag>reality {String(it.reality)}</Tag>}
                {it && it.score != null && <Tag>score {String(it.score)}</Tag>}
                {it && it.tainted && <Tag c={AMBER}>external · {String(it.taint_source || '')}</Tag>}
              </Right>
            </Row>
          ))}
        </div>
      )}

      <Note>
        user tier · fetches public RSS/Atom feeds server-side; every item is third-party, untrusted
        content (each carries tainted:true), never a Nerva finding.
      </Note>
    </Card>
  );
}
