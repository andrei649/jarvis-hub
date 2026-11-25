/* The notices (PHASE_B_PLAN.md §4.4): one stacked region under the running head, ruled lines
   with a mark and a sentence, no striped colour bars. In order:

     safe mode            cannot be dismissed (the hub behaving differently from its settings is
                          the thing to notice)
     power                on battery, background jobs deferred, woke from sleep, keep-awake
     memory and disk      the worst condition the owner has not dismissed, with Dismiss
     demo                 "Demo sample on screen" · Exit demo
     first run            no model loaded yet · Show a demo sample · Dismiss
     appearance sync      App's own node, with its Retry
     the route            "Page not found. Returned to Today.": it names the page the router
                          fell back to when it raised the notice (App records it), as that page's
                          heading names it, never the page on screen now
     a stop that did not halt   worded from the state read again (StopButton, useKillSwitch)
     failed actions       every failed mutation the API client recorded (api/client.ts sink), on
                          every page, not only in the Console; a stop press's own POST is left
                          to the stop's line, so one event never raises two alerts

   Each line says what it is in words; the mark only repeats it. Alarms are role="alert", the
   rest role="status". */
import React, { useEffect, useState } from 'react';
import { actionFailures, clearActionFailures, onActionFailure, type ActionFailure } from '../api/client';
import { pageForRoute, type RoutePage } from '../nav/routes';
import type { PowerState } from '../power-chip';
import type { PressureState } from '../pressure-banner';
import type { SafeModeState } from '../safe-mode-banner';
import type { HubSnapshot } from '../signals/types';
import { pageHeading } from './AreaPage';
import { Mark, clockTime, type MarkKind } from './kit';
import { NOTICE_STRINGS } from './frame-strings';
import { appUrl } from '../base-path';

/** The sample's own address, /v2/?demo=1 under the hub's base path (the 2026-07-14 honesty spec:
 *  the demo is a shareable address, never a hidden mode). */
function DemoAddress({ words }: { words: string }) {
  const [before, after] = words.split('{link}');
  return <span className="n-notice__why">{before}<code className="n-notice__addr">{appUrl('/v2/')}?demo=1</code>{after}</span>;
}
import { fmt, pick, plural, type Lang } from './strings';
import type { FirstRunNotice } from './types';
import { isStopPressFailure } from './useKillSwitch';
import './frame.css';

/** Where the router sends a path it does not know, in the main window (hud-routing.ts). */
const HOME_PAGE = pageForRoute({ mode: 'cockpit', panel: null });

function Line({ kind, mark, alarm = false, lang, children, actions }: {
  kind: string; mark: MarkKind; alarm?: boolean; lang: Lang; children: React.ReactNode; actions?: React.ReactNode;
}) {
  return (
    <div className={['n-notice', alarm ? 'n-notice--alarm' : ''].filter(Boolean).join(' ')} role={alarm ? 'alert' : 'status'} data-notice={kind}>
      <Mark kind={mark} size="sm" lang={lang} />
      <div className="n-notice__text">{children}</div>
      {actions && <span className="n-notice__acts">{actions}</span>}
    </div>
  );
}

function Act({ onClick, children }: { onClick: () => void; children: React.ReactNode }) {
  return <button type="button" className="n-btn n-btn--sm n-btn--quiet" onClick={onClick}>{children}</button>;
}

/** The safe-mode sentence: what was left out, in the hub's order. */
export function safeModeText(state: SafeModeState, lang: Lang): string {
  const s = pick(NOTICE_STRINGS, lang) as unknown as Record<string, string>;
  const left = state.skipped.map((key) => s[`sm_${key}`]).filter((word): word is string => typeof word === 'string');
  const what = left.length ? fmt(s.safeLeftOut, { list: left.join(s.listJoin) }) : s.safeOnlyShipped;
  return fmt(s.safeMode, { what });
}

/** The power notice, piece by piece; empty when there is nothing to say. */
export function powerPieces(state: PowerState, lang: Lang): string[] {
  const s = pick(NOTICE_STRINGS, lang);
  const out: string[] = [];
  if (state.onBattery) {
    out.push(state.percent === null ? s.onBattery : fmt(s.onBatteryPct, { pct: state.percent }));
    if (state.deferred) out.push(s.deferred);
  }
  if (state.resumedAt !== null) out.push(fmt(s.resumed, { time: clockTime(state.resumedAt * 1000) }));
  const k = state.keepAwake;
  if (k.enabled) {
    if (k.refused) out.push(fmt(s.keepAwakeRefused, { reason: k.refused }));
    else if (k.error) out.push(fmt(s.keepAwakeError, { reason: k.error }));
    else out.push(k.active ? s.keepAwakeActive : s.keepAwakeReady);
  }
  return out;
}

/** The memory-and-disk sentence for the worst condition. */
export function pressureSentence(worst: NonNullable<PressureState['worst']>, lang: Lang): string {
  const s = pick(NOTICE_STRINGS, lang);
  const first = worst.paths[0];
  const where = first ? fmt(s.wherePath, { path: first.path, pct: first.percent })
    : worst.percent !== null ? fmt(s.wherePct, { pct: worst.percent }) : s.whereUnknown;
  switch (worst.condition) {
    case 'disk_critical': return fmt(s.diskCritical, { where });
    case 'memory_critical': return worst.percent === null ? s.memoryCriticalUnknown : fmt(s.memoryCritical, { pct: worst.percent });
    case 'oom_restart_suspected': return s.oomRestart;
    case 'disk_elevated': return fmt(s.diskElevated, { where });
    default: return worst.percent === null ? s.memoryElevatedUnknown : fmt(s.memoryElevated, { pct: worst.percent });
  }
}

/** The failures this line reports: a stop press's own POST is the stop's line. */
const shownFailures = (all: ActionFailure[]) => all.filter((f) => !isStopPressFailure(f));

function FailureNotice({ lang }: { lang: Lang }) {
  const s = pick(NOTICE_STRINGS, lang);
  const [fails, setFails] = useState<ActionFailure[]>(() => shownFailures(actionFailures()));
  useEffect(() => onActionFailure((all) => setFails(shownFailures(all))), []);
  if (!fails.length) return null;
  return (
    <Line kind="failures" mark="problem" alarm lang={lang}
      actions={<Act onClick={() => { clearActionFailures(); setFails([]); }}>{s.dismiss}</Act>}>
      <p className="n-notice__lead">{plural(lang, s.failures, fails.length)}</p>
      <ul className="n-notice__list">
        {fails.slice(0, 5).map((f, i) => (
          <li key={`${f.at}-${i}`}>
            <code>{fmt(s.failureLine, { method: f.method, path: f.path, status: f.status })}</code>
            {f.status === 403 && <span className="n-notice__why">{s.failure403}</span>}
            {f.status === 401 && <span className="n-notice__why">{s.failure401}</span>}
          </li>
        ))}
      </ul>
    </Line>
  );
}

export interface NoticesProps {
  lang: Lang;
  hub: HubSnapshot;
  /** The page on screen. No line is worded from it: the route line names `routeNoticePage`. */
  page?: RoutePage;
  demo: boolean;
  onExitDemo?: () => void;
  power?: PowerState;
  pressure?: PressureState;
  onDismissPressure?: (condition: string, bootId: string) => void;
  /** useHudRoute's notice: drawn when non-empty; its own English text is not shown. */
  routeNotice?: string;
  /** The page the router fell back to when it raised the notice (default: Today, the main
   *  window's fallback). */
  routeNoticePage?: RoutePage | null;
  onDismissRouteNotice?: () => void;
  appearanceNotice?: React.ReactNode;
  firstRun?: FirstRunNotice;
  stopRefusal?: string | null;
  onDismissStopRefusal?: () => void;
  /** Failed actions (default on). */
  showFailures?: boolean;
}

export function Notices(props: NoticesProps) {
  const { lang, hub, demo, onExitDemo, power, pressure, onDismissPressure, routeNotice, routeNoticePage, onDismissRouteNotice,
    appearanceNotice, firstRun, stopRefusal, onDismissStopRefusal, showFailures = true } = props;
  const s = pick(NOTICE_STRINGS, lang);
  const powerSaid = power ? powerPieces(power, lang) : [];
  const powerWarn = !!power && (power.deferred || !!power.keepAwake.refused || !!power.keepAwake.error);
  const worst = pressure?.worst && pressure.bootId ? pressure.worst : null;
  const alarm = !!worst && worst.condition !== 'disk_elevated' && worst.condition !== 'memory_elevated';
  const firstRunShown = !!firstRun && !firstRun.dismissed && !demo && hub.serverUp && !hub.llm.model && hub.llm.state !== 'unknown';
  return (
    <div className="n-notices" data-frame="notices">
      {hub.safeMode.enabled && (
        <Line kind="safe-mode" mark="attn" lang={lang}><p>{safeModeText(hub.safeMode, lang)}</p></Line>
      )}
      {powerSaid.length > 0 && (
        <Line kind="power" mark={powerWarn ? 'attn' : 'here'} lang={lang}>
          <p className="n-notice__pieces">{powerSaid.map((piece) => <span key={piece}>{piece}</span>)}</p>
        </Line>
      )}
      {worst && (
        <Line kind="pressure" mark={alarm ? 'problem' : 'attn'} alarm={alarm} lang={lang}
          actions={onDismissPressure && <Act onClick={() => onDismissPressure(worst.condition, pressure!.bootId as string)}>{s.dismiss}</Act>}>
          <p>{pressureSentence(worst, lang)}</p>
        </Line>
      )}
      {demo && (
        <Line kind="demo" mark="attn" lang={lang} actions={onExitDemo && <Act onClick={onExitDemo}>{s.exitDemo}</Act>}>
          <p>{s.demo}{' '}<DemoAddress words={s.demoShare} /></p>
        </Line>
      )}
      {firstRunShown && (
        <Line kind="first-run" mark="attn" lang={lang} actions={<>
          <Act onClick={firstRun!.onDemo}>{s.showDemo}</Act>
          <Act onClick={firstRun!.onDismiss}>{s.dismiss}</Act>
        </>}>
          <p>{s.firstRun}</p>
        </Line>
      )}
      {appearanceNotice ? <div className="n-notice" data-notice="appearance">{appearanceNotice}</div> : null}
      {routeNotice ? (
        <Line kind="route" mark="attn" alarm lang={lang}
          actions={onDismissRouteNotice && <Act onClick={onDismissRouteNotice}>{s.dismiss}</Act>}>
          <p>{fmt(s.routeNotFound, { page: pageHeading(routeNoticePage ?? HOME_PAGE, lang) })}</p>
        </Line>
      ) : null}
      {stopRefusal ? (
        <Line kind="stop" mark="problem" alarm lang={lang}
          actions={onDismissStopRefusal && <Act onClick={onDismissStopRefusal}>{s.dismiss}</Act>}>
          <p>{stopRefusal}</p>
        </Line>
      ) : null}
      {showFailures && <FailureNotice lang={lang} />}
    </div>
  );
}
