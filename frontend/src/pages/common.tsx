/* Small pieces every Phase B page shares: an in-app link, a clock/date stamp, the way a section
   says what a reading that is not current means. */
import React from 'react';
import { routeHref } from '../hud-routing';
import { clockTime, SourceLabel } from '../frame/kit';
import { fmt, pick, defineStrings, type Lang } from '../frame/strings';
import type { Reading } from '../signals/types';

/** An in-app link to a logical path (`/v2/trust`): a real href, so it opens in a new tab, and a
 *  plain click navigates in place. Never pass it a docketHref / decisionsHref. */
export function PageLink({ path, navigate, children, className = 'n-link' }: { path: string; navigate: (path: string) => void; children: React.ReactNode; className?: string }) {
  return (
    <a className={className} href={routeHref(path)}
      onClick={(event) => {
        if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
        event.preventDefault();
        navigate(path);
      }}>{children}</a>
  );
}

export const COMMON_STRINGS = defineStrings({
  en: {
    todayAt: '{time}',
    sinceTime: 'since {time}',
    sinceDate: 'since {date}',
    notAnswered: 'Not shown: this source did not answer.',
    refusedHelp: 'Sign in with the owner credential to read this.',
    offlineHelp: 'The hub did not answer; the last good reading is not shown here.',
    checkingHelp: 'Waiting for the first answer.',
    unknownHelp: 'This reading is unknown; nothing is assumed.',
  },
  ro: {
    todayAt: '{time}',
    sinceTime: 'din {time}',
    sinceDate: 'din {date}',
    notAnswered: 'Nu este afișat: această sursă nu a răspuns.',
    refusedHelp: 'Autentifică-te cu credențialul proprietarului pentru a citi acest lucru.',
    offlineHelp: 'Hubul nu a răspuns; ultima citire bună nu este afișată aici.',
    checkingHelp: 'Se așteaptă primul răspuns.',
    unknownHelp: 'Această citire este necunoscută; nu se presupune nimic.',
  },
});

const sameDay = (a: number, b: number) => new Date(a).toDateString() === new Date(b).toDateString();

/** "08:14" for a time today, "2 Jul" for an older one. */
export function stamp(at: number, now: number, lang: Lang | string): string {
  if (sameDay(at, now)) return clockTime(at);
  try { return new Date(at).toLocaleDateString(lang === 'ro' ? 'ro-RO' : 'en-GB', { day: 'numeric', month: 'short' }); } catch { return clockTime(at); }
}

/** "since 08:14" or "since 2 Jul". */
export function sinceWords(at: number, now: number, lang: Lang | string): string {
  const s = pick(COMMON_STRINGS, lang);
  return sameDay(at, now) ? fmt(s.sinceTime, { time: clockTime(at) }) : fmt(s.sinceDate, { date: stamp(at, now, lang) });
}

/** Whether a reading's value may be drawn as rows: current, merely stale (drawn under its label),
 *  or a demo sample. Unknown, refused, offline and disabled readings draw no value at all. */
export function drawable(reading: Pick<Reading<unknown>, 'state'>): boolean {
  return reading.state === 'live' || reading.state === 'stale' || reading.state === 'demo' || reading.state === 'empty';
}

/** What a section shows instead of rows when its reading has nothing to draw: the source label
 *  and one plain sentence about it. Null when the reading is drawable. */
export function NoReading({ reading, lang }: { reading: Pick<Reading<unknown>, 'state' | 'reason' | 'status' | 'lastGoodAt'>; lang: Lang | string }) {
  if (drawable(reading)) return null;
  const s = pick(COMMON_STRINGS, lang);
  const help = reading.state === 'refused' ? s.refusedHelp : reading.state === 'offline' ? s.offlineHelp
    : reading.reason === 'checking' ? s.checkingHelp : reading.state === 'disabled' ? s.notAnswered : s.unknownHelp;
  return (
    <p className="n-pgnote" data-reading-state={reading.state}>
      <SourceLabel reading={reading} lang={lang} />
      <span> {help}</span>
    </p>
  );
}
