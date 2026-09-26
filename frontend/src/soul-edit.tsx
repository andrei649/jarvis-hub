/* H156 — edit an agent's persona from the Dossier, and make it live.

   The editor starts from the live SOUL (GET /api/agents/{id}/soul). Preview diffs the
   draft against it (POST /api/admin/prompts/{id}/preview with `current`), and Apply
   sends it to PUT /api/admin/agents/{id}/soul. The hub scans it, keeps the old text as a
   version, writes the owner's overlay, reloads the agent and audits it, so the agent's
   next turn uses it. A persona the guard would drop is refused and says so; lines it
   only quarantines are named. "Draft description" asks the local model for a
   one-paragraph description (nothing is saved); "Use it" puts it in the front-matter's
   `description:`, and the next Apply saves it. */
import React, { useState } from 'react';
import { apiPost, apiPut } from './api/client';

/** *content* with its YAML front-matter `description:` set to *text* (one line, quoted). */
export function withDescription(content: string, text: string): string {
  const line = 'description: ' + JSON.stringify(text.split(/\s+/).filter(Boolean).join(' '));
  const m = /^---\r?\n([\s\S]*?)\r?\n---(\r?\n|$)/.exec(content);
  if (!m) return `---\n${line}\n---\n${content}`;
  const kept: string[] = [];
  let skipping = false;
  for (const l of m[1].split(/\r?\n/)) {
    if (/^description\s*:/.test(l)) { skipping = true; continue; }
    if (skipping && /^\s+\S/.test(l)) continue;           // a folded or block value's lines
    skipping = false;
    kept.push(l);
  }
  kept.push(line);
  return `---\n${kept.join('\n')}\n---\n${content.slice(m[0].length)}`;
}

/** The hub's refusal, in words. */
export function refusalText(err: any): string {
  const body = err?.body || {};
  if (body.error === 'soul_blocked') {
    const flags = (body.guard?.flags || []).join(', ');
    return `refused: the SOUL guard would drop this persona${flags ? ` (${flags})` : ''}`;
  }
  if (body.error === 'safe_mode') return 'refused: safe mode is on, and persona edits are not read there';
  if (body.error === 'too_large') return 'refused: the persona is over 256 KiB';
  if (body.error === 'unknown_agent') return 'refused: the hub has not loaded this agent';
  if (body.error === 'no_local_model') return 'no local model to draft with';
  if (body.error === 'empty_draft') return 'the local model answered with nothing';
  if (err?.status === 401 || err?.status === 403) return 'needs the admin token';
  return 'failed: ' + (err?.message || 'offline');
}

const box = { width: '100%', minHeight: 180, background: 'var(--surface)', color: 'var(--ink)', border: '1px solid var(--panel-line)', borderRadius: 4, padding: 6, fontFamily: 'var(--font-mono)', fontSize: 11 };

export function SoulEditor({ id, live, onApplied, onCancel }: { id: string; live: string; onApplied: (text: string) => void; onCancel: () => void }) {
  const [text, setText] = useState(live);
  const [message, setMessage] = useState('');
  const [preview, setPreview] = useState<any>(null);
  const [note, setNote] = useState('');
  const [error, setError] = useState('');
  const [draft, setDraft] = useState('');
  const [busy, setBusy] = useState(false);

  const doPreview = () => {
    setError('');
    apiPost('/api/admin/prompts/' + encodeURIComponent(id) + '/preview', { proposed: text, current: live }, { admin: true })
      .then(setPreview).catch((e) => setError(refusalText(e)));
  };
  const doApply = () => {
    setBusy(true); setError(''); setNote('');
    apiPut<any>('/api/admin/agents/' + encodeURIComponent(id) + '/soul', { content: text, message }, { admin: true })
      .then((r) => {
        const flags = r?.guard?.flags || [];
        setNote(`applied${r?.version ? ' as v' + r.version.version : ''}${flags.length ? ` · ${flags.length} line(s) quarantined: ${flags.join(', ')}` : ''}`);
        onApplied(text);
      })
      .catch((e) => setError(refusalText(e)))
      .finally(() => setBusy(false));
  };
  const doDraft = () => {
    setError(''); setDraft('');
    apiPost<any>('/api/admin/agents/' + encodeURIComponent(id) + '/description/draft', {}, { admin: true })
      .then((r) => setDraft(r?.draft || '')).catch((e) => setError(refusalText(e)));
  };

  return (
    <div className="soul-editor" style={{ marginTop: 6 }}>
      <textarea aria-label="Persona" value={text} onChange={(ev) => { setText(ev.target.value); setPreview(null); }} style={box} />
      <input aria-label="Change note" value={message} onChange={(ev) => setMessage(ev.target.value)} placeholder="what changed (optional)"
        style={{ ...box, minHeight: 0, marginTop: 4 }} />
      <div style={{ display: 'flex', gap: 6, marginTop: 6, flexWrap: 'wrap' }}>
        <button className="tool-btn" onClick={doPreview}>Preview</button>
        <button className="tool-btn" onClick={doApply} disabled={busy || text === live}>Apply</button>
        <button className="tool-btn" onClick={doDraft}>Draft description</button>
        <button className="tool-btn" onClick={onCancel}>Close</button>
      </div>
      {preview && <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, marginTop: 4, color: preview.valid ? 'var(--green)' : 'var(--amber)' }}>
        +{preview.added_lines} −{preview.removed_lines}{preview.valid ? '' : ' · ' + (preview.warnings || []).join('; ')}
      </div>}
      {draft && <div style={{ fontSize: 11, marginTop: 4 }}>
        <span>{draft}</span>{' '}
        <button className="tool-btn" onClick={() => { setText(withDescription(text, draft)); setDraft(''); }}>Use it</button>
      </div>}
      {note && <div role="status" style={{ fontSize: 10, color: 'var(--green)', marginTop: 4 }}>{note}</div>}
      {error && <div role="alert" style={{ fontSize: 10, color: 'var(--amber)', marginTop: 4 }}>{error}</div>}
    </div>
  );
}
