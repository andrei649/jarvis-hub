/* Files — the owner's file browser over the folders Nerva may show (G21 · H142).

   The hub decides everything that matters (agents/core/file_browser.py): which folders are
   approved, which names are never shown (credentials, keys, data stores, hidden files),
   that no link is followed and no hard link is read, and the size limits. This panel only
   shows what it is given and says why something was refused.

   - Browse a folder, preview a text file, download a file.
   - Upload a new file or make a folder: these never replace anything.
   - Rename and delete are never done here. They become a card in the decision inbox, and
     happen only when the owner accepts it there, after the hub checks that the file is
     still the one on the card. */
import React, { useEffect, useMemo, useRef, useState } from 'react';
import { apiGet, apiGetBlob, apiPost, apiPutBytes } from '../api/client';
import { Card, Tag, inpS, mono, refusalReason, useApi } from '../panel-kit';

export const FILES_ROOTS_PATH = '/api/files/roots';

type Root = { id: string; label: string; path: string };
type Entry = { name: string; kind: 'dir' | 'file' | 'link' | 'other'; size?: number; modified: number; hard_link?: boolean };
type Listing = { path: string; entries: Entry[]; hidden: number; truncated: boolean; max_bytes: number };
type Preview = { path: string; size: number; binary: boolean; text: string | null; truncated: boolean };

const q = (o: Record<string, string>) => new URLSearchParams(o).toString();

export function humanSize(n: number | undefined): string {
  if (n == null) return '';
  if (n < 1024) return `${n} B`;
  const units = ['KiB', 'MiB', 'GiB'];
  let v = n / 1024;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i += 1; }
  return `${v.toFixed(1)} ${units[i]}`;
}

const why = (err: any) => {
  const body = err?.body;
  if (body && typeof body === 'object' && typeof body.detail === 'string') return body.detail;
  return refusalReason(err, String(err?.status || 'error'));
};

export function FilesPanel() {
  const roots = useApi(FILES_ROOTS_PATH, true, true);
  const list: Root[] = Array.isArray((roots.d as any)?.roots) ? (roots.d as any).roots : [];
  const [root, setRoot] = useState('');
  const [path, setPath] = useState('');
  const [listing, setListing] = useState<Listing | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [renaming, setRenaming] = useState<string | null>(null);
  const [newName, setNewName] = useState('');
  const [folder, setFolder] = useState('');
  const fileInput = useRef<HTMLInputElement | null>(null);

  useEffect(() => { if (!root && list.length) setRoot(list[0].id); }, [list, root]);

  const load = (r = root, p = path) => {
    if (!r) return;
    setErr(null);
    apiGet<Listing>(`/api/files/list?${q({ root: r, path: p })}`, { admin: true })
      .then((d) => { setListing(d); setPath(p); })
      .catch((e: any) => setErr(why(e)));
  };
  useEffect(() => { if (root) { setPreview(null); load(root, ''); } }, [root]);  // eslint-disable-line react-hooks/exhaustive-deps

  const join = (name: string) => (path ? `${path}/${name}` : name);
  const crumbs = useMemo(() => (path ? path.split('/') : []), [path]);
  const current = list.find((r) => r.id === root);

  const open = (e: Entry) => {
    setNote(null);
    if (e.kind === 'dir') { setPreview(null); load(root, join(e.name)); return; }
    if (e.kind !== 'file') { setNote('links are never followed'); return; }
    apiGet<Preview>(`/api/files/read?${q({ root, path: join(e.name) })}`, { admin: true })
      .then(setPreview).catch((x: any) => setNote(`not shown · ${why(x)}`));
  };
  const download = (e: Entry) => {
    apiGetBlob(`/api/files/download?${q({ root, path: join(e.name) })}`, { admin: true })
      .then((blob) => {
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url; a.download = e.name; a.rel = 'noopener';
        document.body.appendChild(a); a.click(); a.remove();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
      })
      .catch((x: any) => setNote(`not downloaded · ${why(x)}`));
  };
  // One file after another (a drop can carry several); each says how it went.
  const upload = async (files: FileList | File[] | null) => {
    const list = files ? Array.from(files) : [];
    const said: string[] = [];
    for (const file of list) {
      setNote(`uploading ${file.name}…`);
      try {
        const r = await apiPutBytes<{ path: string; size: number }>(`/api/files/upload?${q({ root, path, name: file.name })}`, file, { admin: true });
        said.push(`uploaded ${r.path} · ${humanSize(r.size)}`);
      } catch (x: any) {
        said.push(`${file.name} not uploaded · ${why(x)}`);
      }
    }
    if (fileInput.current) fileInput.current.value = '';
    if (said.length) { setNote(said.join(' · ')); load(); }
  };
  const [dragging, setDragging] = useState(false);
  const mkdir = () => {
    const name = folder.trim();
    if (!name) return;
    apiPost('/api/files/mkdir', { root, path, name }, { admin: true })
      .then(() => { setFolder(''); setNote(`folder ${name} made`); load(); })
      .catch((x: any) => setNote(`not made · ${why(x)}`));
  };
  const queued = (r: any, what: string) => setNote(`${what} waits for your decision · card #${r?.pending}${r?.existing ? ' (already waiting)' : ''} in the decision inbox`);
  const remove = (e: Entry) => {
    apiPost('/api/files/delete', { root, path: join(e.name) }, { admin: true })
      .then((r) => queued(r, `delete ${e.name}`))
      .catch((x: any) => setNote(`not asked · ${why(x)}`));
  };
  const rename = (e: Entry) => {
    const to = newName.trim();
    if (!to) return;
    apiPost('/api/files/rename', { root, path: join(e.name), new_name: to }, { admin: true })
      .then((r) => { setRenaming(null); setNewName(''); queued(r, `rename ${e.name} → ${to}`); })
      .catch((x: any) => setNote(`not asked · ${why(x)}`));
  };

  const maxBytes = (roots.d as any)?.max_bytes;
  return (
    <Card title="FILES" live={roots.d ? 'live' : undefined} onReload={() => { roots.reload(); load(); }}
      sub={current ? `${current.label} · ${listing ? listing.entries.length : 0} shown${listing?.hidden ? ` · ${listing.hidden} hidden` : ''}` : null}>
      {roots.e && <div role="status" style={{ color: 'var(--amber)', fontSize: 11 }}>not loaded · {String(roots.e)}</div>}
      <div style={{ fontSize: 10.5, color: 'var(--ink-2)', marginBottom: 6 }}>
        Only approved folders (<span style={mono}>{(roots.d as any)?.configured_by || 'NERVA_FILE_BROWSER_DIRS'}</span>). Credentials, keys, databases and hidden files are never shown. Rename and delete become a card in the decision inbox.
        {maxBytes ? ` Limit ${humanSize(maxBytes)} per file.` : null}
      </div>
      {roots.d && !list.length && <div style={{ fontSize: 11 }}>No approved folder exists yet.</div>}
      {list.length > 0 && (
        <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap', marginBottom: 6 }}>
          <label htmlFor="files-root" style={{ fontSize: 10.5 }}>Folder</label>
          <select id="files-root" value={root} onChange={(ev) => setRoot(ev.target.value)} style={inpS}>
            {list.map((r) => <option key={r.id} value={r.id}>{r.label}</option>)}
          </select>
          <nav aria-label="path" style={{ ...mono, fontSize: 11 }}>
            <button className="tool-btn" onClick={() => load(root, '')}>{current?.label || '/'}</button>
            {crumbs.map((c, i) => (
              <span key={i}> / <button className="tool-btn" onClick={() => load(root, crumbs.slice(0, i + 1).join('/'))}>{c}</button></span>
            ))}
          </nav>
        </div>
      )}
      {err && <div role="status" style={{ color: 'var(--amber)', fontSize: 11 }}>refused · {err}</div>}
      {note && <div role="status" style={{ color: 'var(--ink-2)', fontSize: 11, marginBottom: 4 }}>{note}</div>}
      {root && (
        <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap', marginBottom: 6 }}>
          <label htmlFor="files-upload" style={{ fontSize: 10.5 }}>Upload</label>
          <input id="files-upload" type="file" ref={fileInput} onChange={(ev) => { void upload(ev.target.files); }} style={{ fontSize: 10.5 }} />
          <label htmlFor="files-mkdir" style={{ fontSize: 10.5 }}>New folder</label>
          <input id="files-mkdir" value={folder} onChange={(ev) => setFolder(ev.target.value)} style={{ ...inpS, width: 120 }} />
          <button className="tool-btn" onClick={mkdir} disabled={!folder.trim()}>make</button>
        </div>
      )}
      {listing && (
        <div aria-label="drop files here to upload"
          onDragOver={(ev) => { ev.preventDefault(); setDragging(true); }}
          onDragLeave={() => setDragging(false)}
          onDrop={(ev) => { ev.preventDefault(); setDragging(false); void upload(ev.dataTransfer?.files || null); }}
          style={{ border: `1px dashed ${dragging ? 'var(--accent-light)' : 'transparent'}`, borderRadius: 4 }}>
        <ul aria-label="files" style={{ listStyle: 'none', margin: 0, padding: 0 }}>
          {path && (
            <li style={{ padding: '4px 0', borderBottom: '1px solid var(--panel-line)' }}>
              <button className="tool-btn" onClick={() => load(root, crumbs.slice(0, -1).join('/'))}>.. up</button>
            </li>
          )}
          {listing.entries.map((e) => (
            <li key={e.name} style={{ display: 'flex', gap: 8, alignItems: 'center', padding: '4px 0', borderBottom: '1px solid var(--panel-line)', flexWrap: 'wrap' }}>
              <button className="tool-btn" onClick={() => open(e)} aria-label={`open ${e.name}`}>{e.kind === 'dir' ? '▸ ' : ''}{e.name}</button>
              {e.kind !== 'file' && <Tag>{e.kind}</Tag>}
              {e.hard_link && <Tag c="var(--amber)">hard link · not readable</Tag>}
              <span style={{ ...mono, fontSize: 10, color: 'var(--ink-2)' }}>{humanSize(e.size)}</span>
              <span style={{ marginLeft: 'auto', display: 'flex', gap: 4 }}>
                {e.kind === 'file' && <button className="tool-btn" onClick={() => download(e)}>download</button>}
                {renaming === e.name ? (
                  <>
                    <label htmlFor={`rename-${e.name}`} style={{ fontSize: 10.5 }}>to</label>
                    <input id={`rename-${e.name}`} value={newName} onChange={(ev) => setNewName(ev.target.value)} style={{ ...inpS, width: 120 }} />
                    <button className="tool-btn" onClick={() => rename(e)} disabled={!newName.trim()}>ask</button>
                    <button className="tool-btn" onClick={() => { setRenaming(null); setNewName(''); }}>cancel</button>
                  </>
                ) : (
                  <button className="tool-btn" onClick={() => { setRenaming(e.name); setNewName(e.name); }}>rename…</button>
                )}
                {e.kind !== 'other' && <button className="tool-btn" onClick={() => remove(e)}>delete…</button>}
              </span>
            </li>
          ))}
          {!listing.entries.length && <li style={{ fontSize: 11, color: 'var(--ink-2)' }}>empty</li>}
          {listing.truncated && <li style={{ fontSize: 11, color: 'var(--amber)' }}>more entries than shown</li>}
        </ul>
        </div>
      )}
      {preview && (
        <div style={{ marginTop: 8 }} aria-label="preview">
          <div style={{ ...mono, fontSize: 10.5, color: 'var(--ink-2)' }}>{preview.path} · {humanSize(preview.size)}{preview.truncated ? ' · first 256 KiB' : ''}</div>
          {preview.binary
            ? <div style={{ fontSize: 11 }}>binary file · download it to open</div>
            : <pre style={{ ...mono, maxHeight: 320, overflow: 'auto', whiteSpace: 'pre-wrap', background: 'var(--surface)', padding: 6 }}>{preview.text}</pre>}
        </div>
      )}
    </Card>
  );
}
