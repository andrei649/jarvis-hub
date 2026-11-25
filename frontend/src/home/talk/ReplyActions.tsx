/* ReplyActions: the fixed action set under a reply, and the owner turn's More
   (PHASE_B_PLAN.md §5.3 "Reply actions").

   A reply carries exactly Copy · Save · Read aloud · Create task · More; More holds Download
   Word, Photoshop, Save to Obsidian, Teach skill, Review Blender model and Turn details, each
   only when it applies. The row is shown on the newest reply and on hover or focus elsewhere
   (talk.css), so it stays in the tab order. An owner turn carries only More (Remember message,
   Create task).

   The controls keep their logic where it lives: Conversation (cockpit.tsx) owns the dialogs and
   passes ready nodes (SaveArtifactButton, the Read aloud button, the Word and Photoshop
   exporters) or handlers; a handler gets the More button as its opener, because the item that
   was pressed is hidden once the menu closes and the dialog returns focus to its opener. */
import React, { useEffect, useRef, useState } from 'react';
import { TalkMenu } from './TalkMenu';
import { talkStrings } from './strings';

export interface MoreItem {
  readonly key: string;
  /** A button the menu draws (closes the menu, then calls onPick with the More button). */
  readonly label?: string;
  readonly onPick?: (opener: HTMLElement) => void;
  /** Or a ready control (an exporter with its own state), drawn as it is. */
  readonly node?: React.ReactNode;
}

function CopyButton({ text, lang }: { text: string; lang: string }) {
  const s = talkStrings(lang);
  const [state, setState] = useState<'idle' | 'copied' | 'failed'>('idle');
  useEffect(() => {
    if (state === 'idle') return undefined;
    const id = setTimeout(() => setState('idle'), 2000);
    return () => clearTimeout(id);
  }, [state]);
  const copy = async () => {
    try {
      if (typeof navigator === 'undefined' || !navigator.clipboard?.writeText) throw new Error('no clipboard');
      await navigator.clipboard.writeText(text);
      setState('copied');
    } catch { setState('failed'); }
  };
  return (
    <button type="button" className="n-acts__btn" data-act="copy" data-state={state} onClick={() => { void copy(); }}>
      {state === 'copied' ? s.copied : state === 'failed' ? s.copyFailed : s.copy}
    </button>
  );
}

function MoreMenu({ items, label, lang, details, detailsOpen, onDetails }: {
  items: readonly MoreItem[]; label: string; lang: string;
  details?: boolean; detailsOpen?: boolean; onDetails?: () => void;
}) {
  const s = talkStrings(lang);
  const [open, setOpen] = useState(false);
  const button = useRef<HTMLButtonElement | null>(null);
  if (!items.length && !details) return null;
  const pick = (item: MoreItem) => {
    setOpen(false);
    const opener = button.current;
    button.current?.focus();
    if (opener) item.onPick?.(opener);
  };
  return (
    <TalkMenu hook="more" menuLabel={label} ariaLabel={label} open={open} onOpenChange={setOpen} align="end" buttonRef={button}
      buttonClassName="n-acts__btn" label={s.more}>
      {items.map((item) => item.node
        ? <div key={item.key} className="n-tmenu__item n-tmenu__item--embed" data-act={item.key}>{item.node}</div>
        : <button key={item.key} type="button" className="n-tmenu__item" data-act={item.key} onClick={() => pick(item)}>{item.label}</button>)}
      {details && (
        <button type="button" className="n-tmenu__item" data-act="details" aria-expanded={!!detailsOpen}
          onClick={() => { setOpen(false); button.current?.focus(); onDetails?.(); }}>{s.turnDetails}</button>
      )}
    </TalkMenu>
  );
}

export interface ReplyActionsProps {
  lang: string;
  /** The reply's text (Copy); '' for a reply written empty, which keeps only More (its Turn details). */
  text: string;
  /** SaveArtifactButton, when the reply may be saved. */
  save?: React.ReactNode;
  /** The Read aloud control. */
  readAloud?: React.ReactNode;
  /** Create task (opens the task dialog on this reply). */
  onTask?: (opener: HTMLElement) => void;
  /** More's items, in order, only those that apply. */
  more: readonly MoreItem[];
  /** The turn's details (the outcome lines that used to sit under the composer), newest reply only. */
  details?: React.ReactNode;
  /** The newest reply shows its row at rest. */
  newest: boolean;
}

export function ReplyActions({ lang, text, save, readAloud, onTask, more, details, newest }: ReplyActionsProps) {
  const s = talkStrings(lang);
  const [detailsOpen, setDetailsOpen] = useState(false);
  return (
    <>
      <div className="n-acts" role="group" aria-label={s.actionsLabel} data-acts="reply" data-newest={newest ? '' : undefined}>
        {text !== '' && <CopyButton text={text} lang={lang} />}
        {save}
        {readAloud}
        {onTask && <button type="button" className="n-acts__btn" data-act="task" onClick={(event) => onTask(event.currentTarget)}>{s.createTask}</button>}
        <MoreMenu items={more} label={s.moreReply} lang={lang} details={!!details} detailsOpen={detailsOpen}
          onDetails={() => setDetailsOpen((value) => !value)} />
      </div>
      {details && detailsOpen && <div className="n-turn__details" data-turn-details="">{details}</div>}
    </>
  );
}

/** An owner turn's actions: More (Remember message, Create task), on hover or focus. */
export function OwnerActions({ lang, onRemember, onTask }: { lang: string; onRemember?: (opener: HTMLElement) => void; onTask?: (opener: HTMLElement) => void }) {
  const s = talkStrings(lang);
  const items: MoreItem[] = [
    ...(onRemember ? [{ key: 'remember', label: s.remember, onPick: onRemember }] : []),
    ...(onTask ? [{ key: 'task', label: s.createTask, onPick: onTask }] : []),
  ];
  if (!items.length) return null;
  return (
    <div className="n-acts" role="group" aria-label={s.ownerActionsLabel} data-acts="owner">
      <MoreMenu items={items} label={s.moreOwner} lang={lang} />
    </div>
  );
}
