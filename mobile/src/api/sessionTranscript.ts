/** The only fields allowed in a retained-history preview or local export. */
export type SessionTranscript = {
  schema_version: 1;
  session_id: string;
  scope: 'retained_current_history';
  redacted: true;
  turn_count: number;
  turns: {
    turn?: number;
    role: 'user' | 'assistant';
    content: string;
    agent_id: string | null;
    timestamp: string;
    reference_revision?: string;
  }[];
};

export function validTranscriptSessionId(value: unknown): value is string {
  return typeof value === 'string' && /^[A-Za-z0-9_-]{1,128}$/.test(value);
}

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/** Strict known-field validation, followed by a fresh whitelist projection. */
export function projectSessionTranscript(raw: unknown, sessionId: string, references = false): SessionTranscript {
  const invalid = () => new Error('Invalid retained session transcript received from the hub');
  if (!validTranscriptSessionId(sessionId) || !record(raw) || raw.schema_version !== 1
    || raw.session_id !== sessionId || raw.scope !== 'retained_current_history' || raw.redacted !== true
    || !Array.isArray(raw.turns) || raw.turns.length > 100
    || !Number.isSafeInteger(raw.turn_count) || raw.turn_count !== raw.turns.length) throw invalid();
  const ordinals = new Set<number>();
  const turns = raw.turns.map((turn): SessionTranscript['turns'][number] => {
    if (!record(turn) || (turn.role !== 'user' && turn.role !== 'assistant')
      || typeof turn.content !== 'string' || typeof turn.timestamp !== 'string'
      || !(turn.agent_id === null || typeof turn.agent_id === 'string')) throw invalid();
    if (turn.turn !== undefined) {
      if (!Number.isSafeInteger(turn.turn) || (turn.turn as number) < 0 || ordinals.has(turn.turn as number)) throw invalid();
      ordinals.add(turn.turn as number);
    }
    if (turn.content.length > 2 * 1024 * 1024 || turn.timestamp.length > 2 * 1024 * 1024
      || (turn.agent_id !== null && turn.agent_id.length > 2 * 1024 * 1024)) throw invalid();
    return { ...(turn.turn !== undefined ? { turn: turn.turn as number } : {}),
      ...(references && typeof turn.reference_revision === 'string' && /^[0-9a-f]{64}$/.test(turn.reference_revision)
        ? { reference_revision: turn.reference_revision } : {}),
      role: turn.role, content: turn.content, agent_id: turn.agent_id, timestamp: turn.timestamp };
  });
  if (ordinals.size !== 0 && ordinals.size !== turns.length) throw invalid();
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

export type SessionMessageHit = {
  session_id: string;
  turn: number;
  role: 'user' | 'assistant';
  timestamp: string | null;
  agent_id: string | null;
  snippet: string;
};

export type SessionMessageSearch = {
  hits: SessionMessageHit[];
  truncated: boolean;
  stopped_by: string | null;
};

export type HistoryReference = {
  session_id: string; turn: number; revision: string; excerpt: string; allow_cloud: boolean;
};
export type HistorySourceReceipt = {
  session_id: string; turn: number; revision: string; role: 'user' | 'assistant';
};
export type HistorySelection = { reference: HistoryReference; role: 'user' | 'assistant' };

export function historyRequiresCloudConsent(agent: string): boolean {
  return !['frigga', 'ultron', 'howard'].includes(agent);
}

export function historySourceReceipt(value: unknown): HistorySourceReceipt | null {
  if (!record(value) || !validTranscriptSessionId(value.session_id)
    || !Number.isSafeInteger(value.turn) || (value.turn as number) < 0
    || typeof value.revision !== 'string' || !/^[0-9a-f]{64}$/.test(value.revision)
    || (value.role !== 'user' && value.role !== 'assistant')) return null;
  return { session_id: value.session_id, turn: value.turn as number,
    revision: value.revision, role: value.role };
}

export function validHistoryReference(value: unknown): value is HistoryReference {
  if (!record(value) || !historySourceReceipt({ ...value, role: 'user' })
    || typeof value.excerpt !== 'string' || !value.excerpt.length
    || typeof value.allow_cloud !== 'boolean') return false;
  let bytes = 0;
  for (let index = 0; index < value.excerpt.length; index++) {
    const code = value.excerpt.charCodeAt(index);
    if (code < 0x80) bytes++;
    else if (code < 0x800) bytes += 2;
    else if (code >= 0xd800 && code <= 0xdbff && index + 1 < value.excerpt.length
      && value.excerpt.charCodeAt(index + 1) >= 0xdc00 && value.excerpt.charCodeAt(index + 1) <= 0xdfff) {
      bytes += 4; index++;
    } else bytes += 3;
    if (bytes > 8000) return false;
  }
  return true;
}

/** A search hit is only a pointer; review the current redacted source before using it. */
export function verifiedSessionTurn(
  transcript: SessionTranscript, hit: SessionMessageHit, references = false,
): SessionTranscript['turns'][number] | null {
  try {
    const current = projectSessionTranscript(transcript, hit.session_id, references);
    const turn = current.turns.find(row => row.turn === hit.turn);
    const snippet = hit.snippet.replace(/^…/, '').replace(/…$/, '');
    return turn && turn.role === hit.role && turn.timestamp === hit.timestamp
      && turn.agent_id === hit.agent_id && !!snippet && turn.content.includes(snippet) ? turn : null;
  } catch {
    return null;
  }
}
