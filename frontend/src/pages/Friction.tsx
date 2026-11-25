/* The two graded confirmations the Trust page needs (PHASE_B_PLAN.md §6, confirm.tsx tiers):

     TypedAction    a typed phrase: the button arms a field, the confirm button stays disabled
                    until the phrase is typed exactly. Enter does nothing; only a click on the
                    confirm button acts, so no stray key can resume the agents or move money.
     TwoStepAction  the button arms, a second button confirms; Escape or cancel disarms. Only a
                    fresh press confirms: a held key's repeat or a double-click's second click is
                    ignored, so one gesture never takes both steps.

   Both return focus to the control that replaced the one pressed, report a refusal in place (the
   action returns false or throws: the control stays armed so the owner can retry or cancel), and
   draw only kit classes (n-btn, n-field). The strings come from the caller, in the owner's
   language. */
import React, { useEffect, useRef, useState } from 'react';

export interface FrictionStrings {
  /** The button that arms the confirmation. */
  label: string;
  confirm: string;
  cancel: string;
  /** The line above the field: "Type DISENGAGE to resume every agent." */
  prompt?: string;
  /** The field's accessible name. */
  inputLabel?: string;
  /** Shown while the action runs. */
  busy?: string;
  /** Said (as an alert) when the action did not go through; the control stays armed. */
  refused: string;
}

interface Common {
  strings: FrictionStrings;
  /** True when the action ran; false, a string (the reason, said in place of `refused`) or a throw keeps the confirmation open. */
  onConfirm: () => Promise<boolean | string | void> | boolean | string | void;
  disabled?: boolean;
  className?: string;
  confirmClassName?: string;
  title?: string;
}

function useArm() {
  const [armed, setArmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [refused, setRefused] = useState<false | true | string>(false);
  return { armed, setArmed, busy, setBusy, refused, setRefused };
}

async function run(common: Common, a: ReturnType<typeof useArm>, reset: () => void) {
  a.setBusy(true); a.setRefused(false);
  try {
    const ok = await common.onConfirm();
    if (typeof ok === 'string') a.setRefused(ok);
    else if (ok === false) a.setRefused(true);
    else { a.setArmed(false); reset(); }
  } catch { a.setRefused(true); } finally { a.setBusy(false); }
}

export function TypedAction({ phrase, ...common }: Common & { phrase: string }) {
  const a = useArm();
  const [typed, setTyped] = useState('');
  const trigger = useRef<HTMLButtonElement>(null);
  const field = useRef<HTMLInputElement>(null);
  const wasArmed = useRef(false);
  useEffect(() => {
    if (a.armed) field.current?.focus();
    else if (wasArmed.current) trigger.current?.focus();
    wasArmed.current = a.armed;
  }, [a.armed]);
  const { strings } = common;
  const cancel = () => { a.setArmed(false); a.setRefused(false); setTyped(''); };
  if (!a.armed) {
    return <button ref={trigger} type="button" className={common.className ?? 'n-btn n-btn--sm'} disabled={common.disabled} title={common.title}
      onClick={() => a.setArmed(true)}>{strings.label}</button>;
  }
  const matches = typed === phrase;
  return (
    <span className="n-friction" role="group" aria-label={strings.label} data-friction="typed"
      onKeyDown={(event) => { if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); cancel(); } }}>
      {strings.prompt && <span className="n-friction__prompt">{strings.prompt}</span>}
      <input ref={field} className="n-field n-field--code n-friction__field" value={typed} placeholder={phrase}
        aria-label={strings.inputLabel ?? strings.prompt ?? strings.label} autoComplete="off" spellCheck={false}
        onChange={(event) => setTyped(event.target.value)}
        onKeyDown={(event) => { if (event.key === 'Enter') event.preventDefault(); }} />
      <button type="button" className={common.confirmClassName ?? 'n-btn n-btn--sm n-btn--accent'} disabled={!matches || common.disabled || a.busy}
        onClick={() => { void run(common, a, () => setTyped('')); }}>{a.busy && strings.busy ? strings.busy : strings.confirm}</button>
      <button type="button" className="n-btn n-btn--sm n-btn--quiet" disabled={a.busy} onClick={cancel}>{strings.cancel}</button>
      {a.refused && <span className="n-friction__refused" role="alert" data-friction-refused="">{typeof a.refused === 'string' ? a.refused : strings.refused}</span>}
    </span>
  );
}

export function TwoStepAction(common: Common) {
  const a = useArm();
  const trigger = useRef<HTMLButtonElement>(null);
  const confirm = useRef<HTMLButtonElement>(null);
  const wasArmed = useRef(false);
  useEffect(() => {
    if (a.armed) confirm.current?.focus();
    else if (wasArmed.current) trigger.current?.focus();
    wasArmed.current = a.armed;
  }, [a.armed]);
  const { strings } = common;
  const cancel = () => { a.setArmed(false); a.setRefused(false); };
  if (!a.armed) {
    return <button ref={trigger} type="button" className={common.className ?? 'n-btn n-btn--sm'} disabled={common.disabled} title={common.title}
      onClick={() => a.setArmed(true)}>{strings.label}</button>;
  }
  return (
    <span className="n-friction" role="group" aria-label={strings.label} data-friction="two-step"
      onKeyDown={(event) => { if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); cancel(); } }}>
      {strings.prompt && <span className="n-friction__prompt">{strings.prompt}</span>}
      {/* Only a fresh press confirms (as confirm.tsx repeatConfirms={false}): the first press arms
          and moves focus here, so a held key's auto-repeat, or the second click of a double-click,
          would otherwise take both steps at once — settling a payment in one gesture. */}
      <button ref={confirm} type="button" className={common.confirmClassName ?? 'n-btn n-btn--sm n-btn--ink'} disabled={common.disabled || a.busy}
        onKeyDown={(event) => { if (event.repeat) event.preventDefault(); }}
        onClick={(event) => { if (event.detail > 1) return; void run(common, a, () => {}); }}>{a.busy && strings.busy ? strings.busy : strings.confirm}</button>
      <button type="button" className="n-btn n-btn--sm n-btn--quiet" disabled={a.busy} onClick={cancel}>{strings.cancel}</button>
      {a.refused && <span className="n-friction__refused" role="alert" data-friction-refused="">{typeof a.refused === 'string' ? a.refused : strings.refused}</span>}
    </span>
  );
}
