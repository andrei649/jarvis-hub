import AsyncStorage from '@react-native-async-storage/async-storage';

const KEY = 'jarvis.chat.selected-outcome.v1';
const scopeOk = /^[a-z0-9-]{1,128}$/;
const sessionOk = /^[A-Za-z0-9_-]{1,128}$/;
const agentOk = /^[a-z][a-z0-9_-]{0,63}$/;
const attemptOk = /^[a-z0-9-]{8,64}$/;
type Marker = { scope: string; sessionId: string; agent: string; attempt: string };
let writes: Promise<unknown> = Promise.resolve();
const failure = () => new Error('Cannot safely track selected image submission');
function valid(scope: unknown, sessionId: unknown, agent: unknown) {
  if (typeof scope !== 'string' || !scopeOk.test(scope)
    || typeof sessionId !== 'string' || !sessionOk.test(sessionId)
    || typeof agent !== 'string' || !agentOk.test(agent)) throw failure();
}
function parse(raw: string | null): Marker[] {
  if (raw === null) return [];
  if (raw.length > 4096) throw failure();
  try {
    const data = JSON.parse(raw);
    if (data?.version !== 1 || !Array.isArray(data.rows) || data.rows.length > 8) throw failure();
    return data.rows.map((row: unknown) => {
      if (!row || typeof row !== 'object' || Array.isArray(row)) throw failure();
      const m = row as Marker;
      valid(m.scope, m.sessionId, m.agent);
      if (typeof m.attempt !== 'string' || !attemptOk.test(m.attempt)) throw failure();
      return { scope: m.scope, sessionId: m.sessionId, agent: m.agent, attempt: m.attempt };
    });
  } catch { throw failure(); }
}
const same = (a: Marker, b: Pick<Marker, 'scope' | 'sessionId' | 'agent'>) =>
  a.scope === b.scope && a.sessionId === b.sessionId && a.agent === b.agent;
async function read(): Promise<Marker[]> { return parse(await AsyncStorage.getItem(KEY)); }
function update<T>(change: (rows: Marker[]) => { rows: Marker[]; result: T }): Promise<T> {
  const next = writes.catch(() => {}).then(async () => {
    const { rows, result } = change(await read());
    const raw = JSON.stringify({ version: 1, rows });
    if (raw.length > 4096) throw failure();
    await AsyncStorage.setItem(KEY, raw);
    return result;
  }).catch(() => { throw failure(); });
  writes = next;
  return next;
}
export async function selectedOutcomeUnknown(scope: string, sessionId: string, agent: string): Promise<boolean> {
  valid(scope, sessionId, agent);
  try { await writes.catch(() => {}); return (await read()).some(row => same(row, { scope, sessionId, agent })); }
  catch { throw failure(); }
}
/** Resolve and retain attempt ID before POST. Full ledger or storage failure closes the send gate. */
export function markSelectedOutcomeUnknown(scope: string, sessionId: string, agent: string): Promise<string> {
  valid(scope, sessionId, agent);
  const marker: Marker = { scope, sessionId, agent,
    attempt: `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 14)}` };
  return update(rows => {
    if (rows.length >= 8 || rows.some(row => same(row, marker))) throw failure();
    return { rows: [...rows, marker], result: marker.attempt };
  });
}
/** Only the same submission can settle itself; an old late result cannot clear a new one. */
export function clearSelectedOutcome(scope: string, sessionId: string, agent: string, attempt: string): Promise<void> {
  valid(scope, sessionId, agent);
  if (typeof attempt !== 'string' || !attemptOk.test(attempt)) throw failure();
  return update(rows => ({ rows: rows.filter(row => !(same(row, { scope, sessionId, agent }) && row.attempt === attempt)), result: undefined }));
}
/** Explicit owner acknowledgement after History inspection. Never called from network callbacks. */
export function acknowledgeSelectedOutcome(scope: string, sessionId: string, agent: string): Promise<void> {
  valid(scope, sessionId, agent);
  return update(rows => ({ rows: rows.filter(row => !same(row, { scope, sessionId, agent })), result: undefined }));
}
