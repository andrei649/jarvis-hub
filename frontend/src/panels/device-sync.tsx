import React, { useEffect, useState } from 'react';
import { apiDelete, apiGet, apiPost, apiPut } from '../api/client';
import { Card } from '../panel-kit';

type SyncPeer = {
  peer_id: string;
  url: string;
  label: string;
};

type SyncStatus = {
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
      setNote(
        res?.ok
          ? `pulled ${res.records_decrypted ?? 0} records (config=${res.config_applied ?? 0}, skills=${(res.skills_applied || []).length})`
          : `sync disabled (${res?.reason || 'off'})`,
      );
      refresh();
    } catch (err: any) {
      setNote(String(err?.message || 'pull failed'));
    }
  };

  const runSyncNow = async () => {
    try {
      const res: any = await apiPost('/api/sync/now', {}, { admin: true });
      setNote(res?.ok ? 'bidirectional sync completed' : `sync disabled (${res?.reason || 'off'})`);
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
      <div style={{ fontSize: 11, color: 'var(--ink-2)', marginBottom: 8 }}>
        status: <strong>{status?.enabled ? 'enabled' : 'disabled'}</strong> ({status?.backend || 'no-key'}) · device:{' '}
        <code>{status?.device_label || status?.device_id || 'local'}</code>
      </div>

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
            <div key={slug} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 11, marginBottom: 3 }}>
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
        <div key={p.peer_id} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 11, marginBottom: 3 }}>
          <code>{p.peer_id}</code>
          <span style={{ color: 'var(--ink-2)' }}>{p.url}</span>
          <button className="tool-btn" style={{ marginLeft: 'auto' }} onClick={() => removePeer(p.peer_id)}>
            remove
          </button>
        </div>
      ))}

      {note && <div style={{ fontSize: 11, color: 'var(--accent-light)', marginTop: 6 }}>{note}</div>}
    </Card>
  );
}
