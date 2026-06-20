// @ts-nocheck
import React, { useEffect, useMemo, useState } from 'react';
import { Icon as Ic, ICONS as IK } from './ui';
import { loadWorldIntelligence } from './api/signalLayer';

function SubH({ children, style }) { return <div className="sub-h" style={style}>{children}</div>; }
function Stat({ value, label }) { return <div className="stat-card"><div className="sv">{value}</div><div className="sl">{label}</div></div>; }
function Cap({ title, detail, tag = 'INFO', kind = 'scoped' }) {
  return <div className="cap-row"><div><div className="cn">{title}</div>{detail && <div className="cd">{detail}</div>}</div><span className={'cap-tag ' + kind}>{tag}</span></div>;
}

function SignalRow({ signal, evidenceById }) {
  const ev = (signal.evidenceIds || []).map(id => evidenceById.get(id)).filter(Boolean)[0];
  const severe = signal.severity === 'high' || signal.severity === 'critical';
  return (
    <div className="trace-row">
      <div className="tr-top">
        <span className="tr-id">{signal.type || 'signal'}</span>
        <span className="tr-q">{signal.title}</span>
        <span className={'tr-status ' + (severe ? 'failed' : 'ok')}>{signal.severity || 'n/a'}</span>
        <span className="tr-tot">{signal.confidence || 'conf?'}</span>
      </div>
      <div className="hx" style={{ marginTop: 6, lineHeight: 1.45 }}>{signal.summary || signal.whyItMatters || signal.relevance?.reasons?.[0] || 'No summary.'}</div>
      <div className="tr-agents" style={{ marginTop: 8 }}>
        <span className="topic-pill">{signal.claimStatus || 'claim'}</span>
        {signal.relevance?.score != null && <span className="topic-pill">relevance {signal.relevance.score}</span>}
        {ev && <span className="topic-pill">{ev.sourceFamily} · {ev.stale ? 'stale' : 'fresh'}</span>}
      </div>
    </div>
  );
}

export function WorldIntelligencePanel() {
  const [state, setState] = useState({ loading: true, data: null, error: '' });
  const load = () => {
    setState(prev => ({ ...prev, loading: true, error: '' }));
    loadWorldIntelligence()
      .then(data => setState({ loading: false, data, error: data.errors.length ? data.errors.join(' · ') : '' }))
      .catch(error => setState({ loading: false, data: null, error: error.message || String(error) }));
  };
  useEffect(() => { load(); }, []);

  const data = state.data || {};
  const health = data.health || {};
  const brief = data.brief || {};
  const signals = data.signals?.length ? data.signals : (brief.topSignals || []);
  const evidenceById = useMemo(() => new Map((data.evidence || []).map(item => [item.id, item])), [data.evidence]);
  const provider = health.provider || {};
  const freshness = brief.freshness || {};

  return (
    <>
      <SubH>WORLD INTELLIGENCE · Signal Layer</SubH>
      <div className="mem-grid" style={{ marginBottom: 'var(--gap)' }}>
        <Stat value={health.ok ? 'OK' : state.loading ? '…' : 'OFF'} label="signal layer" />
        <Stat value={health.mode || brief.provider || 'replay'} label="mode/provider" />
        <Stat value={brief.globalStatus || 'unknown'} label="global status" />
        <Stat value={signals.length} label="relevant signals" />
      </div>

      {state.error && <Cap title="Signal Layer notice" detail={state.error} tag="CHECK" kind="gated" />}

      <div className="obs-grid">
        <div>
          <div className="cap-row" style={{ alignItems: 'flex-start' }}>
            <div>
              <div className="cn">{brief.title || 'Global Intelligence Brief'}</div>
              <div className="cd" style={{ lineHeight: 1.55, marginTop: 6 }}>{brief.executiveSummary || (state.loading ? 'Loading brief…' : 'No brief returned yet.')}</div>
              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 10 }}>
                <span className="cap-tag allow">freshness: {freshness.stale ? 'stale present' : 'ok'}</span>
                <span className="cap-tag scoped">source: Signal Layer</span>
              </div>
            </div>
            <button className="tool-btn" onClick={load} disabled={state.loading}>{state.loading ? '…' : 'refresh'}</button>
          </div>

          <SubH style={{ marginTop: 16 }}>TOP SIGNALS</SubH>
          {signals.slice(0, 6).map((signal, index) => <SignalRow key={signal.id || index} signal={signal} evidenceById={evidenceById} />)}
          {!signals.length && !state.loading && <Cap title="No relevant signals returned" detail="Check that the Signal Layer is running on :8787." tag="EMPTY" />}
        </div>

        <div>
          <SubH>RECOMMENDATIONS · preview</SubH>
          {(brief.recommendations || []).slice(0, 5).map((rec, index) => (
            <Cap key={index} title={rec.label || String(rec)} detail="Preview only. Route through Jarvis approval before action." tag={rec.requiresApproval ? 'APPROVAL' : 'INFO'} kind={rec.requiresApproval ? 'gated' : 'allow'} />
          ))}
          {!(brief.recommendations || []).length && <Cap title="No recommendations loaded" detail="Jarvis will wait for the next brief payload." tag="NONE" />}

          <SubH style={{ marginTop: 16 }}>PROVIDER HEALTH</SubH>
          <Cap title="Signal Layer" detail={data.baseUrl || 'http://localhost:8787'} tag={health.ok ? 'ONLINE' : 'UNKNOWN'} kind={health.ok ? 'allow' : 'gated'} />
          <Cap title="WorldMonitor provider" detail={`${provider.provider || 'worldmonitor'} · ${provider.status || 'replay/unknown'}`} tag={provider.mode || health.mode || 'replay'} />
          <Cap title="Port boundaries" detail="WorldView :3000/:4000 · Signal Layer :8787 · WorldMonitor :3100" tag="CLEAN" kind="allow" />
        </div>
      </div>
    </>
  );
}

export function WorldIntelligenceMode() {
  return (
    <div className="workzone full" style={{ flex: 1, minHeight: 0 }}>
      <div className="panel scroll" style={{ flex: 1 }}>
        <span className="bk tl"></span><span className="bk tr"></span><span className="bk bl"></span><span className="bk br"></span>
        <div className="panel-head"><Ic d={IK.globe || IK.observe} size={14}/><span className="ttl">World Intelligence</span><span className="st">Signal Layer · Argus</span></div>
        <div className="panel-body"><WorldIntelligencePanel /></div>
      </div>
    </div>
  );
}
