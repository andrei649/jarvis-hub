/* MODEL SETUP — the zero-key first-value card (Console → Start).

   Two user-tier routes, both called here:
     · GET  /api/onboarding/model-plan   what this box is → which local model the tier
                                         table suggests, whether a loopback Ollama is up,
                                         whether the pick is already installed, the pull job
     · POST /api/onboarding/model-pull   pull the recommended (or a named) model — governed

   Honesty contract:
   · the recommendation is SPEC-BASED, not benchmarked — the backend's `basis` string is
     printed verbatim under the pick and is never paraphrased into a speed claim;
   · "Ollama not reachable" renders the backend's reason, not an empty model list;
   · the pull is default-off: with the flag unset the backend answers `model_pull_disabled`
     and this card shows that hint instead of a green button;
   · every pull crosses the Action Kernel; a refusal (403) or a queue (202) is rendered as
     such — the mutation passes onErr, so a refused pull is never a silent success
     (panel-kit.tsx:93-97). The card only polls while a job is running. */
import React, { useEffect, useState } from 'react';
import { useApi, arr, mono, asLive, Card, State, Row, Tag, act } from '../panel-kit';

const fmtGb = (bytes: number) => (Number(bytes || 0) / 1024 ** 3).toFixed(1);

const refusalText = (err: any) => {
  const reason = err && err.body && (err.body.reason || err.body.error);
  const status = String((err && err.status) || '?');
  const verb = status === '403' ? 'refused · kernel denied' : `refused (${status})`;
  return reason ? `${verb} · ${String(reason)}` : verb;
};

export function ModelSetupPanel() {
  const { d, e, loading, reload } = useApi('/api/onboarding/model-plan');
  const raw: any = d;
  const rec = (raw && raw.recommendation) || null;
  const ollama = (raw && raw.ollama) || null;
  const pull = (raw && raw.pull) || null;
  const job = pull && pull.job ? pull.job : null;
  const installed = arr(ollama, 'models');
  const present = !!(ollama && ollama.present);
  const enabled = !!(pull && pull.enabled);
  const running = !!(job && job.status === 'running');
  const [note, setNote] = useState(null);
  const [err, setErr] = useState(null);

  // Poll only while a pull is in flight; a finished or absent job costs nothing.
  useEffect(() => {
    if (!running) return undefined;
    const id = setInterval(reload, 3000);
    return () => clearInterval(id);
  }, [running, reload]);

  const doPull = () => {
    setNote(null); setErr(null);
    act('/api/onboarding/model-pull', { model: rec ? rec.model : null },
      (r: any) => {
        if (r && r.status === 'queued') setNote(`queued for approval · ${r.reason || 'ask'}`);
        else if (r && r.ok && r.output && r.output.already_installed) setNote('already installed');
        else if (r && r.ok) setNote(`pull started · ${String(r.model || '')}`);
        else setNote(`not started · ${String((r && r.reason) || 'unknown')}`);
        reload();
      },
      (ex) => setErr(refusalText(ex)));
  };

  const canPull = !!rec && present && enabled && !running && !(raw && raw.recommended_installed);
  const gpu = raw && raw.hardware && raw.hardware.gpu ? raw.hardware.gpu : null;

  return (
    <Card title="MODEL SETUP" live={asLive(d, present)}
      sub={rec ? `${rec.tier} · ${rec.model}` : null} onReload={reload}>
      <State e={e} loading={loading} n={d ? 1 : 0} />

      {rec && (
        <div style={{ marginTop: 6 }}>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            <Tag c="var(--accent-light)">{rec.tier}</Tag>
            <span style={{ ...mono, color: 'var(--ink)' }}>{rec.model}</span>
            <Tag>{`~${Number(rec.approx_gb || 0)} GB`}</Tag>
            {gpu && <Tag>{gpu.measured ? `${gpu.name} · ${gpu.vram_total_mb} MB` : 'no GPU measured'}</Tag>}
          </div>
          <div style={{ fontSize: 10, color: 'var(--amber)', marginTop: 4 }}>{String(rec.basis || '')}</div>
          {arr(rec, 'reasons').slice(0, 4).map((r, i) => (
            <div key={i} style={{ fontSize: 10, color: 'var(--ink-2)' }}>{String(r)}</div>
          ))}
        </div>
      )}

      {ollama && !present && (
        <div style={{ fontSize: 10, color: 'var(--amber)', marginTop: 6 }}>
          {`Ollama not reachable · ${String(ollama.reason || 'unknown')} · ${String(ollama.url || '')} — nothing can be pulled until it runs`}
        </div>
      )}
      {present && installed.slice(0, 8).map((m, i) => (
        <Row key={i}>
          <span style={{ ...mono, color: 'var(--ink)', flex: 1 }}>{String(m)}</span>
          {rec && m === rec.model && <Tag c="var(--green)">recommended</Tag>}
          <Tag>installed</Tag>
        </Row>
      ))}
      {present && installed.length === 0 && (
        <div style={{ fontSize: 10, color: 'var(--ink-2)', marginTop: 6 }}>Ollama is up but holds no models yet</div>
      )}

      <div style={{ display: 'flex', gap: 6, marginTop: 8, alignItems: 'center', flexWrap: 'wrap' }}>
        <button className="tool-btn" disabled={!canPull} onClick={doPull}>
          {raw && raw.recommended_installed ? 'installed' : rec ? `pull ${rec.model}` : 'pull'}
        </button>
        {pull && <span style={{ ...mono, fontSize: 10, color: 'var(--ink-2)' }}>{`cap ${Number(pull.max_gb || 0)} GB`}</span>}
        {pull && !enabled && (
          <span style={{ fontSize: 10, color: 'var(--amber)' }}>{`pulls disabled · ${String(pull.hint || 'model_pull_disabled')}`}</span>
        )}
      </div>

      {job && (
        <div style={{ fontSize: 10, color: job.status === 'failed' ? 'var(--red)' : 'var(--ink-2)', marginTop: 6 }} data-testid="pull-job">
          {`${String(job.model)} · ${String(job.status)}${job.stage ? ` · ${String(job.stage)}` : ''}`}
          {job.bytes_total > 0 ? ` · ${fmtGb(job.bytes_completed)} / ${fmtGb(job.bytes_total)} GB` : ''}
          {job.reason ? ` · ${String(job.reason)}` : ''}
        </div>
      )}

      {note && <div style={{ fontSize: 10, color: 'var(--ink-2)', marginTop: 6 }}>{note}</div>}
      {err && <div role="alert" style={{ fontSize: 10, color: 'var(--red)', marginTop: 6 }}>{err}</div>}

      <div style={{ fontSize: 10, color: 'var(--ink-2)', marginTop: 6 }}>
        Loopback Ollama only; every pull crosses the Action Kernel and stays under the size cap. Nothing leaves this machine.
      </div>
    </Card>
  );
}
