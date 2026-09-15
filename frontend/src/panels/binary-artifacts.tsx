import { appUrl } from '../base-path';
import React, { useEffect, useRef, useState } from 'react';
import { getToken } from '../api/client';

type BinaryItem = { id: string; mime: string; size: number; agent: string; pinned: boolean; validation?: 'on_download' };
const LIMIT = 16 * 1024 * 1024;
async function request(path: string, init: RequestInit = {}) {
  const token = getToken();
  const response = await fetch(appUrl(path), { ...init, headers: token ? { 'X-User-Token': token } : {},
    credentials: 'same-origin', redirect: 'error', cache: 'no-store' });
  if (!response.ok) throw new Error(`Attachment request failed (${response.status})`);
  return response;
}
export function BinaryCard({ item, refresh }: { item: BinaryItem; refresh: () => void }) {
  const [url, setUrl] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const previewRequest = useRef<AbortController | null>(null);
  const previewURL = useRef('');
  useEffect(() => () => {
    previewRequest.current?.abort();
    previewRequest.current = null;
    if (previewURL.current) URL.revokeObjectURL(previewURL.current);
    previewURL.current = '';
  }, []);
  const load = async () => {
    if (previewRequest.current) return;
    const controller = new AbortController();
    previewRequest.current = controller;
    const current = () => previewRequest.current === controller && !controller.signal.aborted;
    setBusy(true); setError('');
    try {
      const response = await request(`/api/artifacts/${encodeURIComponent(item.id)}/blob`, { signal: controller.signal });
      if (!current()) return;
      if (Number(response.headers.get('content-length')) > LIMIT) throw new Error('Attachment too large');
      const blob = await response.blob();
      if (!current()) return;
      if (blob.size > LIMIT || blob.type !== item.mime) throw new Error('Invalid attachment response');
      if (previewURL.current) URL.revokeObjectURL(previewURL.current);
      previewURL.current = URL.createObjectURL(blob);
      setUrl(previewURL.current);
    } catch (e) { if (current()) setError(String(e)); }
    finally {
      if (current()) { previewRequest.current = null; setBusy(false); }
    }
  };
  const mutate = async (pin: boolean) => {
    setBusy(true); setError('');
    try {
      await request(`/api/artifacts/${encodeURIComponent(item.id)}${pin ? `/pin?pinned=${!item.pinned}` : ''}`, { method: pin ? 'POST' : 'DELETE' });
      refresh();
    } catch (e) { setError(String(e)); }
    finally { setBusy(false); }
  };
  return <article className="art-card">
    <div>{item.mime} · {item.size} bytes</div>
    {item.validation === 'on_download' && <small>Content is validated when loaded.</small>}<small>{item.agent} · {item.id}</small>
    {url && item.mime.startsWith('image/') && <img src={url} alt="Attached image" className="art-img" />}
    {url && item.mime.startsWith('audio/') && <audio controls src={url} />}
    {url && item.mime.startsWith('video/') && <video controls src={url} />}
    <div className="art-actions" style={{ flexWrap: 'wrap' }}>
      {url ? <a className="tool-btn" href={url} download={item.id}>Download attachment</a> : <button className="tool-btn" disabled={busy} onClick={load}>Load attachment</button>}
    {item.id.startsWith('ba-') && <button className="tool-btn" disabled={busy} onClick={() => mutate(true)}>{item.pinned ? 'Unpin attachment' : 'Pin attachment'}</button>}
    {item.id.startsWith('ba-') && <button className="tool-btn" disabled={busy} onClick={() => mutate(false)}>Delete attachment</button>}
    </div>
    {error && <div role="alert">{error}</div>}
  </article>;
}
export function BinaryArtifacts() {
  const [items, setItems] = useState<BinaryItem[]>([]);
  const [enabled, setEnabled] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const refresh = async () => {
    try {
      const data = await (await request('/api/artifacts')).json();
      setEnabled(data.enabled === true); setItems(Array.isArray(data.items) ? data.items : []); setError('');
    } catch { setError('Could not load binary attachments.'); }
    finally { setLoading(false); }
  };
  useEffect(() => { void refresh(); }, []);
  const upload = async (file?: File) => {
    if (!file) return;
    if (file.size > LIMIT) { setError('Attachment exceeds 16 MiB.'); return; }
    setBusy(true); setError('');
    const body = new FormData(); body.append('file', file);
    try { await request('/api/artifacts', { method: 'POST', body }); await refresh(); }
    catch (e) { setError(String(e)); }
    finally { setBusy(false); }
  };
  return <section aria-label="Binary attachments">
    {loading ? <p>Loading attachments…</p> : enabled ? <>
      <label>Attach file <input aria-label="Attach file" type="file" disabled={busy}
        accept="image/png,image/jpeg,image/webp,image/gif,application/pdf,audio/mpeg,audio/wav,audio/ogg,video/mp4,video/webm"
        onChange={e => { void upload(e.target.files?.[0]); e.target.value = ''; }} /></label>
      {!items.length && <p>No binary attachments yet.</p>}
      {items.map(item => <BinaryCard key={item.id} item={item} refresh={refresh} />)}
    </> : <p>Binary attachments are disabled. Enable JARVIS_BINARY_ARTIFACTS on the hub.</p>}
    {error && <p role="alert">{error} <button onClick={refresh}>Retry attachments</button></p>}
  </section>;
}

export async function downloadMediaBundle(ids: string[]) {
  const token = getToken();
  const response = await fetch(appUrl('/api/media/export'), {method:'POST', credentials:'same-origin', redirect:'error', cache:'no-store', headers:{'Content-Type':'application/json', ...(token ? {'X-User-Token':token} : {})}, body:JSON.stringify({ids})});
  if (!response.ok) throw new Error(`Export failed (${response.status})`);
  const blob = await response.blob();
  if (blob.size > 129 * 1024 * 1024 || blob.type !== 'application/zip') throw new Error('Invalid export response');
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a'); link.href = url; link.download = 'nerva-media.zip'; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
