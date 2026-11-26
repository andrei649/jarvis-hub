/* The Ledger frame (PHASE_B_PLAN.md §2.1, §4): what every page but Glance sits in.

     SkipLink ("Skip to the conversation" on Home, "Skip to the page" elsewhere)
     Masthead            header[data-frame="masthead"]
     RunningHead         div[data-frame="runhead"]
     Notices             div[data-frame="notices"]
     main[data-frame="page"] → RouteBoundary → the page (Home, an AreaPage, …)
     RunningFoot         footer[data-frame="runfoot"]

   App owns the state (FrameProps, frame/types.ts); the frame reads the hub only through the
   snapshot. The stop's refusals travel from the masthead to the notices here. The page body is
   remounted per route (RouteBoundary), so a page's form state never leaks to the next one. */
import React, { useState } from 'react';
import { DesktopControls } from '../desktop';
import { RouteBoundary } from '../route-boundary';
import { chordOf, displayChord } from '../shortcuts';
import type { TabTurn } from '../signals/types';
import { useFrameAttention } from './attention';
import { PAGE_STRINGS } from './frame-strings';
import { FRAME_PAGE_ID, HOME_TALK_ID } from './ids';
import { Masthead } from './Masthead';
import { Notices } from './Notices';
import { RunningFoot } from './RunningFoot';
import { RunningHead } from './RunningHead';
import { pick } from './strings';
import type { FrameProps } from './types';
import './frame.css';

export { FRAME_PAGE_ID, HOME_TALK_ID };

const NO_TURNS: readonly TabTurn[] = Object.freeze([]);
/** The desktop app's "Float chat" (nothing on the web); one element, so the memoised foot keeps it. */
const DESKTOP_CONTROLS = <DesktopControls />;

function skipTo(id: string) {
  const target = document.getElementById(id);
  if (!target) return;
  if (!target.hasAttribute('tabindex')) target.setAttribute('tabindex', '-1');
  target.focus();
}

export function Frame(props: FrameProps) {
  const {
    route, page, hub, lang, setLang, scheme, schemePreference, setScheme, theme, navigation, onFind, onGlance, children,
    demo = false, onExitDemo, turns = NO_TURNS, shortcutOverrides, voiceStatus, power, pressure, onDismissPressure,
    routeNotice, routeNoticePage, onDismissRouteNotice, appearanceNotice, firstRun,
  } = props;
  const s = pick(PAGE_STRINGS, lang);
  const attention = useFrameAttention({ demo, hub });
  const [stopRefusal, setStopRefusal] = useState<string | null>(null);
  const findChord = displayChord(chordOf(shortcutOverrides || {}, 'session.palette'));
  const home = page.kind === 'home';
  let surfaceLoad: 'pending' | 'settled' | undefined;
  if (home) surfaceLoad = hub.checkedAt === null ? 'pending' : 'settled';
  if (route.mode === 'admin') surfaceLoad = props.adminSettled ? 'settled' : 'pending';
  const skipTarget = home ? HOME_TALK_ID : FRAME_PAGE_ID;
  return (
    <div className="n-frame" data-page-kind={page.kind}>
      <a className="n-frame__skip" href={`#${skipTarget}`} onClick={(event) => { event.preventDefault(); skipTo(skipTarget); }}>
        {home ? s.skipTalk : s.skipPage}
      </a>
      <Masthead page={page} lang={lang} setLang={setLang} scheme={scheme} schemePreference={schemePreference} setScheme={setScheme}
        theme={theme} attention={attention} findChord={findChord} onFind={() => onFind()} onGlance={onGlance}
        navigate={(path) => navigation.navigate(path)} demo={demo} onStopResult={setStopRefusal} />
      <RunningHead hub={hub} lang={lang} demo={demo} voiceStatus={voiceStatus ?? null} navigate={navigation.navigate} />
      <Notices lang={lang} hub={hub} page={page} demo={demo} onExitDemo={onExitDemo} power={power} pressure={pressure}
        onDismissPressure={onDismissPressure} routeNotice={routeNotice} routeNoticePage={routeNoticePage} onDismissRouteNotice={onDismissRouteNotice}
        appearanceNotice={appearanceNotice} firstRun={firstRun} stopRefusal={stopRefusal}
        onDismissStopRefusal={() => setStopRefusal(null)} />
      <main className="n-frame__page" data-frame="page" data-surface-load={surfaceLoad} id={FRAME_PAGE_ID} tabIndex={-1}>
        <RouteBoundary routeKey={`${route.path}:${demo}`}>{children}</RouteBoundary>
      </main>
      <RunningFoot hub={hub} lang={lang} demo={demo} turns={turns} shortcutOverrides={shortcutOverrides} spread={home}
        aside={DESKTOP_CONTROLS} />
    </div>
  );
}
