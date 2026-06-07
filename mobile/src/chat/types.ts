export type ChatMessage = {
  id: string;
  role: 'user' | 'assistant';
  text: string;
  /** assistant message still streaming */
  pending?: boolean;
};
