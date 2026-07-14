import React, { useRef, useState } from 'react';

import { apiPost } from './api/client';
import {
  canonicalizeDesktopSteps,
  desktopPlanSignature,
  reduceDesktopOutcome,
  sanitizeDesktopResult,
  type CanonicalDesktopAction,
  type CanonicalDesktopStep,
  type DesktopOutcome,
  type SafeDesktopResult,
} from './operator-contract';

type BrowserAction = 'navigate' | 'extract' | 'click' | 'type' | 'submit';
type BrowserStep =
  | { action: 'navigate'; url: string }
  | { action: 'extract' | 'click' | 'submit'; selector: string }
  | { action: 'type'; selector: string; text: string };

interface BrowserCheckResult {
  allowed: boolean;
  reason: string;
}

interface BrowserPreviewRow {
  index: number;
  action: string;
  kind: string;
  decision: string;
  reason: string;
}

interface DesktopPreviewRow {
  action: string;
  decision: string;
}

interface DesktopGrant {
  signature: string;
  snapshot: CanonicalDesktopStep[];
}

interface DesktopOutcomeView {
  outcome: DesktopOutcome;
  result: SafeDesktopResult;
}

const MAX_STEPS = 20;
const MAX_URL = 2_000;
const MAX_DOMAIN = 253;
const MAX_SELECTOR = 512;
const MAX_TYPE_TEXT = 4_000;
const MAX_REASON = 240;
const BROWSER_DECISIONS = new Set(['run', 'approve', 'block']);

const mono: React.CSSProperties = { fontFamily: 'var(--font-mono)', fontSize: 11 };
const inputStyle: React.CSSProperties = {
  background: 'var(--surface)',
  color: 'var(--ink)',
  border: '1px solid var(--panel-line)',
  borderRadius: 4,
  padding: 5,
  ...mono,
};
const fieldsetStyle: React.CSSProperties = {
  border: '1px solid var(--panel-line)',
  borderRadius: 4,
  padding: 10,
  margin: '0 0 10px',
};
const rowStyle: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: 8,
  padding: '5px 0',
  borderBottom: '1px solid var(--panel-line)',
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function boundedString(value: unknown, cap: number): string {
  return typeof value === 'string' ? value.slice(0, cap) : '';
}

function boundedError(error: unknown): string {
  if (error instanceof Error && error.message) return error.message.slice(0, MAX_REASON);
  return 'request_failed';
}

function describeBrowserStep(step: BrowserStep): string {
  if (step.action === 'navigate') return `navigate · ${step.url}`;
  if (step.action === 'type') return `type · ${step.selector}`;
  return `${step.action} · ${step.selector}`;
}

function describeDesktopStep(step: CanonicalDesktopStep): string {
  if (step.action === 'read' || step.action === 'locate') return `${step.action} · ${step.args.query}`;
  if (step.action === 'type') return `type · ${step.args.name}`;
  if (step.action === 'click') return `click · ${step.args.name}`;
  return `launch · ${step.args.app}`;
}

function cloneBrowserPlan(plan: BrowserStep[]): BrowserStep[] {
  return plan.map((step) => {
    if (step.action === 'navigate') return { action: 'navigate', url: step.url };
    if (step.action === 'type') return { action: 'type', selector: step.selector, text: step.text };
    return { action: step.action, selector: step.selector };
  });
}

function browserCheckSignature(url: string, allowlist: string[]): string {
  return JSON.stringify({ url: url.trim(), allowlist: [...allowlist] });
}

function browserPreviewSignature(allowlist: string[], plan: BrowserStep[]): string {
  return JSON.stringify({ allowlist: [...allowlist], plan: cloneBrowserPlan(plan) });
}

function sanitizeBrowserPreview(value: unknown, snapshot: BrowserStep[]): BrowserPreviewRow[] | null {
  if (
    !isRecord(value)
    || !Array.isArray(value.steps)
    || value.steps.length !== snapshot.length
  ) return null;
  const rows: BrowserPreviewRow[] = [];
  for (let index = 0; index < snapshot.length; index += 1) {
    const raw = value.steps[index];
    if (
      !isRecord(raw)
      || raw.index !== index
      || typeof raw.action !== 'string'
      || raw.action !== snapshot[index].action
      || typeof raw.decision !== 'string'
      || !BROWSER_DECISIONS.has(raw.decision)
      || typeof raw.reason !== 'string'
    ) return null;
    rows.push({
      index,
      action: snapshot[index].action,
      kind: boundedString(raw.kind, 32),
      decision: boundedString(raw.decision, 32),
      reason: boundedString(raw.reason, MAX_REASON),
    });
  }
  return rows;
}

function sanitizeDesktopPreview(value: unknown, snapshot: CanonicalDesktopStep[]): DesktopPreviewRow[] | null {
  if (
    !isRecord(value)
    || ('ok' in value && typeof value.ok !== 'boolean')
    || value.ok === false
    || !Array.isArray(value.steps)
    || value.steps.length !== snapshot.length
  ) {
    return null;
  }
  const rows: DesktopPreviewRow[] = [];
  for (let index = 0; index < snapshot.length; index += 1) {
    const raw = value.steps[index];
    const action = snapshot[index].action;
    const expectedMutating = action === 'click' || action === 'type' || action === 'launch';
    if (
      !isRecord(raw)
      || typeof raw.action !== 'string'
      || raw.action.trim().toLowerCase() !== action
      || typeof raw.mutating !== 'boolean'
      || typeof raw.requires_approval !== 'boolean'
      || typeof raw.would_run !== 'boolean'
      || raw.mutating !== expectedMutating
      || raw.requires_approval !== expectedMutating
      || raw.would_run !== !expectedMutating
    ) {
      return null;
    }
    rows.push({ action, decision: expectedMutating ? 'approval required' : 'would run' });
  }
  return rows;
}

function Alert({ value }: { value: string | null }) {
  return value ? <div role="alert" style={{ ...mono, color: 'var(--red)', marginTop: 8 }}>{value}</div> : null;
}

function BrowserResult({ check, preview }: {
  check: BrowserCheckResult | null;
  preview: BrowserPreviewRow[] | null;
}) {
  return (
    <>
      {check && (
        <div role="status" aria-label="browser check result" style={{ ...mono, marginTop: 8, color: check.allowed ? 'var(--green)' : 'var(--amber)' }}>
          {check.allowed ? 'Allowed' : 'Blocked'}{check.reason ? <> · <span>{check.reason}</span></> : null}
        </div>
      )}
      {preview && (
        <div role="status" style={{ marginTop: 8 }}>
          <div style={{ ...mono, color: 'var(--ink-3)' }}>Policy dry run · preview only</div>
          <ol aria-label="browser preview result" style={{ margin: '4px 0 0', paddingLeft: 22 }}>
            {preview.map((row) => (
              <li key={`${row.index}:${row.action}`} style={mono}>
                {[row.action || 'unknown', row.decision || row.kind || 'previewed'].filter(Boolean).join(' · ')}
                {row.reason ? <> · <span>{row.reason}</span></> : null}
              </li>
            ))}
          </ol>
        </div>
      )}
    </>
  );
}

function DesktopOutcomeRegion({ value }: { value: DesktopOutcomeView | null }) {
  if (!value) return null;
  const { outcome, result } = value;
  let headline = '';
  if (outcome === 'proposed') headline = 'Preview only · nothing executed';
  if (outcome === 'queued') headline = `Queued · task ${result.task_id || 'pending'} · Decision Inbox`;
  if (outcome === 'blocked') headline = `Blocked${result.reason ? ` · ${result.reason}` : ''}`;
  if (outcome === 'failed') headline = `Failed${result.reason ? ` · ${result.reason}` : ''}`;
  if (outcome === 'partial') headline = 'Partial';
  if (outcome === 'executed') headline = 'Executed';

  return (
    <div role="status" aria-label="desktop outcome" style={{ marginTop: 8 }}>
      <div style={{ ...mono, color: outcome === 'executed' ? 'var(--green)' : 'var(--amber)' }}>{headline}</div>
      {outcome === 'partial' && (
        <div style={{ ...mono, color: 'var(--red)', marginTop: 4 }}>
          Do not retry the whole plan: some steps already ran
        </div>
      )}
      {result.ran.length > 0 && (
        <ol aria-label="desktop outcome steps" style={{ margin: '5px 0 0', paddingLeft: 22 }}>
          {result.ran.map((step, index) => (
            <li key={`${index}:${step.action || 'unknown'}`} style={mono}>
              <span>{[step.action || 'unknown', step.status, step.reason].filter(Boolean).join(' · ')}</span>
              {step.result?.text && <div style={{ color: 'var(--ink-2)' }}>{step.result.text}</div>}
              {step.result?.element && (
                <div style={{ color: 'var(--ink-3)' }}>
                  {[step.result.element.role, step.result.element.name].filter(Boolean).join(' · ')}
                </div>
              )}
              {step.result?.elements?.map((element, elementIndex) => (
                <div key={elementIndex} style={{ color: 'var(--ink-3)' }}>
                  {[element.role, element.name].filter(Boolean).join(' · ')}
                </div>
              ))}
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

export function OperatorPanel() {
  const [browserUrl, setBrowserUrl] = useState('');
  const browserUrlRef = useRef('');
  const [domainDraft, setDomainDraft] = useState('');
  const [allowlist, setAllowlist] = useState<string[]>([]);
  const allowlistRef = useRef<string[]>([]);
  const [browserAction, setBrowserAction] = useState<BrowserAction>('navigate');
  const [browserPrimary, setBrowserPrimary] = useState('');
  const [browserTypeText, setBrowserTypeText] = useState('');
  const [browserPlan, setBrowserPlan] = useState<BrowserStep[]>([]);
  const browserPlanRef = useRef<BrowserStep[]>([]);
  const browserCheckRevisionRef = useRef(0);
  const browserPreviewRevisionRef = useRef(0);
  const browserCheckRequestRef = useRef(0);
  const browserPreviewRequestRef = useRef(0);
  const [browserBusy, setBrowserBusy] = useState<'check' | 'preview' | null>(null);
  const [browserError, setBrowserError] = useState<string | null>(null);
  const [browserCheck, setBrowserCheck] = useState<BrowserCheckResult | null>(null);
  const [browserPreview, setBrowserPreview] = useState<BrowserPreviewRow[] | null>(null);

  const [desktopAction, setDesktopAction] = useState<CanonicalDesktopAction>('read');
  const [desktopPrimary, setDesktopPrimary] = useState('');
  const [desktopTypeText, setDesktopTypeText] = useState('');
  const [desktopSteps, setDesktopSteps] = useState<CanonicalDesktopStep[]>([]);
  const desktopStepsRef = useRef<CanonicalDesktopStep[]>([]);
  const desktopRevisionRef = useRef(0);
  const previewRequestRef = useRef(0);
  const [desktopBusy, setDesktopBusy] = useState<'preview' | 'run' | null>(null);
  const [desktopError, setDesktopError] = useState<string | null>(null);
  const [desktopPreview, setDesktopPreview] = useState<DesktopPreviewRow[] | null>(null);
  const [desktopGrant, setDesktopGrant] = useState<DesktopGrant | null>(null);
  const [desktopOutcome, setDesktopOutcome] = useState<DesktopOutcomeView | null>(null);

  const replaceBrowserUrl = (next: string) => {
    browserUrlRef.current = next;
    browserCheckRevisionRef.current += 1;
    setBrowserUrl(next);
    setBrowserCheck(null);
    setBrowserError(null);
  };

  const replaceAllowlist = (next: string[]) => {
    const snapshot = [...next];
    allowlistRef.current = snapshot;
    browserCheckRevisionRef.current += 1;
    browserPreviewRevisionRef.current += 1;
    setAllowlist(snapshot);
    setBrowserCheck(null);
    setBrowserPreview(null);
    setBrowserError(null);
  };

  const replaceBrowserPlan = (next: BrowserStep[]) => {
    const snapshot = cloneBrowserPlan(next);
    browserPlanRef.current = snapshot;
    browserPreviewRevisionRef.current += 1;
    setBrowserPlan(snapshot);
    setBrowserPreview(null);
    setBrowserError(null);
  };

  const replaceDesktopSteps = (next: CanonicalDesktopStep[]) => {
    const canonical = next.length ? canonicalizeDesktopSteps(next) : [];
    desktopStepsRef.current = canonical;
    desktopRevisionRef.current += 1;
    setDesktopSteps(canonical);
    setDesktopGrant(null);
    setDesktopPreview(null);
    setDesktopOutcome(null);
    setDesktopError(null);
  };

  const addDomain = () => {
    setBrowserError(null);
    const domain = domainDraft.trim();
    if (!domain) return setBrowserError('Enter an explicit allowlisted domain');
    if (domain.length > MAX_DOMAIN) return setBrowserError('Domains are capped at 253 characters');
    if (allowlistRef.current.length >= MAX_STEPS) return setBrowserError('The Operator allowlist is capped at 20 entries');
    replaceAllowlist([...allowlistRef.current, domain]);
    setDomainDraft('');
  };

  const addBrowserStep = () => {
    setBrowserError(null);
    if (browserPlanRef.current.length >= MAX_STEPS) return setBrowserError('Browser plans are capped at 20 steps');
    const primary = browserPrimary.trim();
    if (!primary) return setBrowserError(browserAction === 'navigate' ? 'Enter a browser step URL' : 'Enter a selector');
    let step: BrowserStep;
    if (browserAction === 'navigate') {
      if (browserPrimary.length > MAX_URL) return setBrowserError('Browser URLs are capped at 2,000 characters');
      step = { action: 'navigate', url: primary };
    } else {
      if (primary.length > MAX_SELECTOR) return setBrowserError('Browser selectors are capped at 512 characters');
      if (browserAction === 'type') {
        if (browserTypeText.length > MAX_TYPE_TEXT) return setBrowserError('Browser type text is capped at 4,000 characters');
        step = { action: 'type', selector: primary, text: browserTypeText };
      } else {
        step = { action: browserAction, selector: primary };
      }
    }
    replaceBrowserPlan([...browserPlanRef.current, step]);
    setBrowserPrimary('');
    setBrowserTypeText('');
  };

  const validateBrowserBoundary = (): string | null => {
    if (allowlistRef.current.length === 0) return 'Empty allowlist is fail-closed; add an explicit domain first';
    if (allowlistRef.current.length > MAX_STEPS) return 'The Operator allowlist is capped at 20 entries';
    return null;
  };

  const checkPolicy = async () => {
    setBrowserError(null);
    setBrowserCheck(null);
    const boundaryError = validateBrowserBoundary();
    if (boundaryError) return setBrowserError(boundaryError);
    const urlSnapshot = browserUrlRef.current.trim();
    if (!urlSnapshot) return setBrowserError('Enter a browser URL');
    if (browserUrlRef.current.length > MAX_URL) return setBrowserError('Browser URLs are capped at 2,000 characters');
    const allowlistSnapshot = [...allowlistRef.current];
    const signature = browserCheckSignature(urlSnapshot, allowlistSnapshot);
    const revision = browserCheckRevisionRef.current;
    const requestId = browserCheckRequestRef.current + 1;
    browserCheckRequestRef.current = requestId;
    const isCurrent = () => revision === browserCheckRevisionRef.current
      && requestId === browserCheckRequestRef.current
      && signature === browserCheckSignature(browserUrlRef.current, allowlistRef.current);
    setBrowserBusy('check');
    try {
      const raw = await apiPost('/api/browser/check', { url: urlSnapshot, allowlist: allowlistSnapshot });
      if (!isCurrent()) return;
      if (!isRecord(raw) || typeof raw.allowed !== 'boolean') throw new Error('Invalid browser policy response');
      setBrowserCheck({ allowed: raw.allowed, reason: boundedString(raw.reason, MAX_REASON) });
    } catch (error) {
      if (isCurrent()) setBrowserError(boundedError(error));
    } finally {
      if (requestId === browserCheckRequestRef.current) setBrowserBusy(null);
    }
  };

  const previewBrowserPlan = async () => {
    setBrowserError(null);
    setBrowserPreview(null);
    const boundaryError = validateBrowserBoundary();
    if (boundaryError) return setBrowserError(boundaryError);
    if (!browserPlanRef.current.length) return setBrowserError('Add at least one browser step');
    const allowlistSnapshot = [...allowlistRef.current];
    const storedSnapshot = cloneBrowserPlan(browserPlanRef.current);
    const requestSnapshot = cloneBrowserPlan(browserPlanRef.current);
    const signature = browserPreviewSignature(allowlistSnapshot, storedSnapshot);
    const revision = browserPreviewRevisionRef.current;
    const requestId = browserPreviewRequestRef.current + 1;
    browserPreviewRequestRef.current = requestId;
    const isCurrent = () => revision === browserPreviewRevisionRef.current
      && requestId === browserPreviewRequestRef.current
      && signature === browserPreviewSignature(allowlistRef.current, browserPlanRef.current);
    setBrowserBusy('preview');
    try {
      const raw = await apiPost('/api/browser/plan/preview', {
        allowlist: allowlistSnapshot,
        plan: requestSnapshot,
      });
      if (!isCurrent()) return;
      const safe = sanitizeBrowserPreview(raw, storedSnapshot);
      if (!safe) throw new Error('Invalid browser preview response');
      setBrowserPreview(safe);
    } catch (error) {
      if (isCurrent()) setBrowserError(boundedError(error));
    } finally {
      if (requestId === browserPreviewRequestRef.current) setBrowserBusy(null);
    }
  };

  const addDesktopStep = () => {
    setDesktopError(null);
    if (desktopStepsRef.current.length >= MAX_STEPS) return setDesktopError('Desktop plans are capped at 20 steps');
    const primary = desktopPrimary.trim();
    if (!primary) return setDesktopError('Enter the required desktop target');
    if (primary.length > MAX_SELECTOR) return setDesktopError('Desktop query and name fields are capped at 512 characters');
    if (desktopAction === 'type' && desktopTypeText.length > MAX_TYPE_TEXT) {
      return setDesktopError('Desktop type text is capped at 4,000 characters');
    }
    let raw: unknown;
    if (desktopAction === 'read' || desktopAction === 'locate') raw = { action: desktopAction, args: { query: desktopPrimary } };
    if (desktopAction === 'click') raw = { action: desktopAction, args: { name: desktopPrimary } };
    if (desktopAction === 'type') raw = { action: desktopAction, args: { name: desktopPrimary, text: desktopTypeText } };
    if (desktopAction === 'launch') raw = { action: desktopAction, args: { app: desktopPrimary } };
    try {
      const [step] = canonicalizeDesktopSteps([raw]);
      replaceDesktopSteps([...desktopStepsRef.current, step]);
      setDesktopPrimary('');
      setDesktopTypeText('');
    } catch {
      setDesktopError('Desktop step is outside the governed action contract');
    }
  };

  const previewDesktopPlan = async () => {
    setDesktopError(null);
    setDesktopGrant(null);
    setDesktopPreview(null);
    setDesktopOutcome(null);
    let snapshot: CanonicalDesktopStep[];
    try {
      snapshot = canonicalizeDesktopSteps(desktopStepsRef.current);
    } catch {
      return setDesktopError('Add at least one valid desktop step');
    }
    const signature = desktopPlanSignature(snapshot);
    const revision = desktopRevisionRef.current;
    const requestId = previewRequestRef.current + 1;
    previewRequestRef.current = requestId;
    const storedSnapshot = canonicalizeDesktopSteps(snapshot);
    const requestSnapshot = canonicalizeDesktopSteps(snapshot);
    setDesktopBusy('preview');
    try {
      const raw = await apiPost('/api/desktop/preview', { steps: requestSnapshot });
      if (revision !== desktopRevisionRef.current || requestId !== previewRequestRef.current) return;
      let currentSignature = '';
      try { currentSignature = desktopPlanSignature(desktopStepsRef.current); } catch { return; }
      if (currentSignature !== signature) return;
      if (isRecord(raw) && raw.ok === false) {
        throw new Error(boundedString(raw.reason, MAX_REASON) || 'Desktop preview refused');
      }
      const safePreview = sanitizeDesktopPreview(raw, storedSnapshot);
      if (!safePreview) throw new Error('Invalid desktop preview response');
      setDesktopPreview(safePreview);
      setDesktopGrant({ signature, snapshot: storedSnapshot });
      setDesktopOutcome({ outcome: reduceDesktopOutcome('preview', raw, storedSnapshot.length), result: { ran: [] } });
    } catch (error) {
      if (revision === desktopRevisionRef.current && requestId === previewRequestRef.current) {
        setDesktopError(boundedError(error));
      }
    } finally {
      if (requestId === previewRequestRef.current) setDesktopBusy(null);
    }
  };

  const runDesktopPlan = async () => {
    if (!desktopGrant) return;
    const grant = desktopGrant;
    setDesktopGrant(null);
    setDesktopPreview(null);
    setDesktopOutcome(null);
    setDesktopError(null);
    setDesktopBusy('run');
    try {
      if (desktopPlanSignature(grant.snapshot) !== grant.signature) throw new Error('Desktop preview snapshot changed');
      const requestSnapshot = canonicalizeDesktopSteps(grant.snapshot);
      const raw = await apiPost('/api/desktop/run', { steps: requestSnapshot });
      const outcome = reduceDesktopOutcome('run', raw, grant.snapshot.length);
      const result = sanitizeDesktopResult(raw);
      setDesktopOutcome({ outcome, result });
    } catch (error) {
      setDesktopError(boundedError(error));
    } finally {
      setDesktopBusy(null);
    }
  };

  const browserPrimaryLabel = browserAction === 'navigate' ? 'Browser step URL' : 'Browser selector';
  const desktopPrimaryLabel = desktopAction === 'read' || desktopAction === 'locate'
    ? 'Desktop query' : desktopAction === 'launch' ? 'Desktop app id' : 'Desktop element name';

  return (
    <div className="panel" style={{ marginBottom: 'var(--gap)', breakInside: 'avoid' }}>
      <span className="bk tl" /><span className="bk tr" /><span className="bk bl" /><span className="bk br" />
      <div className="panel-head"><span className="ttl">OPERATOR</span></div>
      <div className="panel-body tight">
        <fieldset style={fieldsetStyle}>
          <legend style={{ ...mono, color: 'var(--accent-light)' }}>Browser policy dry run</legend>
          <p style={{ ...mono, color: 'var(--ink-3)' }}>
            Empty allowlist is fail-closed. This checks policy and previews a plan; it does not run a browser.
          </p>
          <label style={mono} htmlFor="operator-browser-url">Browser URL</label>
          <input
            id="operator-browser-url"
            value={browserUrl}
            maxLength={MAX_URL}
            onChange={(event) => replaceBrowserUrl(event.target.value)}
            style={{ ...inputStyle, width: '100%', boxSizing: 'border-box', marginBottom: 6 }}
          />
          <div style={{ display: 'flex', gap: 6, alignItems: 'end' }}>
            <div style={{ flex: 1 }}>
              <label style={mono} htmlFor="operator-domain">Allowlisted domain</label>
              <input
                id="operator-domain"
                value={domainDraft}
                maxLength={MAX_DOMAIN}
                onChange={(event) => setDomainDraft(event.target.value)}
                style={{ ...inputStyle, width: '100%', boxSizing: 'border-box' }}
              />
            </div>
            <button className="tool-btn" type="button" onClick={addDomain}>add domain</button>
          </div>
          <ol aria-label="browser allowlist" style={{ margin: '5px 0', paddingLeft: 22 }}>
            {allowlist.map((domain, index) => (
              <li key={`${domain}:${index}`} style={mono}>
                {domain}{' '}
                <button
                  className="tool-btn"
                  type="button"
                  aria-label={`remove domain ${domain}`}
                  onClick={() => replaceAllowlist(allowlistRef.current.filter((_, itemIndex) => itemIndex !== index))}
                >×</button>
              </li>
            ))}
          </ol>
          <div style={{ display: 'grid', gridTemplateColumns: '120px 1fr', gap: 6 }}>
            <label style={mono} htmlFor="operator-browser-action">Browser action</label>
            <select
              id="operator-browser-action"
              value={browserAction}
              onChange={(event) => { setBrowserAction(event.target.value as BrowserAction); setBrowserPrimary(''); setBrowserTypeText(''); }}
              style={inputStyle}
            >
              {(['navigate', 'extract', 'click', 'type', 'submit'] as BrowserAction[]).map((action) => <option key={action}>{action}</option>)}
            </select>
            <label style={mono} htmlFor="operator-browser-primary">{browserPrimaryLabel}</label>
            <input
              id="operator-browser-primary"
              aria-label={browserPrimaryLabel}
              value={browserPrimary}
              maxLength={browserAction === 'navigate' ? MAX_URL : MAX_SELECTOR}
              onChange={(event) => setBrowserPrimary(event.target.value)}
              style={inputStyle}
            />
            {browserAction === 'type' && (
              <>
                <label style={mono} htmlFor="operator-browser-type">Browser type text</label>
                <input
                  id="operator-browser-type"
                  value={browserTypeText}
                  maxLength={MAX_TYPE_TEXT}
                  onChange={(event) => setBrowserTypeText(event.target.value)}
                  style={inputStyle}
                />
              </>
            )}
          </div>
          <button className="tool-btn" type="button" onClick={addBrowserStep} style={{ marginTop: 6 }}>add browser step</button>
          <ol aria-label="browser plan" style={{ margin: '5px 0', paddingLeft: 22 }}>
            {browserPlan.map((step, index) => (
              <li key={index} style={mono}>
                {describeBrowserStep(step)}
                {step.action === 'type' ? <> · <span>{step.text.length} characters</span></> : null}{' '}
                <button
                  className="tool-btn"
                  type="button"
                  aria-label={`remove browser step ${index + 1}`}
                  onClick={() => replaceBrowserPlan(browserPlanRef.current.filter((_, itemIndex) => itemIndex !== index))}
                >×</button>
              </li>
            ))}
          </ol>
          <div style={{ display: 'flex', gap: 6 }}>
            <button className="tool-btn" type="button" disabled={browserBusy !== null} onClick={checkPolicy}>check policy</button>
            <button className="tool-btn" type="button" disabled={browserBusy !== null} onClick={previewBrowserPlan}>preview browser plan</button>
          </div>
          <Alert value={browserError} />
          <BrowserResult check={browserCheck} preview={browserPreview} />
        </fieldset>

        <fieldset style={fieldsetStyle}>
          <legend style={{ ...mono, color: 'var(--accent-light)' }}>Governed desktop</legend>
          <p style={{ ...mono, color: 'var(--ink-3)' }}>
            Desktop actuation is default-off and requires an explicitly enabled, isolated host.
          </p>
          <p style={{ ...mono, color: 'var(--ink-3)' }}>
            Mutating work is queued through ToolRPC / Decision Inbox; this panel cannot approve it.
          </p>
          <div style={{ display: 'grid', gridTemplateColumns: '120px 1fr', gap: 6 }}>
            <label style={mono} htmlFor="operator-desktop-action">Desktop action</label>
            <select
              id="operator-desktop-action"
              value={desktopAction}
              disabled={desktopBusy === 'run'}
              onChange={(event) => { setDesktopAction(event.target.value as CanonicalDesktopAction); setDesktopPrimary(''); setDesktopTypeText(''); }}
              style={inputStyle}
            >
              {(['read', 'locate', 'click', 'type', 'launch'] as CanonicalDesktopAction[]).map((action) => <option key={action}>{action}</option>)}
            </select>
            <label style={mono} htmlFor="operator-desktop-primary">{desktopPrimaryLabel}</label>
            <input
              id="operator-desktop-primary"
              aria-label={desktopPrimaryLabel}
              value={desktopPrimary}
              disabled={desktopBusy === 'run'}
              maxLength={desktopAction === 'launch' ? 32 : MAX_SELECTOR}
              onChange={(event) => setDesktopPrimary(event.target.value)}
              style={inputStyle}
            />
            {desktopAction === 'type' && (
              <>
                <label style={mono} htmlFor="operator-desktop-type">Desktop type text</label>
                <input
                  id="operator-desktop-type"
                  value={desktopTypeText}
                  disabled={desktopBusy === 'run'}
                  maxLength={MAX_TYPE_TEXT}
                  onChange={(event) => setDesktopTypeText(event.target.value)}
                  style={inputStyle}
                />
              </>
            )}
          </div>
          <button className="tool-btn" type="button" disabled={desktopBusy === 'run'} onClick={addDesktopStep} style={{ marginTop: 6 }}>add desktop step</button>
          <ol aria-label="desktop plan" style={{ margin: '5px 0', paddingLeft: 22 }}>
            {desktopSteps.map((step, index) => (
              <li key={index} style={mono}>
                {describeDesktopStep(step)}
                {step.action === 'type' ? <> · <span>{step.args.text.length} characters</span></> : null}{' '}
                <button
                  className="tool-btn"
                  type="button"
                  aria-label={`remove desktop step ${index + 1}`}
                  disabled={desktopBusy === 'run'}
                  onClick={() => replaceDesktopSteps(desktopStepsRef.current.filter((_, itemIndex) => itemIndex !== index))}
                >×</button>
              </li>
            ))}
          </ol>
          {desktopPreview && (
            <ol aria-label="desktop preview result" style={{ margin: '5px 0', paddingLeft: 22 }}>
              {desktopPreview.map((row, index) => <li key={index} style={mono}>{row.action} · {row.decision}</li>)}
            </ol>
          )}
          <div style={{ display: 'flex', gap: 6 }}>
            <button className="tool-btn" type="button" disabled={desktopBusy !== null} onClick={previewDesktopPlan}>preview desktop plan</button>
            <button className="tool-btn" type="button" disabled={desktopBusy !== null || desktopGrant === null} onClick={runDesktopPlan}>submit governed plan</button>
          </div>
          <Alert value={desktopError} />
          <DesktopOutcomeRegion value={desktopOutcome} />
        </fieldset>
      </div>
    </div>
  );
}
