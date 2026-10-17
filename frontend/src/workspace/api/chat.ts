/* Assistant conversations (spec §7–§8, S3 routers/workspace_chat.py).

   A question is answered over server-sent events: the stream is opened with the CSRF header
   through streamSse, and a refusal before the first event (`409 conversation_busy`,
   `429 rate_limited`) rejects with the server's code like any JSON call. */
import { appUrl } from '../../base-path';
import { api, query } from './client';
import { unwrapOne } from './shape';
import { streamSse, type SseEvent } from './sse';
import type {
  ChatMessage, Conversation, ConversationDetail, ConversationsResponse, ConversationSummary, FeedbackRequest,
} from './types';

export async function listConversations(departmentId: number): Promise<ConversationSummary[]> {
  const data = await api.get<ConversationsResponse>(appUrl(`/api/workspace/conversations${query({ department_id: departmentId })}`));
  return data?.conversations ?? [];
}

export const createConversation = async (departmentId: number): Promise<Conversation> =>
  unwrapOne<Conversation>(await api.post(appUrl('/api/workspace/conversations'), { department_id: departmentId }), ['conversation']);

export const getConversation = (id: number) => api.get<ConversationDetail>(appUrl(`/api/workspace/conversations/${id}`));

export const renameConversation = async (id: number, title: string): Promise<Conversation> =>
  unwrapOne<Conversation>(await api.patch(appUrl(`/api/workspace/conversations/${id}`), { title }), ['conversation']);

export const deleteConversation = (id: number) => api.del(appUrl(`/api/workspace/conversations/${id}`));

/** Asks a question; yields the named events of spec §8 until `done` or `error`. */
export function streamAnswer(conversationId: number, content: string, signal: AbortSignal): AsyncGenerator<SseEvent> {
  return streamSse(appUrl(`/api/workspace/conversations/${conversationId}/messages`), { json: { content }, signal });
}

export const sendFeedback = async (messageId: number, body: FeedbackRequest): Promise<ChatMessage> =>
  unwrapOne<ChatMessage>(await api.post(appUrl(`/api/workspace/messages/${messageId}/feedback`), body), ['message']);
