/** Session resurrection after the hub gives its exact terminal missing-session reply.
 * Transient and authorization errors are deliberately not recovery signals. */
export type CurrentSessionSnapshot = { session: string; turns: any[] };

export function isMissingSessionError(error: any, sessionId: string): boolean {
  return !!error && error.status === 404 &&
    error.body?.error === `session '${sessionId}' not found`;
}

function isSnapshot(value: any, oldId: string): value is CurrentSessionSnapshot {
  return !!value && typeof value.session === 'string' && value.session.length > 0 &&
    value.session !== oldId && Array.isArray(value.turns) && value.turns.every(isTurnSnapshot);
}

function isTurnSnapshot(value: any): boolean {
  if (!value || typeof value !== 'object' || Array.isArray(value) ||
      typeof value.role !== 'string' || typeof value.content !== 'string') return false;
  if (value.agent_id !== undefined && value.agent_id !== null && typeof value.agent_id !== 'string') return false;
  if (value.timestamp !== undefined && value.timestamp !== null) {
    if (typeof value.timestamp !== 'string' && typeof value.timestamp !== 'number') return false;
    if (Number.isNaN(new Date(value.timestamp || Date.now()).getTime())) return false;
  }
  return true;
}

/** One instance is shared by the app's startup rehydration and desktop poller.
 * Reads coalesce by old id; a successfully committed old id is latched so a delayed
 * poll cannot repeatedly rebind it. Callers provide a post-await freshness guard. */
export class SessionRecovery {
  private readonly reads = new Map<string, { promise: Promise<any>; isCurrent: () => boolean }>();
  private readonly healed = new Set<string>();

  constructor(
    private readonly readCurrent: () => Promise<any>,
    private readonly commit: (snapshot: CurrentSessionSnapshot) => void,
  ) {}

  isHealed(sessionId: string): boolean { return this.healed.has(sessionId); }
  allowExplicitSelection(sessionId: string): void { this.healed.delete(sessionId); }

  async recover(sessionId: string, error: unknown, isCurrent: () => boolean): Promise<boolean> {
    if (!isMissingSessionError(error, sessionId) || this.healed.has(sessionId) || !isCurrent()) return false;

    let entry = this.reads.get(sessionId);
    // A read opened under an old selection/request generation must never be reused
    // by a later A→B→A selection of the same session id.
    if (entry && !entry.isCurrent()) {
      if (this.reads.get(sessionId) === entry) this.reads.delete(sessionId);
      entry = undefined;
    }
    if (!entry) {
      // Start the fallback while the caller's pre-read freshness guard is still
      // current; JavaScript cannot interleave a selection change before this call.
      let promise: Promise<any>;
      try { promise = Promise.resolve(this.readCurrent()); }
      catch (cause) { promise = Promise.reject(cause); }
      entry = { promise, isCurrent };
      this.reads.set(sessionId, entry);
    }
    const read = entry.promise;
    let snapshot: any;
    try { snapshot = await read; }
    catch { return false; }
    finally {
      if (this.reads.get(sessionId) === entry) this.reads.delete(sessionId);
    }

    if (this.healed.has(sessionId) || !isCurrent() || !isSnapshot(snapshot, sessionId)) return false;
    try { this.commit(snapshot); }
    catch { return false; }
    this.healed.add(sessionId);
    return true;
  }
}
