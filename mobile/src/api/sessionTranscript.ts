/** The only fields allowed in a retained-history preview or local export. */
export type SessionTranscript = {
  schema_version: 1;
  session_id: string;
  scope: 'retained_current_history';
  redacted: true;
  turn_count: number;
  turns: {
    role: 'user' | 'assistant';
    content: string;
    agent_id: string | null;
    timestamp: string;
  }[];
};

export function validTranscriptSessionId(value: unknown): value is string {
  return typeof value === 'string' && /^[A-Za-z0-9_-]{1,128}$/.test(value);
}

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/** Strict known-field validation, followed by a fresh whitelist projection. */
export function projectSessionTranscript(raw: unknown, sessionId: string): SessionTranscript {
  const invalid = () => new Error('Invalid retained session transcript received from the hub');
  if (!validTranscriptSessionId(sessionId) || !record(raw) || raw.schema_version !== 1
    || raw.session_id !== sessionId || raw.scope !== 'retained_current_history' || raw.redacted !== true
    || !Array.isArray(raw.turns) || raw.turns.length > 100
    || !Number.isSafeInteger(raw.turn_count) || raw.turn_count !== raw.turns.length) throw invalid();
  const turns = raw.turns.map((turn): SessionTranscript['turns'][number] => {
    if (!record(turn) || (turn.role !== 'user' && turn.role !== 'assistant')
      || typeof turn.content !== 'string' || typeof turn.timestamp !== 'string'
      || !(turn.agent_id === null || typeof turn.agent_id === 'string')) throw invalid();
    if (turn.content.length > 2 * 1024 * 1024 || turn.timestamp.length > 2 * 1024 * 1024
      || (turn.agent_id !== null && turn.agent_id.length > 2 * 1024 * 1024)) throw invalid();
    return { role: turn.role, content: turn.content, agent_id: turn.agent_id, timestamp: turn.timestamp };
  });
  const document: SessionTranscript = {
    schema_version: 1, session_id: sessionId, scope: 'retained_current_history',
    redacted: true, turn_count: turns.length, turns,
  };
  // Count UTF-8 bytes without depending on TextEncoder, which is absent on some native runtimes.
  const serialized = JSON.stringify(document);
  let bytes = 0;
  for (let index = 0; index < serialized.length; index++) {
    const code = serialized.charCodeAt(index);
    if (code < 0x80) bytes++;
    else if (code < 0x800) bytes += 2;
    else if (code >= 0xd800 && code <= 0xdbff) { bytes += 4; index++; }
    else bytes += 3;
    if (bytes > 2 * 1024 * 1024) throw invalid();
  }
  return document;
}
