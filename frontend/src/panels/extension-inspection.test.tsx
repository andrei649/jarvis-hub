// @ts-nocheck
import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { CONSOLE_PANELS } from '../console-routes';
import { ConsoleOverlay } from '../gap';
import { ExtensionInspectionPanel, EXTENSIONS_INSPECTION_PATH } from './extension-inspection';

const active = {
  mode: 'inspection_only', reason: 'activated', extensions: [{
    id: 'boats', version: '1.0.0', reason: 'activated',
    source: 'acquired_manifest_projection', lifecycle_status: 'active',
    signature_verified: true, approval_verified: false, quarantine_state: 'not_inspected',
    execution_available: true,
    declared_tools: ['boats.summarize'], callable_tools: ['boats.summarize'],
    declared_commands: ['boat_report'], callable_commands: ['boat_report'],
    command_requires_args: ['boat_report'], declared_events: ['session.started'],
    capabilities: ['tools', 'commands', 'events.observe'],
  }],
};

function response(body, status = 200) {
  return { ok: status < 400, status, json: async () => body };
}
function hub(handler) {
  const calls = [];
  global.fetch = vi.fn(async (url, init = {}) => {
    calls.push({ url: String(url), init });
    return handler(String(url), init, calls.length);
  });
  return calls;
}

beforeEach(() => {
  localStorage.clear();
  localStorage.setItem('hud.user_token', 'test-user');
  vi.restoreAllMocks();
  window.history.replaceState({}, '', '/v2/console/extensions');
});

describe('Extension inspection panel', () => {
  it('is placed beside acquisition in Build', () => {
    expect(CONSOLE_PANELS).toContainEqual({
      id: 'extensions', label: 'Extensions', group: 'Build', component: 'ExtensionInspectionPanel',
    });
    const acquisition = CONSOLE_PANELS.findIndex((entry) => entry.id === 'acquisition');
    const extensions = CONSOLE_PANELS.findIndex((entry) => entry.id === 'extensions');
    expect(extensions).toBe(acquisition + 1);
  });

  it('mounts the panel through the Console component registry', async () => {
    hub(() => response(active));
    render(<ConsoleOverlay panelId="extensions" onClose={() => {}} />);
    expect(await screen.findByRole('heading', { name: 'Extensions' })).toBeTruthy();
    expect(await screen.findByRole('region', { name: 'Extension boats' })).toBeTruthy();
  });

  it('separates declared and callable tools/commands and only makes the user-guarded GET', async () => {
    localStorage.setItem('hud.user_token', 'user-token');
    localStorage.setItem('hud.admin_token', 'admin-token');
    const calls = hub(() => response(active));
    render(<ExtensionInspectionPanel />);

    expect(await screen.findByRole('region', { name: 'Extension boats' })).toBeTruthy();
    expect(within(screen.getByRole('region', { name: 'Declared tools' })).getByText('boats.summarize')).toBeTruthy();
    expect(within(screen.getByRole('region', { name: 'Currently callable tools' })).getByText('boats.summarize')).toBeTruthy();
    expect(within(screen.getByRole('region', { name: 'Declared commands' })).getByText('boat_report')).toBeTruthy();
    expect(within(screen.getByRole('region', { name: 'Currently callable commands' })).getByText('boat_report')).toBeTruthy();
    expect(screen.getAllByText('requires arguments')).toHaveLength(2);
    expect(screen.getByText('Activated')).toBeTruthy();
    expect(screen.getByText(/signature verified/i)).toBeTruthy();
    expect(screen.getByText(/owner approval not verified/i)).toBeTruthy();
    expect(screen.getByText(/Signature verification, owner approval, and current callability are separate facts/i)).toBeTruthy();
    expect(screen.getByText('Quarantine not checked')).toBeTruthy();
    expect(screen.queryByText(/ready/i)).toBeNull();
    expect(screen.getByText('Inspect declared and currently available tools and commands.')).toBeTruthy();
    expect(screen.getAllByRole('button').map((button) => button.getAttribute('aria-label'))).toEqual(['Reload']);
    expect(calls).toHaveLength(1);
    expect(calls[0].url).toContain(EXTENSIONS_INSPECTION_PATH);
    expect(calls[0].init.method || 'GET').toBe('GET');
    expect(calls[0].init.headers['X-User-Token']).toBe('user-token');
    expect(calls[0].init.headers['X-Admin-Token']).toBeUndefined();
  });

  it.each([
    ['acquisition_disabled', 'Acquisition is disabled.'],
    ['acquisition_not_composed', 'The acquisition runtime is not composed.'],
  ])('shows bounded unavailable state %s without implying readiness', async (reason, message) => {
    const unavailable = { mode: 'inspection_only', reason, extensions: [] };
    hub(() => response(unavailable));
    render(<ExtensionInspectionPanel />);
    expect(await screen.findByText(message)).toBeTruthy();
    expect(screen.getByText(/No extensions reported in this inspection/)).toBeTruthy();
    expect(screen.queryByText(/ready/i)).toBeNull();
  });

  it.each([
    ['acquired_inactive', 'Inactive', false],
    ['acquired_integrity_unverified', 'Integrity not verified', false],
    ['sdk_dispatch_unavailable', 'No callable surface', true],
  ])('uses plain status labels for %s', async (reason, label, signatureVerified) => {
    const report = structuredClone(active);
    report.reason = 'sdk_dispatch_unavailable';
    report.extensions[0] = {
      ...report.extensions[0], reason, signature_verified: signatureVerified,
      execution_available: false, callable_tools: [], callable_commands: [],
    };
    hub(() => response(report));
    render(<ExtensionInspectionPanel />);
    expect(await screen.findByText(label)).toBeTruthy();
    expect(screen.queryByText(reason)).toBeNull();
  });

  it.each([
    [401, 'Sign in to inspect extensions.'],
    [403, 'This account cannot inspect extensions.'],
  ])('shows a fixed read error for HTTP %s and hides prior data', async (status, message) => {
    const calls = hub((_url, _init, count) => count === 1
      ? response(active)
      : response({ detail: 'private exception body must not be rendered' }, status));
    render(<ExtensionInspectionPanel />);
    expect(await screen.findByRole('region', { name: 'Extension boats' })).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Reload' }));
    expect((await screen.findByRole('alert')).textContent).toContain(message);
    expect(screen.queryByRole('region', { name: 'Extension boats' })).toBeNull();
    expect(document.body.textContent).not.toContain('private exception body');
    expect(calls.length).toBe(status === 401 ? 3 : 2);
  });

  it('hides stale data while refreshing, then keeps it hidden after a failed refresh', async () => {
    let finish;
    const calls = hub((_url, _init, count) => count === 1
      ? response(active)
      : new Promise((resolve) => { finish = resolve; }));
    render(<ExtensionInspectionPanel />);
    expect(await screen.findByRole('region', { name: 'Extension boats' })).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Reload' }));
    expect(await screen.findByText('Checking extension state…')).toBeTruthy();
    expect(screen.queryByRole('region', { name: 'Extension boats' })).toBeNull();
    finish(response({ detail: 'private exception body must not be rendered' }, 503));
    expect((await screen.findByRole('alert')).textContent).toContain('The extension inspection service is unavailable.');
    expect(screen.queryByRole('region', { name: 'Extension boats' })).toBeNull();
    expect(document.body.textContent).not.toContain('private exception body');
    expect(calls).toHaveLength(2);
  });

  it.each([
    (report) => { report.extensions[0].callable_commands = ['boat_report', 'delete_everything']; },
    (report) => { report.extensions[0].signature_verified = false; },
  ])('rejects widened or unverified callable claims', async (mutate) => {
    const malformed = structuredClone(active);
    mutate(malformed);
    hub(() => response(malformed));
    render(<ExtensionInspectionPanel />);
    expect((await screen.findByRole('alert')).textContent).toContain('Extension inspection returned invalid data.');
    expect(document.body.textContent).not.toContain('delete_everything');
    expect(screen.queryByRole('region', { name: 'Extension boats' })).toBeNull();
  });

  it('does not carry an unmounted request into a later panel instance', async () => {
    let finishOld;
    const calls = hub((_url, _init, count) => count === 1
      ? new Promise((resolve) => { finishOld = resolve; })
      : response({ ...active, extensions: [{ ...active.extensions[0], id: 'current',
        declared_tools: ['current.summarize'], callable_tools: ['current.summarize'] }] }));
    const first = render(<ExtensionInspectionPanel />);
    first.unmount();
    finishOld(response({ ...active, extensions: [{ ...active.extensions[0], id: 'stale',
      declared_tools: ['stale.summarize'], callable_tools: ['stale.summarize'] }] }));
    render(<ExtensionInspectionPanel />);
    expect(await screen.findByRole('region', { name: 'Extension current' })).toBeTruthy();
    expect(screen.queryByRole('region', { name: 'Extension stale' })).toBeNull();
    expect(calls).toHaveLength(2);
  });
});
