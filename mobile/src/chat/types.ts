import type { ModelCall } from '../api/modelCallProvenance';
import type { ToolActivity, TurnRecall } from './turnOutcome';
import type { ChatNoteReceipt, ChatNoteTarget } from '../api/chatNote';
import type { HistorySourceReceipt } from '../api/sessionTranscript';

export type ChatMessage = {
  id: string;
  role: 'user' | 'assistant';
  text: string;
  /** assistant message still streaming */
  pending?: boolean;
  /** the agent that actually produced this reply (from the stream start event) */
  agent?: string;
  /** transport-error placeholder, not a real completed reply (never saveable) */
  error?: boolean;
  /** confirmed real assistant reply, eligible for owner-reviewed note saving */
  completed?: true;
  savedNote?: { target: ChatNoteTarget; receipt: ChatNoteReceipt };
  /** verified source metadata only; selected excerpt text never enters chat state */
  historySource?: HistorySourceReceipt;
  /** measured provider/model API calls attributed to this completed assistant reply */
  modelCalls?: ModelCall[];
  toolActivity?: ToolActivity;
  /** H18.36 / H430: validated per-provider recall counts for this completed assistant reply (never spoken) */
  recall?: TurnRecall[];
};

/** Save-to-artifacts control states (explicit save only — never automatic). */
export type SaveState = 'saving' | 'saved' | 'saved-trunc' | 'error';
