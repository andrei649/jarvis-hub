/* Glance (/v2/glance): the day at a distance, read only (glance.html; PHASE_B_PLAN.md §6).
   Full screen, no frame. It replaces Ambient.

   Four cells: who needs you (a count; the sign-off happens on the page, never from here), the
   health verdict (the same useVerdict call the Home day register and day band make, so they can
   never disagree), where work ran (a count with its basis, never a large percentage), and what is
   next on the calendar. Under them, this tab's working reply, and a foot with the running head
   as marks and the emergency stop. There is no sign, approve, resume or verdict control here:
   the stop only stops. Large figures are drawn in the second ink; the whole sheet steps a few
   pixels every ten minutes (instantly, and not at all with reduced motion) to spare OLED panels.
   Esc, or the return control, goes back to the page.

   In a window too short for it (the 420×800 floating size, a half-height browser) the sheet
   scrolls from its top and nothing is drawn over anything: its middle never shrinks below what it
   holds, and is centred only where it fits (pages.css .n-glance__main). The foot's marks open their
   popovers inside the window, above themselves at the bottom of the screen (frame/kit Disclosure
   `contain`, which the running head asks for). e2e/ledger-shots.spec.ts runhead-window measures it. */
import React, { useEffect, useRef, useState } from 'react';
import { Mark, SourceLabel, clockTime } from '../frame/kit';
import { defineStrings, fmt, pick, plural, type Lang } from '../frame/strings';
import { hubReading } from '../frame/types';
import { useDocketSummary } from '../docket/links';
import { useVerdict } from '../signals/hooks';
import { RunningHead } from '../frame/RunningHead';
import { useKillSwitch } from '../frame/useKillSwitch';
import type { HubSnapshot, TabTurn, VerdictState } from '../signals/types';
import { rosterAgents } from './agent-states';
import { ageWords } from './WorkOverview';
import { PageLink } from './common';
import './pages.css';

export const GLANCE_STRINGS = defineStrings({
  en: {
    label: 'Glance, {date}',
    mode: 'Glance · the day at a distance · read only',
    returnLabel: 'Return to the page',
    needYou: 'Need you',
    awaitSignature: { one: 'awaits your signature', few: 'await your signature', other: 'await your signature' },
    needUnknown: 'Unknown',
    needNone: 'Nothing waits',
    needNote: 'Signing happens on the page, never from here.',
    friction: '{typed} typed · {twoStep} two-step · {click} one click.',
    health: 'Health',
    healthSince: 'Health · since {time}',
    checkedAt: 'Checked {time}.',
    state_normal: 'Normal',
    state_degraded: 'Degraded',
    state_problem: 'Problem',
    state_halted: 'Halted',
    state_offline: 'Offline',
    state_unknown: 'Unknown',
    state_checking: 'Checking…',
    state_demo: 'Demo sample',
    whereRan: 'Where work ran · all time',
    runsOf: '{local} of {total}',
    runsWhat: 'runs sent to local runners',
    whereNote: 'By route · counted from the route each run used, not a network measurement.',
    whereUnknown: 'Unknown',
    whereUnknownNote: 'The hub did not report where work ran.',
    whereDemoNote: 'A demo sample: no figure is drawn.',
    whereNone: 'None yet',
    whereNoneNote: 'No run has been counted.',
    next: 'Next',
    nextIn: 'Next · in {minutes} min',
    nextNone: 'No event reported',
    nextNoneNote: 'The calendar may be empty or not connected: the hub does not say which.',
    working: '{agent} is working on your question',
    workingMore: 'asked {time} · {age} so far',
    stop: 'Stop all agents',
    stopHint: 'One click. Halts every agent and the job queue. Resuming is done on the Trust page.',
    stopHalted: 'Halted: resume on the Trust page.',
    stopFailed: 'The stop was not confirmed: {why}',
    openTrust: 'Open Trust',
    brand: 'Nerva',
  },
  ro: {
    label: 'Privire rapidă, {date}',
    mode: 'Privire rapidă · ziua de la distanță · doar citire',
    returnLabel: 'Înapoi la pagină',
    needYou: 'Te așteaptă',
    awaitSignature: { one: 'așteaptă semnătura ta', few: 'așteaptă semnătura ta', other: 'așteaptă semnătura ta' },
    needUnknown: 'Necunoscut',
    needNone: 'Nimic nu așteaptă',
    needNote: 'Semnarea se face pe pagină, niciodată de aici.',
    friction: '{typed} cu text scris · {twoStep} în doi pași · {click} cu un clic.',
    health: 'Starea',
    healthSince: 'Starea · din {time}',
    checkedAt: 'Verificat la {time}.',
    state_normal: 'Normal',
    state_degraded: 'Degradat',
    state_problem: 'Problemă',
    state_halted: 'Oprit',
    state_offline: 'Deconectat',
    state_unknown: 'Necunoscut',
    state_checking: 'Se verifică…',
    state_demo: 'Mostră demo',
    whereRan: 'Unde a rulat munca · tot timpul',
    runsOf: '{local} din {total}',
    runsWhat: 'rulări trimise către runnere locale',
    whereNote: 'După rută · numărat după ruta folosită de fiecare rulare, nu o măsurătoare de rețea.',
    whereUnknown: 'Necunoscut',
    whereUnknownNote: 'Hubul nu a raportat unde a rulat munca.',
    whereDemoNote: 'O mostră demo: nu se desenează nicio cifră.',
    whereNone: 'Încă nimic',
    whereNoneNote: 'Nicio rulare nu a fost numărată.',
    next: 'Urmează',
    nextIn: 'Urmează · peste {minutes} min',
    nextNone: 'Niciun eveniment raportat',
    nextNoneNote: 'Calendarul poate fi gol sau neconectat: hubul nu spune care.',
    working: '{agent} lucrează la întrebarea ta',
    workingMore: 'întrebat la {time} · {age} până acum',
    stop: 'Oprește toți agenții',
    stopHint: 'Un clic. Oprește toți agenții și coada de joburi. Reluarea se face pe pagina Încredere.',
    stopHalted: 'Oprit: reia de pe pagina Încredere.',
    stopFailed: 'Oprirea nu a fost confirmată: {why}',
    openTrust: 'Deschide Încredere',
    brand: 'Nerva',
  },
});

export interface GlanceProps {
  hub: HubSnapshot; lang: Lang | string; demo: boolean; clock: Date; turns: readonly TabTurn[];
  onExit: () => void; navigate: (path: string) => void;
}

/** Ten-minute steps for the OLED shift: pixels, never animated. */
export const SHIFTS: ReadonlyArray<readonly [number, number]> = [[0, 0], [4, 2], [2, 5], [-3, 3], [-4, -1], [1, -4]];
export const SHIFT_EVERY_MS = 600_000;

const minutesOf = (hhmm: string): number | null => {
  const m = /^(\d{1,2}):(\d{2})$/.exec(hhmm);
  return m ? Number(m[1]) * 60 + Number(m[2]) : null;
};

export function Glance({ hub, lang, demo, clock, turns, onExit, navigate }: GlanceProps) {
  const s = pick(GLANCE_STRINGS, lang);
  const root = useRef<HTMLElement>(null);
  const docket = useDocketSummary();
  const verdict = useVerdict(hub, lang as Lang, { demo });
  // `lang` words a refused stop's reason, which the sentence around it is in (frame-strings STOP_STRINGS)
  const kill = useKillSwitch(lang);
  const [stopError, setStopError] = useState<string | null>(null);
  const [stopping, setStopping] = useState(false);
  const now = clock.getTime();
  const locale = lang === 'ro' ? 'ro-RO' : 'en-GB';

  // Esc returns to the page, unless an open disclosure (the running head's) is the one that wants it
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== 'Escape' || event.defaultPrevented || event.ctrlKey || event.metaKey || event.altKey) return;
      if (root.current?.querySelector('[aria-expanded="true"]')) return;
      event.preventDefault();
      onExit();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onExit]);

  // OLED care: step the sheet a few pixels every ten minutes, unless the viewer prefers reduced motion
  useEffect(() => {
    let reduced = false;
    try { reduced = !!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches; } catch { /* no media queries */ }
    if (reduced) return;
    let i = 0;
    const timer = window.setInterval(() => {
      i = (i + 1) % SHIFTS.length;
      root.current?.style.setProperty('--n-glance-shift-x', `${SHIFTS[i][0]}px`);
      root.current?.style.setProperty('--n-glance-shift-y', `${SHIFTS[i][1]}px`);
    }, SHIFT_EVERY_MS);
    return () => window.clearInterval(timer);
  }, []);

  const dateWords = (() => { try { return clock.toLocaleDateString(locale, { weekday: 'long', day: 'numeric', month: 'long' }); } catch { return clock.toDateString(); } })();
  const weather = hub.weather as { city?: string; temp?: string | number; desc?: string } | null;
  const weatherLine = weather ? [weather.city, weather.temp !== undefined && weather.temp !== '—' ? `${weather.temp}°` : null, weather.desc && weather.desc !== '—' ? weather.desc : null].filter(Boolean).join(' · ') : null;

  // 1. who needs the owner
  const need = docket.value && (docket.state === 'live' || docket.state === 'stale' || docket.state === 'demo') ? docket.value.entries : docket.state === 'empty' ? 0 : null;
  // 2. health, exactly as the day register says it
  const stateWord = s[`state_${verdict.state}` as keyof typeof s] as string;
  // 3. where work ran
  const locReading = hubReading(hub, now);
  const loc = locReading.state === 'unknown' ? null : hub.locality;
  // 4. next on the calendar
  const calendar = (hub.calendar as Array<{ tm: string; ti: string; vw: string; state: string }>).filter((c) => c && c.ti);
  const nowMin = clock.getHours() * 60 + clock.getMinutes();
  const next = calendar.find((c) => c.state === 'next') ?? calendar.find((c) => (minutesOf(c.tm) ?? -1) > nowMin) ?? null;
  const nextMin = next ? minutesOf(next.tm) : null;
  const after = next && calendar[calendar.indexOf(next) + 1];

  const turn = turns[0];
  const agentName = turn ? rosterAgents(hub.agents).find((a) => a.id === turn.agent.toLowerCase())?.name ?? turn.agent : '';
  const halted = (kill.state === 'live' || kill.state === 'stale') && kill.value ? kill.value.halted : null;
  const stop = async () => {
    if (stopping) return;
    setStopping(true); setStopError(null);
    try {
      const result = await kill.stop();
      if (result.ok === false) setStopError(fmt(s.stopFailed, { why: result.reason }));
    } finally { setStopping(false); }
  };

  return (
    <main className="n-glance" ref={root} aria-label={fmt(s.label, { date: dateWords })} data-glance="" data-demo={demo ? 'true' : undefined}>
      <header className="n-glance__top">
        <span className="n-glance__brand">{s.brand}</span>
        <span>{s.mode}</span>
        <button type="button" className="n-btn n-btn--bare n-glance__return" onClick={onExit}>{s.returnLabel} <kbd className="n-kbd">Esc</kbd></button>
      </header>

      <div className="n-glance__main">
        <div className="n-glance__clock">
          <time dateTime={clock.toISOString()}>{clockTime(clock)}</time>
          <p>{dateWords}{weatherLine && <span>{weatherLine}</span>}</p>
        </div>

        <section className="n-glance__balance" aria-label={s.mode}>
          <div className="n-glance__cell" data-cell="need">
            <p className="n-glance__label"><Mark kind={need !== null && need > 0 ? 'seal-open' : need === 0 ? 'ok' : 'unknown'} size="md" />{s.needYou}</p>
            <p className="n-glance__fig n-glance__fig--hand">{need === null ? '—' : need}</p>
            <p className="n-glance__what">{need === null ? <>{s.needUnknown} <SourceLabel reading={docket} lang={lang} showTime={false} /></> : need === 0 ? s.needNone : plural(lang, s.awaitSignature, need, { n: '' }).trim()}</p>
            <p className="n-glance__note">
              {docket.value && need !== null && need > 0 && <>{fmt(s.friction, { typed: docket.value.friction.typed, twoStep: docket.value.friction.twoStep, click: docket.value.friction.click })} </>}
              {s.needNote}
            </p>
          </div>

          <div className="n-glance__cell" data-cell="health" data-verdict-state={verdict.state}>
            <p className="n-glance__label"><Mark kind={verdict.mark} size="md" />{verdict.since !== null ? fmt(s.healthSince, { time: clockTime(verdict.since) }) : s.health}</p>
            <p className="n-glance__fig n-glance__fig--word">{stateWord}</p>
            <p className="n-glance__what">{verdict.headline}</p>
            <p className="n-glance__note">{verdict.checkedAt !== null ? fmt(s.checkedAt, { time: clockTime(verdict.checkedAt) }) : ''}</p>
          </div>

          <div className="n-glance__cell" data-cell="where">
            <p className="n-glance__label"><Mark kind="here" size="md" />{s.whereRan}</p>
            {demo ? (
              <><p className="n-glance__fig n-glance__fig--word">—</p><p className="n-glance__what">{stateWord}</p><p className="n-glance__note">{s.whereDemoNote}</p></>
            ) : loc && loc.total > 0 ? (
              <><p className="n-glance__fig">{fmt(s.runsOf, { local: loc.local, total: loc.total })}</p><p className="n-glance__what">{s.runsWhat}</p>
                <p className="n-glance__note">{s.whereNote}{locReading.state === 'live' ? '' : <>{' '}<SourceLabel reading={locReading} lang={lang} /></>}</p></>
            ) : loc ? (
              <><p className="n-glance__fig n-glance__fig--word">{s.whereNone}</p><p className="n-glance__what" /><p className="n-glance__note">{s.whereNoneNote}</p></>
            ) : (
              <><p className="n-glance__fig n-glance__fig--word">{s.whereUnknown}</p><p className="n-glance__what" /><p className="n-glance__note">{s.whereUnknownNote}</p></>
            )}
          </div>

          <div className="n-glance__cell" data-cell="next">
            <p className="n-glance__label"><Mark kind="work" size="md" />{next && nextMin !== null && nextMin >= nowMin ? fmt(s.nextIn, { minutes: nextMin - nowMin }) : s.next}</p>
            {next ? (
              <><p className="n-glance__fig">{next.tm}</p><p className="n-glance__what">{next.ti}</p>
                <p className="n-glance__note">{[next.vw, after ? `${after.tm} ${after.ti}` : null].filter(Boolean).join(' · ')}</p></>
            ) : (
              <><p className="n-glance__fig n-glance__fig--word">—</p><p className="n-glance__what">{s.nextNone}</p><p className="n-glance__note">{s.nextNoneNote}</p></>
            )}
          </div>
        </section>

        {turn && (
          <p className="n-glance__now" role="status">
            <Mark kind="work" size="md" />
            <span>{fmt(s.working, { agent: agentName })}</span>
            <span className="n-glance__since">{fmt(s.workingMore, { time: clockTime(turn.askedAt), age: ageWords(Math.max(0, (now - turn.askedAt) / 1000), lang) })}</span>
          </p>
        )}
      </div>

      <footer className="n-glance__foot">
        <RunningHead hub={hub} lang={lang as Lang} demo={demo} variant="marks" />
        <div className="n-glance__stop">
          {halted === true
            ? <p className="n-glance__haltednote"><Mark kind="held" size="md" />{s.stopHalted} <PageLink path="/v2/trust" navigate={navigate}>{s.openTrust}</PageLink></p>
            /* The stop acts on the real hub whatever the page shows, and stopping is the safe
               direction (§4.1): it stays live in the demo sample, as the masthead's does; resuming is
               typed on the Trust page, which the demo sample disables. */
            : <button type="button" className="n-btn n-btn--danger" disabled={stopping} title={s.stopHint} onClick={() => { void stop(); }}>{s.stop}</button>}
          {stopError && <p role="alert" className="n-glance__note">{stopError}</p>}
        </div>
      </footer>
    </main>
  );
}
