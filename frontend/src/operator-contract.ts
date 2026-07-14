export type DesktopOutcome = 'proposed' | 'queued' | 'blocked' | 'failed' | 'partial' | 'executed';
export type DesktopOutcomeContext = 'preview' | 'run';
export type CanonicalDesktopAction = 'read' | 'locate' | 'click' | 'type' | 'launch';

export interface CanonicalDesktopStep {
  action: CanonicalDesktopAction;
  args: Record<string, string>;
}

export interface SafeDesktopElement {
  role?: string;
  name?: string;
}

export interface SafeDesktopStepResult {
  source?: string;
  text?: string;
  count?: number;
  truncated?: boolean;
  elements?: SafeDesktopElement[];
  element?: SafeDesktopElement;
}

export interface SafeDesktopRanStep {
  action?: string;
  status: string;
  reason?: string;
  result?: SafeDesktopStepResult;
}

export interface SafeDesktopResult {
  ok?: boolean;
  reason?: string;
  task_id?: string;
  approval_required?: boolean;
  ran: SafeDesktopRanStep[];
}

const MAX_STEPS = 20;
const MAX_ACTION = 64;
const MAX_ARGUMENT = 512;
const MAX_TYPE_TEXT = 4_000;
const MAX_REASON = 240;
const MAX_TASK_ID = 128;
const MAX_SOURCE = 64;
const MAX_READ_TEXT = 1_000;
const MAX_ELEMENTS = 10;
const MAX_ELEMENT_FIELD = 120;
const APP_KEY = /^[a-z][a-z0-9_]{0,31}$/;

const GOVERNANCE_REASONS = new Set([
  'approval_required',
  'desktop_host_disabled',
  'desktop_proposal_unavailable',
  'kernel_required',
  'injection_detected',
  'unified_action_api_disabled',
  'action_kernel_disabled',
  'contract_denied',
  'contract_error',
  'kernel_refused',
]);
const GOVERNANCE_STATUSES = new Set(['blocked', 'denied', 'refused']);
const SAFE_STEP_STATUSES = new Set(['ran', 'blocked', 'failed', 'skipped', 'queued', 'denied', 'refused']);

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function exactKeys(value: Record<string, unknown>, expected: readonly string[]): boolean {
  const actual = Object.keys(value);
  return actual.length === expected.length && actual.every((key) => expected.includes(key));
}

function boundedString(value: unknown, cap: number): string | undefined {
  return typeof value === 'string' ? value.slice(0, cap) : undefined;
}

function normalizedRequiredString(value: unknown, label: string): string {
  if (typeof value !== 'string') throw new Error(`invalid_${label}`);
  const normalized = value.trim();
  if (!normalized || normalized.length > MAX_ARGUMENT) throw new Error(`invalid_${label}`);
  return normalized;
}

function canonicalizeStep(value: unknown): CanonicalDesktopStep {
  if (!isRecord(value) || !exactKeys(value, ['action', 'args'])) throw new Error('invalid_step');
  if (typeof value.action !== 'string' || value.action.length > MAX_ACTION) throw new Error('invalid_action');
  const action = value.action.trim().toLowerCase();
  if (!isRecord(value.args)) throw new Error('invalid_args');
  const args = value.args;

  if (action === 'read' || action === 'locate') {
    if (!exactKeys(args, ['query'])) throw new Error('invalid_args');
    return { action, args: { query: normalizedRequiredString(args.query, 'query') } };
  }
  if (action === 'click') {
    if (!exactKeys(args, ['name'])) throw new Error('invalid_args');
    return { action, args: { name: normalizedRequiredString(args.name, 'name') } };
  }
  if (action === 'type') {
    if (!exactKeys(args, ['name', 'text'])) throw new Error('invalid_args');
    const name = normalizedRequiredString(args.name, 'name');
    if (typeof args.text !== 'string' || args.text.length > MAX_TYPE_TEXT) throw new Error('invalid_text');
    return { action, args: { name, text: args.text } };
  }
  if (action === 'launch') {
    if (!exactKeys(args, ['app'])) throw new Error('invalid_args');
    const app = normalizedRequiredString(args.app, 'app').toLowerCase();
    if (!APP_KEY.test(app)) throw new Error('invalid_app');
    return { action, args: { app } };
  }
  throw new Error('unsupported_action');
}

export function canonicalizeDesktopSteps(steps: unknown): CanonicalDesktopStep[] {
  if (!Array.isArray(steps) || steps.length === 0 || steps.length > MAX_STEPS) {
    throw new Error('invalid_steps');
  }
  return steps.map(canonicalizeStep);
}

export function desktopPlanSignature(steps: unknown): string {
  return JSON.stringify(canonicalizeDesktopSteps(steps));
}

function boundedTaskId(value: unknown): string | undefined {
  if (typeof value === 'string') {
    const normalized = value.trim();
    return normalized ? normalized.slice(0, MAX_TASK_ID) : undefined;
  }
  if (typeof value === 'number' && Number.isFinite(value) && value > 0) {
    return String(value).slice(0, MAX_TASK_ID);
  }
  return undefined;
}

function isGovernanceRefusal(result: Record<string, unknown>): boolean {
  if (result.approval_required === true || result.blocked === true || result.denied === true || result.refused === true) {
    return true;
  }
  return (typeof result.reason === 'string' && GOVERNANCE_REASONS.has(result.reason))
    || (typeof result.status === 'string' && GOVERNANCE_STATUSES.has(result.status));
}

export function reduceDesktopOutcome(
  context: DesktopOutcomeContext,
  result: unknown,
  submittedCount: number,
): DesktopOutcome {
  if (context === 'preview') return 'proposed';
  const record = isRecord(result) ? result : {};
  const boundedRan = Array.isArray(record.ran) ? record.ran.slice(0, MAX_STEPS) : [];
  const returnedCount = boundedRan.length;
  const ranCount = boundedRan.filter((entry) => isRecord(entry) && entry.status === 'ran').length;
  const approvalRequired = record.approval_required === true || record.reason === 'approval_required';
  const taskId = boundedTaskId(record.task_id);

  if (ranCount === 0 && approvalRequired && taskId) return 'queued';
  if (
    submittedCount > 0
    && record.ok === true
    && returnedCount === submittedCount
    && ranCount === submittedCount
  ) return 'executed';
  if (ranCount > 0) return 'partial';
  if (isGovernanceRefusal(record)) return 'blocked';
  return 'failed';
}

function sanitizeElement(value: unknown): SafeDesktopElement | undefined {
  if (!isRecord(value)) return undefined;
  const element: SafeDesktopElement = {};
  const role = boundedString(value.role, MAX_ELEMENT_FIELD);
  const name = boundedString(value.name, MAX_ELEMENT_FIELD);
  if (role !== undefined) element.role = role;
  if (name !== undefined) element.name = name;
  return Object.keys(element).length ? element : undefined;
}

function sanitizeNestedResult(value: unknown, action: string | undefined): SafeDesktopStepResult | undefined {
  if (!isRecord(value)) return undefined;
  const safe: SafeDesktopStepResult = {};
  const source = boundedString(value.source, MAX_SOURCE);
  if (source !== undefined) safe.source = source;
  if (action === 'read') {
    const text = boundedString(value.text, MAX_READ_TEXT);
    if (text !== undefined) safe.text = text;
  }
  if (
    typeof value.count === 'number'
    && Number.isSafeInteger(value.count)
    && value.count >= 0
  ) safe.count = value.count;
  if (typeof value.truncated === 'boolean') safe.truncated = value.truncated;
  if (Array.isArray(value.elements)) {
    const elements = value.elements.slice(0, MAX_ELEMENTS)
      .map(sanitizeElement)
      .filter((entry): entry is SafeDesktopElement => entry !== undefined);
    if (elements.length) safe.elements = elements;
  }
  const element = sanitizeElement(value.element);
  if (element) safe.element = element;
  return Object.keys(safe).length ? safe : undefined;
}

function sanitizeRanStep(value: unknown): SafeDesktopRanStep | undefined {
  if (!isRecord(value)) return undefined;
  const action = boundedString(value.action, MAX_ACTION);
  const normalizedStatus = typeof value.status === 'string' ? value.status.trim().toLowerCase() : '';
  const safe: SafeDesktopRanStep = {
    status: SAFE_STEP_STATUSES.has(normalizedStatus) ? normalizedStatus : 'unknown',
  };
  if (action !== undefined) safe.action = action;
  const reason = boundedString(value.reason, MAX_REASON);
  if (reason !== undefined) safe.reason = reason;
  const nested = sanitizeNestedResult(value.result, action?.trim().toLowerCase());
  if (nested) safe.result = nested;
  return safe;
}

export function sanitizeDesktopResult(result: unknown): SafeDesktopResult {
  const safe: SafeDesktopResult = { ran: [] };
  if (!isRecord(result)) return safe;
  if (typeof result.ok === 'boolean') safe.ok = result.ok;
  const reason = boundedString(result.reason, MAX_REASON);
  if (reason !== undefined) safe.reason = reason;
  const taskId = boundedTaskId(result.task_id);
  if (taskId !== undefined) safe.task_id = taskId;
  if (result.approval_required === true || result.reason === 'approval_required') {
    safe.approval_required = true;
  } else if (result.approval_required === false) {
    safe.approval_required = false;
  }
  if (Array.isArray(result.ran)) {
    safe.ran = result.ran.slice(0, MAX_STEPS)
      .map(sanitizeRanStep)
      .filter((entry): entry is SafeDesktopRanStep => entry !== undefined);
  }
  return safe;
}
