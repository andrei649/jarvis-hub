/* TalkRegister: the conversation register of the Ledger (PHASE_B_PLAN.md §5.3; ledger README §4).

   Home renders `<TalkRegister {...talk} variant="home" turns={turns}/>`; ChatPage renders it at
   full width ('chat') and in the 420 × 620 desktop window ('floating'). It is today's Conversation
   and InputBar (cockpit.tsx), re-laid, with their props, logic and accessible names:

     head        "Conversation" · "with Jarvis · Prime Orchestrator · Orchestrated" (the declared
                 routing policy, as chat-routing-policy words it; "Routing policy unknown" when the
                 hub did not serve the roster, which is not "Unavailable"), or "no agent chosen" /
                 "checking the selected agent…" (the composer's own sentence) while App holds no
                 recipient, or "with Frigga · not confirmed" while it keeps one the roster could not
                 confirm · "Search earlier conversations", which opens the same chat-history
                 dialog as the composer's Options item. The title is never cut: when the rest does
                 not fit beside it, it goes under the title, and below 760px it always does
                 (home/home.css; its runs of words wrap there, talk.css).
     transcript  one log region, bottom-anchored on the composer: the turns, the working reply of
                 this tab's in-flight turns, each reply's footnote, slip and action budget
     composer    To (the recipient picker: App's selectChatAgent, which never opens the Dossier) ·
                 Mode (the approval mode that applies to the recipient: its own override, else the
                 global mode — home/talk/recipient-mode.ts, through the shared poller) · the field ·
                 Attach · Voice · Options · Send

   The floating variant is the conversation alone: no register head (the window has its own
   controls, the running head as marks and the docket line, all ChatPage's), the transcript and a
   composer that starts at one line. */
import React, { useRef } from 'react';
import { Conversation, InputBar } from '../../cockpit';
import { V2 } from '../../data';
import type { ChatAgent } from '../../chat-routing-policy';
import { Register } from '../../frame/kit';
import { fmt } from '../../frame/strings';
import { agentDisplayName, rosterServed } from './RecipientPicker';
import { useRecipientMode } from './recipient-mode';
import { fill, lowerFirst, policyWord, talkStrings } from './strings';
import type { TalkRegisterProps } from './types';
import './talk.css';

type RosterAgent = ChatAgent & { role?: unknown };

export function TalkRegister(props: TalkRegisterProps) {
  const { variant, turns, onSelectAgent, awaitingAnswer = false, ...talk } = props;
  const s = talkStrings(talk.lang);
  const demo = !!talk.demo;
  const openHistory = useRef<((opener: HTMLElement) => boolean) | null>(null);
  const agents = (talk.agents ?? []) as readonly RosterAgent[];
  const agent = talk.agent ?? 'jarvis';
  const mode = useRecipientMode(agent, { demo });
  const roster = (demo ? (V2.AGENTS as unknown as RosterAgent[]) : agents);
  const selected = demo ? roster.find((a) => a.id === agent) : agents.find((a) => a.id === agent && a.rosterSource === 'api');
  const name = agentDisplayName(agent, roster);
  const role = selected && typeof selected.role === 'string' && selected.role.trim() ? selected.role.trim() : null;
  // Without the hub's roster the declared policy is not known: that is never "Unavailable", which
  // the roster alone can say (an agent it does not offer, or offers disabled).
  const served = demo || rosterServed(agents);
  const policy = demo ? s.policyDemo : !served ? s.policyUnknown
    : !selected || selected.enabled === false ? s.policyUnavailable : policyWord(selected.chat_routing, s);
  const policyTitle = served ? s.policyTitle : s.policyNotServed;
  const canSearch = !!talk.selectedTurn && !demo;
  // App passes `turnActive` to today's InputBar; a page that does not still has the facts
  const turnActive = talk.turnActive ?? (!!talk.thinking || turns.length > 0);

  const conversation = (
    <Conversation messages={talk.messages} thinking={talk.thinking} onStop={talk.onStop} onProv={talk.onProv}
      onArtifactSaved={talk.onArtifactSaved} exportAllowed={talk.exportAllowed} messageActionsAllowed={talk.messageActionsAllowed}
      messageScope={talk.messageScope} sessionId={talk.sessionId} agent={agent} lang={talk.lang} t={talk.t}
      variant={variant} turns={turns} agents={roster} outcome={talk.outcome ?? null} outcomeTurnId={talk.outcomeTurnId}
      power={talk.power} awaitingAnswer={awaitingAnswer} />
  );
  const composer = (
    <InputBar onSubmit={talk.onSubmit} mic={talk.mic} setMic={talk.setMic} voice={talk.voice} cfg={talk.cfg} onCfg={talk.onCfg}
      micMuted={talk.micMuted} motion={talk.motion} t={talk.t} lang={talk.lang} demo={demo} agent={agent} agents={agents as ChatAgent[]}
      recipientStatus={talk.recipientStatus} sessionId={talk.sessionId} selectedTurn={talk.selectedTurn} outcome={talk.outcome}
      power={talk.power} projectForChat={talk.projectForChat} onProjectReviewed={talk.onProjectReviewed}
      boardResultForChat={talk.boardResultForChat} onBoardResultReviewed={talk.onBoardResultReviewed} inspectBlend={talk.inspectBlend}
      turnActive={turnActive} canContinue={talk.canContinue}
      onSelectAgent={onSelectAgent} approvalMode={mode} variant={variant} openHistory={openHistory}
      recipientSwitch={talk.recipientSwitch} onRecipientSwitch={talk.onRecipientSwitch}
      recipientRefusal={talk.recipientRefusal} recipientHold={talk.recipientHold}
      recipientSwitchDropped={talk.recipientSwitchDropped} onRecipientSwitchDropped={talk.onRecipientSwitchDropped} />
  );

  if (variant === 'floating') {
    return (
      <section className="n-talk n-talk--floating" data-register="talk" aria-label={s.title}>
        <div className="n-talk__body">{conversation}</div>
        <div className="n-talk__foot">{composer}</div>
      </section>
    );
  }

  // No recipient to send to (one being checked, or none chosen since App dropped one): the head says
  // so rather than "with  · Unavailable" or the name of an agent nothing will be sent to; the
  // composer's line says why and what happens. A selected agent App keeps but cannot confirm (the
  // hub did not serve the roster) is named "not confirmed", the composer's sentence in its tooltip.
  const recipientReady = !!agent && talk.recipientStatus !== 'checking' && talk.recipientStatus !== 'choose';
  const hold = !demo && talk.recipientStatus === 'checking' ? talk.recipientHold ?? null : null;
  const holdName = hold ? agentDisplayName(hold.agent, agents, hold.name) : '';
  const meta = (
    <>
      {recipientReady ? (
        <span className="n-talk__with">
          {fill(s.withAgent, { agent: <b>{name}</b> })}
          {role && <span className="n-talk__role" data-show-from="m">{' · '}{role}</span>}
          {' · '}<span className="n-talk__policy" title={policyTitle} data-policy={served ? undefined : 'not-served'}>{policy}</span>
        </span>
      ) : hold ? (
        <span className="n-talk__with" data-recipient-state="unconfirmed">
          {fill(s.withAgent, { agent: <b>{holdName}</b> })}
          {' · '}<span className="n-talk__unconfirmed"
            title={fmt(s.recipientNotServed, { agent: holdName, fallback: agentDisplayName('jarvis', agents) })}>{s.unconfirmed}</span>
        </span>
      ) : (
        <span className="n-talk__with" data-recipient-state={talk.recipientStatus === 'checking' ? 'checking' : 'none'}>
          {talk.recipientStatus === 'checking' ? lowerFirst(s.recipientChecking, talk.lang) : s.withNone}
        </span>
      )}
      {canSearch && (
        <button type="button" className="n-link n-talk__search" aria-haspopup="dialog"
          onClick={(event) => { openHistory.current?.(event.currentTarget); }}>{s.searchEarlier}</button>
      )}
    </>
  );
  return (
    <Register title={s.title} meta={meta} register="talk" id="talk" className={`n-talk n-talk--${variant}`}
      bodyProps={{ className: 'n-talk__body' }} foot={composer}>
      {conversation}
    </Register>
  );
}
