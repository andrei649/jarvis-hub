/* Signing, graded by the request's tier (PHASE_B_PLAN.md §5.4; confirm.tsx confirmStyle):

     tier 0, read only        one click on "Sign" (filled: that click is the signature)
     tier 1, reversible       two steps: "Sign" (an outline) → "Sign: <title>" with what it does
                              → "Confirm signature" (filled) or "Cancel"
     tiers 2–3, and unknown   the SignLine: the page's one bordered sheet, "Sign here — type
                              <phrase>"; the box's placeholder is the phrase; the button stays an
                              outline until the phrase matches exactly, then fills with the accent

   Everything goes through ConfirmAction (plain styling, enterConfirms=false, repeatConfirms=false):
   Enter in the signature box does nothing, no key anywhere signs — the docket registers no
   shortcut — and neither a held key's repeat nor the second click of a double-click presses a
   signing button (the first press arms the confirmation and moves focus to it; it must not also
   confirm).
   The accent is spent only here, on the owner's hand: the "awaits your signature" seal on the
   button, filled once the signature is ready. */
import React from 'react';
import { ConfirmAction } from '../confirm';
import { Mark } from '../frame/kit';
import { fmt, pick, type Lang } from '../frame/strings';
import { DOCKET_STRINGS } from './strings';
import { fillNodes } from './text';
import type { Friction } from './types';
import './docket.css';

/** The seal and the word on a signing button: "awaits your signature". On the typed signature's
 *  button (`ready`), the open seal stays while the phrase does not match and the given seal
 *  takes its place once it does — CSS shows one or the other from the button's disabled state. */
export function SealWord({ word, ready = false }: { word: string; ready?: boolean }) {
  return (
    <span className={ready ? 'n-signline__seal n-signline__seal--ready' : 'n-signline__seal'}>
      <Mark kind="seal-open" className="n-signline__seal-open" />
      {ready && <Mark kind="seal" className="n-signline__seal-given" />}
      <span>{word}</span>
    </span>
  );
}

/** A signing button that fills with the accent once it can sign (the kit draws the fill). */
export const FILLED_SIGN = 'n-btn n-btn--accent n-signline__sign n-signline__sign--filled';
/** The first of two steps: an outline with the seal; the fill comes on the second. */
export const OUTLINE_SIGN = 'n-btn n-signline__sign';

export interface SignLineProps {
  phrase: string;
  /** The request's title, for the accessible names. */
  title: string;
  lang: Lang;
  /** The button's word ("Sign", "Save and sign"). */
  word?: string;
  /** The signing button's accessible name; default "Sign: <title>". */
  aria?: string;
  disabled?: boolean;
  busy?: boolean;
  /** Resolves true when the hub took the signature, false when it refused it (the line keeps
   *  what was typed, so the owner can retry or cancel). */
  onSign: () => Promise<boolean>;
}

/** The typed signature: tiers 2 and 3, and any tier the hub did not name. (The docket focuses its
 *  box by class, .n-signline__input, when an entry is opened to sign.) */
export function SignLine({ phrase, title, lang, word, aria, disabled = false, busy = false, onSign }: SignLineProps) {
  const s = pick(DOCKET_STRINGS, lang);
  const label = word || s.sign;
  const name = aria || fmt(s.signAria, { title });
  return (
    <div className="n-signline" data-friction="typed" data-phrase={phrase}>
      <ConfirmAction tier={3} open plain enterConfirms={false} repeatConfirms={false} phrase={phrase}
        label={label}
        groupLabel={fmt(s.signLineLabel, { title })}
        groupClassName="n-signline__group"
        extra={<span className="n-signline__x" aria-hidden="true">×</span>}
        prompt={<span className="n-signline__label"><span className="n-signline__here">{s.signHere}</span>{' '}
          <span className="n-signline__how">{fillNodes(s.typePhrase, { phrase: <i className="n-signline__word">{phrase}</i> })}</span></span>}
        inputLabel={fmt(s.signInput, { phrase, title })}
        inputClassName="n-signline__input"
        armedLabel={<SealWord word={label} ready />}
        confirmAriaLabel={name}
        confirmClassName={FILLED_SIGN}
        className="n-btn"
        disabled={disabled} busy={busy}
        onConfirm={onSign} />
    </div>
  );
}

export interface SignControlProps extends Omit<SignLineProps, 'phrase'> {
  friction: Friction;
  /** The typed phrase (typed friction only). */
  phrase: string | null;
  /** Two steps: whether the confirmation is open, and how it opens and closes (the docket owns
   *  it, so a closed entry's "Sign" can open the entry already armed). */
  armed?: boolean;
  onArm?: () => void;
  onDisarm?: () => void;
  /** What signing does, shown on the second step. */
  consequence?: React.ReactNode;
}

/** The open entry's signature, by friction. */
export function SignControl(props: SignControlProps) {
  const { friction, phrase, title, lang, word, aria, disabled = false, busy = false, onSign, armed = false, onArm, onDisarm, consequence } = props;
  const s = pick(DOCKET_STRINGS, lang);
  const label = word || s.sign;
  const name = aria || fmt(s.signAria, { title });
  const trigger = React.useRef<HTMLButtonElement>(null);
  const wasArmed = React.useRef(armed);
  React.useEffect(() => {
    // The confirmation closed while the trigger is back on screen: focus returns to it.
    if (wasArmed.current && !armed && trigger.current && document.activeElement === document.body) trigger.current.focus();
    wasArmed.current = armed;
  }, [armed]);

  if (friction === 'typed') {
    return <SignLine phrase={phrase || 'sign'} title={title} lang={lang} word={word} aria={aria} disabled={disabled} busy={busy} onSign={onSign} />;
  }
  if (friction === 'click') {
    return (
      <div className="n-entry__signrow" data-friction="click">
        <ConfirmAction tier={0} label={<SealWord word={label} />} ariaLabel={name} repeatConfirms={false}
          className={FILLED_SIGN} disabled={disabled || busy} onConfirm={() => { void onSign(); }} />
      </div>
    );
  }
  return (
    <div className="n-entry__signrow" data-friction="two-step">
      {!armed && (
        <button ref={trigger} type="button" className={OUTLINE_SIGN} aria-label={name}
          disabled={disabled || busy} onClick={onArm}><SealWord word={label} /></button>
      )}
      <ConfirmAction tier={1} armed={armed} block plain repeatConfirms={false} onCancel={onDisarm}
        label={label}
        groupLabel={fmt(s.confirmingLabel, { title })}
        groupClassName="n-entry__confirm"
        prompt={<span className="n-entry__confirm-what">
          <span className="n-entry__confirm-title">{name}</span>
          {consequence ? <span className="n-entry__confirm-does">{consequence}</span> : null}
        </span>}
        armedLabel={<SealWord word={s.confirmSign} />}
        confirmClassName={FILLED_SIGN}
        cancelLabel={s.cancel}
        className="n-btn"
        disabled={disabled} busy={busy}
        onConfirm={async () => { const ok = await onSign(); if (ok) onDisarm?.(); return ok; }} />
    </div>
  );
}
