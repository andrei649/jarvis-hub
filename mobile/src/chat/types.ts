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
};

/** Save-to-artifacts control states (explicit save only — never automatic). */
export type SaveState = 'saving' | 'saved' | 'saved-trunc' | 'error';
