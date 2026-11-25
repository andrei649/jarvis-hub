/* WorkingReply: a reply that is still being written, as a page the owner reads
   (PHASE_B_PLAN.md §5.3; ledger README §4 "Talk").

   Replies take 4 to 60+ seconds, so this is a state, not a flicker. It is drawn only from what
   the stream reports for THIS tab's turn:
     - the three stamps runTurn writes on the reserved bubble (home/talk/types.ts ReplyStamps):
       Sent ✓ (asked) → Started — asked <Agent> (the first `start`) → Writing (the first `token`);
     - the tool cards (`tool` frames, turn-tools.tsx mergeToolEvent), a "Tools" step only when
       cards exist, each with its state;
     - the model the turn's live outcome reported (`outcome_progress`), for the latest turn.
   Not drawn: Classify / Route / Gather / Synthesize and "asking Pepper and Stark" — the stream
   does not report routed agents (gap-2 §5.2). The current step has a dotted rule; nothing
   animates; the elapsed time is a local one-second clock while the reply is in flight. The one
   control stops it ("Stop the replies" when this tab has more than one in flight, because the
   stop ends them all). The block is `aria-live="off"`: its words change on every token, and the
   finished reply is what the transcript's log announces. */
import React, { useEffect, useState } from 'react';
import { Mark } from '../../frame/kit';
import { clockTime } from '../../frame/kit/strings';
import { fmt, plural } from '../../frame/strings';
import type { TabTurn } from '../../signals/types';
import type { ToolCard } from '../../turn-tools';
import type { TurnOutcome } from '../../turn-outcome';
import type { MarkKind } from '../../frame/kit/marks';
import { fill, talkStrings } from './strings';
import type { TalkMessage } from './types';

type StepState = 'done' | 'now' | 'todo';
interface Step { readonly id: 'sent' | 'started' | 'tools' | 'writing'; readonly label: string; readonly state: StepState }

/** Words in a streamed text so far. */
export function wordCount(text: unknown): number {
  return typeof text === 'string' ? text.trim().split(/\s+/).filter(Boolean).length : 0;
}

/** "42 s", "3 min", "1 h 5 min": how long a reply has been in flight. */
export function elapsedWords(ms: number, lang: string): string {
  const s = talkStrings(lang);
  const seconds = Math.max(0, Math.floor(ms / 1000));
  if (seconds < 60) return fmt(s.elapsedSeconds, { n: seconds });
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return fmt(s.elapsedMinutes, { n: minutes });
  return fmt(s.elapsedHours, { h: Math.floor(minutes / 60), m: minutes % 60 });
}

/** A clock that ticks once a second while `active` (a fixed `at` for tests and renders). */
export function useSecondClock(active: boolean, at?: number): number {
  const [now, setNow] = useState(() => at ?? Date.now());
  useEffect(() => {
    if (!active || at !== undefined) return undefined;
    setNow(Date.now());
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [active, at]);
  return at ?? now;
}

const TOOL_MARK: Record<ToolCard['state'], MarkKind> = {
  requested: 'idle', running: 'work', done: 'done', failed: 'problem', stopped: 'held',
};

export function toolStateWord(state: ToolCard['state'], lang: string): string {
  const s = talkStrings(lang);
  switch (state) {
    case 'requested': return s.toolRequested;
    case 'running': return s.toolRunning;
    case 'done': return s.toolDone;
    case 'failed': return s.toolFailed;
    default: return s.toolStopped;
  }
}

export interface WorkingReplyProps {
  /** The reserved reply bubble (its stamps, tools and streamed text). */
  message: TalkMessage;
  /** This tab's record of the turn; its stamps stand in for a bubble's missing ones. */
  turn?: TabTurn | null;
  /** The agent asked, as a name. */
  agentName: string;
  /** How many replies this tab has in flight. */
  inFlight: number;
  /** Draw the one stop control here (the newest reply in flight carries it). */
  showStop: boolean;
  onStop?: () => void;
  /** The live outcome of the latest turn (outcome_progress); only read when `latest`. */
  outcome?: TurnOutcome | null;
  latest: boolean;
  /** A question from this turn waits for the owner's answer. */
  awaitingAnswer?: boolean;
  lang: string;
  /** Tests: a fixed clock. */
  now?: number;
  /** The streamed text, between the steps and the meta line. */
  children?: React.ReactNode;
}

export function WorkingReply({ message, turn, agentName, inFlight, showStop, onStop, outcome, latest, awaitingAnswer = false, lang, now: fixedNow, children }: WorkingReplyProps) {
  const s = talkStrings(lang);
  const now = useSecondClock(true, fixedNow);
  const askedAt = typeof message._askedAt === 'number' ? message._askedAt : turn?.askedAt ?? null;
  const started = typeof message._startedAt === 'number' || typeof turn?.startedAt === 'number';
  const firstToken = typeof message._firstTokenAt === 'number' || typeof turn?.firstTokenAt === 'number';
  const tools: readonly ToolCard[] = Array.isArray(message.tools) ? message.tools : [];
  const running = tools.filter((c) => c.state === 'running');
  const calling = tools.filter((c) => c.state === 'requested');
  const toolActive = running.length > 0 || calling.length > 0;
  const words = wordCount(message.text);

  const steps: Step[] = [
    { id: 'sent', label: s.stepSent, state: 'done' },
    { id: 'started', label: fmt(s.stepStarted, { agent: agentName }), state: started ? 'done' : 'now' },
    ...(tools.length ? [{ id: 'tools' as const, label: s.stepTools, state: (!started ? 'todo' : toolActive ? 'now' : 'done') as StepState }] : []),
    { id: 'writing', label: s.stepWriting, state: !started || toolActive ? 'todo' : 'now' },
  ];
  const status = awaitingAnswer ? s.statusAnswer
    : !started ? fmt(s.statusWaitStart, { agent: agentName })
    : running.length > 1 ? plural(lang, s.statusRunningMore, running.length - 1, { tool: running[0].tool })
    : running.length === 1 ? fmt(s.statusRunning, { tool: running[0].tool })
    : calling.length ? fmt(s.statusCalling, { tool: calling[0].tool })
    : firstToken ? plural(lang, s.statusWriting, words)
    : s.statusFirstWords;
  const stateWord = (state: StepState) => (state === 'done' ? s.stepDone : state === 'now' ? s.stepNow : s.stepTodo);
  const model = latest && outcome && typeof outcome.model === 'string' ? outcome.model : null;

  return (
    <div className="n-working" data-working="" aria-live="off">
      <ol className="n-steps" aria-label={s.stepsLabel}>
        {steps.map((step) => (
          <li key={step.id} className={`n-steps__step n-steps__step--${step.state}`} data-step={step.id} data-state={step.state}
            aria-current={step.state === 'now' ? 'step' : undefined}>
            {step.state === 'done' && <Mark kind="done" size="sm" lang={lang} />}
            {step.state === 'now' && <Mark kind="work" size="sm" lang={lang} />}
            <span className="n-steps__label">{step.label}</span>
            <span data-visually-hidden="">{` — ${stateWord(step.state)}`}</span>
          </li>
        ))}
      </ol>
      {tools.length > 0 && (
        <ul className="n-working__tools" aria-label={s.toolsLabel}>
          {tools.map((card) => (
            <li key={card.key} data-state={card.state}>
              <Mark kind={TOOL_MARK[card.state]} size="sm" lang={lang} />
              <code>{card.tool}</code>
              <span>{toolStateWord(card.state, lang)}</span>
            </li>
          ))}
        </ul>
      )}
      <p className="n-working__line">
        <span className="n-working__status" data-working-status="">{status}</span>
        {showStop && onStop && (
          <button type="button" className="n-btn n-btn--sm n-btn--quiet n-working__stop" onClick={onStop}>
            <svg className="n-working__stop-ico" viewBox="0 0 16 16" aria-hidden="true" focusable="false"><rect x="3" y="3" width="10" height="10" /></svg>
            {inFlight > 1 ? s.stopMany : s.stopOne}
          </button>
        )}
      </p>
      {children}
      <p className="n-working__meta">
        <span data-working-where="">{model ? fill(s.whereModel, { model: <code>{model}</code> }) : s.whereLater}</span>
        {askedAt !== null && (
          <span data-working-elapsed="">
            {fill(s.metaAsked, { time: <time dateTime={new Date(askedAt).toISOString()}>{clockTime(askedAt)}</time>, elapsed: <b>{elapsedWords(now - askedAt, lang)}</b> })}
          </span>
        )}
      </p>
    </div>
  );
}

/** A turn in flight with no reply bubble of its own (a vision analysis, the demo's staged
 *  sample): the waiting line and the stop, nothing invented about its steps. */
export function PendingReply({ who, whoTitle, onStop, inFlight = 1, lang }: { who: string; whoTitle?: string; onStop?: () => void; inFlight?: number; lang: string }) {
  const s = talkStrings(lang);
  return (
    <div className="n-turn n-turn--reply" data-turn="reply" data-pending="">
      <span className="n-turn__time" aria-hidden="true" />
      <span className="n-turn__who" title={whoTitle ?? (who || undefined)}>{who}</span>
      <div className="n-turn__body">
        <div className="n-working" data-working="" aria-live="off">
          <p className="n-working__line">
            <span className="n-working__status" data-working-status="">{s.statusPending}</span>
            {onStop && (
              <button type="button" className="n-btn n-btn--sm n-btn--quiet n-working__stop" onClick={onStop}>
                <svg className="n-working__stop-ico" viewBox="0 0 16 16" aria-hidden="true" focusable="false"><rect x="3" y="3" width="10" height="10" /></svg>
                {inFlight > 1 ? s.stopMany : s.stopOne}
              </button>
            )}
          </p>
        </div>
      </div>
    </div>
  );
}
