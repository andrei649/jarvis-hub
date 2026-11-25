/* The decision client (PHASE_B_PLAN.md §5.4, §2.2): the ONLY module that posts to
   /autonomy/tasks/*. The docket and the Decision Inbox both decide through it, so a decision is
   sent one way, with one body, whichever surface sends it; decisions-source.test.ts fails if any
   other source file names a /autonomy/tasks/ path.

     decide(id, action, {payload, reason})   POST /autonomy/tasks/{id}/decision
                                             {action, payload? (edit only), reason?}
     rejectGroup(group, reason)              POST /autonomy/tasks/groups/{group.id}/reject
                                             {snapshot, member_ids, reason?} exactly as the feed
                                             sent the group
     decideConsent(id, {choice, revision})   POST /autonomy/tasks/{id}/consent
                                             {choice, revision, reason?}
     rejectEach(ids, {reason})               a reject per request, one after the other, with the
                                             refusals reported (the docket's "Reject all N")
     preview(id)                             GET /api/autonomy/tasks/{id}/preview (read only)
     listBlocked()                           GET the decisions feed once

   Rules it keeps whoever calls it:
     - nothing is posted while the demo sample is on (?demo=1): demo ids are not the hub's, and
       a demo id that matched a real task must never decide it;
     - a call it cannot send as asked (an id that is not a task id, an edit without a JSON object,
       a reason longer than the hub's 280 characters) throws before anything is posted;
     - after every decision the shared decisions feed is read again (refreshPolled), and the
       promise resolves only once that answer has landed — no optimistic removal anywhere. Only
       a feed someone reads through the shared poller is read again (the docket, the masthead's
       count): where nothing does (a panel drawn on its own), a Decision Inbox decision posts and
       does not wait for an extra read (the inbox reloads its own list);
     - a refusal comes back as the hub's own words (`error`, `reason` or `detail` of the body,
       read as panel-kit's refusalReason reads them), or null when the hub gave none; the caller
       words "no answer" itself. */
import { apiGet, apiPost } from './client';
import { readDemoMode } from '../demo-mode';
import { EMPTY_SNAPSHOT, pollSnapshot, refreshPolled } from '../signals/poll';
import { DOCKET_FEED_PATH, type DocketGroup } from '../docket/types';

export type DecisionAction = 'accept' | 'reject' | 'defer' | 'edit';
export const DECISION_ACTIONS: readonly DecisionAction[] = ['accept', 'reject', 'defer', 'edit'];
export type ConsentChoice = 'session' | 'always' | 'deny';
/** The hub's limit on a decision reason (routers/autonomy.py AutonomyDecisionBody). */
export const REASON_MAX = 280;

/** What a decision came to. `ok`: the hub took it (`body` is its answer). Otherwise `reason` is
 *  the hub's own words for the refusal, or null when it gave none; `status` is null when no
 *  answer arrived; `demo` marks a decision not sent because the demo sample is on. */
export interface DecisionOutcome {
  readonly ok: boolean;
  readonly body?: unknown;
  readonly status: number | null;
  readonly reason: string | null;
  readonly demo?: true;
}

export const DEMO_REFUSAL: DecisionOutcome = Object.freeze({ ok: false, status: null, reason: null, demo: true as const });

const isTaskId = (v: unknown): v is number => typeof v === 'number' && Number.isSafeInteger(v) && v > 0;
const isPlainObject = (v: unknown): v is Record<string, unknown> =>
  !!v && typeof v === 'object' && !Array.isArray(v) && Object.getPrototypeOf(v) === Object.prototype;

/** True while the demo sample is on (the URL's ?demo=1, which App's demo state follows). */
export function demoActive(): boolean {
  try { return typeof window !== 'undefined' && readDemoMode(window.location.search); } catch { return false; }
}

/** A reason as sent: trimmed, left out when blank; longer than the hub takes is a caller's bug. */
function cleanReason(reason: string | null | undefined): string | null {
  if (reason === null || reason === undefined) return null;
  if (typeof reason !== 'string') throw new TypeError('a decision reason is text');
  const trimmed = reason.trim();
  if (!trimmed) return null;
  if (trimmed.length > REASON_MAX) throw new TypeError(`a decision reason is at most ${REASON_MAX} characters`);
  return trimmed;
}

/** The hub's own words for a refusal, or null: the body's `error` or `reason` (the queue's and
 *  the routers' refusals), else its `detail` (FastAPI's; a validation list is kept as JSON rather
 *  than dropped). The three dialects panel-kit's refusalReason reads, without its fallbacks — and
 *  never the error's message, which only restates the request line. */
export function hubWords(err: unknown): string | null {
  const body = (err as { body?: unknown } | null | undefined)?.body;
  if (!body || typeof body !== 'object') return null;
  const fields = body as Record<string, unknown>;
  for (const key of ['error', 'reason'] as const) {
    const value = fields[key];
    if (typeof value === 'string' && value.trim()) return value.trim();
  }
  const detail = fields.detail;
  if (typeof detail === 'string' && detail.trim()) return detail.trim();
  if (detail !== null && detail !== undefined) {
    try { return JSON.stringify(detail); } catch { /* unreadable: no words */ }
  }
  return null;
}

async function post(path: string, body: Record<string, unknown>): Promise<DecisionOutcome> {
  try {
    const answer = await apiPost<unknown>(path, body, { admin: true });
    return { ok: true, body: answer, status: null, reason: null };
  } catch (err) {
    const status = typeof (err as { status?: unknown })?.status === 'number' ? (err as { status: number }).status : null;
    return { ok: false, status: status || null, reason: hubWords(err) };
  }
}

/** Read the shared decisions feed again; resolves when that answer has landed (or failed). A feed
 *  nobody has read through the shared poller (a panel drawn on its own) is not read: there is
 *  nothing to bring up to date. */
export function refreshDecisions(): Promise<void> {
  if (pollSnapshot(DOCKET_FEED_PATH, { admin: true }) === EMPTY_SNAPSHOT) return Promise.resolve();
  return refreshPolled(DOCKET_FEED_PATH, { admin: true }).catch(() => undefined);
}

/** Accept, reject, defer or edit one request. */
export async function decide(taskId: number, action: DecisionAction,
  opts: { payload?: Record<string, unknown>; reason?: string | null } = {}): Promise<DecisionOutcome> {
  if (!isTaskId(taskId)) throw new TypeError('decide: a task id is a positive integer');
  if (!DECISION_ACTIONS.includes(action)) throw new TypeError(`decide: unknown action ${String(action)}`);
  if (action === 'edit' && !isPlainObject(opts.payload)) throw new TypeError('decide: an edit sends the edited payload, a JSON object');
  if (action !== 'edit' && opts.payload !== undefined) throw new TypeError('decide: only an edit carries a payload');
  const reason = cleanReason(opts.reason);
  if (demoActive()) return DEMO_REFUSAL;
  const body: Record<string, unknown> = { action };
  if (action === 'edit') body.payload = opts.payload;
  if (reason) body.reason = reason;
  const outcome = await post(`/autonomy/tasks/${taskId}/decision`, body);
  await refreshDecisions();
  return outcome;
}

/** Reject a whole hub group, sending back its snapshot and members exactly as the feed sent
 *  them; the hub refuses a changed group (409 "approval group changed"). */
export async function rejectGroup(group: DocketGroup, reason?: string | null): Promise<DecisionOutcome> {
  if (!group || typeof group.id !== 'string' || !group.id) throw new TypeError('rejectGroup: a hub group has an id');
  if (typeof group.snapshot !== 'string' || !group.snapshot) throw new TypeError('rejectGroup: a hub group has a snapshot');
  const members = group.member_ids;
  if (!Array.isArray(members) || members.length < 2 || !members.every(isTaskId)) {
    throw new TypeError('rejectGroup: a hub group has at least two member ids');
  }
  const why = cleanReason(reason);
  if (demoActive()) return DEMO_REFUSAL;
  const body: Record<string, unknown> = { snapshot: group.snapshot, member_ids: [...members] };
  if (why) body.reason = why;
  const outcome = await post(`/autonomy/tasks/groups/${encodeURIComponent(group.id)}/reject`, body);
  await refreshDecisions();
  return outcome;
}

/** Answer a reusable terminal consent offer with the exact revision it was shown at. */
export async function decideConsent(taskId: number,
  opts: { choice: ConsentChoice; revision: string; reason?: string | null }): Promise<DecisionOutcome> {
  if (!isTaskId(taskId)) throw new TypeError('decideConsent: a task id is a positive integer');
  if (!['session', 'always', 'deny'].includes(opts.choice)) throw new TypeError('decideConsent: choice is session, always or deny');
  if (typeof opts.revision !== 'string' || !/^[a-f0-9]{64}$/.test(opts.revision)) throw new TypeError('decideConsent: the offer revision is 64 hex characters');
  const reason = cleanReason(opts.reason);
  if (demoActive()) return DEMO_REFUSAL;
  const body: Record<string, unknown> = { choice: opts.choice, revision: opts.revision };
  if (reason) body.reason = reason;
  const outcome = await post(`/autonomy/tasks/${taskId}/consent`, body);
  await refreshDecisions();
  return outcome;
}

/** What rejecting several requests came to: the ones rejected, and each refusal. */
export interface EachOutcome {
  readonly rejected: readonly number[];
  readonly refused: readonly { readonly id: number; readonly status: number | null; readonly reason: string | null }[];
  readonly demo?: true;
}

/** Reject each request in turn (a display collapse of identical requests has no hub group to
 *  reject at once); every request is tried, and the feed is read again once at the end. */
export async function rejectEach(taskIds: readonly number[], opts: { reason?: string | null } = {}): Promise<EachOutcome> {
  if (!Array.isArray(taskIds) || !taskIds.length || !taskIds.every(isTaskId)) throw new TypeError('rejectEach: task ids are positive integers');
  const reason = cleanReason(opts.reason);
  if (demoActive()) return { rejected: [], refused: [], demo: true };
  const rejected: number[] = [];
  const refused: { id: number; status: number | null; reason: string | null }[] = [];
  for (const id of taskIds) {
    const body: Record<string, unknown> = { action: 'reject' };
    if (reason) body.reason = reason;
    const outcome = await post(`/autonomy/tasks/${id}/decision`, body);
    if (outcome.ok) rejected.push(id);
    else refused.push({ id, status: outcome.status, reason: outcome.reason });
  }
  await refreshDecisions();
  return { rejected, refused };
}

/** The dry run of one request (read only). Throws as apiGet does when it is refused or fails. */
export function preview(taskId: number): Promise<unknown> {
  if (!isTaskId(taskId)) return Promise.reject(new TypeError('preview: a task id is a positive integer'));
  return apiGet<unknown>(`/api/autonomy/tasks/${taskId}/preview`, { admin: true });
}

/** The decisions feed, read once (the docket itself reads it through the shared poller). */
export function listBlocked(): Promise<unknown> {
  return apiGet<unknown>(DOCKET_FEED_PATH, { admin: true });
}
