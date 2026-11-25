/* Today's schedule from the loader's calendar rows (PHASE_B_PLAN.md §5.2 "Today").

   The loader normalises the hub's /dashboard calendar to {tm, ti, vw, state, ts}. The hub's own
   rows carry only `ts` (an ISO date-time with the zone offset, or a bare date for an all-day
   event; agents/core/plugins/google_calendar.py), so `tm` is usually empty: the start is read
   from `tm` when it is a clock time (the seed's shape) and from `ts` otherwise. Which event is
   past and which is next is decided here from the minute clock, not from the row's own `state`,
   so the list cannot lag the time on screen. A row whose start cannot be read ("", "all day") is
   listed as it came and is never called past or next, and nothing downstream may claim "nothing
   more today" while one exists. "in 9 min" is drawn only for the next event, and only when it
   starts today. Titles and places are the hub's plain text.

   Pure: rows and a clock in, items out. */
import { fmt, pick, type Lang } from '../../frame/strings';
import { DAY_STRINGS } from './strings';

export interface ScheduleItem {
  /** "11:00" (local); "" when the start could not be read or the event lasts all day. */
  readonly time: string;
  /** Minutes after midnight, only for an event that starts today; null otherwise. */
  readonly minutes: number | null;
  /** The start as epoch ms; null when it could not be read. */
  readonly at: number | null;
  /** The hub sent a bare date: the event has no start time. */
  readonly allDay: boolean;
  readonly title: string;
  readonly where: string | null;
  readonly phase: 'past' | 'next' | 'later' | 'unknown';
}

const TIME = /^\s*(\d{1,2}):(\d{2})/;
const DATE_ONLY = /^\s*\d{4}-\d{2}-\d{2}\s*$/;
const asText = (v: unknown): string => (typeof v === 'string' ? v.trim() : typeof v === 'number' ? String(v) : '');
const pad = (n: number) => String(n).padStart(2, '0');
const minuteOf = (ms: number): number => Math.floor(ms / 60_000);
const sameDay = (a: Date, b: Date): boolean => a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();

interface Start { time: string; at: number | null; allDay: boolean }

function startOf(row: any, now: Date): Start {
  const tm = asText(row?.tm);
  const m = TIME.exec(tm);
  if (m && Number(m[1]) < 24 && Number(m[2]) < 60) {
    const d = new Date(now);
    d.setHours(Number(m[1]), Number(m[2]), 0, 0);
    return { time: `${pad(Number(m[1]))}:${m[2]}`, at: d.getTime(), allDay: false };
  }
  const ts = asText(row?.ts);
  if (ts && DATE_ONLY.test(ts)) return { time: '', at: null, allDay: true };
  const parsed = ts ? Date.parse(ts) : NaN;
  if (Number.isFinite(parsed)) {
    const d = new Date(parsed);
    return { time: `${pad(d.getHours())}:${pad(d.getMinutes())}`, at: parsed, allDay: false };
  }
  return { time: tm, at: null, allDay: false };
}

/** The day's events in the hub's order, each classified against `now`. */
export function scheduleOf(calendar: readonly any[] | null | undefined, now: Date): ScheduleItem[] {
  const nowMin = minuteOf(now.getTime());
  const rows = (calendar ?? []).flatMap((row): Omit<ScheduleItem, 'phase'>[] => {
    const title = asText(row?.ti) || asText(row?.title);
    if (!title) return [];
    const start = startOf(row, now);
    const today = start.at !== null && sameDay(new Date(start.at), now);
    const minutes = today ? new Date(start.at as number).getHours() * 60 + new Date(start.at as number).getMinutes() : null;
    return [{ ...start, minutes, title, where: asText(row?.vw) || asText(row?.location) || null }];
  });
  const nextIndex = rows.findIndex((r) => r.at !== null && minuteOf(r.at) >= nowMin);
  return rows.map((r, i): ScheduleItem => ({
    ...r,
    phase: r.at === null ? 'unknown' : i === nextIndex ? 'next' : minuteOf(r.at) < nowMin ? 'past' : 'later',
  }));
}

/** "in 9 min", "in 2 h", "in 1 h 15 min"; null when the event is not ahead today. */
export function untilWords(minutes: number | null, now: Date, lang: Lang | string = 'en'): string | null {
  if (minutes === null) return null;
  const left = minutes - (now.getHours() * 60 + now.getMinutes());
  if (left < 0) return null;
  const s = pick(DAY_STRINGS, lang);
  if (left < 60) return fmt(s.inMinutes, { n: left });
  const h = Math.floor(left / 60);
  const m = left % 60;
  return m === 0 ? fmt(s.inHours, { h }) : fmt(s.inHoursMinutes, { h, m });
}

/** The weather line "București · 9° · Mist": only the parts the hub sent. */
export function weatherLine(weather: any | null | undefined): string | null {
  if (!weather || typeof weather !== 'object') return null;
  const parts = [weather.city, weather.temp, weather.desc].map(asText).filter((p) => p !== '' && p !== '—');
  return parts.length ? parts.join(' · ') : null;
}
