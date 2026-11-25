/* The running foot (PHASE_B_PLAN.md §4.3), footer[data-frame="runfoot"]:

     Agents 18 · ▶ 1 working · ⊛ 2 waiting on you · ✓ 3 finished today · ⊘ 1 unavailable ·
     11 no activity reported │ RAM 19% ▬ VRAM 96% ▬ GPU load 3% ▬ Latency p50 ○ Unknown — not
     measured │ Channels ● 2 of 2 running · 1 session in the last 15 min (below 2200px:
     "1 session", the window in its title) │ (≥ 2200) Ctrl K finds every area, panel, agent and
     action · No keyboard shortcut signs or rejects │ Nerva 1.4.0

   Agents by exception and the machine are the signals engineer's derivations
   (signals/agents-exception.ts, signals/machine.ts): one state per agent from a source the hub
   can prove — the word "idle" is never used — and a source that did not answer is said
   ("Running work: unknown without the owner credential"), never read as "nothing running"; a
   machine reading with no total is unknown, never 0, and latency p50 is never measured.
   Channels keep the status chrome's hooks and semantics (data-chrome="gateway" | "sessions" |
   "version"): dashes, not zeros; an unknown gateway says unknown; no version element when the
   hub did not report one. Demo shows the roster's size and the demo label, nothing derived.

   Below 760px nothing in the foot is cut (frame.css): its groups fold onto lines, and an unknown
   machine reading is its label and its mark ("RAM ◌"), its words ("Unknown — not reported") read,
   not drawn, and in its title, as the meters and the latency are left out below 1680px (§4.3). */
import React, { memo, useMemo } from 'react';
import { chordOf, displayChord, type Overrides } from '../shortcuts';
import { agentsByException, agentsSummary } from '../signals/agents-exception';
import { useAway, useBlockedTasks, useKillSwitchReading, useRunningTasks, useSubagents } from '../signals/hooks';
import { machineLabel, machineReadings, machineValue } from '../signals/machine';
import type { HubSnapshot, MachineReading, TabTurn } from '../signals/types';
import { Mark, SourceLabel } from './kit';
import { RUNFOOT_STRINGS } from './frame-strings';
import { useStaleNow } from './stale-now';
import { fmt, pick, plural, type Lang } from './strings';
import { hubReading } from './types';
import './frame.css';

function Machine({ reading, lang }: { reading: MachineReading; lang: Lang }) {
  const known = reading.pct !== null && (reading.state === 'live' || reading.state === 'stale');
  const words = known ? null : machineValue(reading, lang);
  return (
    <span className="n-runfoot__item" data-machine={reading.key} data-state={known ? reading.state : reading.state === 'demo' ? 'demo' : 'unknown'}
      title={reading.detail ?? words ?? undefined} {...(reading.key === 'latency' ? { 'data-show-from': 'l' } : {})}>
      <span className="n-runfoot__key">{machineLabel(reading.key, lang)}</span>
      {known ? <>
        <b className="n-runfoot__figure">{reading.pct}%</b>
        <span className="n-runfoot__meter" aria-hidden="true"><i style={{ width: `${reading.pct}%` }} /></span>
      </> : <>
        {reading.state !== 'demo' && <Mark kind="unknown" size="sm" lang={lang} />}
        {/* below 760px an unknown reading's words are read, not drawn (frame.css); the title keeps them */}
        <span className="n-runfoot__words">{words}</span>
      </>}
    </span>
  );
}

function KeyHint({ lang, chord }: { lang: Lang; chord: string }) {
  const s = pick(RUNFOOT_STRINGS, lang);
  const [before, after] = s.keyHint.split('{key}');
  return (
    <span className="n-runfoot__item" data-runfoot="key-hint">
      {chord ? <>{before}<kbd className="n-kbd">{chord}</kbd>{after}</> : null}
      <span className="n-runfoot__detail">{s.noKeyVerdict}</span>
    </span>
  );
}

export interface RunningFootProps {
  hub: HubSnapshot;
  lang: Lang;
  demo: boolean;
  /** This tab's in-flight turns: an agent answering here is working ("Answering you (asked)"). */
  turns: readonly TabTurn[];
  /** The key hint shows the search sheet's key (shortcuts.ts). */
  shortcutOverrides?: Overrides;
  /** Home's spread carries the agents and the machine at ≥ 2200px: the foot leaves them out there. */
  spread?: boolean;
  /** Something the window adds at the end (the desktop app's "Float chat"). */
  aside?: React.ReactNode;
}

export const RunningFoot = memo(function RunningFoot({ hub, lang, demo, turns, shortcutOverrides, spread = false, aside }: RunningFootProps) {
  const s = pick(RUNFOOT_STRINGS, lang);
  const now = useStaleNow(hub);
  const blocked = useBlockedTasks({ demo });
  const running = useRunningTasks({ demo });
  const subagents = useSubagents({ demo });
  const today = useAway({ demo });
  const killSwitch = useKillSwitchReading({ demo });
  const summary = useMemo(() => agentsSummary(agentsByException({
    roster: hub.agents, rosterKnown: hub.sources.agents === true || demo, blocked, running, subagents, turns, today,
    trust: hub.trust, killSwitch, slots: hub.slots, now,
  }, lang), lang),
    // the readings' fields are what changes; their objects are new on every render
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [hub, lang, demo, turns, now, blocked.state, blocked.value, running.state, running.value, subagents.state, subagents.value,
      today.state, today.value, killSwitch.state, killSwitch.value]);
  const reading = hubReading(hub, now);
  const machine = machineReadings({ sys: hub.sys, hubState: reading.state, hubReason: reading.reason }, lang);
  const chord = displayChord(chordOf(shortcutOverrides || {}, 'session.palette'));
  const gw = hub.chrome.gateway;
  const sessions = hub.chrome.sessions;
  // the window the hub counted over, as it said it; none said is "the recent window", never a default
  const minutes = sessions.windowS !== null && sessions.windowS > 0 ? Math.round(sessions.windowS / 60) : null;
  const below = spread ? { 'data-show-upto': 'l' } : {};
  return (
    <footer className="n-runfoot" data-frame="runfoot">
      <div className="n-runfoot__group" role="group" aria-label={s.agentsGroup} data-runfoot="agents" {...below}>
        <span className="n-runfoot__item n-runfoot__lead">{summary.label}</span>
        {demo ? <SourceLabel reading={{ state: 'demo', lastGoodAt: null }} lang={lang} /> : <>
          {/* below 1680px the foot also carries the channels, so the agents with no activity
              reported (the remainder of the count) are left to the agents pages there */}
          {summary.parts.map((part) => (
            <span key={part.activity} className="n-runfoot__item" data-activity={part.activity}
              {...(part.activity === 'noActivity' ? { 'data-show-from': 'l' } : {})}>
              <Mark kind={part.mark} size="sm" lang={lang} />{part.text}
            </span>
          ))}
          {summary.elsewhere && <span className="n-runfoot__item" data-runfoot="elsewhere">{summary.elsewhere}</span>}
          {summary.unread.map((words) => <span key={words} className="n-runfoot__item n-runfoot__detail" data-show-from="l">{words}</span>)}
        </>}
      </div>
      <div className="n-runfoot__group" role="group" aria-label={s.machineGroup} data-runfoot="machine" {...below}>
        {machine.map((r) => <Machine key={r.key} reading={r} lang={lang} />)}
      </div>
      {/* The channels at every width (status chrome H133: the gateway and the session count must be
          painted on an ordinary screen): in full from 2200px, below it the session count drops its
          window from the line and keeps it in its title. */}
      <div className="n-runfoot__group" role="group" aria-label={s.channelsGroup} data-runfoot="channels">
        <span className="n-runfoot__item" data-chrome="gateway" data-state={gw.state}
          title={gw.running.length ? gw.running.join(', ') : undefined}>
          <span className="n-runfoot__key">{s.channels}</span>
          {gw.state === 'running' ? <>
            <Mark kind="ok" size="sm" lang={lang} />
            <b className="n-runfoot__figure">{gw.total !== null
              ? fmt(s.channelsRunning, { running: gw.running.length, total: gw.total })
              : fmt(s.channelsRunningNoTotal, { running: gw.running.length })}</b>
          </> : gw.state === 'stopped' ? <><Mark kind="held" size="sm" lang={lang} /><span>{s.channelsStopped}</span></>
            : gw.state === 'none' ? <span>{s.channelsNone}</span>
              : <Mark kind="unknown" size="sm" lang={lang} word />}
        </span>
        {sessions.active === null ? <span className="n-runfoot__item" data-chrome="sessions">{s.sessionsUnknown}</span> : (() => {
          const full = minutes === null ? plural(lang, s.sessionsRecent, sessions.active) : plural(lang, s.sessions, sessions.active, { min: minutes });
          return (
            <span className="n-runfoot__item" data-chrome="sessions" title={full}>
              <span data-show-from="xl">{full}</span>
              <span data-show-upto="l">{plural(lang, s.sessionsShort, sessions.active)}</span>
            </span>
          );
        })()}
      </div>
      <div className="n-runfoot__group" data-runfoot="keys" data-show-from="xl">
        <KeyHint lang={lang} chord={chord} />
      </div>
      {aside}
      <span className="n-runfoot__ver">
        {hub.chrome.version ? <span data-chrome="version">{fmt(s.version, { version: hub.chrome.version })}</span> : s.product}
      </span>
    </footer>
  );
});
