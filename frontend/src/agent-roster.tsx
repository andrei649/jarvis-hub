/* H202 — the owner's roster beside the persona editor: create an agent, rename one,
   retire it and bring it back.

   Hermes keeps create/rename/delete profile dialogs next to its SOUL.md editor; these are
   Nerva's, in the panels that host the SOUL editor (the Agents roster and its Dossier).
   Every call is an admin route of agents/core/routers/agents_api.py, backed by
   agents/core/agent_roster.py:

     POST /api/admin/agents                     create from a template or blank — kept across restarts
     POST /api/admin/agents/{id}/rename         a new display name for good (the id stays)
     POST /api/admin/agents/{id}/retire         out of the hub, nothing deleted ({confirm: id})
     POST /api/admin/agents/{id}/restore        back as it was
     GET  /api/admin/agents/roster              active and retired agents, templates, tiers

   Retire is reversible, so it takes the H168 two-step confirmation (confirm.tsx,
   RISK_TIER.REVERSIBLE); the confirm line says what is kept, and the hub is sent the
   agent's id as its own confirmation. Each refusal is said in words. */
import React, { useEffect, useState } from 'react';
import { apiGet, apiPost, getAdminToken } from './api/client';
import { ConfirmAction, RISK_TIER } from './confirm';
import { refusalText } from './soul-edit';

const TIERS = ['command', 'business', 'tech', 'foundation'];
const field = { background: 'var(--surface)', color: 'var(--ink)', border: '1px solid var(--panel-line)', borderRadius: 4, padding: 5, fontFamily: 'var(--font-mono)', fontSize: 11 };

/** The hub's refusal of a roster change, in words. */
export function rosterRefusal(err: any): string {
  const body = err?.body || {};
  switch (body.error) {
    case 'agent_exists': return `refused: ${body.agent || 'that id'} is already an agent${body.detail ? ` (${body.detail})` : ''}`;
    case 'reserved_id': return `refused: ${body.agent || 'that id'} is a reserved name — pick another id`;
    case 'bad_id': return 'refused: an id is lowercase letters, digits, _ or -, starting with a letter or digit';
    case 'bad_name': return 'refused: a name is 1-64 printable characters';
    case 'bad_tier': return 'refused: unknown tier';
    case 'unknown_template': return 'refused: unknown template';
    case 'too_many_agents': return `refused: ${body.max_created ?? 'the most'} created agents are live — retire one first`;
    case 'name_taken': return `refused: ${body.agent || 'another agent'} already has that name`;
    case 'protected': return 'refused: every turn no other agent takes goes to this agent, so it cannot be retired';
    case 'already_retired': return 'already retired';
    case 'not_retired': return 'not retired';
    case 'roster_unreadable': return 'refused: the roster file could not be read; nothing was changed';
    case 'kernel_denied': return 'refused by the Action Kernel: ' + (body.detail || 'denied');
    case 'write_failed': return 'failed: the change could not be written; nothing was changed';
    case 'hub_not_ready': return 'the hub is not ready';
    default: return refusalText(err);
  }
}

/* ── create ─────────────────────────────────────────────────────────────── */

export function NewAgentDialog({ onCreated, onCancel }: { onCreated: (agent: any) => void; onCancel: () => void }) {
  const [templates, setTemplates] = useState<any[]>([]);
  const [name, setName] = useState('');
  const [template, setTemplate] = useState('blank');
  const [agentId, setAgentId] = useState('');
  const [tier, setTier] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => {
    let alive = true;
    apiGet<any>('/api/agent-templates').then((r) => { if (alive) setTemplates(Array.isArray(r?.templates) ? r.templates : []); }).catch(() => {});
    return () => { alive = false; };
  }, []);
  const create = () => {
    if (!name.trim() || busy) return;
    setBusy(true); setError('');
    const body: any = { name: name.trim(), template: template === 'blank' ? '' : template };
    if (agentId.trim()) body.agent_id = agentId.trim().toLowerCase();
    if (tier) body.tier = tier;
    apiPost<any>('/api/admin/agents', body, { admin: true })
      .then((r) => onCreated(r?.agent || {}))
      .catch((e) => setError(rosterRefusal(e)))
      .finally(() => setBusy(false));
  };
  return (
    <div role="dialog" aria-label="New agent" className="agent-dialog" style={{ border: '1px solid var(--panel-line)', borderRadius: 4, padding: 8, margin: '8px 0', display: 'grid', gap: 6 }}>
      <div style={{ fontSize: 10, letterSpacing: '.14em', color: 'var(--ink-2)' }}>NEW AGENT · kept across restarts · no plugins or schedule granted</div>
      <input aria-label="Agent name" value={name} onChange={(ev) => setName(ev.target.value)} placeholder="name" maxLength={64} style={field} />
      <select aria-label="Template" value={template} onChange={(ev) => setTemplate(ev.target.value)} style={field}>
        <option value="blank">blank — an empty persona to fill in</option>
        {templates.map((tp) => <option key={tp.key} value={tp.key}>{tp.key} — {tp.role}</option>)}
      </select>
      <input aria-label="Agent id" value={agentId} onChange={(ev) => setAgentId(ev.target.value)} placeholder="id (optional; from the name)" maxLength={64} style={field} />
      <select aria-label="Tier" value={tier} onChange={(ev) => setTier(ev.target.value)} style={field}>
        <option value="">tier: the template's</option>
        {TIERS.map((t) => <option key={t} value={t}>{t}</option>)}
      </select>
      <div style={{ display: 'flex', gap: 6 }}>
        <button className="tool-btn" onClick={create} disabled={busy || !name.trim()}>Create</button>
        <button className="tool-btn" onClick={onCancel}>Cancel</button>
      </div>
      {error && <div role="alert" style={{ fontSize: 10, color: 'var(--amber)' }}>{error}</div>}
    </div>
  );
}

/* ── rename + retire, in the Dossier ────────────────────────────────────── */

export function AgentProfileControls({ id, name, onRenamed, onRetired }: {
  id: string; name: string; onRenamed: (name: string) => void; onRetired: () => void;
}) {
  const [renaming, setRenaming] = useState(false);
  const [draft, setDraft] = useState(name);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState('');
  const [error, setError] = useState('');
  const rename = () => {
    if (!draft.trim() || busy) return;
    setBusy(true); setError(''); setNote('');
    apiPost<any>('/api/admin/agents/' + encodeURIComponent(id) + '/rename', { name: draft.trim() }, { admin: true })
      .then((r) => {
        const next = r?.agent?.name || draft.trim();
        setRenaming(false);
        setNote(r?.changed === false ? 'unchanged' : `renamed to ${next} · kept across restarts`);
        onRenamed(next);
      })
      .catch((e) => setError(rosterRefusal(e)))
      .finally(() => setBusy(false));
  };
  const retire = () => {
    setError(''); setNote('');
    return apiPost<any>('/api/admin/agents/' + encodeURIComponent(id) + '/retire', { confirm: id }, { admin: true })
      .then(() => { onRetired(); return true; })
      .catch((e) => { setError(rosterRefusal(e)); return false; });
  };
  return (
    <div className="agent-profile">
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
        {!renaming && <button className="tool-btn" onClick={() => { setDraft(name); setRenaming(true); }}>Rename</button>}
        <ConfirmAction tier={RISK_TIER.REVERSIBLE} label="Retire" armedLabel={`Retire ${name}`} cancelLabel="Keep"
          ariaLabel={`Retire ${name}`}
          prompt={`${name} leaves the hub now and at every boot. Nothing is deleted: its persona, versions, run history and memory stay, and Restore brings it back.`}
          onConfirm={retire} />
      </div>
      {renaming && <div role="dialog" aria-label={`Rename ${name}`} style={{ display: 'flex', gap: 6, marginTop: 6 }}>
        <input aria-label="New name" value={draft} maxLength={64} onChange={(ev) => setDraft(ev.target.value)}
          onKeyDown={(ev) => { if (ev.key === 'Enter') rename(); if (ev.key === 'Escape') setRenaming(false); }} style={{ ...field, flex: 1 }} />
        <button className="tool-btn" onClick={rename} disabled={busy || !draft.trim()}>Save name</button>
        <button className="tool-btn" onClick={() => setRenaming(false)}>Cancel</button>
      </div>}
      {note && <div role="status" style={{ fontSize: 10, color: 'var(--green)', marginTop: 4 }}>{note}</div>}
      {error && <div role="alert" style={{ fontSize: 10, color: 'var(--amber)', marginTop: 4 }}>{error}</div>}
    </div>
  );
}

/* ── the retired agents, in the roster ──────────────────────────────────── */

export function RetiredAgents({ refresh = 0, onRestored }: { refresh?: number; onRestored: (id: string) => void }) {
  // An admin route: loaded at once when the HUD holds an admin token, else on request, so
  // opening the roster never asks for a token by itself.
  const [open, setOpen] = useState(() => !!getAdminToken());
  const [rows, setRows] = useState<any[] | null>(null);
  const [error, setError] = useState('');
  const [tick, setTick] = useState(0);
  useEffect(() => {
    if (!open) return;
    let alive = true;
    apiGet<any>('/api/admin/agents/roster', { admin: true })
      .then((r) => { if (alive) { setRows((r?.agents || []).filter((a: any) => a.status === 'retired')); setError(''); } })
      .catch((e) => { if (alive) setError(rosterRefusal(e)); });
    return () => { alive = false; };
  }, [open, refresh, tick]);
  const restore = (id: string) => {
    setError('');
    apiPost<any>('/api/admin/agents/' + encodeURIComponent(id) + '/restore', {}, { admin: true })
      .then(() => { setTick((n) => n + 1); onRestored(id); })
      .catch((e) => setError(rosterRefusal(e)));
  };
  if (!open) {
    return <div className="tier-group"><button className="tool-btn" onClick={() => setOpen(true)}>Show retired agents</button></div>;
  }
  if (!error && (!rows || rows.length === 0)) return null;
  return (
    <div className="tier-group" aria-label="Retired agents">
      <div className="tier-head"><span className="tier-tag">RET</span><span className="tier-lab">Retired · nothing deleted</span></div>
      {error && <div role="alert" style={{ fontSize: 10, color: 'var(--amber)' }}>{error}</div>}
      {(rows || []).map((a) => (
        <div key={a.id} className="retired-row" style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '4px 0', fontFamily: 'var(--font-mono)', fontSize: 11 }}>
          <span>{a.name}</span><span style={{ color: 'var(--ink-2)' }}>{a.id}{a.reason ? ' · ' + a.reason : ''}</span>
          <button className="tool-btn" style={{ marginLeft: 'auto' }} aria-label={`Restore ${a.name}`} onClick={() => restore(a.id)}>Restore</button>
        </div>
      ))}
    </div>
  );
}
