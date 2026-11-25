/* RecipientPicker: the composer's "To" (PHASE_B_PLAN.md §5.3, §12 item 11).

   The recipient is App's `activeId`; the choices are `selectableChatAgents(agents, demo)`, and a
   choice calls `onSelectAgent` (App's `selectChatAgent`), which changes who the owner writes to
   and never opens the Dossier. Choosing someone else while a reply is being written would stop
   that reply (selectChatAgent stops the turn), so the picker asks first.

   The question. While it is open the change waits: Send is held (a message written meanwhile
   would otherwise go to the recipient being replaced) and points at the question's sentence
   (`whyId`). Nothing switches by itself: when the reply ends — finished, or stopped by the owner —
   with the question still open, the question stays, without its "stops the reply" clause ("The
   reply from Jarvis has ended. Write to Frigga?" · "Write to Frigga" · "Stay with Jarvis"), so
   the reply that just ended keeps its outcome and Turn details until the owner answers. "Write
   to <Agent>" from the search sheet or the Dossier becomes the same question while a reply is
   being written (App's writeTo).

   Who keeps the question: App, when it passes `pending` (its RecipientSwitch's id, or null), so
   the question outlives the composer — leaving Home and coming back shows it again — and App
   drops it when the recipient moves some other way, when a roster the hub served no longer offers
   the agent asked for, and at the demo boundary. Drawn without App (`pending` absent, as tests
   do), the picker keeps its own and drops it on the same events. Either way `onPendingChange` is
   told the id asked for, and null once the question is answered or dropped.

   A poll the hub did not serve (GET /api/agents failed, so the roster's rows are not the hub's)
   says nothing about the agent asked for, so it drops nothing: the question stays and Send stays
   held, but its switch cannot be made (App would refuse an agent no served roster offers), so that
   one button waits, saying why, until a served roster offers the agent (`switchStanding` 'held').
   The other answer is always open: the owner can keep the recipient they have.

   Without `onSelectAgent` (a composer drawn on its own), or with no agent to choose, the
   recipient is shown, not chosen here. When the hub did not serve the roster and there is no
   recipient, the To still offers Jarvis — App's own default, which needs no roster — so "choose
   who to write to" is something the owner can do. The same holds while App keeps a selected agent
   it cannot confirm (`unconfirmed`: a poll completed without a served roster): the To names that
   agent "not confirmed" and offers Jarvis; nothing switches by itself. A native select: keyboard-
   and screen-reader-complete as it stands, and its label is the visible "To". */
import React, { useEffect, useId, useRef, useState } from 'react';
import { selectableChatAgents, type ChatAgent } from '../../chat-routing-policy';
import { fmt } from '../../frame/strings';
import { policyWord, talkStrings } from './strings';
import type { RecipientHold, RecipientRefusal } from './types';

const named = (agent: ChatAgent | undefined): string | null =>
  agent && typeof agent.name === 'string' && agent.name.trim() ? agent.name.trim() : null;

/** An agent's name: the hub's roster's; else `known`, the last name the hub's roster gave it (an
 *  agent that left the roster, or one named while the roster is not served, is named as the owner
 *  knew it, not by a /status or seed row); else such a row's name; else its id, capitalised. */
export function agentDisplayName(id: string, agents: readonly ChatAgent[] = [], known?: string | null): string {
  const found = agents.find((a) => a && a.id === id);
  if (found && found.rosterSource === 'api' && named(found)) return named(found) as string;
  if (typeof known === 'string' && known.trim()) return known.trim();
  if (named(found)) return named(found) as string;
  return id ? id.charAt(0).toUpperCase() + id.slice(1) : '';
}

/** Whether the hub served the agent roster (rows from GET /api/agents, `rosterSource: 'api'`).
 *  Without it an agent's declared routing policy is not known — which is not "unavailable" — and
 *  only Jarvis, App's default, can be chosen. */
export function rosterServed(agents: readonly ChatAgent[]): boolean {
  return agents.some((a) => !!a && a.rosterSource === 'api');
}

/** Whether App takes `id` as the recipient now (selectChatAgent's rule; App reads it from here): an
 *  agent the hub's roster offers; without a served roster, Jarvis alone — App's own default, which
 *  needs none (runTurn and submit take it so). In the demo sample, anyone. */
export function recipientChoosable(id: string, agents: readonly ChatAgent[], demo: boolean): boolean {
  return demo || selectableChatAgents(agents as ChatAgent[], false).some((a) => a.id === id)
    || (id === 'jarvis' && !rosterServed(agents));
}

/** Where a change of recipient to `id` stands with the roster as it is now:
 *    open  it can be made
 *    held  the hub did not serve the roster (a failed poll proves nothing about the agent), so it
 *          cannot be made until a served roster offers the agent: the question stays, and Send with it
 *    gone  a roster the hub served no longer offers the agent: the question is dropped */
export function switchStanding(id: string, agents: readonly ChatAgent[], demo: boolean): 'open' | 'held' | 'gone' {
  if (recipientChoosable(id, agents, demo)) return 'open';
  return rosterServed(agents) ? 'gone' : 'held';
}

/** The composer's line for a recipient App dropped (types.ts RecipientRefusal): what happened, and
 *  that nothing is sent until the owner chooses again. Null when there is nothing specific to say. */
export function recipientRefusalText(refusal: RecipientRefusal | null | undefined, agents: readonly ChatAgent[], lang: string): string | null {
  if (!refusal) return null;
  const s = talkStrings(lang);
  switch (refusal.reason) {
    case 'unavailable': return refusal.agent ? fmt(s.recipientUnavailable, { agent: agentDisplayName(refusal.agent, agents, refusal.name) }) : null;
    case 'signin': return s.recipientSignIn;
    case 'conversation': return s.recipientConversation;
    case 'unverified': return s.recipientUnverified;
    default: return null;
  }
}

export interface RecipientPickerProps {
  agent: string;
  agents: readonly ChatAgent[];
  demo: boolean;
  recipientStatus: 'ready' | 'checking' | 'choose';
  /** App's selectChatAgent. Absent: the recipient is shown, not chosen here. */
  onSelectAgent?: (id: string) => void;
  /** A reply is being written: changing the recipient would stop it. */
  inFlight: boolean;
  lang: string;
  /** The change the question waits on, when App keeps the question (null: none is open). Absent:
   *  the picker keeps its own. */
  pending?: string | null;
  /** Told the id asked for when a change must wait, and null once it is answered or dropped. */
  onPendingChange?: (id: string | null) => void;
  /** The id the question's sentence takes, so Send can point at it while it holds. */
  whyId?: string;
  /** Called after a choice that turns the To back into plain words (Jarvis chosen while the roster
   *  was not served): the select goes, and the composer takes the focus instead of the page. */
  onChosen?: () => void;
  /** The last name the hub's roster gave the agent the question asks about (App's RecipientSwitch
   *  `name`): while the roster is not served, the question names the agent as the owner knew it. */
  pendingName?: string;
  /** The selected agent App keeps but cannot confirm (TalkInput.recipientHold), while `recipientStatus`
   *  is 'checking': the To names it "not confirmed" and offers Jarvis. */
  unconfirmed?: RecipientHold | null;
  /** Drawn without App: told the id of its own question when a roster the hub served no longer offers
   *  that agent and the question is dropped, so the composer can say why. */
  onDropped?: (id: string) => void;
}

export function RecipientPicker({ agent, agents, demo, recipientStatus, onSelectAgent, inFlight, lang, pending, onPendingChange, whyId, onChosen, pendingName, unconfirmed = null, onDropped }: RecipientPickerProps) {
  const s = talkStrings(lang);
  const id = useId();
  const warnId = useId();
  const heldId = useId();
  const hold = recipientStatus === 'checking' && !demo ? unconfirmed : null;
  // The hub did not serve the roster and no recipient is chosen, or the one selected cannot be
  // confirmed: Jarvis can still be chosen (App's default, which needs no roster).
  const fallback = !demo && !rosterServed(agents) && (recipientStatus === 'choose' || !!hold);
  const choices: ChatAgent[] = fallback ? [{ id: 'jarvis', name: agentDisplayName('jarvis', agents) }] : selectableChatAgents(agents as ChatAgent[], demo);
  const kept = pending !== undefined;
  const [own, setOwn] = useState<string | null>(null);
  const asked = kept ? pending : own;
  const told = useRef(onPendingChange);
  told.current = onPendingChange;
  const dropped = useRef(onDropped);
  dropped.current = onDropped;
  const ask = (next: string | null) => {
    if (!kept) setOwn(next);
    told.current?.(next);
  };
  // the picker's own question belongs to the recipient it would replace, and to its side of the
  // demo boundary (App drops a question it keeps on the same events, and more)
  useEffect(() => {
    if (kept) return;
    setOwn(null);
    told.current?.(null);
  }, [agent, demo, kept]);
  // Where the change asked for stands with this roster (switchStanding): a roster the hub served
  // that no longer offers the agent drops the question (App drops the one it keeps in the same
  // frame); a poll the hub did not serve drops nothing, and only holds the switch.
  const standing = asked ? switchStanding(asked, agents, demo) : null;
  const open = standing === 'gone' ? null : asked;
  const held = standing === 'held';
  useEffect(() => {
    if (kept || standing !== 'gone' || !own) return;
    const gone = own;
    setOwn(null);
    told.current?.(null);
    dropped.current?.(gone);
  }, [kept, standing, own]);
  // the recipient: the agent App holds, or the one it keeps without being able to confirm it
  const current = hold ? agentDisplayName(hold.agent, agents, hold.name) : agentDisplayName(agent, agents);
  const known = choices.some((a) => a.id === agent);
  const label = (a: ChatAgent) => `${agentDisplayName(a.id, agents)} · ${policyWord(a.chat_routing, s)}`;
  // what the To shows when the recipient is not one of its choices
  const placeholder = hold ? fmt(s.toUnconfirmed, { agent: current }) : recipientStatus === 'choose' || !agent ? s.toChoose : current;

  const choose = (next: string) => {
    if (!next || !onSelectAgent) return;
    // the recipient already chosen: nothing to change, and an open question is answered "stay"
    if (next === agent) { if (asked) ask(null); return; }
    if (inFlight) { ask(next); return; }
    if (asked) ask(null);
    onSelectAgent(next);
    if (fallback) onChosen?.();
  };
  const answer = (take: boolean) => {
    const next = open;
    // held: the switch waits for a served roster that offers the agent, and the question with it
    if (take && held) return;
    ask(null);
    if (take && next && onSelectAgent) onSelectAgent(next);
  };

  // named as the hub's roster named it: while the roster is not served, by the last name it gave
  // (App's question carries it), never by a /status or seed row
  const askedName = open ? agentDisplayName(open, agents, kept ? pendingName : undefined) : '';
  // While the reply is being written the question says the change would stop it; once that reply
  // has ended it asks without that clause, and nothing has switched meanwhile.
  const sentence = inFlight ? fmt(s.switchWarn, { agent: askedName })
    : fmt(current ? s.switchEnded : s.switchEndedNone, { agent: askedName, current });
  const take = fmt(inFlight ? s.switchConfirm : s.writeTo, { agent: askedName });
  const keep = current ? fmt(inFlight ? s.switchCancel : s.switchStay, { current })
    : inFlight ? s.switchCancelNone : s.switchStayNone;
  const warning = open && onSelectAgent ? (
    /* on its own line under the head: the picker asks before it changes who the owner writes to;
       while the hub does not serve the roster, the switch waits and the words after the sentence
       say why (the switch's description), and "stay" is still taken. The two answers wrap as one. */
    <div className="n-composer__switch" id={warnId} role="alert" data-recipient-switch={open}
      data-recipient-switch-state={inFlight ? 'writing' : 'ended'} data-recipient-switch-held={held ? '' : undefined}>
      <span id={whyId}>{sentence}</span>
      {held && <span className="n-composer__held" id={heldId}>{fmt(s.switchHeld, { agent: askedName })}</span>}
      <span className="n-composer__answers">
        <button type="button" className="n-btn n-btn--sm n-btn--quiet" disabled={held}
          aria-describedby={held ? heldId : undefined} onClick={() => answer(true)}>{take}</button>
        <button type="button" className="n-btn n-btn--sm n-btn--bare" onClick={() => answer(false)}>{keep}</button>
      </span>
    </div>
  ) : null;

  if (!onSelectAgent || !choices.length) {
    const selected = (agents as ChatAgent[]).find((a) => a.id === agent);
    const policy = demo ? s.policyDemo : hold ? s.unconfirmed
      : selected && selected.rosterSource === 'api' ? policyWord(selected.chat_routing, s) : null;
    return (
      <>
        <span className="n-composer__to" data-recipient={hold ? hold.agent : agent || ''}>
          <span className="n-composer__k">{s.to}</span>
          <b className="n-composer__name">{hold ? current : recipientStatus === 'choose' || !agent ? s.toChoose : current}</b>
          {policy && <span className="n-composer__policy" title={hold ? s.policyNotServed : s.policyTitle}> · {policy}</span>}
        </span>
        {warning}
      </>
    );
  }

  return (
    <>
      <span className="n-composer__to" data-recipient={hold ? hold.agent : agent || ''}>
        <label className="n-composer__k" htmlFor={id}>{s.to}</label>
        <span className="n-composer__pick">
          <select id={id} className="n-composer__select" value={known ? agent : ''} title={fallback ? s.policyNotServed : s.policyTitle}
            data-recipient-choices={fallback ? 'not-served' : undefined} data-recipient-unconfirmed={hold ? hold.agent : undefined}
            aria-describedby={open ? warnId : undefined} onChange={(event) => choose(event.target.value)}>
            {!known && <option value="" disabled>{placeholder}</option>}
            {choices.map((a) => <option key={a.id} value={a.id}>{label(a)}</option>)}
          </select>
          <svg className="n-composer__chev" viewBox="0 0 16 16" aria-hidden="true" focusable="false"><path d="M3.5 6l4.5 4.5L12.5 6" /></svg>
        </span>
      </span>
      {warning}
    </>
  );
}
