/* H168 — one confirmation for every action that needs one, graded like the approval queue.

   The tiers are agents/core/autonomy/policy.py RiskTier, so the HUD and the queue describe
   risk the same way (tests/test_confirm_tiers.py pins the two lists together):

     READ_ONLY (0)             one click
     REVERSIBLE (1)            two steps: the button arms, a second button confirms
     EXTERNAL (2), IRREVERSIBLE_OR_MONEY (3)
                               a typed phrase: the confirm button stays disabled until the
                               phrase is typed exactly

   A tier the table does not know is treated as the strictest. Focus follows the control
   that replaced the one pressed (the button arms → the confirm button or the phrase box;
   cancel → the button again), Escape cancels, and Enter in the phrase box confirms only
   when the phrase matches. An emergency stop is a tier-0 click on purpose: a stop must
   never wait for a second click. */
import React, { useEffect, useRef, useState } from 'react';

export const RISK_TIER = { READ_ONLY: 0, REVERSIBLE: 1, EXTERNAL: 2, IRREVERSIBLE_OR_MONEY: 3 } as const;
export type ConfirmStyle = 'click' | 'two-step' | 'typed';

/** How much confirmation *tier* takes; anything unknown takes the most. */
export function confirmStyle(tier: number): ConfirmStyle {
  if (tier === RISK_TIER.READ_ONLY) return 'click';
  if (tier === RISK_TIER.REVERSIBLE) return 'two-step';
  return 'typed';
}

type Props = {
  tier: number;
  label: React.ReactNode;
  /** The action. When it returns a promise the confirmation stays open until it settles,
   *  and stays open (armed) when it resolves to `false` — a refusal to fix and retry. */
  onConfirm: () => void | boolean | Promise<unknown>;
  /** Called when the confirmation opens (to prefill a field in `extra`). */
  onArm?: () => void;
  /** The phrase a typed confirmation needs, exactly (tiers 2 and 3). */
  phrase?: string;
  /** Text of the confirming button; default `confirm <label>`. */
  armedLabel?: React.ReactNode;
  cancelLabel?: React.ReactNode;
  /** Line shown before the phrase box; default `type <phrase> to confirm`. For a
   *  two-step confirmation, a line shown above the confirm button. */
  prompt?: React.ReactNode;
  /** Fields that belong to the confirmation (a reason box), shown while it is armed —
   *  before the phrase box, so a typed confirmation is the last thing filled in. */
  extra?: React.ReactNode;
  /** Lay the armed state out as a block (a card) instead of inline. */
  block?: boolean;
  /** A typed confirmation that is always shown (no button to open it, no cancel). */
  open?: boolean;
  /** Controlled: the page opens the confirmation itself (a shared panel armed from a
   *  list); nothing renders while it is false, cancel calls `onCancel`, and the page
   *  closes it when the action lands. */
  armed?: boolean;
  onCancel?: () => void;
  /** Accessible names and the placeholder, where a page already has its own words. */
  inputLabel?: string;
  confirmAriaLabel?: string;
  /** Class of the confirming button, when it differs from the others. */
  confirmClassName?: string;
  cancelAriaLabel?: string;
  placeholder?: string;
  disabled?: boolean;
  busy?: boolean;
  title?: string;
  ariaLabel?: string;
  className?: string;
  style?: React.CSSProperties;
};

const DANGER: React.CSSProperties = { color: 'var(--red)' };

export function ConfirmAction({ tier, label, onConfirm, onArm, phrase = 'CONFIRM', armedLabel, cancelLabel = 'cancel', prompt,
  extra, block = false, open = false, armed: armedProp, onCancel, inputLabel, confirmAriaLabel, confirmClassName, cancelAriaLabel,
  placeholder, disabled = false, busy: busyProp = false, title, ariaLabel, className = 'tool-btn', style }: Props) {
  const mode = confirmStyle(tier);
  const controlled = armedProp !== undefined;
  const [armedState, setArmed] = useState(false);
  const armed = controlled ? !!armedProp : (armedState || (open && mode === 'typed'));
  const [typed, setTyped] = useState('');
  const [pending, setPending] = useState(false);
  const busy = busyProp || pending;
  const [focus, setFocus] = useState<'' | 'trigger' | 'confirm' | 'input'>('');
  const refs = { trigger: useRef<HTMLButtonElement>(null), confirm: useRef<HTMLButtonElement>(null), input: useRef<HTMLInputElement>(null) };

  useEffect(() => { setTyped(''); }, [phrase]);   // a new phrase is typed from scratch
  useEffect(() => {
    if (!focus) return;
    refs[focus].current?.focus();
    setFocus('');
  }, [focus, armed]); // eslint-disable-line react-hooks/exhaustive-deps

  const name = ariaLabel || (typeof label === 'string' ? label : 'action');
  const cancel = () => { setArmed(false); setTyped(''); if (controlled) onCancel?.(); else setFocus('trigger'); };
  const close = () => { setArmed(false); setTyped(''); };
  const fire = () => {
    const outcome = onConfirm();
    if (outcome && typeof (outcome as Promise<unknown>).then === 'function') {
      setPending(true);
      (outcome as Promise<unknown>).then(
        (result) => { setPending(false); if (result !== false) close(); },
        () => setPending(false));
      return;
    }
    if (outcome !== false) close();
  };
  const onKey = (ev: React.KeyboardEvent) => { if (ev.key === 'Escape') { ev.preventDefault(); cancel(); } };

  useEffect(() => {                                    // a controlled confirmation takes focus when opened
    if (controlled && armed && mode !== 'click') setFocus(mode === 'typed' ? 'input' : 'confirm');
  }, [controlled, armed]); // eslint-disable-line react-hooks/exhaustive-deps

  if (controlled && (!armed || mode === 'click')) return null;
  if (mode === 'click' || !armed) {
    return (
      <button ref={refs.trigger} type="button" className={className} style={style} title={title} aria-label={ariaLabel}
        disabled={disabled || busy}
        onClick={() => {
          if (mode === 'click') { onConfirm(); return; }
          onArm?.();
          setArmed(true);
          setFocus(mode === 'typed' ? 'input' : 'confirm');
        }}>{label}</button>
    );
  }
  const Group = block ? 'div' : 'span';
  const layout: React.CSSProperties = block ? { display: 'block' } : { display: 'inline-flex', gap: 5, alignItems: 'center', flexWrap: 'wrap' };
  const buttons = { display: 'inline-flex', gap: 5 };
  if (mode === 'two-step') {
    return (
      <Group role="group" aria-label={`confirming ${name}`} onKeyDown={onKey} style={layout}>
        {prompt && (block ? <div>{prompt}</div> : <span>{prompt}</span>)}
        {extra}
        <span style={buttons}>
          <button ref={refs.confirm} type="button" className={confirmClassName || className} style={block ? undefined : DANGER} disabled={disabled || busy}
            aria-label={confirmAriaLabel} onClick={fire}>{armedLabel || <>confirm {label}</>}</button>
          <button type="button" className={className} disabled={busy} aria-label={cancelAriaLabel} onClick={cancel}>{cancelLabel}</button>
        </span>
      </Group>
    );
  }
  const matches = typed === phrase;
  return (
    <Group role="group" aria-label={`confirming ${name}`} onKeyDown={onKey} style={layout}>
      {extra}
      <span style={{ fontSize: 10, ...DANGER }}>{prompt || <>type {phrase} to confirm</>}</span>
      <input ref={refs.input} value={typed} placeholder={placeholder ?? phrase} aria-label={inputLabel || `type ${phrase} to confirm ${name}`}
        onChange={(ev) => setTyped(ev.target.value)}
        onKeyDown={(ev) => { if (ev.key === 'Enter' && matches && !disabled && !busy) { ev.preventDefault(); fire(); } }}
        style={{ background: 'var(--surface)', color: 'var(--ink)', border: '1px solid var(--panel-line)', borderRadius: 4, padding: 4, fontFamily: 'var(--font-mono)', fontSize: 11, width: Math.max(90, phrase.length * 8) }} />
      <button ref={refs.confirm} type="button" className={confirmClassName || className} style={matches ? DANGER : { color: 'var(--ink-3)' }}
        aria-label={confirmAriaLabel} disabled={!matches || disabled || busy} onClick={fire}>{armedLabel || <>confirm {label}</>}</button>
      {!open && <button type="button" className={className} disabled={busy} aria-label={cancelAriaLabel} onClick={cancel}>{cancelLabel}</button>}
    </Group>
  );
}
