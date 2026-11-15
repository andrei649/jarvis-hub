import React, { useEffect, useState } from 'react';
import { apiDelete, apiGet, apiPost } from '../api/client';
import { Card } from '../panel-kit';

type BrokerSession = {
  session_id: string;
  principal_id: string;
  label: string;
  capabilities: string[];
  allow_private_urls: boolean;
  transport: string;
  live: boolean;
  expires_at: number;
};

type BrokerArtifact = {
  artifact_id: string;
  session_id: string;
  filename: string;
  mime_type: string;
  uploaded: boolean;
  size_bytes: number;
  sha256: string;
};

type BrokerCommand = {
  command_id: string;
  session_id: string;
  action: string;
  status: string;
};

type BrokerSnapshot = {
  principal_id: string;
  sessions: BrokerSession[];
  artifacts: BrokerArtifact[];
  recent_commands: BrokerCommand[];
};

export function BrowserBrokerPanel() {
  const [snap, setSnap] = useState<BrokerSnapshot | null>(null);
  const [label, setLabel] = useState('remote-chromium');
  const [selectedSession, setSelectedSession] = useState('');
  const [stepAction, setStepAction] = useState('navigate');
  const [stepUrl, setStepUrl] = useState('https://example.com');
  const [artifactName, setArtifactName] = useState('screenshot.png');
  const [artifactMime, setArtifactMime] = useState('image/png');
  const [issuedSecret, setIssuedSecret] = useState('');
  const [commandDetail, setCommandDetail] = useState('');
  const [statusNote, setStatusNote] = useState('');

  const refresh = () => {
    apiGet('/api/browser/broker')
      .then((res: any) => {
        setSnap(res);
        if (!selectedSession && res?.sessions?.length) {
          setSelectedSession(res.sessions[0].session_id);
        }
      })
      .catch(() => setSnap(null));
  };

  useEffect(() => {
    refresh();
  }, []);

  const registerSession = async () => {
    try {
      const res: any = await apiPost(
        '/api/browser/broker/sessions',
        { label: label.trim() || 'remote-browser' },
        { admin: true },
      );
      setIssuedSecret(`controller_token=${res.controller_token}`);
      setSelectedSession(res.session?.session_id || '');
      setStatusNote(`registered ${res.session?.session_id}`);
      refresh();
    } catch (err: any) {
      setStatusNote(String(err?.message || 'registration refused'));
    }
  };

  const detachSession = async (sid: string) => {
    try {
      await apiDelete(`/api/browser/broker/sessions/${encodeURIComponent(sid)}`, { admin: true });
      setStatusNote(`detached ${sid}`);
      refresh();
    } catch (err: any) {
      setStatusNote(String(err?.message || 'detach failed'));
    }
  };

  const dispatchStep = async () => {
    if (!selectedSession) return;
    const step: Record<string, unknown> = { action: stepAction };
    if (stepUrl.trim()) step.url = stepUrl.trim();
    try {
      const res: any = await apiPost(
        `/api/browser/broker/sessions/${encodeURIComponent(selectedSession)}/steps`,
        { step },
        { admin: true },
      );
      setStatusNote(`dispatched ${res.command_id} (${res.status})`);
      refresh();
    } catch (err: any) {
      setStatusNote(String(err?.message || 'step refused'));
    }
  };

  const inspectCommand = async (cmdId: string) => {
    try {
      const res: any = await apiGet(`/api/browser/broker/commands/${encodeURIComponent(cmdId)}`);
      setCommandDetail(JSON.stringify(res, null, 2));
    } catch (err: any) {
      setStatusNote(String(err?.message || 'command read failed'));
    }
  };

  const mintUploadTicket = async () => {
    if (!selectedSession) return;
    try {
      const res: any = await apiPost(
        `/api/browser/broker/sessions/${encodeURIComponent(selectedSession)}/artifacts/upload-ticket`,
        { filename: artifactName.trim() || 'screenshot.png', mime_type: artifactMime },
        { admin: true },
      );
      setIssuedSecret(`upload_ticket=${res.upload_ticket} (${res.artifact_id})`);
      setStatusNote(`minted one-shot upload ticket for ${res.artifact_id}`);
      refresh();
    } catch (err: any) {
      setStatusNote(String(err?.message || 'upload ticket failed'));
    }
  };

  const mintDownloadTicket = async (artifactId: string) => {
    try {
      const res: any = await apiPost(
        `/api/browser/broker/artifacts/${encodeURIComponent(artifactId)}/download-ticket`,
        { ttl_s: 300 },
      );
      setIssuedSecret(`download_ticket=${res.download_ticket} (${res.artifact_id})`);
      setStatusNote(`minted one-shot download ticket for ${res.artifact_id}`);
    } catch (err: any) {
      setStatusNote(String(err?.message || 'download ticket failed'));
    }
  };

  const sessions = snap?.sessions || [];
  const artifacts = snap?.artifacts || [];
  const commands = snap?.recent_commands || [];

  return (
    <Card
      title="BROWSER BROKER · remote sessions & one-shot artifacts"
      sub={sessions.length}
      onReload={refresh}
    >
      <div style={{ fontSize: 11, color: 'var(--ink-2)', marginBottom: 8 }}>
        principal: <code>{snap?.principal_id || 'owner'}</code> · sessions: {sessions.length} · artifacts: {artifacts.length}
      </div>

      <div style={{ display: 'flex', gap: 6, marginBottom: 10 }}>
        <input
          aria-label="Controller label"
          value={label}
          onChange={(ev) => setLabel(ev.target.value)}
          placeholder="controller label"
          style={{ flex: 1, padding: '4px 6px' }}
        />
        <button className="tool-btn" onClick={registerSession}>
          + register controller
        </button>
      </div>

      {sessions.map((s) => (
        <div
          key={s.session_id}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            padding: '4px 0',
            borderBottom: '1px solid var(--panel-line)',
            fontSize: 11,
          }}
        >
          <button
            className="tool-btn"
            onClick={() => setSelectedSession(s.session_id)}
            style={{ fontWeight: selectedSession === s.session_id ? 700 : 400 }}
          >
            {s.label} ({s.session_id.slice(0, 10)})
          </button>
          <span>{s.live ? 'live' : 'offline'} · {s.transport}</span>
          <button
            className="tool-btn"
            style={{ marginLeft: 'auto' }}
            onClick={() => detachSession(s.session_id)}
          >
            detach
          </button>
        </div>
      ))}

      {selectedSession && (
        <div style={{ marginTop: 10, display: 'grid', gap: 8 }}>
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            <select
              aria-label="Browser step action"
              value={stepAction}
              onChange={(ev) => setStepAction(ev.target.value)}
            >
              <option value="navigate">navigate</option>
              <option value="snapshot">snapshot</option>
              <option value="extract">extract</option>
              <option value="click">click</option>
            </select>
            <input
              aria-label="Target URL"
              value={stepUrl}
              onChange={(ev) => setStepUrl(ev.target.value)}
              placeholder="https://..."
              style={{ flex: 1, padding: '4px 6px' }}
            />
            <button className="tool-btn" onClick={dispatchStep}>
              dispatch step
            </button>
          </div>

          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            <input
              aria-label="Artifact filename"
              value={artifactName}
              onChange={(ev) => setArtifactName(ev.target.value)}
              placeholder="screenshot.png"
              style={{ flex: 1, padding: '4px 6px' }}
            />
            <select
              aria-label="Artifact MIME type"
              value={artifactMime}
              onChange={(ev) => setArtifactMime(ev.target.value)}
            >
              <option value="image/png">image/png</option>
              <option value="application/json">application/json</option>
              <option value="application/pdf">application/pdf</option>
            </select>
            <button className="tool-btn" onClick={mintUploadTicket}>
              mint upload ticket
            </button>
          </div>
        </div>
      )}

      {commands.length > 0 && (
        <div style={{ marginTop: 10 }}>
          <div style={{ fontSize: 10, color: 'var(--ink-2)', marginBottom: 4 }}>RECENT COMMANDS</div>
          {commands.map((c) => (
            <div key={c.command_id} style={{ display: 'flex', gap: 6, alignItems: 'center', fontSize: 11, marginBottom: 3 }}>
              <code>{c.command_id}</code>
              <span>{c.action} · {c.status}</span>
              <button className="tool-btn" style={{ marginLeft: 'auto' }} onClick={() => inspectCommand(c.command_id)}>
                inspect
              </button>
            </div>
          ))}
        </div>
      )}

      {artifacts.length > 0 && (
        <div style={{ marginTop: 10 }}>
          <div style={{ fontSize: 10, color: 'var(--ink-2)', marginBottom: 4 }}>ARTIFACTS</div>
          {artifacts.map((a) => (
            <div key={a.artifact_id} style={{ display: 'flex', gap: 6, alignItems: 'center', fontSize: 11, marginBottom: 3 }}>
              <code>{a.filename}</code>
              <span>{a.uploaded ? `${a.size_bytes} B` : 'awaiting upload'}</span>
              {a.uploaded && (
                <button className="tool-btn" style={{ marginLeft: 'auto' }} onClick={() => mintDownloadTicket(a.artifact_id)}>
                  mint download ticket
                </button>
              )}
            </div>
          ))}
        </div>
      )}

      {issuedSecret && (
        <pre style={{ fontSize: 10, padding: 6, marginTop: 8, overflowX: 'auto' }}>{issuedSecret}</pre>
      )}
      {commandDetail && (
        <pre style={{ fontSize: 10, padding: 6, marginTop: 6, overflowX: 'auto' }}>{commandDetail}</pre>
      )}
      {statusNote && (
        <div style={{ fontSize: 11, color: 'var(--accent-light)', marginTop: 6 }}>{statusNote}</div>
      )}
    </Card>
  );
}
