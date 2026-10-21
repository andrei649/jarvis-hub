/* H133 — the live status chrome: the gateway (which channels run), the active-session
   count and the hub version, read from the same `/status` poll as the LLM badge. Any field
   the poll did not answer stays unknown, so the chrome renders a dash, never a guessed 0.
   Kept apart from loaders.ts so the shell and app can import it where tests mock the loader. */
import type { StatusResp } from './types';

export type GatewayState = 'running' | 'stopped' | 'none' | 'unknown';

export interface StatusChrome {
  gateway: { state: GatewayState; running: string[]; total: number | null };
  sessions: { active: number | null; windowS: number | null };
  version: string | null;
}

export const STATUS_CHROME_UNKNOWN: StatusChrome = {
  gateway: { state: 'unknown', running: [], total: null },
  sessions: { active: null, windowS: null },
  version: null,
};

const count = (v: unknown): number | null =>
  typeof v === 'number' && Number.isInteger(v) && v >= 0 ? v : null;

export function readStatusChrome(d: unknown): StatusChrome {
  const s = (d && typeof d === 'object' ? d : {}) as StatusResp;
  const gw = (s.gateway && typeof s.gateway === 'object' ? s.gateway : {}) as NonNullable<StatusResp['gateway']>;
  const ss = (s.sessions && typeof s.sessions === 'object' ? s.sessions : {}) as NonNullable<StatusResp['sessions']>;
  const state: GatewayState = gw.state === 'running' || gw.state === 'stopped' || gw.state === 'none' ? gw.state : 'unknown';
  const running = state === 'unknown' || !Array.isArray(gw.running) ? []
    : gw.running.filter((id): id is string => typeof id === 'string' && id.length > 0);
  return {
    gateway: { state, running, total: state === 'unknown' ? null : count(gw.total) },
    sessions: { active: count(ss.active), windowS: count(ss.window_s) },
    version: typeof s.version === 'string' && s.version.trim() ? s.version.trim() : null,
  };
}
