import { describe, expect, it, vi } from 'vitest';
import { isMissingSessionError, SessionRecovery } from '../session-recovery';

const missing = (id: string) => ({ status: 404, body: { error: `session '${id}' not found` } });

describe('terminal session recovery', () => {
  it('accepts only the exact hub missing-session 404 for the requested id', () => {
    expect(isMissingSessionError(missing('old'), 'old')).toBe(true);
    expect(isMissingSessionError({ status: 404, body: { error: "session 'other' not found" } }, 'old')).toBe(false);
    expect(isMissingSessionError({ status: 404, body: { detail: "session 'old' not found" } }, 'old')).toBe(false);
    expect(isMissingSessionError({ status: 403, body: missing('old').body }, 'old')).toBe(false);
    expect(isMissingSessionError({ status: 503, body: missing('old').body }, 'old')).toBe(false);
    expect(isMissingSessionError(new TypeError('network down'), 'old')).toBe(false);
  });

  it('coalesces a terminal recovery and latches the healed id after one commit', async () => {
    let release!: (snapshot: unknown) => void;
    const read = vi.fn(() => new Promise(resolve => { release = resolve; }));
    const commit = vi.fn();
    const recovery = new SessionRecovery(read, commit);
    const guard = () => true;

    const a = recovery.recover('old', missing('old'), guard);
    const b = recovery.recover('old', missing('old'), guard);
    await Promise.resolve();
    expect(read).toHaveBeenCalledOnce();
    release({ session: 'current', turns: [{ role: 'assistant', content: 'current transcript' }] });
    expect(await a).toBe(true);
    expect(await b).toBe(false);
    expect(commit).toHaveBeenCalledOnce();
    expect(recovery.isHealed('old')).toBe(true);
    expect(await recovery.recover('old', missing('old'), guard)).toBe(false);
    expect(read).toHaveBeenCalledOnce();
  });

  it('does not commit if the selection became stale while reading current session', async () => {
    let release!: (snapshot: unknown) => void;
    const read = () => new Promise(resolve => { release = resolve; });
    const commit = vi.fn();
    const recovery = new SessionRecovery(read, commit);
    let current = true;
    const pending = recovery.recover('old', missing('old'), () => current);
    await Promise.resolve();
    current = false;
    release({ session: 'current', turns: [{ role: 'assistant', content: 'late' }] });
    expect(await pending).toBe(false);
    expect(commit).not.toHaveBeenCalled();
    expect(recovery.isHealed('old')).toBe(false);
  });

  it('does not reuse a fallback read from an earlier A→B→A selection cycle', async () => {
    const releases: Array<(snapshot: unknown) => void> = [];
    const read = vi.fn(() => new Promise(resolve => { releases.push(resolve); }));
    const commit = vi.fn();
    const recovery = new SessionRecovery(read, commit);
    let generation = 0;
    const first = recovery.recover('old', missing('old'), () => generation === 0);
    generation = 1;
    generation = 2; // the selected id is old again, but its request generation changed
    const second = recovery.recover('old', missing('old'), () => generation === 2);
    expect(read).toHaveBeenCalledTimes(2);
    releases[0]({ session: 'stale', turns: [{ role: 'assistant', content: 'stale read' }] });
    expect(await first).toBe(false);
    expect(commit).not.toHaveBeenCalled();
    releases[1]({ session: 'current', turns: [{ role: 'assistant', content: 'current read' }] });
    expect(await second).toBe(true);
    expect(commit).toHaveBeenCalledTimes(1);
    expect(commit).toHaveBeenCalledWith({ session: 'current', turns: [{ role: 'assistant', content: 'current read' }] });
  });

  it('rejects malformed current transcripts before committing a replacement', async () => {
    const commit = vi.fn();
    const recovery = new SessionRecovery(async () => ({ session: 'current', turns: [
      { role: 'assistant', content: {} },
    ] }), commit);
    expect(await recovery.recover('old', missing('old'), () => true)).toBe(false);
    expect(commit).not.toHaveBeenCalled();
    expect(recovery.isHealed('old')).toBe(false);
  });
});
