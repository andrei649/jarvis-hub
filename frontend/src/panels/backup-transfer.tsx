/* H162 — restore, download, upload and checkpoints in the System › Backup section.

   The hub decides everything that matters (agents/core/routers/backup.py):
   - A restore is never applied by this panel. "restore…" asks the hub, which drills the
     archive and queues a `backup.restore` card at the irreversible tier; only the owner's
     accept in the decision inbox stages it, and it is applied at the next hub start. A
     staged restore can be withdrawn here until then.
   - By default a restore keeps the live credentials (security/) and hooks (hooks/); the
     owner can ask for them to be replaced too, and the card says so.
   - A download streams to disk (the browser's own download with the owner session, or
     the File System Access API with a token); it is never held whole in the page.
   - An upload must be encrypted with this box's backup key; it is restore-drilled before
     it is listed, and one that fails is refused and not kept. Its restore card says it
     came from elsewhere.
   - Checkpoints are listed read-only; diff and restore stay on /checkpoints and
     `nerva checkpoints` (each restore is its own card). */
import React, { useRef, useState } from 'react';
import { apiDelete, apiDownload, apiPost, apiPutBytes } from '../api/client';
import { ConfirmAction, RISK_TIER } from '../confirm';
import { Tag, mono, refusalReason, useApi } from '../panel-kit';

export const BACKUP_CHECKPOINTS_PATH = '/api/admin/backup/checkpoints?limit=10';

type Staged = { name?: string; state?: string; expires_at?: string; deferred_reason?: string; action_needed?: string } | null;

const why = (err: any) => {
  const body = err?.body;
  if (body && typeof body === 'object') {
    if (typeof body.error === 'string' && body.verify && body.verify.problem) return `${body.error} · ${body.verify.problem}`;
    if (typeof body.detail === 'string') return body.detail;
  }
  return refusalReason(err, String(err?.status || 'error'));
};

export function restoreQueuedNote(r: any, name: string): string {
  const card = `card #${r?.pending}${r?.existing ? ' (already waiting)' : ''}`;
  const restart = r?.restart === 'self' ? 'the hub restarts itself after your accept'
    : 'restart the hub after your accept';
  return `restore of ${name} waits for your decision · ${card} in the decision inbox · ${restart}`;
}

/** Restore + download actions for one listed archive. */
export function BackupRowActions({ name, uploaded = false, onNote }: { name: string; uploaded?: boolean; onNote: (s: string) => void }) {
  const [replace, setReplace] = useState(false);
  const download = () => {
    apiDownload(`/api/admin/backup/download?${new URLSearchParams({ name })}`, name, { admin: true })
      .then((how) => onNote(how === 'streamed' ? `downloaded ${name}` : `download of ${name} started in your browser`))
      .catch((x: any) => { if (x?.name !== 'AbortError') onNote(`not downloaded · ${why(x)}`); });
  };
  const restore = () => apiPost('/api/admin/backup/restore', { name, replace_credentials: replace }, { admin: true })
    .then((r) => { onNote(restoreQueuedNote(r, name)); return true; })
    .catch((x: any) => { onNote(`restore not asked · ${why(x)}`); return false; });
  const what = replace ? 'including the credentials (security/) and hooks (hooks/)'
    : 'keeping the live credentials (security/) and hooks (hooks/)';
  return (
    <span style={{ display: 'inline-flex', gap: 4, alignItems: 'center' }}>
      {uploaded && <Tag c="var(--amber)">uploaded</Tag>}
      <button className="tool-btn" aria-label={`download ${name}`} onClick={download}>download</button>
      <label style={{ fontSize: 10, display: 'inline-flex', gap: 3, alignItems: 'center' }}>
        <input type="checkbox" checked={replace} aria-label={`also replace credentials and hooks from ${name}`}
          onChange={(e) => setReplace(e.target.checked)} />creds
      </label>
      <ConfirmAction tier={RISK_TIER.IRREVERSIBLE_OR_MONEY} label="restore…" phrase="RESTORE" armedLabel="ask to restore"
        ariaLabel={`restore ${name}`}
        prompt={`type RESTORE to ask for ${uploaded ? 'the UPLOADED archive ' : ''}${name} over the live data, ${what} (a card waits for your accept; a rollback snapshot is taken first):`}
        onConfirm={restore} />
    </span>
  );
}

/** The staged restore, if any, with a withdraw button. */
export function StagedRestore({ staged, onDone }: { staged: Staged; onDone: (s: string) => void }) {
  if (!staged || !staged.name) return null;
  const withdraw = () => apiDelete('/api/admin/backup/restore', { admin: true })
    .then(() => onDone(`withdrew the staged restore of ${staged.name}`))
    .catch((x: any) => onDone(`not withdrawn · ${why(x)}`));
  const state = staged.state || 'waiting';
  return (
    <div role="status" style={{ fontSize: 10, marginTop: 6, color: state === 'expired' ? 'var(--ink-2)' : 'var(--amber)' }}>
      staged restore · <span style={mono}>{staged.name}</span> · {state === 'waiting' ? 'applied at the next hub start'
        : state === 'deferred' ? `deferred${staged.deferred_reason ? ` (${staged.deferred_reason})` : ''}` : 'expired, never applied'}
      {staged.action_needed ? ` · ${staged.action_needed}` : ''}
      {state !== 'expired' && (
        <ConfirmAction tier={RISK_TIER.REVERSIBLE} label="withdraw" armedLabel="confirm withdraw"
          prompt="withdraw the staged restore?" style={{ marginLeft: 6 }} onConfirm={withdraw} />
      )}
    </div>
  );
}

/** Upload an archive from elsewhere: drilled by the hub, listed only if it passes. */
export function BackupUpload({ onDone }: { onDone: (s: string) => void }) {
  const input = useRef<HTMLInputElement | null>(null);
  const [busy, setBusy] = useState(false);
  const send = async (files: FileList | null) => {
    const file = files && files[0];
    if (!file) return;
    setBusy(true);
    onDone(`uploading ${file.name}…`);
    try {
      const r: any = await apiPutBytes('/api/admin/backup/upload', file, { admin: true });
      onDone(`uploaded and drilled · listed as ${r.name} · restore it from the list (its card says it was uploaded)`);
    } catch (x: any) {
      onDone(`${file.name} not added · ${why(x)}`);
    } finally {
      setBusy(false);
      if (input.current) input.current.value = '';
    }
  };
  return (
    <label className="tool-btn" style={{ cursor: busy ? 'wait' : 'pointer' }}>
      {busy ? 'uploading…' : 'upload a backup…'}
      <input ref={input} type="file" accept=".enc,application/octet-stream"
        aria-label="upload a backup archive" disabled={busy} style={{ display: 'none' }}
        onChange={(e) => send(e.target.files)} />
    </label>
  );
}

/** File checkpoints, read-only. */
export function CheckpointList() {
  const { d, e, loading } = useApi(BACKUP_CHECKPOINTS_PATH, true, true);
  const items: any[] = Array.isArray((d as any)?.items) ? (d as any).items : [];
  return (
    <div style={{ marginTop: 10 }}>
      <div style={{ fontSize: 10, color: 'var(--ink-2)', letterSpacing: 1 }}>CHECKPOINTS</div>
      {e ? <div style={{ fontSize: 10, color: 'var(--ink-2)' }}>checkpoints unavailable · {why(e)}</div>
        : loading && !d ? <div style={{ fontSize: 10, color: 'var(--ink-2)' }}>loading…</div>
        : !items.length ? <div style={{ fontSize: 10, color: 'var(--ink-2)' }}>no file checkpoints</div>
        : items.map((it, i) => (
          <div key={it.id ?? i} style={{ display: 'flex', gap: 6, fontSize: 10, alignItems: 'center' }}>
            <span style={{ ...mono, color: 'var(--ink-2)' }}>{String(it.id ?? '')}</span>
            <span style={{ color: 'var(--ink-2)' }}>{String(it.path ?? it.root ?? '')}</span>
            <span style={{ marginLeft: 'auto' }}>{it.type && <Tag>{String(it.type)}</Tag>}</span>
          </div>
        ))}
      {(d as any)?.truncated && items.length > 0 && (
        <div style={{ fontSize: 10, color: 'var(--ink-2)' }}>more in /checkpoints list or nerva checkpoints list</div>
      )}
    </div>
  );
}
