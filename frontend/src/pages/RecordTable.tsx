/* RecordTable: the audit trail as a ledger (secondary.html "chain"; PHASE_B_PLAN.md §5.5, §6).

   Rows come from GET /api/security/audit/intent. Only fields the hub sends are drawn: the time,
   the entry's own words (`why`, and the `action` as an identifier), who acted (`actor`), a risk
   column only when entries carry a tier, and the seal (the entry hash). The seal mark says
   "sealed" only when the chain was verified in the same answer; a chain that failed shows a
   problem mark, and an answer without a verdict shows the hash alone. Text is plain: the hub's
   words are never parsed as markup. */
import React from 'react';
import { Mark, TierGlyph, clockTime } from '../frame/kit';
import { defineStrings, fmt, pick, type Lang } from '../frame/strings';
import type { RecordEntry } from './sources';
import { stamp } from './common';
import { IDENT } from '../theme/type';

export const RECORD_TABLE_STRINGS = defineStrings({
  en: {
    label: 'Recent entries in the audit chain',
    time: 'Time',
    entry: 'Entry',
    risk: 'Risk',
    seal: 'Seal',
    by: 'by {who}',
    sealed: 'Sealed',
    notVerified: 'Not verified',
    broken: 'Seal broken',
    noWords: 'No description recorded',
  },
  ro: {
    label: 'Intrările recente din lanțul de audit',
    time: 'Ora',
    entry: 'Intrare',
    risk: 'Risc',
    seal: 'Sigiliu',
    by: 'de {who}',
    sealed: 'Sigilat',
    notVerified: 'Neverificat',
    broken: 'Sigiliu rupt',
    noWords: 'Nicio descriere înregistrată',
  },
});

/** The first and last four characters of a hash: "9f2c…a41b". */
export function shortHash(hash: string | null): string | null {
  if (!hash) return null;
  return hash.length <= 9 ? hash : `${hash.slice(0, 4)}…${hash.slice(-4)}`;
}

export interface RecordTableProps {
  entries: readonly RecordEntry[];
  lang: Lang | string;
  /** The chain's own verdict from the same answer; null when it sent none. */
  chainOk: boolean | null;
  /** How many rows to draw (newest first). */
  limit?: number;
  now?: number;
}

export function RecordTable({ entries, lang, chainOk, limit = 8, now = Date.now() }: RecordTableProps) {
  const s = pick(RECORD_TABLE_STRINGS, lang);
  const rows = entries.slice(0, limit);
  const showRisk = rows.some((r) => r.tier !== null);
  const cols = showRisk ? 'n-record n-record--risk' : 'n-record';
  return (
    <div className={cols} role="table" aria-label={s.label} data-record-table="">
      <div className="n-record__cols" role="row">
        <span role="columnheader">{s.time}</span>
        <span role="columnheader">{s.entry}</span>
        {showRisk && <span role="columnheader">{s.risk}</span>}
        <span role="columnheader">{s.seal}</span>
      </div>
      <div className="n-record__rows" role="rowgroup">
        {rows.map((row) => {
          const hash = shortHash(row.hash);
          return (
            <div className="n-record__row" role="row" key={row.seq} data-record-seq={row.seq}>
              {row.at !== null
                ? <time role="cell" dateTime={new Date(row.at).toISOString()} title={new Date(row.at).toLocaleString(lang === 'ro' ? 'ro-RO' : 'en-GB')}>{
                  new Date(row.at).toDateString() === new Date(now).toDateString() ? clockTime(row.at) : stamp(row.at, now, lang)}</time>
                : <span role="cell">—</span>}
              <div role="cell">
                <p className="n-record__what">{row.why ?? row.action ?? s.noWords}</p>
                {(row.actor || (row.why && row.action)) && (
                  <p className="n-record__sub">
                    {row.actor && <b>{fmt(s.by, { who: row.actor })}</b>}
                    {row.why && row.action && <code style={IDENT}>{row.action}</code>}
                  </p>
                )}
              </div>
              {showRisk && <span role="cell" className="n-record__risk">{row.tier !== null ? <TierGlyph tier={row.tier} lang={lang} word /> : null}</span>}
              <span role="cell" className="n-record__seal">
                {chainOk === true && <Mark kind="chain" size="md" label lang={lang} />}
                {chainOk === false && <><Mark kind="problem" size="md" lang={lang} /><span className="n-record__flag">{s.broken}</span></>}
                {hash && <code style={IDENT}>{hash}</code>}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
