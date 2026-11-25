/* The conversation register's contract (PHASE_B_PLAN.md §5.3, §9.2.5).

   TalkRegister (home/talk/TalkRegister.tsx) is today's Conversation and InputBar (cockpit.tsx),
   re-laid, plus the recipient picker, this tab's turns and a variant. App owns `TalkInput` —
   exactly today's props of those two components plus `onSelectAgent` — and hands it to Home and
   ChatPage as `talk`; the page adds `variant` (its own: Home is 'home', ChatPage passes its
   variant on) and `turns` (App's, given to the page once), so nothing has to be kept in step.

   The three stamps: runTurn (app.tsx) writes them on the reply bubble it reserves for a turn,
   as epoch milliseconds. A stamp is absent until its moment happens, and later frames never
   move it. The working reply reads them: Sent ✓ (asked) → Started (start) → Writing (first token),
   and "asked 10:48 · 3 min so far" from `_askedAt`. A stopped reply keeps its stamps and never
   gets `_complete`: the working reply is drawn only for a bubble whose `_turnId` is in `turns`. */
import type React from 'react';
import type { ChatAgent } from '../../chat-routing-policy';
import type { BoardResultRef } from '../../composer-board-result';
import type { PowerState } from '../../power-chip';
import type { TabTurn } from '../../signals/types';
import type { ToolCard } from '../../turn-tools';
import type { TurnOutcome } from '../../turn-outcome';
import type { WorkshopRef } from '../../workshop-projects';

/** The stamps on a reply bubble (epoch ms, set once). */
export interface ReplyStamps {
  /** The reply bubble was reserved: the owner's message is about to be sent ("asked 10:48"). */
  readonly _askedAt?: number;
  /** The first `start` frame arrived: the hub took the turn and named the agent asked. */
  readonly _startedAt?: number;
  /** The first `token` frame arrived: the reply began to be written. */
  readonly _firstTokenAt?: number;
}
export const REPLY_STAMPS = ['_askedAt', '_startedAt', '_firstTokenAt'] as const;

/** A transcript message as App keeps it. Fields exist only when set; read them defensively. */
export interface TalkMessage extends ReplyStamps {
  /** 'user' (the owner), 'agent' (a reply or a system notice: who === 'system'), 'vision'. */
  readonly role: 'user' | 'agent' | 'vision' | string;
  readonly text?: string;
  readonly who?: string;
  readonly role_label?: string;
  /** HH:MM, as App formats it. */
  readonly ts?: string;
  /** The turn a reserved reply bubble belongs to (runTurn's id). */
  readonly _turnId?: number;
  /** The `end` frame arrived. */
  readonly _complete?: boolean;
  readonly _unattributed?: boolean;
  /** Tool cards, one per call (turn-tools.tsx mergeToolEvent). */
  readonly tools?: readonly ToolCard[];
  /** The approval cards this turn queued (turn-tools.tsx approvalIds). */
  readonly approvals?: readonly number[];
  readonly toolActivity?: unknown;
  /** Measured provider/model pairs (model-call-provenance). */
  readonly prov?: { readonly models: readonly { readonly provider: string; readonly model: string }[] };
  readonly attachmentNames?: readonly string[];
  readonly imageNames?: readonly string[];
  readonly vaultNames?: readonly string[];
  readonly boardSources?: readonly unknown[];
  readonly notice?: string;
  readonly [field: string]: unknown;
}

/** App's in-flight marker: set while a turn is routing or streaming. */
export interface Thinking { readonly label: string; readonly route: readonly string[] | null }

/** App's submit(): true when the message was accepted for sending. */
export type SubmitFn = (text: string, vision?: unknown, excerpts?: readonly unknown[], directReply?: boolean, options?: unknown) => boolean | Promise<boolean>;

/** Today's Conversation props (cockpit.tsx), unchanged. */
export interface ConversationProps {
  readonly messages: readonly TalkMessage[];
  readonly thinking: Thinking | null;
  readonly onStop: () => void;
  /** Opens the provenance modal with a reply's model pairs. */
  readonly onProv: (prov: TalkMessage['prov']) => void;
  readonly onArtifactSaved?: () => void;
  readonly exportAllowed?: boolean;
  readonly messageActionsAllowed?: boolean;
  /** `${agent}:${sessionId}`: dialogs opened on a message belong to this scope. */
  readonly messageScope?: string;
  readonly lang: string;
  /** V2.I18N[lang]. */
  readonly t: Readonly<Record<string, any>>;
}

/** Today's InputBar props (cockpit.tsx), unchanged. */
export interface InputBarProps {
  readonly onSubmit: SubmitFn;
  readonly mic?: boolean;
  readonly setMic?: () => void;
  readonly voice?: unknown;
  readonly cfg?: Readonly<Record<string, string>>;
  readonly onCfg?: (patch: Readonly<Record<string, string>>) => void;
  readonly micMuted?: boolean;
  readonly motion?: string;
  readonly t: Readonly<Record<string, any>>;
  readonly lang: string;
  readonly demo?: boolean;
  readonly agent?: string;
  readonly agents?: readonly ChatAgent[];
  readonly recipientStatus?: 'ready' | 'checking' | 'choose';
  readonly sessionId?: string;
  readonly selectedTurn?: boolean;
  readonly outcome?: TurnOutcome | null;
  readonly power?: PowerState;
  readonly projectForChat?: WorkshopRef | null;
  readonly onProjectReviewed?: () => void;
  readonly boardResultForChat?: BoardResultRef | null;
  readonly onBoardResultReviewed?: () => void;
  readonly inspectBlend?: React.RefObject<((file: File) => boolean) | null>;
  readonly turnActive?: boolean;
  readonly canContinue?: () => boolean;
}

/** home: Home's conversation register · chat: /v2/chat at full width · floating: the 420 × 620
 *  desktop window (one docket line, the running head as marks, no signing). */
export type TalkVariant = 'home' | 'chat' | 'floating';

/** What App owns for the conversation and passes to Home and ChatPage as `talk`. */
export interface TalkInput extends ConversationProps, InputBarProps {
  /** App's selectChatAgent: changes who the owner writes to (it stops an in-flight reply, so the
   *  picker asks first while one is being written) and never opens the Dossier. */
  readonly onSelectAgent: (id: string) => void;
  /** Optional: the turn `outcome` belongs to (runTurn's id; null when it belongs to no reply
   *  drawn here). `outcome` is drawn only on that turn's reply, once written. Absent, the
   *  transcript takes the newest turn it has seen, which is right unless the register mounted
   *  after that turn's bubble was removed (a board or chat source the hub did not use). */
  readonly outcomeTurnId?: number | null;
  /** Optional: the change of recipient the owner asked for while a reply was being written, waiting
   *  for the owner's answer in the composer's To (PHASE_B_PLAN.md §12 item 11). App keeps it, so the
   *  question outlives the composer: leaving Home and coming back shows the same question. It is
   *  made from a pick in the To, or from "Write to <Agent>" in the search sheet or the Dossier
   *  (App's writeTo; with no reply being written that switches at once, there being nothing to
   *  stop). Send is held while it is open. Nothing switches by itself: when the reply ends the
   *  question stays, reworded without "stops the reply", and the finished reply keeps its outcome
   *  and Turn details. It goes when the owner answers, when the recipient moves some other way, when
   *  a roster the hub served no longer offers the agent asked for, and at the demo boundary. A poll
   *  the hub did not serve drops nothing: the question stays, Send with it, and only its switch
   *  waits, saying why, until a served roster offers the agent (RecipientPicker switchStanding).
   *  `null`: no question open. Absent (a composer drawn without App, as tests do): the To keeps its
   *  own question. */
  readonly recipientSwitch?: RecipientSwitch | null;
  /** The To asks (the id it would switch to) or the question is answered or dropped (null). */
  readonly onRecipientSwitch?: (id: string | null) => void;
  /** Optional: why App holds no recipient (`recipientStatus` 'choose'), so the composer says so at
   *  once instead of "Checking the selected agent…" or a bare "Choose an agent". */
  readonly recipientRefusal?: RecipientRefusal | null;
  /** Optional: the selected agent App keeps but cannot confirm because a poll has completed without
   *  the hub serving the roster (`recipientStatus` 'checking'; null or absent: still being checked,
   *  "Checking the selected agent…"). The composer says so in the hub's terms, the head names the
   *  agent "not confirmed", and the To offers Jarvis, App's default, which needs no roster. The choice
   *  is kept and confirmed once a served roster offers the agent; nothing switches by itself. */
  readonly recipientHold?: RecipientHold | null;
  /** Optional: a change of recipient App dropped because a roster the hub served no longer offers
   *  the agent asked for. The composer says so on one line until the next send, a change of
   *  recipient, or `onRecipientSwitchDropped` (Dismiss). Absent (a composer drawn without App): the
   *  composer says it of the To's own question. */
  readonly recipientSwitchDropped?: RecipientSwitchDropped | null;
  readonly onRecipientSwitchDropped?: () => void;
}

/** A change of recipient waiting for the owner's answer (App's state): to `id`, asked at `at`
 *  (epoch ms) while `from` was the recipient, on `demo`'s side of the demo boundary. `name` is the
 *  last display name the hub's roster gave `id` (RecipientRefusal's rule), so the question names the
 *  agent as the owner knew it while the roster is not served, not by a /status or seed row. */
export interface RecipientSwitch {
  readonly id: string;
  readonly from: string;
  readonly demo: boolean;
  readonly at: number;
  readonly name?: string;
}

/** The selected agent App keeps but cannot confirm (TalkInput.recipientHold): `agent`, named `name`,
 *  the last display name the hub's roster gave it (RecipientRefusal's rule). */
export interface RecipientHold {
  readonly agent: string;
  readonly name?: string;
}

/** A change of recipient App dropped (TalkInput.recipientSwitchDropped): to `id` (named `name`, as in
 *  RecipientSwitch), asked while `from` was the recipient, on `demo`'s side of the demo boundary. */
export interface RecipientSwitchDropped {
  readonly id: string;
  readonly name?: string;
  readonly from: string;
  readonly demo: boolean;
}

/** Why App dropped the recipient it had or had saved (app.tsx clearRecipient):
 *    unavailable   the agent is not one this sign-in may write to now (it left the roster, or was
 *                  disabled or retired); `agent` names it
 *    signin        the credential changed since it was chosen; the earlier choice is not named,
 *                  since it was made under another sign-in
 *    conversation  another conversation was selected: a choice belongs to its conversation
 *    unverified    the saved choice could not be checked (no digest on this connection, or the
 *                  tab was reloaded before the check was stored)
 *  Whatever the reason, nothing is sent until the owner chooses again: the message never goes to a
 *  substitute. `name` is the last display name the hub's roster gave `agent` (an agent that left the
 *  roster is named as the owner knew it, not by its id), when one is known. */
export interface RecipientRefusal {
  readonly reason: 'unavailable' | 'signin' | 'conversation' | 'unverified';
  readonly agent?: string;
  readonly name?: string;
}

export interface TalkRegisterProps extends TalkInput {
  /** Set by the page that renders the register, never by App. */
  readonly variant: TalkVariant;
  /** This tab's in-flight turns (signals/types.ts TabTurn), from the page's own `turns` prop. The
   *  working reply is drawn only for a reply whose `_turnId` is here (a stopped one is not), and
   *  its one control reads "Stop the replies" when more than one is here. */
  readonly turns: readonly TabTurn[];
  /** Optional (stage 2, E5): a mid-turn question from this tab waits for the owner's answer
   *  (App's `question` state is set). The working reply of the turn that asked then reads
   *  "Waiting for your answer": pass that turn's id (App's questionTurn); `true` names no turn,
   *  so it is drawn only while exactly one turn is in flight. Absent reads as no question. */
  readonly awaitingAnswer?: boolean | number;
}

/* What TalkRegister adds to today's two components (all optional; ConversationProps and
   InputBarProps above are unchanged):
     Conversation  variant, turns, agents, outcome, outcomeTurnId, power, awaitingAnswer
     InputBar      onSelectAgent, approvalMode, variant, openHistory, recipientSwitch,
                   onRecipientSwitch, recipientRefusal, recipientHold, recipientSwitchDropped,
                   onRecipientSwitchDropped
   `variant` reads 'home' when left out: since the stage 5 cleanup deleted ChatMode, every
   Conversation draws the Ledger turns (data-turn hooks) and every InputBar its head (To, Mode),
   leaving the turn's outcome lines to that turn's "Turn details"; the composer is a multi-line
   field and the bar Attach · Voice · Options · the `/` and `@` hints · Send. */

/** The transcript's test hooks (§1.3): data-turn on each turn, data-turn-body on its words;
 *  the composer keeps data-composer (and data-anchor="composer") and adds data-composer-bar and
 *  data-composer-send. */
export const TURN_HOOKS = ['owner', 'reply', 'system', 'vision'] as const;
export type TurnHook = typeof TURN_HOOKS[number];
