/* "Run now" for a report. A report runs one at a time: when a run is already queued or
   running, the server refuses with `409 run_in_progress` and names that run (`run_id`), so the
   person is taken to the run in progress instead of being shown an error for a run that is,
   in fact, happening. */
import { WorkspaceApiError } from '../../api/client';
import { runReport } from '../../api/reports';

export interface StartedRun {
  runId: number;
  /** True when the report was already running and *runId* is that run. */
  alreadyRunning: boolean;
}

export async function startRun(reportId: number): Promise<StartedRun> {
  try {
    return { runId: (await runReport(reportId)).id, alreadyRunning: false };
  } catch (err) {
    const running = err instanceof WorkspaceApiError && err.code === 'run_in_progress' ? Number(err.extra.run_id) : Number.NaN;
    if (Number.isInteger(running) && running > 0) return { runId: running, alreadyRunning: true };
    throw err;
  }
}
