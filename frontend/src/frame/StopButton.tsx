/* The masthead's emergency stop (PHASE_B_PLAN.md §4.1).

     armed or unknown   ■ Stop all agents     one click, the stop's own colours
     global halt on     ‖ Halted · resume in Trust   a link to Trust › Emergency stop
     halt, but stale    ■ Stop all agents, saying the last reading said halted and is out of date
                        (a halt read 2.5 polls ago may be over; stopping is the safe direction)

   Stopping is one click on purpose (a stop must never wait for a second click), and an unknown
   state still offers it, because stopping is the safe direction. Resuming is never here: it is
   typed DISENGAGE on Trust › Emergency stop. While the request is out the button is busy, so a
   double click cannot post twice; its busy words ("Stopping…") change the masthead's width, and
   the masthead refits on them (frame/fit.ts watches its words).

   Both forms keep every word in their name and their tooltip, whatever the masthead draws: its
   "stop" fit step shortens them to "Stop" and "Halted" (Masthead.tsx), so "all agents" and
   "resume in Trust › Emergency stop" live in the title as well as the name.

   What a press came to goes to `onResult` (the frame's notices), worded from the state read
   again after it (useKillSwitch): nothing when the switch reads halted, "Stop was refused — ….
   Nothing was halted." only when the hub refused and the switch still reads armed, and an
   unknown said as unknown. Once the switch reads halted, any earlier sentence is withdrawn: the
   masthead's "Halted" is then the truth. */
import React, { useEffect, useId, useState } from 'react';
import { routeHref } from '../hud-routing';
import { pathOf } from '../nav/routes';
import { Mark, clockTime } from './kit';
import { STOP_STRINGS } from './frame-strings';
import { fmt, pick, type Lang } from './strings';
import { isHalted, type KillSwitch, type StopResult } from './useKillSwitch';

/** What a press that did not end halted says (null when the switch reads halted). */
export function stopRefusalText(result: StopResult, lang: Lang | string): string | null {
  if (result.ok === true) return null;
  const { answer, after, reason } = result;
  const s = pick(STOP_STRINGS, lang);
  if (after === 'armed') {
    if (answer === 'refused') return fmt(s.refused, { reason });
    return answer === 'unanswered' ? s.unansweredArmed : s.acceptedArmed;
  }
  if (answer === 'refused') return fmt(s.refusedUnknown, { reason });
  return answer === 'unanswered' ? s.unanswered : s.acceptedUnknown;
}

const KILL_SWITCH_PAGE = pathOf({ kind: 'panel', id: 'kill-switch' });

export interface StopButtonProps {
  killSwitch: KillSwitch;
  lang: Lang;
  navigate: (path: string) => void;
  /** Called after every press with what it came to (a sentence, or null when the switch reads
   *  halted), and with null when the switch comes to read halted. */
  onResult?: (refusal: string | null) => void;
}

export function StopButton({ killSwitch, lang, navigate, onResult }: StopButtonProps) {
  const s = pick(STOP_STRINGS, lang);
  const [busy, setBusy] = useState(false);
  const staleId = useId();
  // only a current reading hides the stop: a stale "halted" may no longer hold
  const halted = isHalted(killSwitch) && killSwitch.state === 'live';
  const staleHalt = isHalted(killSwitch) && killSwitch.state === 'stale';
  useEffect(() => { if (halted) onResult?.(null); }, [halted, onResult]);
  if (halted) {
    const href = routeHref(KILL_SWITCH_PAGE);
    return (
      <a className="n-masthead__halted" href={href} aria-label={s.haltedLabel} title={s.haltedLabel} data-stop="halted"
        onClick={(event) => {
          if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
          event.preventDefault();
          navigate(KILL_SWITCH_PAGE);
        }}>
        <Mark kind="held" lang={lang} />
        <span data-show-from="s">{s.halted}</span>
        <span data-show-upto="xs">{s.haltedShort}</span>
      </a>
    );
  }
  const press = async () => {
    if (busy) return;
    setBusy(true);
    try {
      const result = await killSwitch.stop();
      onResult?.(stopRefusalText(result, lang));
    } finally {
      setBusy(false);
    }
  };
  const staleWords = staleHalt ? fmt(s.staleHalted, { time: killSwitch.lastGoodAt !== null ? clockTime(killSwitch.lastGoodAt) : '—' }) : null;
  return (
    <>
    {staleWords && <span id={staleId} data-visually-hidden="">{staleWords}</span>}
    <button type="button" className="n-btn n-btn--danger n-btn--sm n-masthead__stop" data-stop={staleHalt ? 'stale-halted' : 'armed'}
      title={staleWords ?? s.stopTitle} aria-label={s.stop} aria-describedby={staleWords ? staleId : undefined}
      aria-busy={busy || undefined} disabled={busy} onClick={press}>
      <svg className="n-masthead__stop-icon" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
        <rect x="3" y="3" width="10" height="10" fill="currentColor" />
      </svg>
      {busy ? <span>{s.stopping}</span> : <>
        <span data-show-from="s">{s.stop}</span>
        <span data-show-upto="xs">{s.stopShort}</span>
      </>}
    </button>
    </>
  );
}
