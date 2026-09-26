/* H157 — the rest of "edit every configuration key from the UI", beside SettingsPanel:
   a search across every category, per-category reset, and moving a configuration to
   another box as JSON.

   - Search matches a setting's category.key and its label, across all categories.
   - Reset puts one category back to its declared values. It asks first (a second
     click), since the owner's values in that category are gone once it runs.
   H259 — the reset shows what it would change before its second step (the hub's dry
   run), "reset every category…" does the same for all of them (secrets kept), and the
   latest reset can be undone: the hub puts back what it replaced, leaving a setting
   changed since then as it is and naming it. A reset is REVERSIBLE (tier 1, H168).
   - Export downloads the hub's settings document. The hub leaves out secrets, values
     that look like credentials and settings that hold credentials by design, and this
     panel names what was left out so nobody expects it on the other box.
   - Import takes a document (pasted, or a file), asks the hub what would change (a dry
     run: every key validated as a single write is, nothing written), shows each change,
     and applies it only on a second step. The hub writes all of it or none of it; a
     refusal lists every reason. A secret's values are never shown. */
import React, { useEffect, useRef, useState } from 'react';
import { apiGet, apiPost } from '../api/client';
import { ConfirmAction, RISK_TIER } from '../confirm';
import { inpS, mono, refusalReason, taS } from '../panel-kit';

export const EXPORT_PATH = '/api/admin/settings/export';
export const IMPORT_PATH = '/api/admin/settings/import';
export const resetPath = (cat: string) => `/api/admin/settings/${encodeURIComponent(cat)}/reset`;
export const RESEED_PATH = '/api/admin/settings/reseed';
export const RESETS_PATH = '/api/admin/settings/resets';
export const UNDO_PATH = '/api/admin/settings/undo';

/** Whether a setting matches the search text: its category.key or its label. */
export function settingMatches(cat: string, it: any, query: string): boolean {
  const q = query.trim().toLowerCase();
  if (!q) return true;
  return `${cat}.${it?.key ?? ''}`.toLowerCase().includes(q)
    || String(it?.label ?? '').toLowerCase().includes(q);
}

/** The hub's refusal as a list: an import's 422 carries every reason in `details`. */
export function refusalList(err: any): string[] {
  const details = err?.body?.details;
  if (Array.isArray(details) && details.length) return details.map(String);
  return [refusalReason(err, 'refused')];
}

export const shown = (v: any): string => {
  if (typeof v === 'string') return v === '' ? '""' : v;
  try { return JSON.stringify(v); } catch { return String(v); }
};

const PREVIEW_LINES = 8;
const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? '' : 's'}`;

/** What a reset would change, from the hub's dry run: one line per setting (the first
    few), and the secrets it keeps and the settings the posture still forces. */
function ResetPreview({ plan }: { plan: any }) {
  if (!plan) return <span style={{ ...mono, fontSize: 9.5, color: 'var(--ink-3)' }}>asking the hub what would change…</span>;
  if (plan.error) return <span role="alert" style={{ ...mono, fontSize: 9.5, color: 'var(--red)' }}>no preview · {plan.error}</span>;
  const changes = Array.isArray(plan.changes) ? plan.changes : [];
  const kept = Array.isArray(plan.kept) ? plan.kept.length : 0;
  const forced = Array.isArray(plan.overridden) ? plan.overridden : [];
  return <div style={{ ...mono, fontSize: 9.5, color: 'var(--ink-2)', margin: '4px 0' }}>
    <div>{changes.length ? `${plural(changes.length, 'setting')} would change` : 'nothing to change: already the defaults'}
      {kept ? ` · ${plural(kept, 'secret')} kept` : ''}</div>
    {changes.slice(0, PREVIEW_LINES).map((c: any) => <div key={c.setting}>{`${c.setting}: ${shown(c.from)} → ${shown(c.to)}`}</div>)}
    {changes.length > PREVIEW_LINES && <div>…and {changes.length - PREVIEW_LINES} more</div>}
    {forced.length > 0 && <div>{forced.join(', ')} still set by the posture</div>}
  </div>;
}

function usePreview(path: string) {
  const [plan, setPlan] = useState<any>(null);
  const ask = () => {
    setPlan(null);
    apiPost(path, { dry_run: true }, { admin: true })
      .then((r: any) => setPlan(r || { changes: [] }))
      .catch((err) => setPlan({ error: refusalReason(err, 'refused') }));
  };
  return { plan, ask };
}

export function ResetCategory({ cat, count, onDone }: { cat: string; count?: number; onDone?: (cat: string) => void }) {
  const [note, setNote] = useState('');
  const { plan, ask } = usePreview(resetPath(cat));
  const run = () => apiPost(resetPath(cat), {}, { admin: true })
    .then((r: any) => {
      const moved = Array.isArray(r?.reset) ? r.reset.length : 0;
      const kept = Array.isArray(r?.kept) && r.kept.length ? ` · kept ${r.kept.length} secret${r.kept.length === 1 ? '' : 's'}` : '';
      const forced = Array.isArray(r?.overridden) && r.overridden.length ? ` · ${r.overridden.join(', ')} still set by the posture` : '';
      setNote((moved ? `reset ${moved}${r?.undo != null ? ' · can be undone' : ''}` : 'already the defaults') + kept + forced);
      if (onDone) onDone(cat);
      return true;
    })
    .catch((err) => { setNote(`not reset · ${refusalReason(err, 'refused')}`); return true; });
  const all = count ? `all ${count} ` : '';
  return <span style={{ display: 'inline-flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
    <ConfirmAction tier={RISK_TIER.REVERSIBLE} label="reset" ariaLabel={`reset ${cat}`} style={{ padding: '0 5px', fontSize: 9.5 }}
      onArm={() => { setNote(''); ask(); }} extra={<ResetPreview plan={plan} />} onConfirm={run}
      armedLabel={<>reset {all}{cat} settings to defaults? (secrets kept)</>} confirmAriaLabel={`confirm reset ${cat}`} />
    {note && <span style={{ ...mono, fontSize: 9.5, color: note.startsWith('not') ? 'var(--red)' : 'var(--green)' }}>{note}</span>}
  </span>;
}

/** Every category back to its declared values (the hub's reseed): previewed, secrets kept. */
export function ResetAll({ onDone }: { onDone?: () => void }) {
  const [note, setNote] = useState('');
  const { plan, ask } = usePreview(RESEED_PATH);
  const run = () => apiPost(RESEED_PATH, {}, { admin: true })
    .then((r: any) => {
      const moved = Array.isArray(r?.reset) ? r.reset.length : 0;
      setNote(moved ? `reset ${plural(moved, 'setting')}${r?.undo != null ? ' · can be undone' : ''}` : 'already the defaults');
      if (onDone) onDone();
      return true;
    })
    .catch((err) => { setNote(`not reset · ${refusalReason(err, 'refused')}`); return true; });
  return <div style={{ marginTop: 6 }}>
    <ConfirmAction tier={RISK_TIER.REVERSIBLE} block label="reset every category…" onArm={() => { setNote(''); ask(); }}
      extra={<ResetPreview plan={plan} />} armedLabel="reset them to defaults" onConfirm={run} />
    {note && <div role="status" style={{ ...mono, fontSize: 9.5, color: note.startsWith('not') ? 'var(--red)' : 'var(--green)' }}>{note}</div>}
  </div>;
}

/** The latest reset, and a way back: the hub restores what it replaced and names what it
    left as it was (changed since, or no longer valid). */
export function UndoReset({ refresh = 0, onDone }: { refresh?: number; onDone?: (categories: string[]) => void }) {
  const [last, setLast] = useState<any>(null);
  const [note, setNote] = useState('');
  const [error, setError] = useState('');
  const load = () => apiGet(RESETS_PATH, { admin: true })
    .then((r: any) => setLast((Array.isArray(r?.resets) ? r.resets : [])[0] || null))
    .catch(() => setLast(null));
  useEffect(() => { load(); }, [refresh]); // eslint-disable-line react-hooks/exhaustive-deps
  const run = () => apiPost(UNDO_PATH, {}, { admin: true })
    .then((r: any) => {
      const skipped = Array.isArray(r?.skipped) ? r.skipped : [];
      const restored = Array.isArray(r?.restored) ? r.restored : [];
      setError('');
      setNote(`restored ${restored.length}` + (skipped.length ? ` · left ${skipped.map((x: any) => `${x.setting} (${x.reason})`).join(', ')}` : ''));
      load();
      if (onDone) onDone([...new Set([...restored, ...skipped.map((x: any) => x.setting)].map((n: string) => n.split('.')[0]))]);
      return true;
    })
    .catch((err) => { setError(`not undone · ${refusalReason(err, 'refused')}`); load(); return true; });
  const open = last && !last.undone;
  if (!open && !note && !error) return null;
  const count = Array.isArray(last?.settings) ? last.settings.length : 0;
  const scope = last?.scope === 'all' ? 'every category' : last?.scope;
  return <div style={{ ...mono, fontSize: 9.5, marginTop: 6, display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
    {open && <>
      <span style={{ color: 'var(--ink-2)' }}>last reset: {scope} · {plural(count, 'setting')}
        {last.at ? ` · ${new Date(last.at * 1000).toLocaleString()}` : ''}</span>
      <ConfirmAction tier={RISK_TIER.REVERSIBLE} label="undo…" armedLabel="undo the reset" onConfirm={run}
        style={{ padding: '0 5px', fontSize: 9.5 }} />
    </>}
    {note && <span role="status" style={{ color: 'var(--green)' }}>{note}</span>}
    {error && <span role="alert" style={{ color: 'var(--red)' }}>{error}</span>}
  </div>;
}

function download(doc: any) {
  try {
    const blob = new Blob([JSON.stringify(doc, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `nerva-settings-${new Date().toISOString().slice(0, 10)}.json`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);   // some browsers cancel a download revoked at once
    return true;
  } catch {
    return false;          // no Blob URLs here (an old browser, a test): the note still says what was exported
  }
}

export function SettingsTransfer({ onDone }: { onDone?: (categories: string[]) => void }) {
  const [exported, setExported] = useState<any>(null);
  const [text, setText] = useState('');
  const [plan, setPlan] = useState<any>(null);       // { doc, changes }
  const [errors, setErrors] = useState<string[]>([]);
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);

  const doExport = () => apiGet(EXPORT_PATH, { admin: true })
    .then((doc: any) => { download(doc); setExported(doc); })
    .catch((err) => setErrors([`export refused · ${refusalReason(err, 'refused')}`]));

  const preview = () => {
    setNote(''); setErrors([]); setPlan(null);
    let doc: any;
    try { doc = JSON.parse(text); } catch { setErrors(['the document is not JSON']); return; }
    if (doc && typeof doc === 'object' && !Array.isArray(doc)) {
      const { dry_run: _ignored, ...rest } = doc;   // the apply step is never a dry run
      doc = rest;
    }
    setBusy(true);
    apiPost(IMPORT_PATH, { ...doc, dry_run: true }, { admin: true })
      .then((r: any) => setPlan({ doc, changes: Array.isArray(r?.changes) ? r.changes : [] }))
      .catch((err) => setErrors(refusalList(err)))
      .finally(() => setBusy(false));
  };

  const apply = () => {
    if (!plan) return;
    setBusy(true);
    apiPost(IMPORT_PATH, plan.doc, { admin: true })
      .then((r: any) => {
        setNote(`imported ${r?.updated ?? 0} setting${r?.updated === 1 ? '' : 's'}`);
        const touched = Array.from(new Set((Array.isArray(r?.changes) ? r.changes : [])
          .map((c: any) => String(c.setting || '').split('.')[0]).filter(Boolean))) as string[];
        setPlan(null); setText('');
        if (onDone) onDone(touched);
      })
      .catch((err) => { setErrors(refusalList(err)); setPlan(null); })
      .finally(() => setBusy(false));
  };

  const readFile = (file?: File | null) => {
    if (!file) return;
    file.text().then((t) => { setText(t); setPlan(null); setErrors([]); }).catch(() => setErrors(['the file could not be read']));
  };

  const count = exported ? Object.values(exported.settings || {}).reduce((n: number, o: any) => n + Object.keys(o || {}).length, 0) : 0;
  return <div style={{ marginTop: 10, borderTop: '1px solid var(--panel-line)', paddingTop: 8 }}>
    <div style={{ ...mono, fontSize: 9.5, letterSpacing: '.16em', color: 'var(--ink-3)', marginBottom: 4 }}>MOVE A CONFIGURATION</div>
    <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
      <button className="tool-btn" onClick={doExport}>⬇ export JSON</button>
      <button className="tool-btn" onClick={() => fileInput.current && fileInput.current.click()}>⬆ import file</button>
      <input ref={fileInput} type="file" accept="application/json,.json" aria-label="import settings file"
        tabIndex={-1} style={{ position: 'absolute', width: 1, height: 1, opacity: 0, pointerEvents: 'none' }}
        onChange={(e) => readFile(e.target.files && e.target.files[0])} />
    </div>
    {exported && <div role="status" style={{ fontSize: 11, color: 'var(--ink-2)', marginTop: 4 }}>
      exported {count} settings{(exported.excluded || []).length ? ' · left out: ' : ''}
      {(exported.excluded || []).map((x: any) => `${x.setting} (${x.reason})`).join(', ')}
    </div>}
    <textarea aria-label="settings document" value={text} placeholder='{"settings": {"system": {"log_level": "INFO"}}}'
      disabled={busy} onChange={(e) => { setText(e.target.value); setPlan(null); }} style={{ ...taS, marginTop: 6 }} />
    <div style={{ display: 'flex', gap: 6, marginTop: 4, alignItems: 'center' }}>
      <button className="tool-btn" onClick={preview} disabled={!text.trim() || busy}>preview import</button>
      {plan && plan.changes.length > 0 && <button className="tool-btn" onClick={apply} disabled={busy}>apply {plan.changes.length} change{plan.changes.length === 1 ? '' : 's'}</button>}
      {note && <span style={{ fontSize: 10, color: 'var(--green)' }}>{note}</span>}
    </div>
    {plan && plan.changes.length === 0 && <div style={{ fontSize: 11, color: 'var(--ink-2)', marginTop: 4 }}>nothing to change: every setting already has that value</div>}
    {plan && plan.changes.map((c: any) => (
      <div key={c.setting} data-testid="import-change" style={{ ...mono, fontSize: 10.5, padding: '2px 0' }}>
        {c.setting}: <span style={{ color: 'var(--ink-3)' }}>{shown(c.from)}</span> → <span style={{ color: 'var(--accent-light)' }}>{shown(c.to)}</span>
      </div>
    ))}
    {errors.map((r, i) => <div key={`${i}:${r}`} role="alert" style={{ ...mono, fontSize: 10, color: 'var(--red)', marginTop: 3 }}>{r}</div>)}
  </div>;
}

export function SettingsSearch({ value, onChange, matches }: { value: string; onChange: (v: string) => void; matches: number }) {
  return <div style={{ display: 'flex', gap: 6, alignItems: 'center', marginBottom: 6 }}>
    <input aria-label="search settings" value={value} placeholder="search every setting (key or label)"
      onChange={(e) => onChange(e.target.value)} style={{ ...inpS, flex: 1 }} />
    {value.trim() && <span style={{ ...mono, fontSize: 10, color: 'var(--ink-3)' }}>{matches} match{matches === 1 ? '' : 'es'}</span>}
  </div>;
}
