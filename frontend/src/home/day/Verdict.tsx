/* The verdict (PHASE_B_PLAN.md §5.2): its state word, one honest sentence, the causes in the
   probes' own words, the remedy (a link to the docket entry that restarts what is down), and
   what did not answer. It draws what the pure verdict() decided and decides nothing itself. */
import React, { useId } from 'react';
import { docketHref, openDocketEntry } from '../../docket/links';
import { Mark } from '../../frame/kit';
import { clockTime } from '../../frame/kit/strings';
import { fmt, pick, type Lang } from '../../frame/strings';
import { routeHref } from '../../hud-routing';
import { VERDICT_STRINGS } from '../../signals/verdict';
import type { Verdict as VerdictModel, VerdictState } from '../../signals/types';
import { DAY_STRINGS } from './strings';
import './day.css';

export interface VerdictProps {
  verdict: VerdictModel;
  lang: Lang;
  /** In-app navigation for the verdict's own link (a logical path from nav/routes pathOf). */
  navigate: (path: string) => void;
}

const STATE_KEY: Readonly<Record<VerdictState, 'stateDemo' | 'stateChecking' | 'stateOffline' | 'stateHalted' | 'stateDegraded' | 'stateProblem' | 'stateNormal' | 'stateUnknown'>> = {
  demo: 'stateDemo', checking: 'stateChecking', offline: 'stateOffline', halted: 'stateHalted',
  degraded: 'stateDegraded', problem: 'stateProblem', normal: 'stateNormal', unknown: 'stateUnknown',
};

/** The name a cause is drawn under: `service.lmstudio` → `lmstudio`. */
export const causeName = (key: string): string => key.replace(/^service\./, '');

export function Verdict({ verdict, lang, navigate }: VerdictProps) {
  const s = pick(DAY_STRINGS, lang);
  const words = pick(VERDICT_STRINGS, lang);
  const headingId = `n-verdict-${useId().replace(/[^a-zA-Z0-9_-]/g, '')}`;
  const stateWord = words[STATE_KEY[verdict.state]];
  const since = verdict.since !== null ? clockTime(verdict.since) : null;
  const checked = verdict.checkedAt !== null ? fmt(s.checkedAt, { time: clockTime(verdict.checkedAt) }) : null;
  const link = verdict.link ?? null;
  const remedy = verdict.remedy ?? null;
  return (
    <section className="n-verdict" aria-labelledby={headingId} data-verdict-state={verdict.state} data-verdict-rule={verdict.rule}>
      <p className="n-verdict__state">
        <Mark kind={verdict.mark} />
        <span>
          <b>{stateWord}</b>{since ? ` ${fmt(s.sinceTime, { time: since })}` : ''}
        </span>
        {checked && <span className="n-verdict__asof">{checked}</span>}
      </p>
      <h3 className="n-verdict__line" id={headingId}>{verdict.headline}</h3>
      {verdict.causes.length > 0 && (
        <ul className="n-causes" aria-label={since ? fmt(s.causesLabelSince, { time: since }) : s.causesLabel}>
          {verdict.causes.map((cause) => (
            <li key={`${cause.source}:${cause.key}`} data-cause={cause.key}>
              <Mark kind={cause.mark} size="sm" />
              <code className="n-causes__key">{causeName(cause.key)}</code>
              <span className="n-causes__text">
                {cause.detail}
                {cause.consequence && <span className="n-causes__consequence">{cause.consequence}</span>}
              </span>
            </li>
          ))}
        </ul>
      )}
      {remedy && (
        <p className="n-verdict__remedy">
          <Mark kind="seal-open" size="sm" />
          <span>
            {s.remedyLead}{' '}
            <a className="n-link" href={remedy.href || docketHref(remedy.taskId)}
              onClick={(event) => { event.preventDefault(); openDocketEntry(remedy.taskId); }}>{remedy.text}</a>.
          </span>
        </p>
      )}
      {link && (
        <p className="n-verdict__remedy">
          <span>
            <a className="n-link" href={routeHref(link.href)} onClick={(event) => { event.preventDefault(); navigate(link.href); }}>{link.text}</a>
          </span>
        </p>
      )}
      {verdict.missing && verdict.missing.length > 0 && verdict.rule !== 13 && (
        <p className="n-verdict__missing">{fmt(s.missingNote, { list: verdict.missing.join(', ') })}</p>
      )}
    </section>
  );
}
