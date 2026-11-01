/* "Run now" for a report. A report runs one at a time: when a run is already queued or
   running, the server refuses with `409 run_in_progress` and names that run (`run_id`), so the
   person is taken to the run in progress instead of being shown an error for a run that is,
   in fact, happening. */
import { WorkspaceApiError } from '../../api/client';
import { runReport } from '../../api/reports';
import { toAppPath } from '../../router';

export interface StartedRun {
  runId: number;
  /** True when the report was already running and *runId* is that run. */
  alreadyRunning: boolean;
}

/** Keep just the current navigation's origin. An abandoned run must not be announced as new
    when someone opens its link later in the same tab. */
const ORIGIN_TTL_MS = 30_000;
const startedRuns: { id: number; expiresAt: number }[] = [];

// The mark belongs to the immediate run view. Leaving that URL before its first GET resolves
// abandons the mark, so a later direct open cannot announce an old result as newly started.
function discardOriginsForOtherRoutes() {
  const path = toAppPath(window.location.pathname);
  for (let i = startedRuns.length - 1; i >= 0; i -= 1) {
    if (path !== `/report-runs/${startedRuns[i].id}`) startedRuns.splice(i, 1);
  }
}

if (typeof window !== 'undefined') {
  window.addEventListener('nerva-workspace:navigate', discardOriginsForOtherRoutes);
  window.addEventListener('popstate', discardOriginsForOtherRoutes);
}

export function consumeStartedRun(runId: number): boolean {
  const now = Date.now();
  for (let i = startedRuns.length - 1; i >= 0; i -= 1) {
    if (startedRuns[i].expiresAt <= now) startedRuns.splice(i, 1);
  }
  const index = startedRuns.findIndex((run) => run.id === runId);
  if (index < 0) return false;
  startedRuns.splice(index, 1);
  return true;
}

export async function startRun(reportId: number): Promise<StartedRun> {
  try {
    const runId = (await runReport(reportId)).id;
    startedRuns.push({ id: runId, expiresAt: Date.now() + ORIGIN_TTL_MS });
    if (startedRuns.length > 8) startedRuns.shift();
    return { runId, alreadyRunning: false };
  } catch (err) {
    const running = err instanceof WorkspaceApiError && err.code === 'run_in_progress' ? Number(err.extra.run_id) : Number.NaN;
    if (Number.isInteger(running) && running > 0) return { runId: running, alreadyRunning: true };
    throw err;
  }
}
