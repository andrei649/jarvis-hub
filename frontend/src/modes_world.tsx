import React, { useEffect, useMemo, useState } from 'react';
import { Icon, ICONS } from './ui';

const SIGNAL_LAYER_URL = ((import.meta as any).env?.VITE_SIGNAL_LAYER_URL || 'http://localhost:8787').replace(/\/+$/, '');

function Panel({ icon = 'globe', title, status, children, scroll = true }) {
  return (
    <div className={'panel' + (scroll ? ' scroll' : '')} style={{ flex: 1, minHeight: 0 }}>
      <span className="bk tl"></span><span className="bk tr"></span><span className="bk bl"></span><span className="bk br"></span>
      <div className="panel-head"><Icon d={ICONS[icon] || ICONS.globe} size={14}/><span className="ttl">{title}</span>{status && <span className="st">{status}</span>}</div>
      <div className="panel-body">{children}</div>
    </div>
  );
}

function SubH({ children, style }) { return <div className="sub-h" style={style}>{children}</div>; }

async function getJson(path) {
  const res = await fetch(`${SIGNAL_LAYER_URL}${path}`, { cache: 'no-store' });
  if (!res.ok) throw Object.assign(new Error(`Signal Layer ${path} -> ${res.status}`), { status: res.status });
  return res.json();
}

async function postJson(path, body) {
  const res = await fetch(`${SIGNAL_LAYER_URL}${path}`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body || {}),
  });
  if (!res.ok) throw Object.assign(new Error(`Signal Layer ${path} -> ${res.status}`), { status: res.status });
  return res.json();
}

function fmtTs(value) {
  if (!value) return 'unknown';
  try { return new Date(value).toLocaleString(); } catch { return String(value); }
}

function sevClass(sev) {
  if (sev === 'critical' || sev === 'high') return 'gated';
  if (sev === 'elevated') return 'scoped';
  return 'allow';
}

function WorldIntelligenceMode({ t }) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [health, setHealth] = useState(null);
  const [brief, setBrief] = useState(null);
  const [payload, setPayload] = useState(null);
  const [selected, setSelected] = useState(null);
  const [question, setQuestion] = useState('What changed overnight that matters to me?');
  const [answer, setAnswer] = useState(null);
  const [asking, setAsking] = useState(false);

  async function refresh() {
    setLoading(true);
    setError('');
    try {
      const [h, b, s] = await Promise.all([
        getJson('/provider-health/worldmonitor'),
        getJson('/briefs/world'),
        getJson('/signals?limit=18&relevantOnly=true'),
      ]);
      setHealth(h);
      setBrief(b);
      setPayload(s);
      setSelected((current) => current || (s.signals || [])[0] || null);
    } catch (e) {
      setError(e?.message || 'Signal Layer unavailable');
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    let alive = true;
    (async () => { if (alive) await refresh(); })();
    const iv = setInterval(() => { if (alive) refresh(); }, 30000);
    return () => { alive = false; clearInterval(iv); };
  }, []);

  async function ask() {
    setAsking(true);
    setAnswer(null);
    try {
      const res = await postJson('/ask/world', { question, mode: 'world_intelligence', limit: 8 });
      setAnswer(res);
    } catch (e) {
      setAnswer({ status: 'unavailable', answer: `Signal Layer unavailable: ${e?.message || e}` });
    } finally {
      setAsking(false);
    }
  }

  const signals = payload?.signals || [];
  const evidence = payload?.evidence || brief?.sources || [];
  const selectedEvidence = useMemo(() => {
    const ids = new Set(selected?.evidenceIds || []);
    return evidence.filter((ev) => ids.has(ev.id));
  }, [selected, evidence]);

  const globalStatus = String(brief?.globalStatus || health?.status || (error ? 'offline' : 'loading')).toUpperCase();
  const stale = !!(brief?.freshness?.stale || payload?.freshness?.stale || health?.stale);
  const providerMode = health?.mode || payload?.mode || 'replay';
  const recommendations = brief?.recommendations || [];

  if (error && !brief && !payload) {
    return (
      <Panel icon="globe" title="World Intelligence" status="offline">
        <div style={{ maxWidth: 680 }}>
          <div style={{ fontFamily: 'var(--font-mono)', color: 'var(--red)', letterSpacing: '.12em', fontSize: 11 }}>SIGNAL LAYER UNAVAILABLE</div>
          <p style={{ color: 'var(--ink-2)', lineHeight: 1.6 }}>Jarvis cannot reach the local Signal Layer at <code>{SIGNAL_LAYER_URL}</code>. Start it with <code>START.bat</code>, <code>./start.sh</code>, or <code>cd services/signal-layer &amp;&amp; npm start</code>.</p>
          <button className="tool-btn" onClick={refresh}>retry</button>
        </div>
      </Panel>
    );
  }

  return (
    <div className="workzone full" style={{ gridTemplateColumns: '1fr', minHeight: 0 }}>
      <div style={{ display: 'grid', gridTemplateRows: 'auto minmax(0,1fr)', gap: 'var(--gap)', minHeight: 0 }}>
        <div className="panel" style={{ minHeight: 0 }}>
          <span className="bk tl"></span><span className="bk tr"></span><span className="bk bl"></span><span className="bk br"></span>
          <div className="panel-body" style={{ padding: 14 }}>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, minmax(120px, 1fr))', gap: 10 }}>
              <Metric k="GLOBAL" v={globalStatus} tone={globalStatus === 'HIGH' || globalStatus === 'CRITICAL' ? 'var(--amber)' : 'var(--accent-light)'} />
              <Metric k="PROVIDER" v={health?.provider || 'worldmonitor'} />
              <Metric k="MODE" v={String(providerMode).toUpperCase()} />
              <Metric k="FRESHNESS" v={stale ? 'STALE PRESENT' : 'GOOD'} tone={stale ? 'var(--amber)' : 'var(--green)'} />
              <Metric k="SIGNALS" v={String(signals.length)} />
            </div>
          </div>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: '340px 1fr 360px', gap: 'var(--gap)', minHeight: 0 }}>
          <Panel icon="globe" title="Brief" status={loading ? 'loading' : providerMode}>
            <div style={{ color: 'var(--ink)', fontSize: 15, lineHeight: 1.45, marginBottom: 10 }}>{brief?.title || 'Global Intelligence Brief'}</div>
            <div style={{ color: 'var(--ink-2)', fontSize: 12.5, lineHeight: 1.6 }}>{brief?.executiveSummary || 'Signal Layer is loading the world brief.'}</div>
            <SubH style={{ marginTop: 18 }}>RECOMMENDATION PREVIEW</SubH>
            {recommendations.length === 0 && <Empty text="No recommendations loaded." />}
            {recommendations.map((rec, i) => (
              <div className="cap-row" key={`${rec.label}-${i}`}>
                <div><div className="cn" style={{ fontFamily: 'var(--font-ui)' }}>{rec.label}</div><div className="cd">preview only · {rec.requiresApproval ? 'approval required' : 'monitoring note'}</div></div>
                <span className={'cap-tag ' + (rec.requiresApproval ? 'gated' : 'allow')}>{rec.type || 'action'}</span>
              </div>
            ))}
            <SubH style={{ marginTop: 18 }}>SURFACES</SubH>
            <div className="cap-row"><div><div className="cn">WorldView</div><div className="cd">4D geospatial stack</div></div><a className="tool-btn" href="http://localhost:3000" target="_blank" rel="noreferrer">open</a></div>
            <div className="cap-row"><div><div className="cn">Signal Layer</div><div className="cd">evidence · signals · assessments</div></div><a className="tool-btn" href={`${SIGNAL_LAYER_URL}/healthz`} target="_blank" rel="noreferrer">health</a></div>
          </Panel>

          <Panel icon="observe" title="Relevant Signals" status={`${signals.length} ranked`}>
            {signals.length === 0 && <Empty text={loading ? 'Loading signals…' : 'No relevant signals returned.'} />}
            <div style={{ display: 'grid', gap: 10 }}>
              {signals.map((signal) => (
                <button key={signal.id} onClick={() => setSelected(signal)}
                  style={{ textAlign: 'left', background: selected?.id === signal.id ? 'var(--accent-faint)' : 'var(--surface-2)', border: `1px solid ${selected?.id === signal.id ? 'var(--accent-dim)' : 'var(--panel-line)'}`, color: 'var(--ink)', borderRadius: 'var(--radius)', padding: 12 }}>
                  <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', fontFamily: 'var(--font-mono)', fontSize: 9.5, color: 'var(--ink-3)', letterSpacing: '.08em', textTransform: 'uppercase' }}>
                    <span>{signal.type}</span><span>·</span><span>{signal.severity}</span><span>·</span><span>{signal.confidence} confidence</span>
                    <span className={'cap-tag ' + sevClass(signal.severity)} style={{ marginLeft: 'auto' }}>{signal.claimStatus || 'unknown'}</span>
                  </div>
                  <div style={{ marginTop: 8, fontSize: 14, color: 'var(--ink)' }}>{signal.title}</div>
                  <div style={{ marginTop: 6, fontSize: 12.5, color: 'var(--ink-2)', lineHeight: 1.5 }}>{signal.summary}</div>
                  {signal.relevance?.reasons?.length ? <div style={{ marginTop: 8, fontSize: 11.5, color: 'var(--accent-light)' }}>Why it matters: {signal.relevance.reasons[0]}</div> : null}
                </button>
              ))}
            </div>
          </Panel>

          <div className="col" style={{ minHeight: 0 }}>
            <Panel icon="shield" title="Evidence" status={selectedEvidence.length ? `${selectedEvidence.length} source` : 'select signal'}>
              {!selected && <Empty text="Select a signal to inspect evidence." />}
              {selected && <>
                <div style={{ fontSize: 14, color: 'var(--ink)', marginBottom: 8 }}>{selected.title}</div>
                <div className="verified-row" style={{ marginBottom: 10 }}><Icon d={ICONS.shield} size={12}/>{selected.claimStatus || 'unknown'} · {selected.confidence} confidence · {selected.stale ? 'stale' : 'fresh'}</div>
                {selectedEvidence.length === 0 && <Empty text="No source details returned for this signal." />}
                {selectedEvidence.map((ev) => (
                  <div className="cap-row" key={ev.id} style={{ alignItems: 'start' }}>
                    <div>
                      <div className="cn" style={{ fontFamily: 'var(--font-ui)' }}>{ev.sourceName || ev.sourceFamily || 'source'}</div>
                      <div className="cd">{ev.sourceFamily || 'unknown'} · {ev.reliability || 'unknown'} reliability</div>
                      <div className="cd">cached {fmtTs(ev.cachedAt)} · fetched {fmtTs(ev.fetchedAt)}</div>
                    </div>
                    <span className={'cap-tag ' + (ev.stale ? 'scoped' : 'allow')}>{ev.stale ? 'stale' : 'fresh'}</span>
                  </div>
                ))}
              </>}
            </Panel>

            <Panel icon="chat" title="Ask Argus" status={asking ? 'thinking' : 'signal layer'} scroll={false}>
              <textarea value={question} onChange={(e) => setQuestion(e.target.value)}
                style={{ width: '100%', minHeight: 68, resize: 'vertical', background: 'var(--void)', color: 'var(--ink)', border: '1px solid var(--panel-line)', borderRadius: 'var(--radius)', padding: 10, fontFamily: 'var(--font-ui)', outline: 0 }} />
              <button className="tool-btn" onClick={ask} disabled={asking} style={{ marginTop: 10 }}>{asking ? 'asking…' : 'ask world analyst'}</button>
              {answer && <div style={{ marginTop: 12, whiteSpace: 'pre-wrap', fontSize: 12.5, color: 'var(--ink-2)', lineHeight: 1.55, background: 'var(--void)', border: '1px solid var(--panel-line)', borderRadius: 'var(--radius)', padding: 10 }}>{answer.answer || JSON.stringify(answer, null, 2)}</div>}
            </Panel>
          </div>
        </div>
      </div>
    </div>
  );
}

function Metric({ k, v, tone = 'var(--ink)' }) {
  return <div className="badge" style={{ minWidth: 0 }}><div className="k">{k}</div><div className="v" style={{ color: tone }}>{v}</div></div>;
}

function Empty({ text }) {
  return <div style={{ color: 'var(--ink-3)', fontSize: 11, textAlign: 'center', padding: '16px 0', fontFamily: 'var(--font-mono)', letterSpacing: '.05em' }}>{text}</div>;
}

export { WorldIntelligenceMode };
