/* HUD v2 · SHELL — Cinema (`m`): the full-bleed neural mesh, the voice orb and the briefing wall.

   Phase B (docs/design/hud-next/PHASE_B_PLAN.md §2.4) retired the rest of the HUD v2 shell that
   lived here: the top bar with its badges and clock, the ticker and "ALL NOMINAL", the mode rail,
   its drawer and tabs, the roster and context columns, the command palette with its language menu,
   and Ambient. The Ledger frame replaces them (frame/, nav/, home/, pages/Glance.tsx). Cinema is
   kept as it was: the owner asked for the mesh, the orb and the wall. */
import React, { useState, useEffect } from 'react';
import { Reactor } from './primitives';
import { isExecutingAgent, NeuralMesh } from './mesh';
import { VoiceOrb } from './orb';
import { BriefingWall } from './wall';
import { runningTasks } from './task-state';
import { bindings as shortcutBindings, chordOf, displayChord, matchAction } from './shortcuts';

/* Cinema stage switcher — mesh (who is working) · orb (voice state) · brain (the
   full briefing wall). Rendered inside the cinema frame, or floating over the wall. */
function StagePicker({ stage, setStage, floating = false, overrides = {} }: any) {
  const key = (id) => displayChord(chordOf(overrides, id));
  return (
    <div className={'cin-stage-pick' + (floating ? ' wl-pick' : '')}>
      <button className={stage === 'mesh' ? 'on' : ''} onClick={() => setStage('mesh')} title={`neural mesh (${key('cinema.mesh')})`}>mesh</button>
      <button className={stage === 'orb' ? 'on' : ''} onClick={() => setStage('orb')} title={`voice orb (${key('cinema.orb')})`}>orb</button>
      <button className={stage === 'brain' ? 'on' : ''} onClick={() => setStage('brain')} title={`briefing wall (${key('cinema.brain')})`}>brain</button>
    </div>
  );
}

/* HUD v3 · CINEMA MODE — full-bleed Neural Mesh framed as a shareable demo (handover §4).
   Port of v3-shell.jsx CinemaMesh; reuses the native NeuralMesh (cinema=true). Esc exits.
   Honesty contract: the prototype hardcoded "87% on-device / 0 cloud leaks" — we show only
   REAL figures (live agent count from the roster, %-local from /api/analytics/locality),
   never a fabricated split. */
export function CinemaMesh({ agents = [], tasks = [], llm, trust, sources, demo = false, localPct, voice, decisions, calendar, heartbeat, serverUp = false, clock, motion = 'lively', localPctSource = null, shortcutOverrides = null, onExit, t }: any) {
  const [tag, setTag] = useState(0);
  // Two stages share the cinema frame: the mesh (who is working) and the voice orb
  // (is Jarvis listening / speaking). Mesh stays the default so an existing demo
  // opens exactly as before; `o` flips to the orb, `n` back.
  const [stage, setStage] = useState('mesh');
  useEffect(() => { const iv = setInterval(() => setTag((x) => x + 1), 4200); return () => clearInterval(iv); }, []);
  useEffect(() => {
    // H209: the stage keys are registry actions (rebindable); Esc always exits.
    const list = shortcutBindings(shortcutOverrides || {});
    const h = (e) => {
      if (e.key === 'Escape') { onExit(); return; }
      const action = matchAction(e, list, 'cinema');
      if (action) { e.preventDefault(); setStage(action.id.slice('cinema.'.length)); }
    };
    window.addEventListener('keydown', h);
    return () => window.removeEventListener('keydown', h);
  }, [onExit, shortcutOverrides]);
  const trustEvidence = sources?.trust === true;
  const cloudReported = trustEvidence
    && (trust?.cloud_available === true || trust?.claude_available === true);
  const TAGS = demo
    ? [
      'DEMO · seeded sample data',
      'DEMO · illustrative constellation',
      'DEMO · simulated choreography',
    ]
    : [
      'Governed operator view',
      'Current evidence only',
      !trustEvidence
        ? 'Trust evidence unavailable'
        : cloudReported ? 'Cloud lane reported by trust status' : 'Trust status connected',
    ];
  const live = agents.filter(isExecutingAgent).length;
  const running = runningTasks(tasks).length;
  // The briefing wall owns the whole screen (its own chrome, cards and status rail), so
  // it replaces the cinema frame rather than sitting inside the mesh stage.
  if (stage === 'brain') {
    return (
      <>
        <BriefingWall
          agents={agents} tasks={tasks} decisions={decisions} calendar={calendar} heartbeat={heartbeat}
          llm={llm} trust={trust} sources={sources} localPct={localPct} voice={voice}
          serverUp={serverUp} demo={demo} clock={clock} motion={motion} localPctSource={localPctSource} onExit={onExit} />
        <StagePicker stage={stage} setStage={setStage} overrides={shortcutOverrides || {}} floating />
      </>
    );
  }
  return (
    <div className="cinema">
      <div className="cin-top">
        <div className="cin-mark"><Reactor /><span className="cin-word">NERVA</span></div>
        <div className="cin-tag" key={tag}>{TAGS[tag % TAGS.length]}</div>
      </div>
      <div className="cin-stage">
        <StagePicker stage={stage} setStage={setStage} overrides={shortcutOverrides || {}} />
        {stage === 'orb'
          ? <VoiceOrb status={(voice && voice.error) ? 'error' : (voice && voice.status) || 'off'} level={(voice && voice.level) || 0} motion={motion} />
          : <NeuralMesh agents={agents} tasks={tasks} llm={llm} trust={trust} sources={sources} demo={demo} cinema={true} motion={motion} onSelect={() => {}} t={t} />}
      </div>
      <div className="cin-bottom">
        <div className="cin-feed"><div className="cin-frow"><span className="cin-dot"></span>{live > 0 || running > 0 ? 'the Cabinet is working…' : 'no live activity'}</div></div>
        <div className="cin-stats">
          <span><b>{live}</b> agents live</span>
          {/* never a bare %: what was counted (where the hub sent the prompt) and on what basis */}
          {localPct != null && <span data-cinema="locality"><b>{localPct}%</b> sent to local runners · {localPctSource === 'measured' ? 'by route'
            : localPctSource === 'strict-local' ? 'strict-local setting, not measured' : localPctSource === 'seeded' ? 'demo sample' : 'basis unknown'}</span>}
        </div>
      </div>
      <button className="cin-exit" onClick={onExit}>Esc</button>
    </div>
  );
}
