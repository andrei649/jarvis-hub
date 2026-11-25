/* The approval mode that applies to the composer's recipient (PHASE_B_PLAN.md §5.3, "Mode").

   GET /autonomy/mode is the global dial only, and an agent may have its own override
   (autonomy.agent_modes): agents/core/autonomy/mode.py resolve() — the agent's own mode when it
   has one, else the global mode, except that a global Off is a floor no override loosens. So the
   global dial beside a recipient could say "anything with a side effect waits for you" while that
   agent runs on Auto. The composer therefore reads GET /autonomy/policy (admin, the same 60 s
   cadence as the approval mode; it carries the global mode and every override) and resolves the
   recipient's mode the way the hub does.

   The global reading (useApprovalMode, the running head's request, shared) still serves twice:
   a global Off is shown at once, being the floor for everyone; and when the owner changes the
   global mode, the policy is read again rather than up to a minute later. Without a policy
   reading and with a global Auto or Ask, the recipient's mode is not known, and is not guessed. */
import { useEffect, useRef } from 'react';
import { useApprovalMode } from '../../signals/hooks';
import { usePolled } from '../../signals/poll';
import type { Reading } from '../../signals/types';
import type { ApprovalModeReading, ApprovalModeValue } from '../../signals/wire';
import type { ApprovalModeInput } from './ComposerMode';

export const MODE_POLICY_PATH = '/autonomy/policy';
const S60 = 60_000;

/** GET /autonomy/policy: the global mode and each agent's own override. */
export interface ModePolicy {
  readonly global: ApprovalModeValue;
  readonly agents: ReadonlyMap<string, ApprovalModeValue>;
}

const isMode = (value: unknown): value is ApprovalModeValue => value === 'auto' || value === 'ask' || value === 'off';

/** Only the three exact words count, for the global mode and for every override (the hub reads
 *  each through read_mode, so anything else is a malformed answer, not a mode to guess at). */
export function parseModePolicy(raw: unknown): ModePolicy {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) throw new Error('approval policy');
  const r = raw as Record<string, unknown>;
  if (!isMode(r.global)) throw new Error('unknown global approval mode');
  const agents = new Map<string, ApprovalModeValue>();
  if (r.agents !== undefined && r.agents !== null) {
    if (typeof r.agents !== 'object' || Array.isArray(r.agents)) throw new Error('agent approval modes');
    for (const [id, mode] of Object.entries(r.agents as Record<string, unknown>)) {
      if (!isMode(mode)) throw new Error('unknown agent approval mode');
      agents.set(id, mode);
    }
  }
  return { global: r.global, agents };
}

const SHOWN = new Set(['live', 'stale', 'offline']);

/** The recipient's mode from the policy reading (and the global one for its floor), as the hub
 *  resolves it: the agent's own override, else the global mode; a global Off for everyone. */
export function recipientMode(policy: Reading<ModePolicy>, global: Reading<ApprovalModeReading>, agent: string): ApprovalModeInput {
  if (policy.value && SHOWN.has(policy.state)) {
    const overall = policy.value.global;
    const own = overall === 'off' ? undefined : policy.value.agents.get(agent);
    return { ...policy, value: { mode: own ?? overall, source: own ? 'agent' : 'global' } };
  }
  if (global.value && global.value.mode === 'off' && SHOWN.has(global.state)) {
    return { ...global, value: { mode: 'off', source: 'global' } };
  }
  return { ...policy, value: null };
}

/** The composer's "Mode" for `agent` (TalkRegister). */
export function useRecipientMode(agent: string, opts: { demo?: boolean } = {}): ApprovalModeInput {
  const global = useApprovalMode({ demo: opts.demo });
  const policy = usePolled<ModePolicy>(MODE_POLICY_PATH, { admin: true, intervalMs: S60, parse: parseModePolicy, demo: opts.demo });
  // The owner changed the global mode (the running head): read the overrides again now.
  const word = global.value?.mode;
  const last = useRef(word);
  const refresh = policy.refresh;
  useEffect(() => {
    if (word && last.current && word !== last.current) void refresh();
    if (word) last.current = word;
  }, [word, refresh]);
  return recipientMode(policy, global, agent);
}
