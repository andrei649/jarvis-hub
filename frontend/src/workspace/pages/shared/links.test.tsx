import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { renderApp } from '../../test/render';
import { makeUser, mockFetch, shellRoutes, signedIn, type RouteHandler } from '../../test/mockApi';

const NOW = Date.now() / 1000;

function note(id: number, title: string, link: string) {
  return { id, kind: 'info', title, body: '', link, created_at: NOW - 60, read_at: null };
}

const DOCUMENT = {
  id: 5, title: 'Contract cadru', filename: 'contract.pdf', mime: 'application/pdf', size_bytes: 1000, department_id: 1,
  visibility: 'department', status: 'ready', error: null, page_count: 2, chunk_count: 6, uploader: null, created_at: NOW,
  can_delete: false, can_reindex: false, can_publish: false,
};

function boot(path: string, routes: Record<string, RouteHandler>) {
  const mock = mockFetch({
    'GET /api/workspace/session': signedIn(makeUser({ role: 'member' })),
    ...shellRoutes(),
    'POST /api/workspace/notifications/read': { unread_count: 0 },
    ...routes,
  });
  renderApp(path);
  return mock;
}

async function openNotification(title: RegExp) {
  fireEvent.click(await screen.findByRole('button', { name: /^Notificări/ }));
  const panel = await screen.findByRole('dialog', { name: 'Notificări' });
  fireEvent.click(await within(panel).findByRole('button', { name: title }));
}

describe('Notification links land on the screen they name', () => {
  it('opens a finished report run', async () => {
    boot('/workspace/assistant', {
      'GET /api/workspace/conversations': { conversations: [] },
      'GET /api/workspace/notifications': { items: [note(1, 'Raportul este gata', '/workspace/report-runs/40')], unread_count: 1 },
      'GET /api/workspace/report-runs/40': {
        id: 40, report_id: 3, status: 'succeeded', trigger: 'schedule', triggered_by: null, model: 'qwen', route: 'local', locality: 'local',
        error_code: null, error: null, shared_company: false, delivered_to: ['sef@acme.ro'], started_at: NOW - 60, finished_at: NOW - 5,
        created_at: NOW - 61, content_md: '## Rezumat\n\nTotul este în regulă.', citations: [], can_share: false, can_email: false,
        report: { id: 3, name: 'Raport săptămânal', department_id: 1 },
      },
    });
    await openNotification(/Raportul este gata/);
    await waitFor(() => expect(window.location.pathname).toBe('/workspace/report-runs/40'));
    expect(await screen.findByRole('heading', { name: 'Rezumat' })).toBeTruthy();
    expect(screen.getByText('sef@acme.ro')).toBeTruthy();
  });

  it('opens a published document in its preview drawer', async () => {
    boot('/workspace/assistant', {
      'GET /api/workspace/conversations': { conversations: [] },
      'GET /api/workspace/notifications': { items: [note(2, 'Document publicat în companie', '/workspace/documents?document=5')], unread_count: 1 },
      'GET /api/workspace/documents': { documents: [DOCUMENT] },
      'GET /api/workspace/documents/5': { ...DOCUMENT, preview: 'Primul paragraf.' },
    });
    await openNotification(/Document publicat în companie/);
    const drawer = await screen.findByRole('dialog', { name: 'Contract cadru' });
    expect(await within(drawer).findByText('Primul paragraf.')).toBeTruthy();
  });
});

describe('Email availability for administrators', () => {
  it('reads the SMTP settings when the eligibility probe does not say, and hides the action when unconfigured', async () => {
    const answer = {
      id: 12, role: 'assistant', content: 'Răspuns.', citations: [], status: 'complete', error_code: null, model: 'qwen',
      locality: 'local', latency_ms: 900, feedback: null, created_at: NOW,
    };
    const mock = mockFetch({
      'GET /api/workspace/session': signedIn(makeUser({ role: 'admin' })),
      ...shellRoutes(),
      'GET /api/workspace/conversations': { conversations: [] },
      'GET /api/workspace/conversations/7': { conversation: { id: 7, title: 'T', department_id: 1, updated_at: NOW }, messages: [answer] },
      'GET /api/workspace/approvals/eligible': { count: 1 },
      'GET /api/workspace/admin/smtp': { host: '', port: 0, security: 'starttls', username: '', from_address: '', from_name: '', allowed_domains: [], has_password: false },
    });
    renderApp('/workspace/assistant/7');
    expect(await screen.findByRole('button', { name: 'Răspuns util' })).toBeTruthy();
    await waitFor(() => expect(mock.find('GET', '/api/workspace/admin/smtp')).toHaveLength(1));
    await waitFor(() => expect(screen.queryByRole('button', { name: 'Trimite pe email' })).toBeNull());
  });
});
