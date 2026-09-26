/* H247 — who holds each microphone, in the voice settings: the hub's lease table
   (GET /api/voice/mic). Each device names its holder (host:hub — the hub's wake-word
   listener; hud:<tab>; mobile:<device>) with pause and stop; a paused lease can be
   resumed (the hub asks again: consent, and whether another surface holds the device).
   The kinds the owner allows to open a microphone are shown (voice.mic_surfaces). */
import React, { useEffect, useState } from 'react';
import { apiGet, apiPost } from './api/client';

export const MIC_STATUS = '/api/voice/mic';
const MIC_PAUSE = '/api/voice/mic/pause';
const MIC_RESUME = '/api/voice/mic/resume';
const MIC_STOP_ANY = '/api/voice/mic/stop';

const small = { padding: '0 5px', fontSize: 9.5 };
const line = { display: 'flex', alignItems: 'center', gap: 6, fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--ink-2)', margin: '3px 0' };

export function MicLeases() {
  const [st, setSt] = useState<any>(null);
  const [note, setNote] = useState('');
  const load = () => apiGet<any>(MIC_STATUS).then(setSt).catch(() => setSt({ error: true }));
  useEffect(() => { load(); }, []);
  const act = (path: string, surface: string) => apiPost(path, { surface })
    .then(() => { setNote(''); load(); })
    .catch((err: any) => { setNote(err?.body?.detail || err?.body?.error || 'refused'); load(); });
  if (!st) return null;
  if (st.error) return <div style={line}>microphones: the hub did not answer</div>;
  const devices = Array.isArray(st.devices) ? st.devices : [];
  const paused = Array.isArray(st.paused) ? st.paused : [];
  return (
    <div aria-label="microphones" style={{ marginTop: 8 }}>
      <div style={{ color: 'var(--accent-light)', fontFamily: 'var(--font-mono)', fontSize: 10, letterSpacing: '.14em' }}>MICROPHONES</div>
      {devices.length === 0 && paused.length === 0 && <div style={line}>no microphone is open</div>}
      {devices.map((d: any) => (
        <div key={d.device} style={line}>
          <span>{d.device} · {d.holder.surface}</span>
          <button className="tool-btn" style={small} onClick={() => act(MIC_PAUSE, d.holder.surface)} aria-label={`pause ${d.holder.surface}`}>pause</button>
          <button className="tool-btn" style={small} onClick={() => act(MIC_STOP_ANY, d.holder.surface)} aria-label={`stop ${d.holder.surface}`}>stop</button>
        </div>
      ))}
      {paused.map((p: any) => (
        <div key={p.surface} style={line}>
          <span>{p.device} · {p.surface} (paused{p.paused_by ? ` by ${p.paused_by}` : ''})</span>
          <button className="tool-btn" style={small} onClick={() => act(MIC_RESUME, p.surface)} aria-label={`resume ${p.surface}`}>resume</button>
        </div>
      ))}
      <div style={{ ...line, color: 'var(--ink-3)' }}>allowed: {(st.allowed || []).join(', ') || 'none'}</div>
      {note && <div role="alert" style={{ ...line, color: 'var(--amber)' }}>{note}</div>}
    </div>
  );
}
