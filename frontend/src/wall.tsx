/* HUD v3 · BRIEFING WALL — the wall-screen briefing surface.

   Reference: the owner-supplied video (2026-08-06). Its layout is a dark room-facing
   board: wordmark + live pill + clock across the top, stat cards down both sides, a
   subsystem status rail on the right edge, the spoken line along the bottom, and the
   neural firing field filling the middle.

   The reference's cards show a marketing agency's KPIs (leads found, ad spend, MRR).
   Nerva does not have those numbers and will not invent them, so the same slots carry
   the figures this hub can actually prove: who is executing, what is queued, how much
   ran on-device, what the voice stack can do. Every cell that has no evidence renders
   `—` with the reason in its title attribute — never a plausible-looking number.

   Layout only; the field itself is burst.tsx. Rendered as the `brain` stage of cinema
   mode (shell.tsx). */
import React, { useState, useEffect, useCallback, useRef } from 'react';
import { NeuralBurst, burstEnergy } from './burst';
import { isExecutingAgent } from './mesh';
import { runningTasks } from './task-state';

const two = (n: number) => String(n).padStart(2, '0');

export function wallClock(d: Date) {
  return `${two(d.getHours())}:${two(d.getMinutes())}:${two(d.getSeconds())}`;
}

/* The one-word state in the top-right corner. Voice wins when the loop is live,
   because that is what the room is reacting to; otherwise the cabinet's own work. */
export function wallState({ voice = null, agents = [], tasks = [], serverUp = false }: any = {}) {
  const status = String((voice && voice.status) || 'off');
  if (voice && voice.error) return { word: 'voice error', tone: 'bad' };
  if (status === 'listening') return { word: 'listening', tone: 'live' };
  if (status === 'transcribing') return { word: 'thinking', tone: 'work' };
  if (status === 'speaking') return { word: 'speaking', tone: 'live' };
  const firing = (Array.isArray(agents) ? agents : []).filter(isExecutingAgent).length;
  const running = runningTasks(Array.isArray(tasks) ? tasks : []).length;
  if (firing || running) return { word: 'working', tone: 'work' };
  if (!serverUp) return { word: 'offline', tone: 'bad' };
  return { word: 'standing by', tone: 'idle' };
}

/* A metric with provenance. `value === null` means "not measured" and prints as `—`
   with `why` explaining the absence — the wall never fills a gap with a guess.

   `prov` is per-CELL on purpose. A connected DEMO session replaces seeded values with real
   ones as each backend source answers (see `loadJarvisData`), so one card can legitimately
   hold live and seeded figures at the same time and no single card-level label can describe
   them all truthfully. A seeded value carries its own tag; the card stamp is derived from
   the cells it actually holds. */
function Cell({ label, value, why, sub, prov }: any) {
  const missing = value === null || value === undefined || value === '';
  return (
    <div className="wl-row" data-prov={missing ? 'none' : (prov || 'unknown')}>
      <span className="wl-k">{label}</span>
      <span className={'wl-v' + (missing ? ' wl-miss' : '')} title={missing ? (why || 'no evidence available') : undefined}>
        {missing ? '—' : value}
        {!missing && prov === 'seeded' && <span className="wl-prov" title="seeded demo value, not a live reading">seeded</span>}
        {!missing && prov === 'derived' && <span className="wl-prov wl-prov-derived" title="derived from a governance flag, not measured">derived</span>}
      </span>
      {sub && <span className="wl-sub">{sub}</span>}
    </div>
  );
}

/* The card's stamp is a summary of the provenance of the values it is actually showing —
   never a blanket assumption from `demo`. Cells with no value contribute nothing. */
export function cardStamp(provs: any[], liveLabel: string) {
  const shown = (Array.isArray(provs) ? provs : []).filter(Boolean);
  // A card showing nothing has no provenance to summarize. Returning the live label
  // there let an all-`—` card announce evidence it does not have; absence of
  // contradiction is not proof of measurement.
  if (!shown.length) return 'no evidence';
  const seeded = shown.some((p) => p === 'seeded');
  const derived = shown.some((p) => p === 'derived');
  const live = shown.some((p) => p === 'live');
  if (seeded && (live || derived)) return 'mixed · live + seeded';
  if (seeded) return 'demo · seeded';
  if (derived && live) return 'mixed · live + derived';
  if (derived) return 'derived';
  if (shown.every((p) => p === 'live')) return liveLabel;
  return 'unverified';
}

/* The stamp is the card's provenance label, and it must be true AT THE POINT the figures
   are read: a page-level DEMO badge does not stop `CABINET · NOW · live` or
   `THIS SESSION · measured` from claiming seeded numbers are live/measured. In demo every
   card stamps `demo · seeded` instead. (App supplies a demo `localPct` of 87, which would
   otherwise have sat under a "measured" stamp.) */
function Card({ title, stamp, children }: any) {
  return (
    <div className="wl-card">
      <div className="wl-card-h"><span>{title}</span><span className="wl-stamp">{stamp}</span></div>
      {children}
    </div>
  );
}

function Dot({ tone }: any) { return <i className={'wl-dot wl-' + (tone || 'off')} />; }

/* HOLD TO TALK — the reference's round mic control, wired to the real `useVoice()`
   loop: press starts it, release stops it. That is genuine push-to-talk regardless of
   the configured mode, because `stop()` cancels an in-flight turn. It refuses honestly
   when the mic is muted or the browser can't do voice — it never pretends to listen. */
function PushToTalk({ voice, micState, trustEvidence }: any) {
  const [held, setHeld] = useState(false);
  const usable = !!voice && typeof voice.start === 'function' && typeof voice.stop === 'function' && voice.supported !== false;
  // Fails closed on a microphone, over the whole lifecycle:
  //  - `sources.trust` must prove the status is CURRENT (a retained object is not proof);
  //  - the mic state must be an EXACT affirmative 'on' — missing, unknown or malformed
  //    values authorize nothing;
  //  - capture stops the moment either stops holding, and on unmount/stage switch.
  const permitted = trustEvidence && micState === 'on';
  const blocked = !permitted || !usable;
  // `useVoice()` returns a FRESH wrapper object every render, and the parent rerenders on
  // every clock tick. Depending on that identity made the unmount cleanup fire on ordinary
  // rerenders and stop a perfectly valid capture ~once a second. Hold the callbacks in refs
  // so release/cleanup identity is stable and only real events stop the mic.
  const stopRef = useRef(voice && voice.stop);
  stopRef.current = voice && voice.stop;
  const release = useCallback(() => {
    setHeld((wasHeld) => { if (wasHeld && stopRef.current) stopRef.current(); return false; });
  }, []);
  // release outside the button still ends the turn
  useEffect(() => {
    if (!held) return undefined;
    window.addEventListener('pointerup', release);
    window.addEventListener('pointercancel', release);
    return () => { window.removeEventListener('pointerup', release); window.removeEventListener('pointercancel', release); };
  }, [held, release]);
  // permission lost mid-capture (mute, trust evidence expiry) → cut the mic immediately
  useEffect(() => { if (held && blocked) release(); }, [held, blocked, release]);
  // unmount (Esc out of the wall, stage switch) must never leave the loop running.
  // Empty deps + refs: this runs on a REAL unmount, never on a rerender.
  const heldRef = useRef(held);
  heldRef.current = held;
  useEffect(() => () => { if (heldRef.current && stopRef.current) stopRef.current(); }, []);
  const press = () => { if (blocked) return; setHeld(true); voice.start(); };
  // keyboard hold/release — the control must be operable without a pointer
  const keyDown = (e: any) => {
    if (e.key !== ' ' && e.key !== 'Enter') return;
    e.preventDefault();
    if (e.repeat || held) return;
    press();
  };
  const keyUp = (e: any) => { if (e.key === ' ' || e.key === 'Enter') release(); };
  const label = !trustEvidence ? 'trust status unavailable'
    : micState === 'off' ? 'mic muted'
    : micState !== 'on' ? 'mic state unknown'
    : !usable ? 'voice unavailable'
    : held ? 'listening…'
    : 'hold to talk';
  const lv = held ? Math.min(1, (Number(voice && voice.level) || 0) / 0.25) : 0;
  return (
    <button
      className={'wl-ptt' + (held ? ' on' : '') + (blocked ? ' off' : '')}
      onPointerDown={press}
      onPointerUp={release}
      onKeyDown={keyDown}
      onKeyUp={keyUp}
      disabled={blocked}
      title={!trustEvidence ? 'no current trust status — the wall will not open the mic without it'
        : micState === 'off' ? 'mic is muted — unmute Nerva to talk'
        : micState !== 'on' ? 'mic permission is not an explicit yes — the wall will not open it'
        : usable ? 'hold to speak (or hold space)' : 'this browser cannot capture audio'}
      style={held ? { boxShadow: `0 0 ${18 + lv * 40}px rgba(65,245,155,${0.3 + lv * 0.5})` } : undefined}
    >
      <span>{label}</span>
    </button>
  );
}

/* The spoken line is a ROOM-FACING exposure, unlike the same text in the cockpit: a wall
   screen has an audience. The reviewer asked for default-hide or an explicit opt-in; the
   line is also the reference's signature element. Raised that tension in review; the owner
   reaffirmed default-hide, so the wall now opens redacted and the spoken line is an
   explicit, persisted opt-in per installation. One click shows it; the choice survives
   reloads. */
export const TRANSCRIPT_DEFAULT_VISIBLE = false;
const TRANSCRIPT_KEY = 'hud.wall.transcript';

export function readTranscriptPref(storage?: any) {
  try {
    const store = storage || (typeof localStorage !== 'undefined' ? localStorage : null);
    if (!store) return TRANSCRIPT_DEFAULT_VISIBLE;
    const raw = store.getItem(TRANSCRIPT_KEY);
    if (raw === 'hidden') return false;
    if (raw === 'shown') return true;
    return TRANSCRIPT_DEFAULT_VISIBLE;
  } catch { return TRANSCRIPT_DEFAULT_VISIBLE; }
}

function SpokenLine({ voice }: any) {
  const [shown, setShown] = useState(readTranscriptPref);
  const toggle = () => setShown((v) => {
    const next = !v;
    try { if (typeof localStorage !== 'undefined') localStorage.setItem(TRANSCRIPT_KEY, next ? 'shown' : 'hidden'); } catch { /* ignore */ }
    return next;
  });
  const transcript = voice && voice.transcript;
  return (
    <div className="wl-said">
      {!shown
        ? <span className="wl-said-idle">transcript hidden · room mode</span>
        : transcript
          ? <><span className="wl-caret">▸</span> {transcript}</>
          : <span className="wl-said-idle">{voice && voice.active ? 'listening…' : 'nothing heard yet'}</span>}
      <button
        className="wl-said-toggle"
        onClick={toggle}
        aria-pressed={!shown}
        title={shown ? 'hide the spoken line (this screen faces a room)' : 'show the spoken line'}
      >{shown ? 'hide' : 'show'}</button>
    </div>
  );
}

/* Collapsed side tabs — the reference's vertical "AGENT OPS" / "CORTEX" rails. They
   carry live counts, so on a narrow screen (where the stat cards are hidden) the wall
   still says how much is running. */
function EdgeTab({ side, label, badge }: any) {
  return (
    <div className={'wl-tab wl-tab-' + side}>
      {badge !== null && badge !== undefined && <span className="wl-tab-badge">{badge}</span>}
      <span className="wl-tab-label">{label}</span>
    </div>
  );
}

export function BriefingWall({
  agents = [], tasks = [], decisions = [], calendar = [], heartbeat = [],
  llm = null, trust = null, sources = null, localPct = null, voice = null,
  serverUp = false, demo = false, clock = null, motion = 'lively', localPctSource = null, onExit,
}: any) {
  const list = Array.isArray(agents) ? agents : [];
  // Evidence gate (review finding, 2026-08-06): `sources.tasks` is the proof that the
  // task feed answered on THIS load. A retained array from an earlier poll must not
  // survive that proof going away — otherwise the wall can render WORKING, firing
  // regions and task-attributed chips while its own rail reports "task feed · no data".
  // When the evidence is absent there are no tasks, for every consumer.
  const taskEvidence = !!(sources && sources.tasks === true);
  // Same rule for the roster: `sources.agents` is set by the loader only when agents
  // really arrived, so without it neither the roster size nor an executing count is
  // knowable — and "0 executing" is a claim, not a neutral default.
  // `sources.agents` means REAL LIVE evidence, and `loadJarvisData(demo)` deliberately seeds
  // the roster while leaving that flag false — demo is a separate, explicitly watermarked
  // provenance, not a claim about a live source. Gating on the flag alone emptied the demo
  // wall. Both provenances are honest here because the wall badges DEMO in its own chrome.
  const agentEvidence = !!demo || !!(sources && sources.agents === true);
  // One boundary, every consumer — the same rule as `evidenceTasks`. Gating only the two
  // metric cells left the roster half-fixed: a retained non-empty roster with
  // `sources.agents === false` could still drive WORKING, work-driven energy, firing
  // regions and a cabinet badge while the cards correctly said the roster was unavailable.
  const evidenceAgents = agentEvidence ? list : [];
  // There is no live decisions endpoint yet: `decisions` is seeded in demo and otherwise
  // stays []. Rendering 0 would assert "nothing is pending" on no evidence at all.
  const decisionEvidence = !!demo && Array.isArray(decisions) && decisions.length > 0;
  const evidenceTasks = taskEvidence && Array.isArray(tasks) ? tasks : [];
  const running = runningTasks(evidenceTasks);
  const waiting = evidenceTasks.length - running.length;
  const firing = evidenceAgents.filter(isExecutingAgent).length;
  const state = wallState({ voice, agents: evidenceAgents, tasks: evidenceTasks, serverUp });
  const energy = burstEnergy({ agents: evidenceAgents, tasks: evidenceTasks, voice, demo });
  const caps = (voice && voice.caps) || null;
  // `trust` is RETAINED across polls in app.tsx (`if (d.trust) setTrust(d.trust)`), so a
  // stale `mic: 'on'` can outlive its evidence. Everything trust-derived on this wall —
  // including the microphone control — keys off `sources.trust`, never off the object
  // alone. A default/retained object is not a current trust proof.
  const trustEvidence = !!(sources && sources.trust === true);
  const cloud = trustEvidence ? ((trust && (trust.claude_available || trust.cloud_available)) ? 'reported' : 'none reported') : null;
  // Raw mic state, un-normalized: only an exact 'on'/'off' means anything downstream.
  const micState = trust && typeof trust.mic === 'string' ? trust.mic : null;
  const model = (llm && llm.model) || (llm && Array.isArray(llm.residents) && llm.residents[0] && llm.residents[0].id) || null;

  // Per-source provenance. `sources.*` is set by the loader only when THAT source answered,
  // so a connected demo reports `live` for whatever really arrived and `seeded` only for
  // what is still the demo corpus.
  const provOf = (liveFlag: boolean, seededWhen: boolean) => (liveFlag ? 'live' : (demo && seededWhen ? 'seeded' : null));
  const src = sources || {};
  const provRoster = provOf(src.agents === true, list.length > 0);
  const provTasks = provOf(src.tasks === true, false);        // demo seeds no tasks
  const provModel = model ? 'live' : null;                    // llm is never demo-seeded
  const provCloud = trustEvidence ? 'live' : null;
  const provCal = provOf(src.calendar === true, Array.isArray(calendar) && calendar.length > 0);
  const provHb = provOf(src.heartbeat === true, Array.isArray(heartbeat) && heartbeat.length > 0);
  const provDecisions = decisionEvidence ? 'seeded' : null;   // no live decision feed exists
  // %-local provenance comes from App, which knows whether it measured, proved strict-local,
  // or fell back to the demo sample — it must not be inferred from `demo` alone.
  // Three-way, preserved end to end: a strict-local 100% is DERIVED from a governance
  // flag, not measured, so it gets its own provenance rather than being folded into live.
  const provLocal = localPct == null ? null
    : localPctSource === 'seeded' ? 'seeded'
    : localPctSource === 'strict-local' ? 'derived'
    : localPctSource === 'measured' ? 'live'
    : (demo ? 'seeded' : 'live');
  // The page caption follows the same evidence as the cells: a CONNECTED demo really is
  // showing live data, so calling the whole corpus seeded there is its own false claim.
  const allProvs = [provRoster, provTasks, provModel, provCloud, provCal, provHb, provDecisions, provLocal];
  const anyLive = allProvs.some((pv) => pv === 'live');
  const anySeeded = allProvs.some((pv) => pv === 'seeded');
  const demoCaption = anyLive && anySeeded ? 'demo mode · live + seeded data'
    : anyLive ? 'demo mode · live data'
    : anySeeded ? 'demo corpus · seeded data'
    : 'demo mode · no data yet';
  const now = clock instanceof Date ? clock : new Date();

  const subsystems = [
    { k: 'server', v: serverUp ? 'up' : 'down', tone: serverUp ? 'live' : 'bad' },
    { k: 'local model', v: model ? 'loaded' : (llm && llm.state === 'unknown' ? null : 'none'), tone: model ? 'live' : 'off' },
    { k: 'cloud lane', v: cloud, tone: cloud === 'reported' ? 'work' : 'off' },
    { k: 'mic', v: trustEvidence && (micState === 'on' || micState === 'off') ? (micState === 'off' ? 'muted' : 'on') : null, tone: micState === 'off' ? 'bad' : 'live' },
    { k: 'speech-to-text', v: caps ? (caps.stt ? 'ready' : 'not installed') : null, tone: caps && caps.stt ? 'live' : 'off' },
    { k: 'text-to-speech', v: caps ? (caps.tts ? 'ready' : 'not installed') : null, tone: caps && caps.tts ? 'live' : 'off' },
    { k: 'strict-local', v: trustEvidence && trust ? (trust.strict_local ? 'enforced' : 'off') : null, tone: trust && trust.strict_local ? 'live' : 'off' },
    { k: 'task feed', v: sources ? (sources.tasks ? 'live' : 'no data') : null, tone: sources && sources.tasks ? 'live' : 'off' },
  ];

  return (
    <div className="wall">
      {/* the field spans the whole wall and passes BEHIND the cards, as in the reference */}
      <div className="wl-field"><NeuralBurst agents={evidenceAgents} tasks={evidenceTasks} voice={voice} demo={demo} motion={motion} /></div>
      <span className="wl-bk tl" /><span className="wl-bk tr" /><span className="wl-bk bl" /><span className="wl-bk br" />
      <EdgeTab side="left" label="agent ops" badge={taskEvidence ? running.length : null} />
      <EdgeTab side="right" label="cabinet" badge={agentEvidence ? (evidenceAgents.length || null) : null} />

      <div className="wl-top">
        <div className="wl-brand">
          <div className="wl-word">N.E.R.V.A.</div>
          <div className="wl-cap">{demo ? demoCaption : 'local-first cabinet · ' + (serverUp ? 'connected' : 'no backend')}</div>
        </div>
        <div className={'wl-pill wl-pill-' + (demo ? 'demo' : serverUp ? 'live' : 'bad')}>
          <Dot tone={demo ? 'work' : serverUp ? 'live' : 'bad'} />
          <span>{demo ? 'DEMO' : serverUp ? 'BRIEFING · LIVE' : 'BACKEND OFFLINE'}</span>
          <span className="wl-when">{now.toLocaleDateString(undefined, { day: '2-digit', month: '2-digit' })} {now.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })}</span>
        </div>
        <div className="wl-state">
          <div className={'wl-state-word wl-' + state.tone}>{state.word}</div>
          <div className="wl-clock">{wallClock(now)}</div>
        </div>
      </div>

      <div className="wl-body">
        <div className="wl-col wl-left">
          <Card title="CABINET · NOW" stamp={cardStamp([
            agentEvidence ? provRoster : null, agentEvidence ? provRoster : null,
            taskEvidence ? provTasks : null, taskEvidence ? provTasks : null,
          ], 'live')}>
            <Cell label="AGENTS IN ROSTER" value={agentEvidence ? evidenceAgents.length : null} prov={provRoster} why="roster feed unavailable" />
            <Cell label="EXECUTING" value={agentEvidence ? firing : null} prov={provRoster} why="roster feed unavailable — an executing count needs a current roster" />
            <Cell label="TASKS RUNNING" value={taskEvidence ? running.length : null} prov={provTasks} why="task feed unavailable" />
            <Cell label="TASKS WAITING" value={taskEvidence ? Math.max(0, waiting) : null} prov={provTasks} why="task feed unavailable" />
          </Card>
          <Card title="THIS SESSION" stamp={cardStamp([provLocal, provModel, provCloud], provLocal === 'live' ? 'measured' : 'live')}>
            <Cell label="ON-DEVICE" value={localPct == null ? null : localPct + '%'} prov={provLocal} why="no measured locality split yet" />
            <Cell label="LOCAL MODEL" value={model} prov={provModel} why="no resident model reported" />
            <Cell label="CLOUD LANE" value={cloud} prov={provCloud} why="trust status unavailable" />
          </Card>
        </div>

        <div className="wl-stage">
          <PushToTalk voice={voice} micState={micState} trustEvidence={trustEvidence} />
          <SpokenLine voice={voice} />
        </div>

        <div className="wl-col wl-right">
          <Card title="ATTENTION" stamp={cardStamp([provDecisions, provCal, provHb], 'live')}>
            <Cell label="DECISIONS PENDING" value={decisionEvidence ? decisions.length : null} prov={provDecisions} why="no live decision feed — the HUD has no backend source for this yet" />
            <Cell label="UPCOMING EVENTS" value={Array.isArray(calendar) && calendar.length ? calendar.length : null} prov={provCal} why="calendar not connected" />
            <Cell label="HEARTBEATS" value={Array.isArray(heartbeat) && heartbeat.length ? heartbeat.length : null} prov={provHb} why="no heartbeat entries" />
          </Card>
          <div className="wl-rail">
            <div className="wl-rail-h">SUBSYSTEM STATUS</div>
            {subsystems.map((s) => (
              <div className="wl-rail-row" key={s.k}>
                <span className="wl-rail-k">{s.k}</span>
                <span className={'wl-rail-v' + (s.v === null ? ' wl-miss' : '')} title={s.v === null ? 'not reported' : undefined}>{s.v === null ? '—' : s.v}</span>
                <Dot tone={s.v === null ? 'off' : s.tone} />
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="wl-bottom">
        {/* Exact-state rendering: 'on' and 'off' are the only values that mean anything.
            Anything else — missing, 'unknown', empty, a number — is UNKNOWN, so the footer
            can never read OPEN for a state the mic control itself refuses. */}
        <span className="wl-foot">MIC · {!trustEvidence || micState === null ? 'UNKNOWN'
          : micState === 'off' ? 'MUTED'
          : micState !== 'on' ? 'UNKNOWN'
          : voice && voice.active ? 'OPEN' : 'IDLE'}</span>
        <span className="wl-foot wl-foot-mid">{energy.detail}</span>
        <span className="wl-foot">FIELD DRIVEN BY · {energy.source.toUpperCase()}</span>
      </div>
      {onExit && <button className="cin-exit wl-exit" onClick={onExit}>esc</button>}
    </div>
  );
}
