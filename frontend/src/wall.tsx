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
import React, { useState, useEffect, useCallback } from 'react';
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
   with `why` explaining the absence — the wall never fills a gap with a guess. */
function Cell({ label, value, why, sub }: any) {
  const missing = value === null || value === undefined || value === '';
  return (
    <div className="wl-row">
      <span className="wl-k">{label}</span>
      <span className={'wl-v' + (missing ? ' wl-miss' : '')} title={missing ? (why || 'no evidence available') : undefined}>
        {missing ? '—' : value}
      </span>
      {sub && <span className="wl-sub">{sub}</span>}
    </div>
  );
}

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
function PushToTalk({ voice, muted }: any) {
  const [held, setHeld] = useState(false);
  const usable = !!voice && typeof voice.start === 'function' && typeof voice.stop === 'function' && voice.supported !== false;
  const blocked = muted || !usable;
  const release = useCallback(() => {
    setHeld((wasHeld) => { if (wasHeld && voice && voice.stop) voice.stop(); return false; });
  }, [voice]);
  // release outside the button still ends the turn
  useEffect(() => {
    if (!held) return undefined;
    window.addEventListener('pointerup', release);
    window.addEventListener('pointercancel', release);
    return () => { window.removeEventListener('pointerup', release); window.removeEventListener('pointercancel', release); };
  }, [held, release]);
  const press = () => { if (blocked) return; setHeld(true); voice.start(); };
  const label = muted ? 'mic muted'
    : !usable ? 'voice unavailable'
    : held ? 'listening…'
    : 'hold to talk';
  const lv = held ? Math.min(1, (Number(voice && voice.level) || 0) / 0.25) : 0;
  return (
    <button
      className={'wl-ptt' + (held ? ' on' : '') + (blocked ? ' off' : '')}
      onPointerDown={press}
      onPointerUp={release}
      disabled={blocked}
      title={muted ? 'mic is muted — unmute Nerva to talk' : usable ? 'hold to speak' : 'this browser cannot capture audio'}
      style={held ? { boxShadow: `0 0 ${18 + lv * 40}px rgba(65,245,155,${0.3 + lv * 0.5})` } : undefined}
    >
      <span>{label}</span>
    </button>
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
  serverUp = false, demo = false, clock = null, onExit,
}: any) {
  const list = Array.isArray(agents) ? agents : [];
  const running = runningTasks(Array.isArray(tasks) ? tasks : []);
  const waiting = (Array.isArray(tasks) ? tasks : []).length - running.length;
  const firing = list.filter(isExecutingAgent).length;
  const state = wallState({ voice, agents, tasks, serverUp });
  const energy = burstEnergy({ agents, tasks, voice, demo });
  const caps = (voice && voice.caps) || null;
  const trustEvidence = sources && sources.trust === true;
  const cloud = trustEvidence ? ((trust && (trust.claude_available || trust.cloud_available)) ? 'reported' : 'none reported') : null;
  const model = (llm && llm.model) || (llm && Array.isArray(llm.residents) && llm.residents[0] && llm.residents[0].id) || null;
  const now = clock instanceof Date ? clock : new Date();

  const subsystems = [
    { k: 'server', v: serverUp ? 'up' : 'down', tone: serverUp ? 'live' : 'bad' },
    { k: 'local model', v: model ? 'loaded' : (llm && llm.state === 'unknown' ? null : 'none'), tone: model ? 'live' : 'off' },
    { k: 'cloud lane', v: cloud, tone: cloud === 'reported' ? 'work' : 'off' },
    { k: 'mic', v: trust ? (trust.mic === 'off' ? 'muted' : 'on') : null, tone: trust && trust.mic === 'off' ? 'bad' : 'live' },
    { k: 'speech-to-text', v: caps ? (caps.stt ? 'ready' : 'not installed') : null, tone: caps && caps.stt ? 'live' : 'off' },
    { k: 'text-to-speech', v: caps ? (caps.tts ? 'ready' : 'not installed') : null, tone: caps && caps.tts ? 'live' : 'off' },
    { k: 'strict-local', v: trust ? (trust.strict_local ? 'enforced' : 'off') : null, tone: trust && trust.strict_local ? 'live' : 'off' },
    { k: 'task feed', v: sources ? (sources.tasks ? 'live' : 'no data') : null, tone: sources && sources.tasks ? 'live' : 'off' },
  ];

  return (
    <div className="wall">
      {/* the field spans the whole wall and passes BEHIND the cards, as in the reference */}
      <div className="wl-field"><NeuralBurst agents={agents} tasks={tasks} voice={voice} demo={demo} motion="lively" /></div>
      <span className="wl-bk tl" /><span className="wl-bk tr" /><span className="wl-bk bl" /><span className="wl-bk br" />
      <EdgeTab side="left" label="agent ops" badge={sources && sources.tasks ? running.length : null} />
      <EdgeTab side="right" label="cabinet" badge={list.length || null} />

      <div className="wl-top">
        <div className="wl-brand">
          <div className="wl-word">N.E.R.V.A.</div>
          <div className="wl-cap">{demo ? 'demo corpus · seeded data' : 'local-first cabinet · ' + (serverUp ? 'connected' : 'no backend')}</div>
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
          <Card title="CABINET · NOW" stamp="live">
            <Cell label="AGENTS IN ROSTER" value={list.length || null} why="roster not loaded" />
            <Cell label="EXECUTING" value={firing} />
            <Cell label="TASKS RUNNING" value={sources && sources.tasks ? running.length : null} why="task feed unavailable" />
            <Cell label="TASKS WAITING" value={sources && sources.tasks ? Math.max(0, waiting) : null} why="task feed unavailable" />
          </Card>
          <Card title="THIS SESSION" stamp="measured">
            <Cell label="ON-DEVICE" value={localPct == null ? null : localPct + '%'} why="no measured locality split yet" />
            <Cell label="LOCAL MODEL" value={model} why="no resident model reported" />
            <Cell label="CLOUD LANE" value={cloud} why="trust status unavailable" />
          </Card>
        </div>

        <div className="wl-stage">
          <PushToTalk voice={voice} muted={!!(trust && trust.mic === 'off')} />
          <div className="wl-said">
            {voice && voice.transcript
              ? <><span className="wl-caret">▸</span> {voice.transcript}</>
              : <span className="wl-said-idle">{voice && voice.active ? 'listening…' : 'nothing heard yet'}</span>}
          </div>
        </div>

        <div className="wl-col wl-right">
          <Card title="ATTENTION" stamp="queue">
            <Cell label="DECISIONS PENDING" value={(Array.isArray(decisions) ? decisions.length : 0) || 0} />
            <Cell label="UPCOMING EVENTS" value={Array.isArray(calendar) && calendar.length ? calendar.length : null} why="calendar not connected" />
            <Cell label="HEARTBEATS" value={Array.isArray(heartbeat) && heartbeat.length ? heartbeat.length : null} why="no heartbeat entries" />
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
        <span className="wl-foot">MIC · {trust && trust.mic === 'off' ? 'MUTED' : (voice && voice.active ? 'OPEN' : 'IDLE')}</span>
        <span className="wl-foot wl-foot-mid">{energy.detail}</span>
        <span className="wl-foot">FIELD DRIVEN BY · {energy.source.toUpperCase()}</span>
      </div>
      {onExit && <button className="cin-exit wl-exit" onClick={onExit}>esc</button>}
    </div>
  );
}
