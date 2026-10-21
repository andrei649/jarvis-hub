/* H665 — several skills edited in one atomic batch, in the Decision Inbox.

   Two halves. The batches the agent proposed (skill_propose with operations) wait here,
   each with the diff of every file it would touch, read from the hub's ledger; approving
   decides the batch's own card, and the hub applies it whole or not at all. Below them,
   the owner's own batch editor: paste an ordered operations list (create, patch,
   write_file, remove_file, delete), check it (a dry run that shows every diff and changes
   nothing), then apply exactly what was checked. A refused batch shows the failing
   operation, the hub's hints and the file as the batch had it at that point. */
import React, { useState } from 'react';
import { Row, Tag, actA, arr, inpS, mono, refusalReason } from '../panel-kit';
import { ChangeDiff, originLabel } from './skill-changes';

export const SKILL_BATCHES_PATH = '/api/skills/batches';
export const SKILL_BATCH_PATH = '/api/skills/batch';

type FileChange = { file?: string; change?: string; diff?: string; diff_truncated?: boolean; added_truncated?: boolean };
type SkillChange = { name?: string; change?: string; files?: FileChange[]; lint?: { field?: string; message?: string }[] };

/** What a decision on a batch's card did, from the decide route's answer. */
export function batchOutcome(reply: any, approved: boolean): string {
  const action = reply && reply.action;
  if (action && typeof action.note === 'string' && action.note) return action.note;
  const applied = action && action.applied;
  if (!approved) return applied && applied.ok === false ? `not rejected · ${applied.reason}` : 'rejected · no skill changed';
  if (!applied) return 'approved · not applied yet';
  if (applied.ok) return `applied · ${arr(applied, 'skills').map((s: any) => `${s.name} ${s.change}`).join(', ')}`;
  return `not applied · ${applied.detail || applied.reason || 'refused'}`;
}

/** The operations the editor's text holds: a list, or {operations: [...]}; null when not. */
export function parseOperations(text: string): any[] | null {
  try {
    const value = JSON.parse(text);
    const ops = Array.isArray(value) ? value : value && Array.isArray(value.operations) ? value.operations : null;
    return ops && ops.length ? ops : null;
  } catch {
    return null;
  }
}

/** The hub's lesson for a refused batch: the failing operation, hints, the file preview. */
export function BatchLesson({ body }: { body: any }) {
  if (!body || typeof body !== 'object') return null;
  const op = body.failed_op;
  const preview = body.file_preview;
  return (
    <div data-testid="skill-batch-lesson" style={{ ...mono, fontSize: 10.5, marginTop: 6, color: 'var(--amber)' }}>
      <div>{body.detail || body.reason}</div>
      {op && <div style={{ color: 'var(--ink-2)' }}>
        operation {op.index} · {op.action} · {op.name}{op.file_path ? ` · ${op.file_path}` : ''}
      </div>}
      {arr(body, 'hints').map((h: string, i: number) => <div key={i} style={{ color: 'var(--ink-2)' }}>· {h}</div>)}
      {arr(body, 'rolled_back').length > 0 && <div style={{ color: 'var(--ink-2)' }}>
        put back as they were: {arr(body, 'rolled_back').join(', ')}
      </div>}
      {preview && <pre style={{ ...mono, fontSize: 10.5, whiteSpace: 'pre-wrap', margin: '4px 0 0', padding: 6,
        maxHeight: 240, overflow: 'auto', color: 'var(--ink-2)', background: 'var(--surface)',
        border: '1px solid var(--panel-line)', borderRadius: 4 }}>
        {`${preview.skill}/${preview.path}\n${preview.content}`}
      </pre>}
    </div>
  );
}

/** A diff this long opens on request, whole: the hub's ledger keeps every line. */
export const LONG_DIFF_CHARS = 8000;

/** One file's diff. A long one folds behind its line count and opens whole; a diff the hub
    cut short (only past what any allowed file needs) says so. */
export function BatchFileDiff({ f }: { f: FileChange }) {
  const text = f.diff || `${f.change} ${f.file}`;
  const note = f.diff_truncated && <div style={{ ...mono, fontSize: 10, color: 'var(--amber)', marginTop: 2 }}>
    {f.added_truncated ? 'cut short · text this change adds is not all shown' : 'cut short · only removed or unchanged lines omitted'}
  </div>;
  if (text.length <= LONG_DIFF_CHARS) return <><ChangeDiff text={text} />{note}</>;
  return (
    <details data-testid="skill-batch-long-diff" style={{ marginTop: 6 }}>
      <summary style={{ ...mono, fontSize: 10.5, color: 'var(--ink-2)', cursor: 'pointer' }}>
        {f.change} {f.file} · {text.split('\n').length.toLocaleString()} lines · show the whole diff
      </summary>
      <ChangeDiff text={text} />
      {note}
    </details>
  );
}

function BatchDiffs({ skills }: { skills: SkillChange[] }) {
  return <>{skills.map((s, i) => (
    <div key={`${s.name}-${i}`} data-testid="skill-batch-skill" style={{ marginTop: 4 }}>
      <div style={{ ...mono, fontSize: 10.5, color: 'var(--ink-2)' }}>{s.name} · {s.change}</div>
      {(s.files || []).map((f, j) => <BatchFileDiff key={`${f.file}-${j}`} f={f} />)}
    </div>
  ))}</>;
}

export function SkillBatchesInbox({ reply, error, onDecided }:
  { reply: any; error?: string | null; onDecided?: () => void }) {
  const [outcome, setOutcome] = useState<Record<string, string>>({});
  if (error) {
    return <div style={{ ...mono, fontSize: 10, color: 'var(--amber)', marginTop: 8 }}>
      skill batches could not be read · {error}
    </div>;
  }
  const rows = arr(reply, 'batches');
  if (!rows.length) return null;
  const decide = (b: any, approved: boolean) => {
    const id = String(b.id || '');
    setOutcome((o) => ({ ...o, [id]: approved ? 'applying…' : 'rejecting…' }));
    actA(`/api/actions/${encodeURIComponent(String(b.card))}/decide`, { approved },
      (r: any) => { setOutcome((o) => ({ ...o, [id]: batchOutcome(r, approved) })); if (onDecided) onDecided(); },
      (err: any) => setOutcome((o) => ({ ...o, [id]: 'refused · ' + refusalReason(err) })));
  };
  return (
    <div style={{ marginTop: 10 }}>
      <div style={{ ...mono, fontSize: 10, color: 'var(--ink-2)', letterSpacing: 1 }}>
        SKILL BATCHES · {rows.length} awaiting you
      </div>
      {rows.map((b: any, i: number) => (
        <div key={b.id || i} data-testid="skill-batch">
          <Row>
            <span style={{ ...mono, color: 'var(--ink-2)' }}>
              {arr(b, 'operations').length} operation(s) on {arr(b, 'skills').join(', ')}
            </span>
            <span style={{ marginLeft: 'auto', display: 'flex', gap: 5, alignItems: 'center' }}>
              <Tag>{originLabel(b.origin)}</Tag>
              <Tag>all or nothing</Tag>
              <button className="tool-btn" title="approve skill batch" disabled={!b.card}
                onClick={() => decide(b, true)}>✓</button>
              <button className="tool-btn" title="reject skill batch" disabled={!b.card}
                onClick={() => decide(b, false)}>✕</button>
            </span>
          </Row>
          <BatchDiffs skills={arr(b, 'preview')} />
          {outcome[String(b.id || '')] && <div role="status" style={{ ...mono, fontSize: 10, marginTop: 4 }}>
            {outcome[String(b.id || '')]}
          </div>}
        </div>
      ))}
    </div>
  );
}

export function SkillBatchEditor({ onApplied }: { onApplied?: () => void }) {
  const [text, setText] = useState('');
  const [checked, setChecked] = useState<{ text: string; reply: any } | null>(null);
  const [refusal, setRefusal] = useState<any>(null);
  const [status, setStatus] = useState('');
  const ops = parseOperations(text);
  const send = (dryRun: boolean) => {
    if (!ops) return;
    setRefusal(null);
    setStatus(dryRun ? 'checking…' : 'applying…');
    actA(SKILL_BATCH_PATH, { operations: ops, dry_run: dryRun }, (r: any) => {
      if (dryRun) {
        setChecked({ text, reply: r });
        setStatus(`checked · ${arr(r, 'skills').length} skill(s) would change; nothing changed yet`);
      } else {
        setChecked(null);
        setStatus(`applied · ${arr(r, 'skills').map((s: any) => `${s.name} ${s.change}`).join(', ')}`);
        if (onApplied) onApplied();
      }
    }, (err: any) => {
      setChecked(null);
      setRefusal(err && err.body);
      setStatus('refused · ' + refusalReason(err));
    });
  };
  return (
    <details style={{ marginTop: 10 }}>
      <summary style={{ ...mono, fontSize: 10, color: 'var(--ink-2)', letterSpacing: 1, cursor: 'pointer' }}>
        EDIT SEVERAL SKILLS · one atomic batch
      </summary>
      <textarea aria-label="skill batch operations" value={text} rows={8}
        placeholder='[{"name": "my-skill", "action": "patch", "old_string": "…", "new_string": "…"}]'
        onChange={(ev) => { setText(ev.target.value); setChecked(null); }}
        style={{ ...inpS, width: '100%', marginTop: 6, boxSizing: 'border-box' }} />
      <div style={{ display: 'flex', gap: 6, marginTop: 4, alignItems: 'center' }}>
        <button className="tool-btn" disabled={!ops} onClick={() => send(true)}>check</button>
        <button className="tool-btn" title="apply exactly the checked batch"
          disabled={!checked || checked.text !== text} onClick={() => send(false)}>apply</button>
        {!ops && text.trim() && <span style={{ ...mono, fontSize: 10, color: 'var(--amber)' }}>
          not a list of operations
        </span>}
      </div>
      {status && <div role="status" style={{ ...mono, fontSize: 10, marginTop: 4 }}>{status}</div>}
      {checked && <BatchDiffs skills={arr(checked.reply, 'skills')} />}
      <BatchLesson body={refusal} />
    </details>
  );
}
