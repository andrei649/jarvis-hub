/* Small text helpers for the docket's components: a whole translated sentence with an element in
   one of its {placeholders} (a command in mono, a link), times in the owner's language, and an
   agent's name and role from the roster. */
import React from 'react';
import { fmt, type Lang } from '../frame/strings';
import { clockTime } from '../frame/kit/strings';
import { V2 } from '../data';

/** A template whose {placeholders} are filled with elements (and strings): the sentence stays
 *  whole, the element sits where the translation puts it. Unknown placeholders stay visible. */
export function fillNodes(template: string, values: { readonly [name: string]: React.ReactNode }): React.ReactNode {
  const parts: React.ReactNode[] = [];
  const re = /\{(\w+)\}/g;
  let last = 0;
  let m: RegExpExecArray | null;
  let i = 0;
  while ((m = re.exec(template))) {
    if (m.index > last) parts.push(template.slice(last, m.index));
    const name = m[1];
    parts.push(Object.prototype.hasOwnProperty.call(values, name)
      ? <React.Fragment key={`v${i++}`}>{values[name]}</React.Fragment> : m[0]);
    last = m.index + m[0].length;
  }
  if (last < template.length) parts.push(template.slice(last));
  return <>{parts}</>;
}

const sameDay = (a: Date, b: Date) => a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();

/** A time on the docket: "10:50" today, "2 Jul" (with the time when asked) on another day of this
 *  year, "2 Jul 2025" in another year. */
export function formatWhen(at: number, lang: Lang | string, opts: { now?: number; withTime?: boolean } = {}): string {
  const now = new Date(opts.now ?? Date.now());
  const d = new Date(at);
  if (sameDay(d, now)) return clockTime(d);
  const locale = lang === 'ro' ? 'ro-RO' : 'en-GB';
  const day = new Intl.DateTimeFormat(locale, d.getFullYear() === now.getFullYear()
    ? { day: 'numeric', month: 'short' } : { day: 'numeric', month: 'short', year: 'numeric' }).format(d);
  return opts.withTime ? `${day}, ${clockTime(d)}` : day;
}

/** Whole days between two instants (0 when under a day). */
export function wholeDays(from: number, to: number = Date.now()): number {
  return Math.max(0, Math.floor((to - from) / 86_400_000));
}

type RosterAgent = { id: string; name: string; role?: string };
const ROSTER: ReadonlyMap<string, RosterAgent> = new Map((V2.AGENTS as RosterAgent[]).map((a) => [a.id, a]));

/** An agent as the roster names it ("Steve", "CTO / Builds"); an id the roster does not know is
 *  shown as sent, with no role. */
export function agentOf(id: string | null): { name: string; role: string | null } | null {
  if (!id) return null;
  const known = ROSTER.get(id.toLowerCase());
  return known ? { name: known.name, role: known.role ?? null } : { name: id, role: null };
}

/** fmt, re-exported so components import their text helpers from one place. */
export { fmt };
