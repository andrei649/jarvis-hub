/* The docket model (PHASE_B_PLAN.md §5.4): the Decision Inbox's own feed —
   GET /autonomy/tasks?status=blocked&limit=200 (admin), its tasks and its top-level groups[] —
   turned into the entries the docket draws. Pure: no React, no fetch, no words (the components
   word everything from their {en, ro} tables).

   Entries, three kinds:
     group       a hub group, validated as the inbox validates it (at least two members, `count`
                 equal to them, no repeats, the leader among them, every member in the feed) and
                 with the 32-character snapshot Reject group must send back; a group that fails
                 is no group here, its members are drawn as single requests or a collapse
     identical   a display collapse of identical requests: same kind, title, agent, tier,
                 deadline and payload (compared as canonical JSON), shown as "N identical"
     single      one request
   Groups and collapses are signed one request at a time (`taskId`, the leader); nothing signs
   them all. The special kinds (docket/special.ts) are never collapsed: each opens in Decisions.

   Order: tier descending (money and an unknown tier count as the strictest), then the soonest
   approval deadline, then the oldest, then the lowest id.

   Honesty: titles stay the hub's plain text, verbatim; every optional row (why, sub-agent,
   pushed, rollback, taint, opinion, consent, member targets) exists only when the hub sent its
   field in a readable shape — otherwise the key is absent, never a default. */
import { confirmStyle } from '../confirm';
import { tierKey, type TierKey } from '../frame/kit/marks';
import { isMoney } from './kinds';
import { phraseFor } from './phrases';
import { specialKindOf } from './special';
import type {
  ApprovalMode, DocketConsentOffer, DocketEntry, DocketGroup, DocketModel, DocketPreview, DocketSummary, DocketTask,
  DocketWhy, Friction, Verb,
} from './types';

type Rec = Record<string, unknown>;
const isRecord = (v: unknown): v is Rec => !!v && typeof v === 'object' && !Array.isArray(v);
/** A task id the hub could have issued: a positive safe integer. */
export const isTaskId = (v: unknown): v is number => typeof v === 'number' && Number.isSafeInteger(v) && v > 0;
const text = (v: unknown, max = 300): string | null => (typeof v === 'string' && v.trim() ? v.trim().slice(0, max) : null);

/** An ISO string, or an epoch in seconds or milliseconds, as epoch ms; null otherwise. */
export function toEpochMs(v: unknown): number | null {
  if (typeof v === 'number' && Number.isFinite(v) && v > 0) return v < 1e11 ? Math.round(v * 1000) : Math.round(v);
  if (typeof v === 'string' && v.trim()) {
    const at = Date.parse(v);
    return Number.isNaN(at) ? null : at;
  }
  return null;
}

/** JSON with every object's keys sorted: two payloads with the same content give the same text. */
export function canonicalJson(value: unknown): string {
  const seen = new WeakSet<object>();
  const walk = (v: unknown): unknown => {
    if (!v || typeof v !== 'object') return v;
    if (seen.has(v as object)) return null;
    seen.add(v as object);
    if (Array.isArray(v)) return v.map(walk);
    const out: Rec = {};
    for (const key of Object.keys(v as Rec).sort()) out[key] = walk((v as Rec)[key]);
    return out;
  };
  try { return JSON.stringify(walk(value)) ?? 'null'; } catch { return 'null'; }
}

// ---- optional rows ----------------------------------------------------------------------------

const MODES: readonly ApprovalMode[] = ['auto', 'ask', 'off'];
const asMode = (v: unknown): ApprovalMode | null => (MODES as readonly unknown[]).includes(v) ? v as ApprovalMode : null;

/** The Why row's facts, fail-closed as approvalModeNote() reads them: only the three mode words
 *  survive. Null when neither field says anything readable. */
export function normaliseWhy(approvalMode: unknown, askedUnder: unknown): DocketWhy | null {
  const now = isRecord(approvalMode) ? asMode(approvalMode.effective) : null;
  const nowSource = now && isRecord(approvalMode)
    ? (approvalMode.source === 'agent' ? 'agent' : approvalMode.source === 'global' ? 'global' : null) : null;
  const asked = isRecord(askedUnder) && asMode(askedUnder.mode)
    ? { mode: asMode(askedUnder.mode) as ApprovalMode, source: askedUnder.source === 'agent' ? 'agent' as const : 'global' as const,
      byMode: askedUnder.by_mode === true }
    : null;
  if (!now && !asked) return null;
  return { modeNow: now, modeNowSource: nowSource, askedUnder: asked };
}

/** "asked by a sub-agent of <parent>" (H400); the hub's English label is not kept. */
export function normaliseDelegatedBy(raw: unknown): { parent: string; spawnId: string | null } | null {
  if (!isRecord(raw)) return null;
  const parent = text(raw.parent, 80);
  if (!parent) return null;
  return { parent, spawnId: text(raw.spawn_id, 80) };
}

/** A terminal consent offer, validated exactly as the Decision Inbox validates it. */
export function normaliseConsentOffer(raw: unknown): DocketConsentOffer | null {
  if (!isRecord(raw)) return null;
  const { revision, count, choices, categories } = raw;
  if (typeof revision !== 'string' || !/^[a-f0-9]{64}$/.test(revision)) return null;
  if (typeof count !== 'number' || !Number.isSafeInteger(count) || count < 1 || count > 64) return null;
  if (!Array.isArray(choices) || choices.join(',') !== 'session,always,deny') return null;
  if (!Array.isArray(categories) || !categories.length || categories.length > 64) return null;
  if (!categories.every((c) => isRecord(c) && typeof c.description === 'string' && c.description.length > 0
    && c.description.length <= 500 && typeof c.permanent === 'boolean')) return null;
  return {
    revision, count, choices: ['session', 'always', 'deny'],
    categories: categories.map((c) => ({ description: (c as Rec).description as string, permanent: (c as Rec).permanent as boolean })),
  };
}

/** The capability manifest's rollback story, only with a description to say. */
export function normaliseRollback(raw: unknown): { description: string; limitations: string | null } | null {
  if (!isRecord(raw)) return null;
  const description = text(raw.description, 600);
  return description ? { description, limitations: text(raw.limitations, 600) } : null;
}

/** The judge's opinion (advisory), or a guardian's terminal verdict (advisory false). */
export function normaliseOpinion(raw: unknown): NonNullable<DocketEntry['opinion']> | null {
  if (!isRecord(raw)) return null;
  const who = isRecord(raw.judge) ? raw.judge : {};
  const advisory = raw.advisory !== false;
  return {
    score: typeof raw.score === 'number' && Number.isFinite(raw.score) ? raw.score : null,
    provider: text(who.provider, 80), model: text(who.model, 120),
    local: typeof who.local === 'boolean' ? who.local : null,
    advisory, verdict: advisory ? null : raw.decision === 'deny' ? 'deny' : 'escalate',
    flagged: Array.isArray(raw.flags) && raw.flags.length > 0,
    truncated: raw.truncated === true,
  };
}

/** Raised from untrusted content: the producer marked the payload (injection flags or an
 *  untrusted source), as Telegram and the CLI already warn. */
export function isTainted(payload: unknown): boolean {
  if (!isRecord(payload)) return false;
  const flags = payload.injection_flags;
  const flagged = flags === true || (Array.isArray(flags) && flags.length > 0);
  const source = payload.untrusted_source;
  return flagged || source === true || (typeof source === 'string' && source.trim() !== '');
}

const TARGET_KEYS = ['service', 'target', 'url', 'to', 'recipient', 'path', 'file', 'channel'] as const;

/** What a request acts on, from its payload, or null. */
export function targetOf(task: DocketTask | undefined): string | null {
  const payload = task?.payload;
  if (!isRecord(payload)) return null;
  for (const key of TARGET_KEYS) {
    const v = payload[key];
    if (typeof v === 'number' && Number.isFinite(v)) return String(v);
    const t = text(v, 200);
    if (t) return t;
  }
  return null;
}

// ---- the preview --------------------------------------------------------------------------------

const valueText = (v: unknown): string => {
  if (typeof v === 'string') return v.slice(0, 400);
  if (typeof v === 'number' || typeof v === 'boolean') return String(v);
  try { return JSON.stringify(v).slice(0, 400); } catch { return ''; }
};

/** GET /api/autonomy/tasks/{id}/preview, read defensively; null when it is not a preview. */
export function parsePreview(raw: unknown): DocketPreview | null {
  if (!isRecord(raw)) return null;
  const effects = Array.isArray(raw.effects)
    ? raw.effects.flatMap((ef) => (isRecord(ef) && typeof ef.field === 'string' && ef.field.trim()
      ? [{ field: ef.field.trim().slice(0, 60), value: valueText(ef.value) }] : []))
    : [];
  let prompt: DocketPreview['prompt'] = null;
  if (isRecord(raw.prompt)) {
    prompt = raw.prompt.available === true && typeof raw.prompt.text === 'string'
      ? { available: true, text: raw.prompt.text, choices: Array.isArray(raw.prompt.choices) ? raw.prompt.choices.filter((c): c is string => typeof c === 'string') : [] }
      : { available: false };
  }
  return {
    target: typeof raw.target === 'string' && raw.target.trim() ? raw.target.trim().slice(0, 400) : null,
    effects,
    wouldExecute: typeof raw.would_execute === 'boolean' ? raw.would_execute : null,
    prompt,
  };
}

/** The command a preview says would run (`cmd`, after B1, or `command`), or null. */
export function commandOf(preview: DocketPreview | null): string | null {
  const ef = preview?.effects.find((e) => (e.field === 'cmd' || e.field === 'command') && e.value.trim());
  return ef ? ef.value : null;
}

// ---- groups -------------------------------------------------------------------------------------

/** The feed's groups[] that are valid on the docket: the inbox's rules, plus a 32-character
 *  snapshot; a task claimed by an earlier valid group cannot join another. */
export function validGroups(raw: unknown, tasks: ReadonlyMap<number, DocketTask>): DocketGroup[] {
  if (!Array.isArray(raw)) return [];
  const claimed = new Set<number>();
  const out: DocketGroup[] = [];
  for (const g of raw) {
    if (!isRecord(g)) continue;
    const { id, leader_id: leader, member_ids: members, count, snapshot } = g;
    if (typeof id !== 'string' || !id.trim() || typeof snapshot !== 'string' || snapshot.length !== 32) continue;
    if (!isTaskId(leader) || !Array.isArray(members) || members.length < 2 || members.length !== count) continue;
    if (!members.every(isTaskId) || new Set(members).size !== members.length || !members.includes(leader)) continue;
    if (!members.every((m) => tasks.has(m as number) && !claimed.has(m as number))) continue;
    (members as number[]).forEach((m) => claimed.add(m));
    out.push({ id, leader_id: leader, member_ids: [...members] as number[], count, snapshot });
  }
  return out;
}

// ---- entries ------------------------------------------------------------------------------------

function verbsFor(kind: DocketEntry['kind'], special: boolean): Verb[] {
  if (special) return ['openInDecisions'];
  const verbs: Verb[] = ['sign', 'preview', 'edit', 'defer', 'reject'];
  if (kind === 'group') verbs.push('rejectGroup');
  if (kind === 'identical') verbs.push('rejectAllIdentical');
  return verbs;
}

/** Friction (confirm.tsx confirmStyle): tier 0 one click, 1 two steps, 2–3 and anything else typed. */
export function frictionOf(riskTier: unknown): Friction {
  return confirmStyle(typeof riskTier === 'number' ? riskTier : Number.NaN);
}

function entryFrom(kind: DocketEntry['kind'], leader: DocketTask, members: readonly DocketTask[], group: DocketGroup | null): DocketEntry {
  const tier: TierKey = tierKey(leader.risk_tier, isMoney(leader));
  const friction = frictionOf(leader.risk_tier);
  const consentOffer = normaliseConsentOffer(leader.consent_offer);
  const specialKind = specialKindOf(leader, consentOffer !== null);
  const special = specialKind !== null;
  const memberIds = members.map((m) => m.id);
  const entry: Record<string, unknown> = {
    key: kind === 'group' ? `group:${group!.id}` : kind === 'identical' ? `same:${leader.id}` : `task:${leader.id}`,
    kind,
    taskId: leader.id,
    group,
    memberIds,
    title: typeof leader.title === 'string' ? leader.title : '',
    nativeKind: typeof leader.kind === 'string' && leader.kind ? leader.kind : null,
    tier,
    friction,
    phrase: phraseFor(leader, tier, friction),
    agent: text(leader.agent, 80),
    createdAt: toEpochMs(leader.created_at),
    deadlineAt: toEpochMs(leader.approval_deadline_at),
    verbs: verbsFor(kind, special),
    special,
    specialKind,
    task: leader,
  };
  // Optional rows: present only when the hub sent the field in a readable shape.
  const why = 'approval_mode' in leader || 'asked_under' in leader ? normaliseWhy(leader.approval_mode, leader.asked_under) : null;
  if (why) entry.why = why;
  const delegated = normaliseDelegatedBy(leader.delegated_by);
  if (delegated) entry.delegatedBy = delegated;
  if (leader.pushed === true || leader.pushed === 1) entry.pushed = true;
  else if (leader.pushed === false || leader.pushed === 0) entry.pushed = false;
  const rollback = normaliseRollback(leader.rollback);
  if (rollback) entry.rollback = rollback;
  if (isTainted(leader.payload)) entry.tainted = true;
  const opinion = normaliseOpinion(leader.judge);
  if (opinion) entry.opinion = opinion;
  if (consentOffer) entry.consentOffer = consentOffer;
  if (kind !== 'single') entry.memberTargets = members.map((m) => targetOf(m));
  return entry as unknown as DocketEntry;
}

const strictness = (tier: TierKey): number => (tier === 'money' || tier === 'unknown' ? 3 : tier);
const later = (v: number | null) => (v === null ? Number.POSITIVE_INFINITY : v);

/** Tier descending, then the soonest deadline, then the oldest, then the lowest id. */
export function compareEntries(a: DocketEntry, b: DocketEntry): number {
  return strictness(b.tier) - strictness(a.tier)
    || later(a.deadlineAt) - later(b.deadlineAt)
    || later(a.createdAt) - later(b.createdAt)
    || a.taskId - b.taskId;
}

/** The counts the masthead, Glance and the docket head read. The friction mix counts only the
 *  entries signed here; a special kind is counted apart (`inDecisions`), as it opens in Decisions. */
export function summaryOf(entries: readonly DocketEntry[]): DocketSummary {
  const friction = { typed: 0, twoStep: 0, click: 0, inDecisions: 0 };
  let requests = 0;
  for (const e of entries) {
    requests += e.memberIds.length;
    if (e.special) friction.inDecisions += 1;
    else if (e.friction === 'typed') friction.typed += 1;
    else if (e.friction === 'two-step') friction.twoStep += 1;
    else friction.click += 1;
  }
  return { entries: entries.length, requests, friction };
}

const collapseKey = (t: DocketTask): string => [
  typeof t.kind === 'string' ? t.kind : '', typeof t.title === 'string' ? t.title : '', typeof t.agent === 'string' ? t.agent : '',
  String(t.risk_tier), typeof t.approval_deadline_at === 'string' ? t.approval_deadline_at : '', canonicalJson(t.payload ?? null),
].join('\u0001');

const byAge = (a: DocketTask, b: DocketTask) => later(toEpochMs(a.created_at)) - later(toEpochMs(b.created_at)) || a.id - b.id;

/** The docket from the feed. Throws when the answer is not the feed (the poller then says
 *  "malformed"). `elsewhere` counts are null here: useDocket adds them from their own feeds. */
export function parseDocketFeed(raw: unknown): DocketModel {
  if (!isRecord(raw) || !Array.isArray(raw.tasks)) throw new Error('not the decisions feed');
  const tasks = new Map<number, DocketTask>();
  for (const t of raw.tasks) if (isRecord(t) && isTaskId(t.id) && !tasks.has(t.id)) tasks.set(t.id, t as unknown as DocketTask);
  const groups = validGroups(raw.groups, tasks);
  const grouped = new Set<number>();
  const entries: DocketEntry[] = [];
  for (const g of groups) {
    g.member_ids.forEach((id) => grouped.add(id));
    const leader = tasks.get(g.leader_id)!;
    const members = [leader, ...g.member_ids.filter((id) => id !== g.leader_id).map((id) => tasks.get(id)!)];
    entries.push(entryFrom('group', leader, members, g));
  }
  const buckets = new Map<string, DocketTask[]>();
  for (const t of tasks.values()) {
    if (grouped.has(t.id)) continue;
    if (specialKindOf(t, normaliseConsentOffer(t.consent_offer) !== null) !== null) {
      entries.push(entryFrom('single', t, [t], null));
      continue;
    }
    const key = collapseKey(t);
    const bucket = buckets.get(key);
    if (bucket) bucket.push(t); else buckets.set(key, [t]);
  }
  for (const bucket of buckets.values()) {
    const members = [...bucket].sort(byAge);
    entries.push(entryFrom(members.length > 1 ? 'identical' : 'single', members[0], members, null));
  }
  entries.sort(compareEntries);
  return { entries, summary: summaryOf(entries), elsewhere: { payments: null, skillChanges: null } };
}

/** "Nothing is waiting": the feed answered with no entry. */
export const docketIsEmpty = (model: DocketModel): boolean => model.entries.length === 0;

/** The summary alone (the masthead's and Glance's parse). */
export const parseDocketSummary = (raw: unknown): DocketSummary => parseDocketFeed(raw).summary;
export const summaryIsEmpty = (summary: DocketSummary): boolean => summary.entries === 0;

/** The entry that holds a request (as its leader or as a member), or null. */
export function entryHolding(model: DocketModel | null, taskId: number): DocketEntry | null {
  if (!model) return null;
  return model.entries.find((e) => e.memberIds.includes(taskId)) ?? null;
}
