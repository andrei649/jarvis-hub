/* H18.25 — the briefing wall's state contract, ported to native.
 *
 * `frontend/src/wall.tsx` is a canvas-composed board (neural firing field from
 * burst.tsx, stat cards, a spoken line). Native BriefingWall uses this same state
 * contract with a bounded SVG field and independently validated source evidence;
 * it does not require the browser's canvas implementation.
 *
 * `wallState` is that contract — the single word + tone the wall announces,
 * derived from voice state, agent activity, running tasks and server reachability.
 * Both implementations assert the SAME vector file
 * (`tests/_fixtures/wall_state_vectors.json`), the pattern this repo already
 * uses for the cross-language WorldView capability vectors.
 *
 * Ordering is load-bearing and mirrored exactly: an explicit voice error wins
 * over every other signal, voice states outrank background work, and "offline"
 * is only reported when nothing else is happening — so a working system is
 * never announced as offline just because a health check lagged.
 */

export type WallTone = 'live' | 'work' | 'idle' | 'bad';

export interface WallState {
  word: string;
  tone: WallTone;
}

/** Mirrors frontend/src/task-state.ts effectiveTaskState. */
function effectiveTaskState(task: any): string {
  const state = typeof task?.state === 'string' && task.state.trim() ? task.state : task?.status;
  return typeof state === 'string' ? state.trim().toLowerCase() : '';
}

/** Mirrors frontend/src/mesh.tsx isExecutingAgent. */
function isExecutingAgent(agent: any): boolean {
  const status = String(agent?.status || '').trim().toLowerCase();
  return status === 'busy' || status === 'active';
}

export function wallState(
  { voice = null, agents = [], tasks = [], serverUp = false }: any = {},
): WallState {
  const status = String((voice && voice.status) || 'off');
  if (voice && voice.error) return { word: 'voice error', tone: 'bad' };
  if (status === 'listening') return { word: 'listening', tone: 'live' };
  if (status === 'transcribing') return { word: 'thinking', tone: 'work' };
  if (status === 'speaking') return { word: 'speaking', tone: 'live' };
  const firing = (Array.isArray(agents) ? agents : []).filter(isExecutingAgent).length;
  const running = (Array.isArray(tasks) ? tasks : [])
    .filter((t: any) => effectiveTaskState(t) === 'running').length;
  if (firing || running) return { word: 'working', tone: 'work' };
  if (!serverUp) return { word: 'offline', tone: 'bad' };
  return { word: 'standing by', tone: 'idle' };
}
