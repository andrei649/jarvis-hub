/* Edit, then sign (PHASE_B_PLAN.md §5.4): the request's payload as JSON, checked as it is typed
   (it must be a JSON object), then signed with the request's own friction — the same typed
   phrase, two steps or click as signing it unchanged; a money request is typed with the edited
   amount, and so is a tier-3 request the edit gives an amount (it is money once edited). It is
   sent as {action: 'edit', payload} and the hub checks the edited request again before anything
   runs. Not offered for the special kinds (they open in Decisions). */
import React, { useId, useMemo, useState } from 'react';
import { fmt, pick, type Lang } from '../frame/strings';
import { tierKey, type TierKey } from '../frame/kit/marks';
import { isMoney } from './kinds';
import { phraseFor } from './phrases';
import { SignControl } from './SignLine';
import { DOCKET_STRINGS } from './strings';
import type { DocketTask, Friction } from './types';
import './docket.css';

type Parsed = { ok: true; value: Record<string, unknown> } | { ok: false };

/** The draft as a JSON object, or not (an array, a number or broken JSON is not a payload). */
export function parsePayloadDraft(draft: string): Parsed {
  try {
    const value = JSON.parse(draft);
    return value && typeof value === 'object' && !Array.isArray(value) ? { ok: true, value } : { ok: false };
  } catch { return { ok: false }; }
}

export interface PayloadEditorProps {
  task: DocketTask;
  title: string;
  tier: TierKey;
  friction: Friction;
  lang: Lang;
  disabled: boolean;
  busy: boolean;
  /** Sign the edited request; resolves true when the hub took it. */
  onSign: (payload: Record<string, unknown>) => Promise<boolean>;
  onCancel: () => void;
  armed?: boolean;
  onArm?: () => void;
  onDisarm?: () => void;
}

/** The phrase an edited request is signed with: the edited payload decides whether it is money
 *  (tier 3 with an amount), and so whether the amount is typed. */
export function editedPhrase(task: DocketTask, tier: TierKey, friction: Friction, lang: Lang, payload: Record<string, unknown> | null): string | null {
  if (!payload) return phraseFor(task, tier, friction, lang);
  const edited = tierKey(task.risk_tier, isMoney({ ...task, payload }));
  return phraseFor(task, edited, friction, lang, payload);
}

export function PayloadEditor({ task, title, tier, friction, lang, disabled, busy, onSign, onCancel, armed, onArm, onDisarm }: PayloadEditorProps) {
  const s = pick(DOCKET_STRINGS, lang);
  const [draft, setDraft] = useState(() => JSON.stringify(task.payload ?? {}, null, 2));
  const parsed = useMemo(() => parsePayloadDraft(draft), [draft]);
  const phrase = editedPhrase(task, tier, friction, lang, parsed.ok ? parsed.value : null);
  const auto = useId().replace(/[^a-zA-Z0-9_-]/g, '');
  const fieldId = `n-entry-editor-${auto}`;
  const noteId = `${fieldId}-note`;
  return (
    <div className="n-entry__editor" data-editor="">
      <label className="n-entry__editor-label" htmlFor={fieldId}>{s.editLabel}</label>
      <textarea id={fieldId} className="n-textarea n-field--code n-entry__editor-field" value={draft} spellCheck={false}
        aria-invalid={!parsed.ok} aria-describedby={noteId} onChange={(ev) => setDraft(ev.target.value)} />
      <p className="n-entry__editor-note" id={noteId} role={parsed.ok ? undefined : 'status'}>
        {parsed.ok ? s.editNote : s.editInvalid}
      </p>
      <SignControl friction={friction} phrase={phrase} title={title} lang={lang} word={s.editSign}
        aria={fmt(s.editSignAria, { title })}
        disabled={disabled || !parsed.ok} busy={busy}
        armed={armed} onArm={onArm} onDisarm={onDisarm}
        onSign={() => (parsed.ok ? onSign(parsed.value) : Promise.resolve(false))} />
      <div className="n-entry__editor-acts">
        <button type="button" className="n-btn n-btn--sm n-btn--quiet" onClick={onCancel} disabled={busy}>{s.editCancel}</button>
      </div>
    </div>
  );
}
