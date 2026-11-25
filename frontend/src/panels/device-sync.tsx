import React, { useEffect, useState } from 'react';
import { apiDelete, apiGet, apiPost, apiPut } from '../api/client';
import { Card } from '../panel-kit';

type SyncPeer = {
  peer_id: string;
  url: string;
  label: string;
};

type SyncStatus = {
  inbound_mode?: 'stage_only';
  enabled: boolean;
  available: boolean;
  backend: string;
  device_id: string;
  device_label?: string;
  skill_policies?: Record<string, boolean>;
  peers?: SyncPeer[];
  transports?: string[];
  last_push_at?: number | null;
  last_pull_at?: number | null;
};

function pullReceipt(res: any): string {
  const count = (n: number, noun: string) => `${n} ${noun}${n === 1 ? '' : 's'}`;
  if (res?.enabled === false) return `Sync disabled (${res?.reason || 'off'}).`;
  if (res?.inbound_mode === 'stage_only') {
    const configs = Array.isArray(res.config_pending_import) ? res.config_pending_import.length : 0;
    const skills = Array.isArray(res.skills_pending_install) ? res.skills_pending_install.length : 0;
    const errors = Array.isArray(res.staging_errors) ? res.staging_errors.length : 0;
    const invalidConfig = Array.isArray(res.config_errors) ? res.config_errors.length : 0;
    const quarantined = Array.isArray(res.skills_quarantined) ? res.skills_quarantined.length : 0;
    return `${count(configs, 'configuration candidate')} and ${count(skills, 'skill candidate')} staged for review. `
      + (configs + skills ? 'Import and installation are pending.' : 'No candidates are pending from this pull.')
      + (errors ? ` ${count(errors, 'candidate')} could not be staged.` : '')
      + (invalidConfig ? ` ${count(invalidConfig, 'configuration validation issue')}.` : '')
      + (quarantined ? ` ${count(quarantined, 'skill')} quarantined.` : '');
  }
  if (!res?.ok) return `Pull did not finish (${res?.reason || 'no receipt'}).`;
  return `Server reported ${count(res.config_applied ?? 0, 'configuration change')} and `
    + `${count(Array.isArray(res.skills_applied) ? res.skills_applied.length : 0, 'skill transfer')}; `
    + 'installation status is unverified.';
}

export function DeviceSyncPanel() {
  const [status, setStatus] = useState<SyncStatus | null>(null);
  const [labelInput, setLabelInput] = useState('');
  const [skillSlug, setSkillSlug] = useState('');
  const [peerId, setPeerId] = useState('');
  const [peerUrl, setPeerUrl] = useState('');
  const [note, setNote] = useState('');

  const refresh = () => {
    apiGet('/api/sync')
      .then((res: any) => {
        setStatus(res);
        if (!labelInput && res?.device_label) {
          setLabelInput(res.device_label);
        }
      })
      .catch(() => setStatus(null));
  };

  useEffect(() => {
    refresh();
  }, []);

  const runPush = async () => {
    try {
      const res: any = await apiPost('/api/sync/push', {
        sync_device_state: true,
        include_config: true,
        include_skills: true,
      });
      setNote(res?.ok ? `pushed ${res.artefact_count ?? 0} artefacts` : `sync disabled (${res?.reason || 'off'})`);
      refresh();
    } catch (err: any) {
      setNote(String(err?.message || 'push failed'));
    }
  };

  const runPull = async () => {
    try {
      const res: any = await apiPost('/api/sync/pull', { apply_device_state: true });
      setNote(pullReceipt(res));
      refresh();
    } catch (err: any) {
      setNote(String(err?.message || 'pull failed'));
    }
  };

  const runSyncNow = async () => {
    try {
      const res: any = await apiPost('/api/sync/now', {}, { admin: true });
      setNote(res?.enabled === false ? `Sync disabled (${res?.reason || 'off'}).` : res?.pull
        ? `${res?.ok ? '' : 'Sync incomplete. '}${pullReceipt(res.pull)}`
        : `Sync request returned no incoming-change receipt (${res?.reason || 'unavailable'}).`);
      refresh();
    } catch (err: any) {
      setNote(String(err?.message || 'sync now failed'));
    }
  };

  const saveLabel = async () => {
    if (!labelInput.trim()) return;
    try {
      await apiPut('/api/sync/device', { label: labelInput.trim() }, { admin: true });
      setNote(`device labelled '${labelInput.trim()}'`);
      refresh();
    } catch (err: any) {
      setNote(String(err?.message || 'label update failed'));
    }
  };

  const toggleSkill = async (slug: string, enabled: boolean) => {
    const clean = slug.trim().toLowerCase();
    if (!clean) return;
    try {
      await apiPut(`/api/sync/skills/${encodeURIComponent(clean)}`, { enabled }, { admin: true });
      setSkillSlug('');
      setNote(`${clean}: sync ${enabled ? 'enabled' : 'disabled'}`);
      refresh();
    } catch (err: any) {
      setNote(String(err?.message || 'skill policy failed'));
    }
  };

  const addPeer = async () => {
    if (!peerId.trim() || !peerUrl.trim()) return;
    try {
      await apiPost(
        '/api/sync/peers',
        { peer_id: peerId.trim(), url: peerUrl.trim(), label: peerId.trim() },
        { admin: true },
      );
      setPeerId('');
      setPeerUrl('');
      setNote('peer hub added');
      refresh();
    } catch (err: any) {
      setNote(String(err?.message || 'peer add failed'));
    }
  };

  const removePeer = async (pid: string) => {
    try {
      await apiDelete(`/api/sync/peers/${encodeURIComponent(pid)}`, { admin: true });
      setNote(`removed peer ${pid}`);
      refresh();
    } catch (err: any) {
      setNote(String(err?.message || 'peer remove failed'));
    }
  };

  const policies = Object.entries(status?.skill_policies || {});
  const peers = status?.peers || [];

  return (
    <Card title="DEVICE SYNC · E2E config & skills" sub={peers.length} onReload={refresh}>
      <div style={{ fontSize: 'var(--n-fs-meta)', color: 'var(--ink-2)', marginBottom: 8 }}>
        status: <strong>{status?.enabled ? 'enabled' : 'disabled'}</strong> ({status?.backend || 'no-key'}) · device:{' '}
        <code>{status?.device_label || status?.device_id || 'local'}</code>
      </div>

      {status?.inbound_mode === 'stage_only' && (
        <p style={{ fontSize: 'var(--n-fs-meta)', color: 'var(--ink-2)' }}>
          Incoming changes are staged for review; automatic import is paused.
        </p>
      )}

      <div style={{ display: 'flex', gap: 6, marginBottom: 10 }}>
        <button className="tool-btn" onClick={runSyncNow}>
          sync now
        </button>
        <button className="tool-btn" onClick={runPush}>
          push
        </button>
        <button className="tool-btn" onClick={runPull}>
          pull
        </button>
      </div>

      <div style={{ display: 'flex', gap: 6, marginBottom: 10 }}>
        <input
          aria-label="Device label"
          value={labelInput}
          onChange={(ev) => setLabelInput(ev.target.value)}
          placeholder="MacBook Pro / Home Hub"
          style={{ flex: 1, padding: '4px 6px' }}
        />
        <button className="tool-btn" onClick={saveLabel}>
          save label
        </button>
      </div>

      <div style={{ display: 'flex', gap: 6, marginBottom: 10 }}>
        <input
          aria-label="Skill slug"
          value={skillSlug}
          onChange={(ev) => setSkillSlug(ev.target.value)}
          placeholder="skill slug"
          style={{ flex: 1, padding: '4px 6px' }}
        />
        <button className="tool-btn" onClick={() => toggleSkill(skillSlug, true)}>
          enable skill
        </button>
        <button className="tool-btn" onClick={() => toggleSkill(skillSlug, false)}>
          disable skill
        </button>
      </div>

      {policies.length > 0 && (
        <div style={{ marginBottom: 10 }}>
          {policies.map(([slug, on]) => (
            <div key={slug} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 'var(--n-fs-meta)', marginBottom: 3 }}>
              <code>{slug}</code>
              <span>{on ? 'synced' : 'excluded'}</span>
              <button className="tool-btn" style={{ marginLeft: 'auto' }} onClick={() => toggleSkill(slug, !on)}>
                {on ? 'disable' : 'enable'}
              </button>
            </div>
          ))}
        </div>
      )}

      <div style={{ display: 'flex', gap: 6, marginBottom: 8 }}>
        <input
          aria-label="Peer ID"
          value={peerId}
          onChange={(ev) => setPeerId(ev.target.value)}
          placeholder="peer-id"
          style={{ width: 110, padding: '4px 6px' }}
        />
        <input
          aria-label="Peer URL"
          value={peerUrl}
          onChange={(ev) => setPeerUrl(ev.target.value)}
          placeholder="https://peer-hub:8000"
          style={{ flex: 1, padding: '4px 6px' }}
        />
        <button className="tool-btn" onClick={addPeer}>
          + peer
        </button>
      </div>

      {peers.map((p) => (
        <div key={p.peer_id} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 'var(--n-fs-meta)', marginBottom: 3 }}>
          <code>{p.peer_id}</code>
          <span style={{ color: 'var(--ink-2)' }}>{p.url}</span>
          <button className="tool-btn" style={{ marginLeft: 'auto' }} onClick={() => removePeer(p.peer_id)}>
            remove
          </button>
        </div>
      ))}

      {note && <div style={{ fontSize: 'var(--n-fs-meta)', color: 'var(--accent-light)', marginTop: 6 }}>{note}</div>}
    </Card>
  );
}
