// @ts-nocheck
/* H262 — a write that makes retention delete deeper than a person approved goes to the
   approval queue: the hub answers 202 with the task id and the gated keys, and the
   Settings panel says the change was sent to Approvals (it is not "saved"). Retention on
   with nothing approved deletes nothing: the Retention category says so and offers to
   confirm (the stored values sent again, which queues them). A reset that keeps a
   retention setting, and an import the hub would refuse, say so; the Decision Inbox card
   shows what the change would delete. fetch is mocked. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor, fireEvent, cleanup } from '@testing-library/react';
import { SettingsPanel, DecisionInboxPanel } from '../gap';
import { ResetCategory, SettingsTransfer, UndoReset } from '../panels/settings-tools';
import { RETENTION_STATE_PATH, refusedWhy, retentionConfirmValues, saveOrder } from '../panels/retention';

let calls;
let putReply;
let state;
let settings;

function reply(status, body) {
  return { ok: status < 400, status, json: async () => body, text: async () => JSON.stringify(body) };
}

const CURRENT = {
  'retention.enabled': true, 'retention.conversation_ttl_days': 90, 'retention.audit_ttl_days': 365,
  'retention.ingestion_ttl_days': 0, 'retention.artifact_ttl_days': 0, 'memory.auto_archive_days': 30,
};

const SETTINGS = {
  retention: [
    { key: 'enabled', value: true, default: false, source: 'set', label: 'Enable data-retention sweeps', kind: 'toggle' },
    { key: 'audit_ttl_days', value: 365, default: 365, source: 'default', label: 'Prune audit-log rows older than', kind: 'number' },
    { key: 'min_interval_hours', value: 24, default: 24, source: 'default', label: 'Run the sweep at most every', kind: 'number' },
  ],
  system: [{ key: 'log_level', value: 'INFO', default: 'INFO', source: 'default', label: 'Log level', kind: 'select', opts: ['INFO', 'DEBUG'] }],
};

beforeEach(() => {
  cleanup();
  try { localStorage.clear(); localStorage.setItem('hud.admin_token', 'admin-secret'); } catch { /* ignore */ }
  calls = [];
  putReply = null;
  settings = SETTINGS;
  state = { current: CURRENT, approved: null, awaiting_approval: true, horizons: {}, sweep: {} };
  global.fetch = vi.fn(async (url, init = {}) => {
    const u = String(url).replace(/^https?:\/\/[^/]+/, '');
    const method = init.method || 'GET';
    const body = init.body ? JSON.parse(init.body) : undefined;
    calls.push({ method, url: u, body });
    if (u === '/api/admin/settings') return reply(200, settings);
    if (u === '/api/admin/retention') return reply(200, state);
    if (u === '/api/admin/settings/resets') return reply(200, { resets: [] });
    if (method === 'PUT' && putReply) return putReply(u, body);
    if (method === 'PUT') return reply(200, { updated: Object.keys(body.values).length });
    if (u === '/api/admin/settings/retention/reset') {
      if (body?.dry_run) return reply(200, { dry_run: true, changes: [], kept: [], retention_kept: ['retention.enabled'], overridden: [] });
      return reply(200, { ok: true, reset: ['min_interval_hours'], undo: 3, kept: [], retention_kept: ['retention.enabled'], overridden: [] });
    }
    if (u === '/api/admin/settings/import') {
      return reply(200, { dry_run: true, count: 1, changes: [{ setting: 'retention.audit_ttl_days', from: 365, to: 30 }],
        guards: [], retention_needs_approval: ['retention.audit_ttl_days'] });
    }
    return reply(404, { error: 'unexpected' });
  });
});

const puts = () => calls.filter((c) => c.method === 'PUT');

describe('Settings → sent to Approvals — H262', () => {
  it('a 202 says the gated keys went to Approvals, not that they were saved', async () => {
    putReply = (u, body) => reply(202, { updated: 1, category: 'retention', pending: 42, gated: ['retention.audit_ttl_days'] });
    state = { ...state, awaiting_approval: false, approved: { values: CURRENT } };
    render(<SettingsPanel />);
    await screen.findByText('Prune audit-log rows older than');
    const boxes = screen.getAllByRole('spinbutton');
    fireEvent.change(boxes[0], { target: { value: '30' } });
    fireEvent.change(boxes[1], { target: { value: '12' } });
    fireEvent.click(screen.getByText(/save 2 changes/));
    const note = await screen.findByTestId('sent-to-approvals');
    expect(note.textContent).toContain('sent to Approvals');
    expect(note.textContent).toContain('retention.audit_ttl_days');
    expect(note.textContent).toContain('42');
    expect(puts()[0].body).toEqual({ values: { audit_ttl_days: 30, min_interval_hours: 12 } });
    // the queued edit is not kept as unsaved (a second save would queue it twice)
    await waitFor(() => expect(screen.queryByText(/save \d change/)).toBeNull());
  });

  it('a plain 200 save shows no Approvals note', async () => {
    render(<SettingsPanel />);
    await screen.findByText('Log level');
    fireEvent.change(screen.getAllByRole('combobox')[0], { target: { value: 'DEBUG' } });
    fireEvent.click(screen.getByText(/save 1 change/));
    await screen.findByText('updated 1');
    expect(screen.queryByTestId('sent-to-approvals')).toBeNull();
  });
});

describe('Settings → Retention not confirmed — H262', () => {
  it('names the values it would confirm: the stored retention keys of the retention category', () => {
    expect(retentionConfirmValues(CURRENT)).toEqual({ enabled: true, conversation_ttl_days: 90, audit_ttl_days: 365,
      ingestion_ttl_days: 0, artifact_ttl_days: 0 });
    expect(retentionConfirmValues(null)).toEqual({});
  });

  it('shows the banner when retention is on with nothing approved, and Confirm re-sends the PUT', async () => {
    putReply = (u, body) => reply(202, { updated: 0, category: 'retention', pending: 7,
      gated: Object.keys(body.values).map((k) => `retention.${k}`).sort() });
    render(<SettingsPanel />);
    const banner = await screen.findByTestId('retention-unconfirmed');
    expect(banner.textContent).toContain('Retention is on but not confirmed');
    expect(banner.textContent).toContain('deletes nothing');
    expect(calls.some((c) => c.url === RETENTION_STATE_PATH)).toBe(true);
    fireEvent.click(screen.getByRole('button', { name: 'confirm retention settings' }));
    await waitFor(() => expect(puts()).toHaveLength(1));
    expect(puts()[0].url).toBe('/api/admin/settings/retention');
    expect(puts()[0].body).toEqual({ values: retentionConfirmValues(CURRENT) });
    const sent = await screen.findByTestId('retention-confirm-sent');
    expect(sent.textContent).toContain('sent to Approvals');
    expect(sent.textContent).toContain('retention.enabled');
    expect(sent.textContent).toContain('7');
    // a second confirm would queue a second card
    expect(screen.queryByRole('button', { name: 'confirm retention settings' })).toBeNull();
  });

  it('no banner once a snapshot is approved, or with retention off', async () => {
    state = { ...state, awaiting_approval: false, approved: { values: CURRENT } };
    render(<SettingsPanel />);
    await screen.findByText('Prune audit-log rows older than');
    await waitFor(() => expect(calls.some((c) => c.url === RETENTION_STATE_PATH)).toBe(true));
    expect(screen.queryByTestId('retention-unconfirmed')).toBeNull();
  });

  it('a refused confirm says why (the queue could not take it)', async () => {
    putReply = () => reply(503, { error: 'retention_needs_approval', reason: 'approval_queue_unavailable', gated: ['retention.enabled'] });
    render(<SettingsPanel />);
    await screen.findByTestId('retention-unconfirmed');
    fireEvent.click(screen.getByRole('button', { name: 'confirm retention settings' }));
    const alert = await screen.findByTestId('retention-confirm-refused');
    expect(alert.textContent).toContain('not sent');
    expect(alert.textContent).toContain('approval_queue_unavailable');
    expect(screen.getByRole('button', { name: 'confirm retention settings' })).toBeTruthy();
  });

  it('does not ask for the retention state when no Retention category is shown', async () => {
    settings = { system: SETTINGS.system };
    render(<SettingsPanel />);
    await screen.findByText('Log level');
    await new Promise((r) => setTimeout(r, 20));
    expect(calls.some((c) => c.url === RETENTION_STATE_PATH)).toBe(false);
    expect(screen.queryByTestId('retention-unconfirmed')).toBeNull();
  });
});

describe('Settings tools — a retention setting kept or refused — H262', () => {
  it('a reset names the retention settings it kept for approval', async () => {
    render(<ResetCategory cat="retention" count={3} />);
    fireEvent.click(screen.getByRole('button', { name: 'reset retention' }));
    fireEvent.click(await screen.findByRole('button', { name: 'confirm reset retention' }));
    const note = await screen.findByText(/reset 1/);
    expect(note.textContent).toContain('retention.enabled kept (needs approval)');
  });

  it('an import the hub would refuse says which settings need approval and offers no apply', async () => {
    render(<SettingsTransfer />);
    fireEvent.change(screen.getByLabelText('settings document'), { target: { value: '{"settings": {"retention": {"audit_ttl_days": 30}}}' } });
    fireEvent.click(screen.getByText('preview import'));
    const alert = await screen.findByTestId('import-needs-approval');
    expect(alert.textContent).toContain('retention.audit_ttl_days');
    expect(alert.textContent).toContain('Settings → Retention');
    expect(screen.queryByText(/apply 1 change/)).toBeNull();
  });
});

describe('Decision Inbox — the retention card — H262', () => {
  it('shows the horizons and what the change would delete', async () => {
    global.fetch = vi.fn(async (url) => {
      const u = String(url);
      if (u.includes('/autonomy/tasks')) {
        return reply(200, { tasks: [{ id: 42, kind: 'settings.retention', risk_tier: 3, status: 'blocked',
          title: 'Retention: delete deeper (retention.audit_ttl_days=30)',
          payload: { values: { retention: { audit_ttl_days: 30 } }, before: CURRENT, reversible: false,
            preview: { horizons: { conversations: 90, audit: 30, ingestion: null, artifacts: null },
              approved: { conversations: 90, audit: 365, ingestion: null, artifacts: null },
              widened: ['audit'], would_delete: { archived_chats: 0, audit_rows: 1234 } } } }] });
      }
      return reply(200, {});
    });
    render(<DecisionInboxPanel />);
    const card = await screen.findByTestId('retention-card');
    expect(card.textContent).toContain('audit');
    expect(card.textContent).toContain('365 days → 30 days');
    expect(card.textContent).toContain('1234 audit rows');
    expect(card.textContent).toContain('0 archived chats');
    expect(card.textContent).toContain('cannot be undone');
  });

  it('a first confirmation (nothing approved) and an unknown count read plainly', async () => {
    global.fetch = vi.fn(async (url) => {
      const u = String(url);
      if (u.includes('/autonomy/tasks')) {
        return reply(200, { tasks: [{ id: 43, kind: 'settings.retention', risk_tier: 3, status: 'blocked', title: 'Retention',
          payload: { preview: { horizons: { conversations: 90, audit: 365, ingestion: null, artifacts: null }, approved: null,
            widened: ['conversations', 'audit'], would_delete: { archived_chats: 5, audit_rows: null } } } }] });
      }
      return reply(200, {});
    });
    render(<DecisionInboxPanel />);
    const card = await screen.findByTestId('retention-card');
    expect(card.textContent).toContain('nothing approved yet');
    expect(card.textContent).toContain('kept forever → 90 days');
    expect(card.textContent).toContain('5 archived chats');
    expect(card.textContent).toContain('audit rows: unknown');
  });
});

describe('H262 review — counts, the waiting card, readable refusals', () => {
  it('the card counts every class the change deletes, a capped count as a lower bound and the uncounted plainly', async () => {
    global.fetch = vi.fn(async (url) => {
      const u = String(url);
      if (u.includes('/autonomy/tasks')) {
        return reply(200, { tasks: [{ id: 44, kind: 'settings.retention', risk_tier: 3, status: 'blocked', title: 'Retention',
          payload: { preview: { horizons: { conversations: 90, audit: 365, ingestion: 7, artifacts: 30 }, approved: null,
            widened: ['conversations', 'audit', 'ingestion', 'artifacts'],
            would_delete: { archived_chats: { count: 500, more: true }, chats_to_archive: { count: 5, more: false },
              audit_rows: { count: 1234, more: false }, ingestion: { counted: false }, attachments: { counted: false } } } } }] });
      }
      return reply(200, {});
    });
    render(<DecisionInboxPanel />);
    const card = await screen.findByTestId('retention-card');
    expect(card.textContent).toContain('500+ archived chats past the horizon now (gone within 7 days)');
    expect(card.textContent).toContain('5 chats archived by the next sweep, deleted 7 days later');
    expect(card.textContent).toContain('1234 audit rows');
    expect(card.textContent).toContain('ingestion: not counted');
    expect(card.textContent).toContain('attachments: not counted');
  });

  it('a card already waiting replaces Confirm with a pointer to Approvals', async () => {
    state = { ...state, pending_task: 9 };
    render(<SettingsPanel />);
    const banner = await screen.findByTestId('retention-unconfirmed');
    expect(banner.textContent).toContain('waiting in Approvals');
    expect(banner.textContent).toContain('task 9');
    expect(screen.queryByRole('button', { name: 'confirm retention settings' })).toBeNull();
  });

  it('a refused save names the hub\'s reason before its error code', async () => {
    putReply = () => reply(503, { error: 'retention_needs_approval', reason: 'approval_queue_unavailable', gated: ['retention.audit_ttl_days'] });
    state = { ...state, awaiting_approval: false };
    render(<SettingsPanel />);
    await screen.findByText('Prune audit-log rows older than');
    fireEvent.change(screen.getAllByRole('spinbutton')[0], { target: { value: '30' } });
    fireEvent.click(screen.getByText(/save 1 change/));
    const alert = await screen.findByText(/not saved ·/);
    expect(alert.textContent).toContain('approval_queue_unavailable');
    expect(refusedWhy({ body: { error: 'e', reason: 'r' } })).toBe('r');
    expect(refusedWhy({ body: { error: 'e' } })).toBe('e');
  });

  it('saveOrder sends the ungated one first: retention when it is on, memory when it is off', () => {
    expect(saveOrder(['memory', 'system', 'retention'], true)).toEqual(['retention', 'memory', 'system']);
    expect(saveOrder(['retention', 'system', 'memory'], false)).toEqual(['memory', 'retention', 'system']);
    expect(saveOrder(['system', 'voice'], false)).toEqual(['system', 'voice']);
  });

  it('with retention off a save sends memory first, so turning both on at once gives a card that applies', async () => {
    settings = {
      memory: [{ key: 'auto_archive_days', value: 0, default: 0, source: 'default', label: 'Archive chats idle for', kind: 'number' }],
      retention: SETTINGS.retention.map((it) => (it.key === 'enabled' ? { ...it, value: false } : it)),
      system: SETTINGS.system,
    };
    state = { ...state, awaiting_approval: false };
    render(<SettingsPanel />);
    await screen.findByText('Archive chats idle for');
    const boxes = screen.getAllByRole('spinbutton');
    fireEvent.change(boxes[1], { target: { value: '900' } });      // retention edited first
    fireEvent.change(boxes[0], { target: { value: '30' } });       // then memory
    fireEvent.click(screen.getByText(/save 2 changes/));
    await waitFor(() => expect(calls.filter((c) => c.method === 'PUT').length).toBe(2));
    const puts = calls.filter((c) => c.method === 'PUT').map((c) => c.url);
    expect(puts).toEqual(['/api/admin/settings/memory', '/api/admin/settings/retention']);
  });

  it('with retention on a save sends retention before memory, so the memory card previews what retention will hold (review round 2)', async () => {
    settings = {
      memory: [{ key: 'auto_archive_days', value: 0, default: 0, source: 'default', label: 'Archive chats idle for', kind: 'number' }],
      ...SETTINGS,
    };
    state = { ...state, awaiting_approval: false };
    render(<SettingsPanel />);
    await screen.findByText('Archive chats idle for');
    const boxes = screen.getAllByRole('spinbutton');
    fireEvent.change(boxes[0], { target: { value: '30' } });       // memory edited first
    fireEvent.change(boxes[1], { target: { value: '900' } });      // then retention
    fireEvent.click(screen.getByText(/save 2 changes/));
    await waitFor(() => expect(calls.filter((c) => c.method === 'PUT').length).toBe(2));
    const puts = calls.filter((c) => c.method === 'PUT').map((c) => c.url);
    expect(puts).toEqual(['/api/admin/settings/retention', '/api/admin/settings/memory']);
  });

  it('a refused undo names the hub\'s reason', async () => {
    global.fetch = vi.fn(async (url, init = {}) => {
      const u = String(url).replace(/^https?:\/\/[^/]+/, '');
      if (u === '/api/admin/settings/resets') {
        return reply(200, { resets: [{ id: 3, at: 1790000000, scope: 'retention', settings: ['retention.enabled'], undone: false }] });
      }
      if (u === '/api/admin/settings/undo') {
        return reply(409, { error: 'retention_needs_approval', reason: 'needs approval in Settings → Retention: retention.enabled',
          settings: ['retention.enabled'] });
      }
      return reply(404, {});
    });
    render(<UndoReset />);
    fireEvent.click(await screen.findByRole('button', { name: /undo…/ }));
    fireEvent.click(await screen.findByRole('button', { name: /undo the reset/ }));
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain('needs approval in Settings → Retention');
  });
});
