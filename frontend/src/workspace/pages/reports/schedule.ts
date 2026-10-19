/* Schedules in words, and the choices the schedule builder offers.

   Weekdays follow the server's numbering (Python `date.weekday()`: 0 = Monday … 6 = Sunday).
   Times are "HH:MM" in the report's IANA time zone, Europe/Bucharest unless chosen otherwise;
   the server computes the next run (spec §9), the UI only describes the rule. */
import type { Report, ReportRun } from '../../api/types';
import type { I18n, MessageKey } from '../../i18n';

export const DEFAULT_TIMEZONE = 'Europe/Bucharest';
export const DEFAULT_TIME = '08:00';
export const TIME_PATTERN = /^([01]\d|2[0-3]):[0-5]\d$/;

const WEEKDAY_KEYS: MessageKey[] = ['weekday.0', 'weekday.1', 'weekday.2', 'weekday.3', 'weekday.4', 'weekday.5', 'weekday.6'];
export const WEEKDAYS = WEEKDAY_KEYS.map((_, index) => index);

const FALLBACK_ZONES = [
  'Europe/Bucharest', 'Europe/Chisinau', 'Europe/London', 'Europe/Berlin', 'Europe/Paris', 'Europe/Madrid', 'Europe/Rome',
  'Europe/Vienna', 'Europe/Warsaw', 'Europe/Budapest', 'Europe/Sofia', 'Europe/Athens', 'Europe/Istanbul', 'UTC',
  'America/New_York', 'America/Chicago', 'America/Los_Angeles', 'Asia/Dubai', 'Asia/Singapore', 'Asia/Tokyo',
];

/** The day as it reads inside a sentence ("luni", "Monday"). */
export function weekdayName(i18n: I18n, weekday: number): string {
  return i18n.t(WEEKDAY_KEYS[weekday] ?? WEEKDAY_KEYS[0]);
}

/** The day as a list option ("Luni"). */
export function weekdayOption(i18n: I18n, weekday: number): string {
  const name = weekdayName(i18n, weekday);
  return name.charAt(0).toLocaleUpperCase(i18n.locale) + name.slice(1);
}

type ScheduleFields = Pick<Report, 'schedule_kind' | 'schedule_time' | 'schedule_weekday'>;

export function scheduleSummary(i18n: I18n, report: ScheduleFields): string {
  const time = report.schedule_time || DEFAULT_TIME;
  if (report.schedule_kind === 'daily') return i18n.t('schedule.summary.daily', { time });
  if (report.schedule_kind === 'weekly') return i18n.t('schedule.summary.weekly', { weekday: weekdayName(i18n, report.schedule_weekday ?? 0), time });
  return i18n.t('schedule.manual');
}

/** Every zone the browser knows (falling back to a short list), always including *current*. */
export function timezoneOptions(current: string): string[] {
  const supported = (Intl as unknown as { supportedValuesOf?: (key: string) => string[] }).supportedValuesOf;
  let zones: string[] = FALLBACK_ZONES;
  try {
    if (typeof supported === 'function') zones = supported('timeZone');
  } catch {
    zones = FALLBACK_ZONES;
  }
  const all = new Set([DEFAULT_TIMEZONE, ...zones]);
  if (current) all.add(current);
  return [...all].sort((a, b) => (a === DEFAULT_TIMEZONE ? -1 : b === DEFAULT_TIMEZONE ? 1 : a.localeCompare(b)));
}

export function runDurationMs(run: Pick<ReportRun, 'started_at' | 'finished_at'>): number | null {
  if (!run.started_at || !run.finished_at) return null;
  return Math.max(0, (run.finished_at - run.started_at) * 1000);
}

export function isRunActive(run: Pick<ReportRun, 'status'> | null | undefined): boolean {
  return run?.status === 'queued' || run?.status === 'running';
}

/** The report is ready and its approved email is still on the way: the server stores the run
    `succeeded` first and only then talks to the mail server, which can take seconds (NWS-20). */
export function isDeliveryPending(run: Pick<ReportRun, 'status' | 'delivery_state'> | null | undefined): boolean {
  return run?.status === 'succeeded' && run.delivery_state === 'pending';
}

/** The reader's own IANA zone ('' when the browser does not say). */
export function browserTimeZone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || '';
  } catch {
    return '';
  }
}
