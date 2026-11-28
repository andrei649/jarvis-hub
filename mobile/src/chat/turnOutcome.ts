export type ToolActivity = { proposed: number; queued: number; executed: number | null;
  failures: number | null; basis: 'observed' | 'unknown' };

const WITHHELD_REASONS = ['rejected_taint', 'rejected_privacy', 'rejected_stale',
  'rejected_contradiction', 'abstained'] as const;
export type WithheldReason = typeof WITHHELD_REASONS[number];

const RECALL_PROVIDERS = {
  long_term_memory: 'Long-term memory',
  message_archive: 'Message archive',
} as const;
export type RecallProvider = keyof typeof RECALL_PROVIDERS;
const PROVIDER_ORDER = Object.keys(RECALL_PROVIDERS) as RecallProvider[];
const MAX_RECALL_COUNT = 10_000;

/** H430 / H18.36: what one memory provider's last prefetch this turn put in the prompt —
 *  counts and closed words only, never memory content. */
export type TurnRecall = {
  schema: 'nerva.recall-status.v1';
  provider: RecallProvider;
  basis: 'this_turn' | 'previous_recall' | 'unavailable';
  recalled: number | null;
  withheld: Partial<Record<WithheldReason, number>>;
  untrusted: number;
};

export type TurnOutcome = {
  latency_ms?: number;
  tools?: ToolActivity;
  recall?: TurnRecall[];
};

function nonNegSafeInt(value: unknown): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0;
}

function count(value: unknown): value is number {
  return nonNegSafeInt(value) && value <= 1_000_000;
}

function recallCount(value: unknown): value is number {
  return nonNegSafeInt(value) && value <= MAX_RECALL_COUNT;
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === 'object' && !Array.isArray(value);
}

/** Mirror of recall_admission.valid_recall_status: a status or nothing, never a partial one. */
export function turnRecall(value: unknown): TurnRecall | null {
  if (!isPlainObject(value)) return null;
  const keys = Object.keys(value).sort().join(',');
  if (keys !== 'basis,provider,recalled,schema,untrusted,withheld') return null;
  if (value.schema !== 'nerva.recall-status.v1'
    || !(PROVIDER_ORDER as readonly string[]).includes(String(value.provider))) return null;
  if (!['this_turn', 'previous_recall', 'unavailable'].includes(String(value.basis))) return null;
  const { recalled, untrusted, withheld } = value;
  if (!(recalled === null || recallCount(recalled)) || !recallCount(untrusted) || !isPlainObject(withheld)) return null;
  if (!Object.entries(withheld).every(([name, n]) =>
    (WITHHELD_REASONS as readonly string[]).includes(name) && recallCount(n) && n > 0)) return null;
  const reasons = Object.keys(withheld).length;
  const used = recalled as number | null;
  if (used === null) {
    if (reasons || untrusted) return null;
  } else if (untrusted > used || (value.basis === 'unavailable' && (used || reasons))) return null;
  return value as TurnRecall;
}

/** Mirror of recall_admission.describe_recall — pinned to frontend/src/test/recall-line-cases.json. */
export function recallLine(recall: TurnRecall): string {
  const label = RECALL_PROVIDERS[recall.provider];
  if (recall.basis === 'unavailable') return `🧠 ${label} — unavailable this turn, no memory used`;
  const parts: string[] = [];
  if (recall.recalled === null) parts.push('recalled relevant memory');
  else if (recall.recalled) parts.push(recall.recalled === 1 ? 'recalled 1 memory' : `recalled ${recall.recalled} memories`);
  if (parts.length && recall.basis === 'previous_recall') parts[0] += " from this session's previous recall";
  if (parts.length && recall.untrusted) parts[0] += ` (${recall.untrusted} from an untrusted source)`;
  const reasons = WITHHELD_REASONS.filter(name => recall.withheld[name]);
  const total = reasons.reduce((sum, name) => sum + (recall.withheld[name] ?? 0), 0);
  if (total) parts.push(`${total} withheld (${reasons.map(name =>
    `${name.replace(/^rejected_/, '')}: ${recall.withheld[name]}`).join(', ')})`);
  return parts.length ? `🧠 ${label} — ${parts.join(', ')}` : '';
}

/** Well-formed statuses, first per provider, in canonical provider order. */
export function turnRecalls(value: unknown): TurnRecall[] | null {
  if (!Array.isArray(value)) return null;
  const byProvider = new Map<RecallProvider, TurnRecall>();
  for (const item of value) {
    const recall = turnRecall(item);
    if (recall && !byProvider.has(recall.provider)) byProvider.set(recall.provider, recall);
  }
  const recalls = PROVIDER_ORDER.flatMap(provider => byProvider.has(provider) ? [byProvider.get(provider)!] : []);
  return recalls.length ? recalls : null;
}

/** One human-readable recall line per provider with something to report (never spoken by TTS). */
export function recallLines(recalls: readonly TurnRecall[]): string[] {
  return recalls.map(recallLine).filter(Boolean);
}

/** The hub counts agent tool invocations; individual external effects have separate receipts. */
export function toolActivity(value: unknown): ToolActivity | undefined {
  if (!isPlainObject(value)
    || Object.keys(value).sort().join(',') !== 'basis,executed,failures,proposed,queued') return;
  const { proposed, queued, executed, failures, basis } = value;
  if (!count(proposed) || !count(queued)) return;
  if (basis === 'observed' && count(executed) && count(failures)) return { proposed, queued, executed, failures, basis };
  if (basis === 'unknown' && (executed === null || count(executed)) && failures === null)
    return { proposed, queued, executed, failures, basis };
}

export function normalizeTurnOutcome(value: unknown): TurnOutcome | null {
  if (!isPlainObject(value)) return null;
  const tools = toolActivity(value.tools);
  const recall = turnRecalls(value.recall);
  const milliseconds = value.latency_ms;
  const outcome: TurnOutcome = {
    ...(tools ? { tools } : {}),
    ...(recall ? { recall } : {}),
  };
  if (Object.prototype.hasOwnProperty.call(value, 'latency_ms') && typeof milliseconds === 'number'
    && Number.isSafeInteger(milliseconds) && milliseconds >= 0) outcome.latency_ms = milliseconds;
  return Object.keys(outcome).length ? outcome : null;
}
