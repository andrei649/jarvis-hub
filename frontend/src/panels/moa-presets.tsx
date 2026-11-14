import React, { useEffect, useState } from 'react';
import { apiDelete, apiGet, apiPost, apiPut } from '../api/client';
import { Card } from '../panel-kit';

type MoAPreset = {
  name: string;
  model_id: string;
  description: string;
  proposers: string[];
  aggregator: string;
  min_quorum: number;
  timeout_s: number;
  temperature: number;
  pure_local: boolean;
};

type ProposerMetric = {
  spec: string;
  model: string;
  route: string;
  ok: boolean;
  latency_ms: number;
  tokens_est: number;
  reason?: string | null;
};

type MoATelemetry = {
  ts: number;
  preset: string;
  agent: string;
  ok: boolean;
  quorum_met: boolean;
  succeeded: number;
  min_quorum: number;
  total_proposers: number;
  proposer_wall_ms: number;
  sum_proposer_ms: number;
  parallel_speedup: number;
  total_ms: number;
  proposers: ProposerMetric[];
};

type MoACatalog = {
  presets: MoAPreset[];
  active: string | null;
  recent_runs: MoATelemetry[];
};

type MoARunResult = {
  ok: boolean;
  model: string;
  route: string;
  answer: string;
  telemetry?: MoATelemetry | null;
};

function formatError(err: unknown): string {
  const e = err as { status?: number; body?: { detail?: string; error?: string } };
  const detail = e?.body?.detail || e?.body?.error || 'request failed';
  return `refused · HTTP ${e?.status || 'error'} · ${detail}`;
}

export function MoaPresetsPanel() {
  const [catalog, setCatalog] = useState<MoACatalog | null>(null);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState('');
  const [name, setName] = useState('');
  const [proposers, setProposers] = useState('local,local-deep');
  const [aggregator, setAggregator] = useState('local-deep');
  const [description, setDescription] = useState('');
  const [minQuorum, setMinQuorum] = useState('2');
  const [timeoutS, setTimeoutS] = useState('45');
  const [runPreset, setRunPreset] = useState('');
  const [runPrompt, setRunPrompt] = useState('');
  const [runResult, setRunResult] = useState<MoARunResult | null>(null);

  const reload = async () => {
    const data = await apiGet<MoACatalog>('/api/llm/moa/presets', { admin: true });
    setCatalog(data);
    if (!runPreset && data.presets.length > 0) {
      setRunPreset(data.active || data.presets[0].name);
    }
  };

  useEffect(() => {
    void reload().catch((err) => setNote(formatError(err)));
  }, []);

  const savePreset = async () => {
    const cleanName = name.trim();
    const cleanProps = proposers.split(',').map((s) => s.trim()).filter(Boolean);
    const cleanAgg = aggregator.trim();
    if (!cleanName || cleanProps.length < 2 || !cleanAgg) {
      setNote('provide preset name, 2..6 comma-separated proposers, and an aggregator');
      return;
    }
    setBusy(true);
    setNote('');
    try {
      await apiPut(
        `/api/llm/moa/presets/${encodeURIComponent(cleanName)}`,
        {
          proposers: cleanProps,
          aggregator: cleanAgg,
          description: description.trim(),
          min_quorum: Math.max(1, Number(minQuorum) || 2),
          timeout_s: Math.max(2, Number(timeoutS) || 45),
          temperature: 0.6,
        },
        { admin: true },
      );
      setName('');
      setDescription('');
      await reload();
      setRunPreset(cleanName);
      setNote(`saved moa:${cleanName}`);
    } catch (err) {
      setNote(formatError(err));
    } finally {
      setBusy(false);
    }
  };

  const setActive = async (target: string | null) => {
    setBusy(true);
    setNote('');
    try {
      await apiPost('/api/llm/moa/active', { name: target }, { admin: true });
      await reload();
      setNote(target ? `activated moa:${target}` : 'cleared active MoA preset');
    } catch (err) {
      setNote(formatError(err));
    } finally {
      setBusy(false);
    }
  };

  const removePreset = async (target: string) => {
    setBusy(true);
    setNote('');
    try {
      await apiDelete(`/api/llm/moa/presets/${encodeURIComponent(target)}`, { admin: true });
      await reload();
      setNote(`deleted moa:${target}`);
    } catch (err) {
      setNote(formatError(err));
    } finally {
      setBusy(false);
    }
  };

  const executeRun = async () => {
    const chosen = runPreset.trim() || catalog?.active || catalog?.presets[0]?.name || '';
    const promptText = runPrompt.trim();
    if (!chosen || !promptText) {
      setNote('select a preset and enter a prompt to synthesize');
      return;
    }
    setBusy(true);
    setNote('');
    try {
      const res = await apiPost<MoARunResult>(
        '/api/llm/moa/run',
        { preset: chosen, prompt: promptText, agent: 'jarvis' },
        { admin: true },
      );
      setRunResult(res);
      await reload();
      setNote(`synthesized via ${res.model} (${res.route})`);
    } catch (err) {
      setNote(formatError(err));
    } finally {
      setBusy(false);
    }
  };

  const presets = catalog?.presets || [];
  const active = catalog?.active || null;
  const recent = catalog?.recent_runs || [];

  return (
    <Card
      title="MOA · COMMITTEE PRESETS"
      live={catalog ? true : undefined}
      sub={active ? `active · moa:${active}` : `${presets.length} preset(s)`}
      onReload={() => { void reload(); }}
    >
      <p style={{ fontSize: 11, color: 'var(--ink-2)', marginBottom: 8 }}>
        Mixture-of-Agents committees (H032): 2–6 proposers run in parallel under quorum timeout, synthesized by one aggregator while inheriting strict-local, approved-model, and H513 consent gates across every member.
      </p>
      {note && (
        <div role="status" style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: note.startsWith('refused') ? 'var(--red)' : 'var(--amber)', marginBottom: 8 }}>
          {note}
        </div>
      )}

      {active && (
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 10 }}>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--green)' }}>
            global active committee: moa:{active}
          </span>
          <button type="button" className="tool-btn" disabled={busy} onClick={() => { void setActive(null); }}>
            clear active
          </button>
        </div>
      )}

      <div style={{ display: 'grid', gap: 6, marginBottom: 12 }}>
        {presets.length === 0 && (
          <div style={{ fontSize: 11, color: 'var(--ink-2)' }}>no MoA presets configured yet</div>
        )}
        {presets.map((p) => (
          <div
            key={p.name}
            style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center', padding: '6px 8px', border: '1px solid var(--panel-line)', borderRadius: 4 }}
          >
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11 }}>{p.model_id}</span>
            <span style={{ fontSize: 10, color: p.pure_local ? 'var(--green)' : 'var(--amber)' }}>
              {p.pure_local ? 'local-only' : 'hybrid'}
            </span>
            <span style={{ fontSize: 10, color: 'var(--ink-2)' }}>
              [{p.proposers.join(', ')}] → {p.aggregator} · quorum {p.min_quorum}/{p.proposers.length}
            </span>
            <span style={{ marginLeft: 'auto', display: 'flex', gap: 6 }}>
              {active !== p.name && (
                <button type="button" className="tool-btn" disabled={busy} onClick={() => { void setActive(p.name); }}>
                  activate {p.name}
                </button>
              )}
              <button type="button" className="tool-btn" disabled={busy} onClick={() => { void removePreset(p.name); }}>
                delete {p.name}
              </button>
            </span>
          </div>
        ))}
      </div>

      <div style={{ borderTop: '1px solid var(--panel-line)', paddingTop: 10, marginBottom: 12 }}>
        <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--ink-2)', marginBottom: 6 }}>
          SAVE COMMITTEE PRESET
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 6, marginBottom: 6 }}>
          <input aria-label="preset name" placeholder="name (e.g. council)" value={name} onChange={(e) => setName(e.target.value)} />
          <input aria-label="proposer specs" placeholder="proposers (local,local-deep)" value={proposers} onChange={(e) => setProposers(e.target.value)} />
          <input aria-label="aggregator spec" placeholder="aggregator (local-deep)" value={aggregator} onChange={(e) => setAggregator(e.target.value)} />
          <input aria-label="minimum quorum" placeholder="min quorum" value={minQuorum} onChange={(e) => setMinQuorum(e.target.value)} />
          <input aria-label="member timeout seconds" placeholder="timeout (s)" value={timeoutS} onChange={(e) => setTimeoutS(e.target.value)} />
          <input aria-label="preset description" placeholder="description" value={description} onChange={(e) => setDescription(e.target.value)} />
        </div>
        <button type="button" className="tool-btn" disabled={busy} onClick={() => { void savePreset(); }}>
          save preset
        </button>
      </div>

      <div style={{ borderTop: '1px solid var(--panel-line)', paddingTop: 10 }}>
        <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--ink-2)', marginBottom: 6 }}>
          SYNTHESIS TESTBENCH &amp; QUORUM TELEMETRY
        </div>
        <div style={{ display: 'flex', gap: 6, marginBottom: 6, flexWrap: 'wrap' }}>
          <input
            aria-label="preset to run"
            placeholder="preset name"
            value={runPreset}
            onChange={(e) => setRunPreset(e.target.value)}
            style={{ width: 160 }}
          />
          <input
            aria-label="committee prompt"
            placeholder="prompt to synthesize across proposers"
            value={runPrompt}
            onChange={(e) => setRunPrompt(e.target.value)}
            style={{ flex: 1, minWidth: 220 }}
          />
          <button type="button" className="tool-btn" disabled={busy} onClick={() => { void executeRun(); }}>
            run committee
          </button>
        </div>
        {runResult && (
          <div style={{ padding: 8, border: '1px solid var(--panel-line)', borderRadius: 4, marginBottom: 8 }}>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, whiteSpace: 'pre-wrap' }}>{runResult.answer}</div>
            {runResult.telemetry && (
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--ink-2)', marginTop: 4 }}>
                quorum {runResult.telemetry.succeeded}/{runResult.telemetry.total_proposers} · speedup {runResult.telemetry.parallel_speedup}x · {runResult.telemetry.total_ms} ms
              </div>
            )}
          </div>
        )}
        {recent.slice(0, 5).map((r, idx) => (
          <div key={`${r.preset}-${r.ts}-${idx}`} style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--ink-2)' }}>
            moa:{r.preset} · {r.ok ? 'ok' : 'failed'} · quorum {r.succeeded}/{r.total_proposers} · speedup {r.parallel_speedup}x · {r.total_ms} ms
          </div>
        ))}
      </div>
    </Card>
  );
}
