/* H441 — getting back into a conversation. Resume switches the hub to a past session
   and now answers with a recap the hub rendered from the stored turns, with no model
   call: the last exchanges, each turn on one line, and the tools a reply used
   collapsed to a count ("[3 tool calls: terminal_run, web_search]"). Before this the
   resume button posted and showed nothing; the owner had to open the chat and re-read
   the raw turns. Text only: a turn is rendered as text, never as markup.
   H262 — pin a chat, on both tabs: a pinned chat is never auto-archived and never deleted
   by retention; the row says so with a badge (hover: when it was pinned).
   H440 — a row is a session nobody continued yet: the newest part of a continued chat
   (each branch, if it was continued more than once) or a plain chat. The hub leaves the
   earlier parts out and says how many other sessions the conversation has
   (`continuations`); the row shows that count. Rename sets the owner's own title, which
   the automatic titles never replace. Archive, unarchive and pin act on the whole
   conversation (the hub stamps every member), in both views. Delete removes the row's
   session; for a continued chat the confirm button offers the whole conversation
   (`lineage=true`) and says how many other sessions go with it.
   Third review: a session that was continued and then used again is a row too, under its
   own title, with an "earlier part" badge (the hub marks it `earlier_part`): its later
   turns are in no continuation. And a whole-conversation delete that stops part way says
   what it did delete (the hub's refusal carries `deleted` and `backups`) and reloads the
   list — it used to read "not deleted" over a list that still showed the deleted rows. */
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { apiDelete, apiDownload, apiGet, apiPatch, apiPost } from '../api/client';
import { Card, Row, State, arr, asLive, mono, refusalReason, useApi } from '../panel-kit';

export const RESUME_PATH = '/sessions/resume';
/** H218 — archive, bring back, or delete a conversation for good (backup first, admin). */
export const archivePath = (sid: string) => `/sessions/${encodeURIComponent(sid)}/archive`;
export const unarchivePath = (sid: string) => `/sessions/${encodeURIComponent(sid)}/unarchive`;
/** H440: `lineage` says the whole conversation — a continued chat is never deleted without it. */
export const deletePath = (sid: string, lineage = false) =>
  `/sessions/${encodeURIComponent(sid)}?confirm=DELETE${lineage ? '&lineage=true' : ''}`;
/** H262 — pin a conversation (kept out of archiving and retention), or take the pin off. */
export const pinPath = (sid: string) => `/sessions/${encodeURIComponent(sid)}/pin`;
export const unpinPath = (sid: string) => `/sessions/${encodeURIComponent(sid)}/unpin`;
/** H440 — the owner's own title for a conversation. */
export const titlePath = (sid: string) => `/sessions/${encodeURIComponent(sid)}/title`;
/** H440 — the session a resume of this row opens: the newest member of its lineage. */
export function resumeTarget(s: any): string {
  const sid = s?.session_id || s?.id || (typeof s === 'string' ? s : '');
  return typeof s?.resume_id === 'string' && s.resume_id ? s.resume_id : sid;
}

/** "[3 tool calls: a, b]" — the count of calls, then the distinct names. */
export function toolLine(entry: any): string {
  const n = Number(entry?.tool_calls) || 0;
  if (!n) return '';
  const names = Array.isArray(entry?.tools) ? entry.tools.map(String) : [];
  return `[${n} tool call${n === 1 ? '' : 's'}${names.length ? `: ${names.join(', ')}` : ''}]`;
}

export function RecapView({ recap, session }: { recap: any; session: string }) {
  const exchanges = Array.isArray(recap?.exchanges) ? recap.exchanges : [];
  const total = Number(recap?.total) || exchanges.length;
  return <div data-testid="session-recap" style={{ marginTop: 8, borderTop: '1px solid var(--panel-line)', paddingTop: 6 }}>
    <div style={{ ...mono, fontSize: 9.5, letterSpacing: '.16em', color: 'var(--ink-2)', marginBottom: 4 }}>
      RESUMED {session} · {exchanges.length < total ? `LAST ${exchanges.length} OF ${total} EXCHANGES` : `${total} EXCHANGE${total === 1 ? '' : 'S'}`}
    </div>
    {exchanges.length === 0 && <div style={{ fontSize: 11, color: 'var(--ink-2)' }}>This conversation has no turns yet.</div>}
    {exchanges.map((ex: any[], i: number) => <div key={i} data-testid="recap-exchange" style={{ padding: '3px 0' }}>
      {(Array.isArray(ex) ? ex : []).map((t: any, j: number) => (
        <div key={j} style={{ fontSize: 11, lineHeight: 1.45, color: t.role === 'user' ? 'var(--amber)' : 'var(--ink)' }}>
          <span aria-hidden="true">{t.role === 'user' ? '● ' : '◆ '}</span>
          <span style={{ ...mono, fontSize: 10, color: 'var(--ink-2)' }}>{t.role === 'user' ? 'you' : (t.agent || 'nerva')}: </span>
          {String(t.text ?? '')}
          {toolLine(t) && <span style={{ ...mono, fontSize: 10, color: 'var(--ink-2)' }}> {toolLine(t)}</span>}
        </div>
      ))}
    </div>)}
  </div>;
}

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? '' : 's'}`;

type RetainedTranscript = {
  schema_version: 1; session_id: string; scope: 'retained_current_history'; redacted: true;
  turn_count: number;
  turns: { role: 'user' | 'assistant'; content: string; agent_id: string | null; timestamp: string }[];
};

function validTranscript(value: any, sid: string): value is RetainedTranscript {
  return value?.schema_version === 1 && value.session_id === sid
    && value.scope === 'retained_current_history' && value.redacted === true
    && Array.isArray(value.turns) && value.turns.length <= 100
    && value.turn_count === value.turns.length
    && value.turns.every((turn: any) => turn && (turn.role === 'user' || turn.role === 'assistant')
      && typeof turn.content === 'string' && turn.content.length <= 2 * 1024 * 1024
      && (turn.agent_id === null || typeof turn.agent_id === 'string') && typeof turn.timestamp === 'string')
    && JSON.stringify(value).length <= 2 * 1024 * 1024;
}

const TRANSCRIPT_REFUSALS = new Set(['owner_required', 'admin_required', 'source_busy',
  'session_busy', 'session_not_found', 'not_found', 'transcript_unavailable',
  'transcript_too_large', 'redaction_failed']);
function transcriptRefusal(error: any): string {
  const code = error?.body?.error;
  return typeof code === 'string' && TRANSCRIPT_REFUSALS.has(code) ? code : 'unavailable';
}

const transcriptPath = (sid: string) => `/sessions/${encodeURIComponent(sid)}/transcript`;

/** H440 third review — what a refused delete did before it stopped: the hub's refusal of a
    whole-conversation delete carries the sessions already deleted and their backups.
    '' when nothing was deleted. */
export function partDeleted(err: any): string {
  const gone = arr(err?.body, 'deleted').filter(Boolean);
  if (!gone.length) return '';
  const backups = arr(err?.body, 'backups').filter(Boolean).length;
  return `stopped part way · ${refusalReason(err, 'refused')} · ${plural(gone.length, 'session')} deleted`
    + ` (${plural(backups, 'backup')} written) · the rest of the conversation is still here`;
}

export function SessionsPanel() {
  const [archived, setArchived] = useState(false);
  const { d, e, loading, reload: reloadList } = useApi(archived ? '/sessions?archived=true' : '/sessions');
  const list = arr(d, 'sessions');
  const [resumed, setResumed] = useState<any>(null);   // { session, recap }
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [note, setNote] = useState('');
  const [confirming, setConfirming] = useState('');   // the session a delete waits to be confirmed for
  const [renaming, setRenaming] = useState<{ sid: string; title: string } | null>(null);
  const [preview, setPreview] = useState<{ sid: string; loading: boolean; data: RetainedTranscript | null;
    error: string; downloading: boolean; note: string } | null>(null);
  const previewGeneration = useRef(0);
  const clearPreview = useCallback(() => { ++previewGeneration.current; setPreview(null); }, []);
  const mounted = useRef(false);
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; ++previewGeneration.current; };
  }, []);
  const reload = () => { clearPreview(); reloadList(); };

  const openPreview = async (sid: string) => {
    const generation = ++previewGeneration.current;
    const current = () => mounted.current && previewGeneration.current === generation;
    setPreview({ sid, loading: true, data: null, error: '', downloading: false, note: '' });
    try {
      const result = await apiGet(transcriptPath(sid), { admin: true });
      if (!current()) return;
      if (!validTranscript(result, sid)) throw new Error('Invalid retained conversation response');
      setPreview({ sid, loading: false, data: result, error: '', downloading: false, note: '' });
    } catch (error: any) {
      if (current()) setPreview({ sid, loading: false, data: null, downloading: false, note: '',
        error: `Could not preview retained conversation · ${transcriptRefusal(error)}` });
    }
  };
  const downloadTranscript = async (sid: string) => {
    const generation = ++previewGeneration.current;
    const current = () => mounted.current && previewGeneration.current === generation;
    setPreview((previous) => previous && ({ ...previous, loading: false, downloading: true, error: '', note: '' }));
    try {
      const result = await apiDownload(`${transcriptPath(sid)}?download=true`,
        `session-${sid.replace(/[^A-Za-z0-9_-]/g, '_')}-transcript.json`, { admin: true });
      if (current()) setPreview((previous) => previous && ({ ...previous, downloading: false,
        note: result === 'streamed' ? 'Retained conversation JSON saved' : 'Retained conversation JSON download requested' }));
    } catch (error: any) {
      if (!current()) return;
      const reason = error?.message === 'stream_unavailable'
        ? 'Use a browser with file saving support, or sign in with an owner session instead of a header token.'
        : error?.name === 'AbortError' ? 'File save cancelled' : transcriptRefusal(error);
      setPreview((previous) => previous && ({ ...previous, downloading: false, data: null, note: '',
        error: `Could not download retained conversation · ${reason}` }));
    }
  };

  const resume = (sid: string) => {
    clearPreview();
    setBusy(sid); setError(''); setNote('');
    apiPost(RESUME_PATH, { session_id: sid })
      .then((r: any) => {
        const sessionId = r?.session || sid;
        setResumed({ session: sessionId, recap: r?.recap || null });
        reload();
        window.dispatchEvent(new CustomEvent('nerva:session-selected', {
          detail: { sessionId, turns: Array.isArray(r?.turns) ? r.turns : [] },
        }));
      })
      .catch((err) => { setResumed(null); setError(`not resumed · ${refusalReason(err, 'refused')}`); })
      .finally(() => setBusy(''));
  };
  /* `partly`: what a refusal says when the action was done in part (then the list is stale). */
  const act = (sid: string, run: () => Promise<any>, done: (r: any) => string, verb: string,
    partly?: (err: any) => string) => {
    clearPreview();
    setBusy(sid); setError(''); setNote(''); setConfirming('');
    run()
      .then((r) => { setNote(done(r)); reload(); })
      .catch((err) => {
        const part = partly ? partly(err) : '';
        setError(part || `not ${verb} · ${refusalReason(err, 'refused')}`);
        if (part) reload();
      })
      .finally(() => setBusy(''));
  };
  const archive = (sid: string) => act(sid, () => apiPost(archivePath(sid)), () => `archived ${sid}`, 'archived');
  const unarchive = (sid: string) => act(sid, () => apiPost(unarchivePath(sid)), () => `back in the list: ${sid}`, 'unarchived');
  const remove = (sid: string, more = 0) => act(sid, () => apiDelete(deletePath(sid, more > 0), { admin: true }),
    (r) => (more > 0
      ? `deleted the whole conversation · ${plural(r?.deleted?.length ?? more + 1, 'session')} · ${plural(arr(r, 'backups').filter(Boolean).length, 'backup')}`
      : `deleted ${sid}${r?.backup ? ` · backup at ${r.backup}` : ''}`), 'deleted', partDeleted);
  const pin = (sid: string) => act(sid, () => apiPost(pinPath(sid)),
    () => `pinned ${sid} · never archived or deleted by retention`, 'pinned');
  const unpin = (sid: string) => act(sid, () => apiPost(unpinPath(sid)), () => `unpinned ${sid}`, 'unpinned');
  const rename = () => {
    if (!renaming) return;
    const { sid } = renaming;
    const title = renaming.title.trim();
    if (!title) return;
    clearPreview();
    setBusy(sid); setError(''); setNote('');
    apiPatch(titlePath(sid), { title })
      .then((r: any) => { setRenaming(null); setNote(`renamed ${sid} · ${r?.title || title}`); reload(); })
      .catch((err) => setError(`not renamed · ${refusalReason(err, 'refused')}`))   // the editor stays open
      .finally(() => setBusy(''));
  };
  const confirmingMore = Number(list.find((s: any) => (s?.session_id || s?.id) === confirming)?.continuations) || 0;
  const flip = (next: boolean) => { clearPreview(); setArchived(next); setConfirming(''); setNote(''); setError(''); setResumed(null); setRenaming(null); };
  return <Card title={archived ? 'ARCHIVED CHATS' : 'SESSIONS'} live={asLive(d)} sub={list.length} onReload={reload}>
    <div role="tablist" aria-label="sessions view" style={{ display: 'flex', gap: 6, marginBottom: 6 }}>
      <button role="tab" aria-selected={!archived} className="tool-btn" onClick={() => flip(false)}>chats</button>
      <button role="tab" aria-selected={archived} className="tool-btn" onClick={() => flip(true)}>archived</button>
    </div>
    <State e={e} loading={loading} n={list.length} />
    {list.slice(0, 12).map((s: any, i: number) => {
      const sid = s?.session_id || s?.id || (typeof s === 'string' ? s : '');
      const pinned = typeof s?.pinned_at === 'string' && s.pinned_at !== '';
      const more = Number(s?.continuations) || 0;
      if (renaming?.sid === sid) return <Row key={i}>
        <input aria-label={`title for ${sid}`} value={renaming.title} maxLength={100} autoFocus
          onChange={(ev) => setRenaming({ sid, title: ev.target.value })}
          onKeyDown={(ev) => { if (ev.key === 'Enter') rename(); if (ev.key === 'Escape') setRenaming(null); }}
          style={{ flex: 1, minWidth: 0, fontSize: 12, background: 'transparent', color: 'var(--ink)', border: '1px solid var(--panel-line)', borderRadius: 3, padding: '2px 5px' }} />
        <button className="tool-btn" disabled={!!busy || !renaming.title.trim()} aria-label={`save title for ${sid}`} onClick={rename}>
          {busy === sid ? 'saving…' : 'save'}
        </button>
        <button className="tool-btn" disabled={!!busy} aria-label="cancel rename" onClick={() => setRenaming(null)}>cancel</button>
      </Row>;
      return <React.Fragment key={i}><Row>
        {/* H413: the session's title (its first words, then the local model's name); the id stays visible. */}
        {s?.title
          ? <span style={{ fontSize: 12, color: 'var(--ink)' }} title={sid}>{s.title}
              <span style={{ ...mono, fontSize: 9.5, color: 'var(--ink-2)', marginLeft: 6 }}>{sid.slice(0, 8)}</span></span>
          : <span style={{ ...mono, color: 'var(--accent-light)' }}>{sid}</span>}
        {pinned && <span data-testid="pinned-badge" title={`pinned ${s.pinned_at}`}
          style={{ ...mono, fontSize: 9.5, padding: '1px 5px', border: '1px solid var(--panel-line)', borderRadius: 3, color: 'var(--amber)' }}>pinned</span>}
        {more > 0 && <span data-testid="lineage-badge"
          title={`${plural(more, 'other session')} in this conversation (earlier parts, other branches)`}
          style={{ ...mono, fontSize: 9.5, padding: '1px 5px', border: '1px solid var(--panel-line)', borderRadius: 3, color: 'var(--ink-2)' }}>+{more}</span>}
        {s?.earlier_part === true && <span data-testid="earlier-part-badge"
          title="an earlier part of this conversation, used again after it was continued — its later turns are only here"
          style={{ ...mono, fontSize: 9.5, padding: '1px 5px', border: '1px solid var(--panel-line)', borderRadius: 3, color: 'var(--ink-2)' }}>earlier part · in use</span>}
        <span style={{ marginLeft: 'auto', fontSize: 10, color: 'var(--ink-2)' }}>{s?.turns ?? s?.count ?? ''}</span>
        {sid && <button className="tool-btn" disabled={!!busy} aria-label={`preview retained conversation ${sid}`}
          aria-expanded={preview?.sid === sid} onClick={() => void openPreview(sid)}>preview</button>}
        {sid && <button className="tool-btn" disabled={!!busy} aria-label={`rename ${sid}`}
          onClick={() => { clearPreview(); setError(''); setNote(''); setRenaming({ sid, title: String(s?.title || '') }); }}>rename</button>}
        {sid && (pinned
          ? <button className="tool-btn" disabled={!!busy} aria-label={`unpin ${sid}`} onClick={() => unpin(sid)}>unpin</button>
          : <button className="tool-btn" disabled={!!busy} aria-label={`pin ${sid}`} onClick={() => pin(sid)}>pin</button>)}
        {sid && !archived && <>
          <button className="tool-btn" disabled={!!busy} aria-label={`resume ${sid}`} onClick={() => resume(resumeTarget(s))}>
            {busy === resumeTarget(s) ? 'resuming…' : 'resume'}
          </button>
          <button className="tool-btn" disabled={!!busy} aria-label={`archive ${sid}`} onClick={() => archive(sid)}>archive</button>
        </>}
        {sid && archived && <>
          <button className="tool-btn" disabled={!!busy} aria-label={`resume ${sid}`} onClick={() => resume(resumeTarget(s))}>resume</button>
          <button className="tool-btn" disabled={!!busy} aria-label={`unarchive ${sid}`} onClick={() => unarchive(sid)}>unarchive</button>
          {confirming === sid
            ? <button className="tool-btn" disabled={!!busy} aria-label={`confirm delete ${sid}`} style={{ color: 'var(--red)' }}
                onClick={() => remove(sid, more)}>{more > 0 ? `confirm: delete the whole conversation (${plural(more + 1, 'session')})` : 'confirm: delete for good'}</button>
            : <button className="tool-btn" disabled={!!busy} aria-label={`delete ${sid} permanently`}
                onClick={() => setConfirming(sid)}>delete permanently</button>}
        </>}
      </Row>
      {preview?.sid === sid && <section aria-label={`retained conversation ${sid}`}
        style={{ padding: 8, borderBottom: '1px solid var(--panel-line)' }}>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
          <span style={{ ...mono }}>Retained conversation · {sid}</span>
          <button className="tool-btn" aria-label={`close retained conversation ${sid}`} onClick={clearPreview}>close</button>
          <button className="tool-btn" disabled={preview.downloading} aria-label={`download retained conversation JSON ${sid}`}
            onClick={() => void downloadTranscript(sid)}>{preview.downloading ? 'saving…' : 'download JSON'}</button>
        </div>
        <p style={{ fontSize: 11, color: 'var(--ink-2)' }}>
          Current retained user and assistant text only; automatic secret redaction applied.
          Compacted archives, tool results, media and system messages are excluded. This is not a complete conversation archive.
        </p>
        {preview.loading && <div role="status">Loading retained conversation…</div>}
        {preview.error && <div role="alert" style={{ color: 'var(--red)', fontSize: 11 }}>{preview.error}</div>}
        {preview.note && <div role="status" style={{ fontSize: 11 }}>{preview.note}</div>}
        {preview.data && <>
          <div style={{ fontSize: 11 }}>{plural(preview.data.turn_count, 'retained text turn')} · redacted</div>
          {preview.data.turn_count === 0 && <div style={{ fontSize: 11 }}>No retained text turns.</div>}
          <div style={{ maxHeight: 320, overflow: 'auto', overflowWrap: 'anywhere' }}>
            {preview.data.turns.map((turn, index) => <div key={index} style={{ paddingTop: 8 }}>
              <div style={{ ...mono, color: 'var(--ink-2)' }}>{turn.role}{turn.agent_id ? ` · ${turn.agent_id}` : ''}{turn.timestamp ? ` · ${turn.timestamp}` : ''}</div>
              <div style={{ whiteSpace: 'pre-wrap', fontSize: 12 }}>{turn.content}</div>
            </div>)}
          </div>
        </>}
      </section>}
      </React.Fragment>;
    })}
    {archived && confirming && <div role="note" style={{ fontSize: 11, color: 'var(--ink-2)', marginTop: 4 }}>
      A backup is written first; then the conversation, its checkpoints and its checklist are gone from the hub
      {confirmingMore > 0 ? ` — all ${confirmingMore + 1} sessions of it, earlier parts and other branches included, each with its own backup.` : '.'}</div>}
    {error && <div role="alert" style={{ fontSize: 11, color: 'var(--red)', marginTop: 4 }}>{error}</div>}
    {note && <div role="status" style={{ fontSize: 11, color: 'var(--ink-2)', marginTop: 4 }}>{note}</div>}
    {resumed && (resumed.recap
      ? <RecapView recap={resumed.recap} session={resumed.session} />
      : <div role="status" style={{ fontSize: 11, color: 'var(--ink-2)', marginTop: 4 }}>resumed {resumed.session}</div>)}
  </Card>;
}
