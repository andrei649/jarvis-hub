export interface CloudHistoryPreview {
  session_id: string;
  agent: string;
  provider: string;
  model: string;
  revision: string;
}

export interface CloudHistorySend {
  cloudHistory: CloudHistoryPreview;
  reviewedMessage: string;
  awaitAdmission: true;
}

export function cloudHistoryPreview(value: unknown, sessionId: string, agent: string): CloudHistoryPreview | null {
  if (!value || typeof value !== 'object') return null;
  const entry = value as Record<string, unknown>;
  if (entry.session_id !== sessionId || entry.agent !== agent ||
      !['provider', 'model', 'revision'].every(key => typeof entry[key] === 'string' && !!entry[key])) return null;
  return { session_id: sessionId, agent, provider: entry.provider as string,
    model: entry.model as string, revision: entry.revision as string };
}
