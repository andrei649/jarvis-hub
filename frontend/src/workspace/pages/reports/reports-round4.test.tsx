/* QA round 4 on Reports (frontend fixer).

   NWS-20: the server stores a run `succeeded` before it talks to the mail server, with
   `delivery_state: 'pending'` until the mail server answered. The live run page keeps polling
   while the email is on the way, says so ("se trimite pe email…"), then shows to whom it went
   or why it was not sent — and says that once in its status region — with no reload; the run
   history does the same. A delivery cut short by a restart (`delivery_interrupted`) says nobody
   knows whether it arrived, never that it was not sent.
   UX-23: a run the model could not write says why in the chat's own words (`error_reason`) and
   with the chat's next step, for members and admins alike.
   UX-22: the run history has four columns (what started a run sits under its date, "shared"
   next to its status) so it fits 1024 px, and its locality chip shows the short form with the
   full words as its name and tooltip. That nothing wraps or scrolls is the journey's layout check. */
import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { ModelPosture, Report, ReportRunDetail } from '../../api/types';
import { renderApp } from '../../test/render';
import { makeUser, mockFetch, shellRoutes, signedIn, type RouteHandler } from '../../test/mockApi';
import { sseChannel } from '../../test/streams';
import { RUN_POLL_MS } from './RunView';

const NOW = Date.now() / 1000;

const REPORT: Report = {
  id: 3, department_id: 1, name: 'Raport lunar contracte', instructions: 'Rezumă contractele lunii.', document_ids: [5],
  schedule_kind: 'manual', schedule_time: null, schedule_weekday: null, timezone: 'Europe/Bucharest',
  delivery_emails: ['sef@acme.ro'], delivery_status: 'approved', owner_id: 1, active: true,
  next_run_at: null, last_run_at: null, created_at: NOW - 100, updated_at: NOW - 100,
  last_run: null, can_edit: true, can_run: true,
};

function run(over: Partial<ReportRunDetail> = {}): ReportRunDetail {
  return {
    id: 40, report_id: 3, status: 'succeeded', trigger: 'manual', triggered_by: 1, model: 'qwen2.5', route: 'local', locality: 'local',
    error_code: null, error_reason: null, error: null, shared_company: false, delivered_to: [], delivery_state: null,
    started_at: NOW - 70, finished_at: NOW - 10, created_at: NOW - 75,
    content_md: '# Raport lunar\n\n## Rezumat\n\nPlata se face în 30 de zile.',
    citations: [], can_share: true, can_email: true, share_pending: false,
    report: { id: 3, name: 'Raport lunar contracte', department_id: 1 }, department_name: 'General', ...over,
  };
}

const RUNNING = run({ status: 'running', content_md: null, finished_at: null, delivery_state: null });
const SENDING = run({ delivery_state: 'pending' });
const SENT = run({ delivery_state: 'sent', delivered_to: ['sef@acme.ro'] });
const NOT_SENT = run({ delivery_state: 'failed', error: 'delivery_failed', error_code: 'smtp_failed', error_reason: 'connection_failed' });

const POSTURE_UP: ModelPosture = {
  available: true, backend: 'lm-studio', model: 'qwen', route: 'local', locality: 'local', policy: 'local_only', reason: null, guardrails_mode: null,
};
const POSTURE_DOWN: ModelPosture = { ...POSTURE_UP, available: false, reason: 'model_unreachable' };

function boot(path: string, routes: Record<string, RouteHandler> = {}, role: 'admin' | 'member' = 'member') {
  const mock = mockFetch({
    'GET /api/workspace/session': signedIn(makeUser({ role })),
    ...shellRoutes(),
    'GET /api/workspace/reports': { reports: [REPORT] },
    'GET /api/workspace/reports/3': REPORT,
    'GET /api/workspace/reports/3/runs': { runs: [] },
    'GET /api/workspace/documents': { documents: [] },
    'GET /api/workspace/approvals/eligible': { count: 1, smtp_configured: true },
    ...routes,
  });
  renderApp(path);
  return mock;
}

/** Answers the reads of run 40 in order, then repeats the last one. */
function sequence(...answers: ReportRunDetail[]) {
  let reads = 0;
  return () => { const answer = answers[Math.min(reads, answers.length - 1)]; reads += 1; return answer; };
}

/** The run page's own status region (the one always-mounted live region it announces through). */
function runStatus(): string {
  return document.querySelector('p.ws-sr-only[role="status"]')?.textContent ?? '';
}

async function tick(ms: number) {
  await act(async () => { await vi.advanceTimersByTimeAsync(ms); });
}

afterEach(() => { vi.useRealTimers(); });

describe('Run view → the email outcome arrives on the live page (NWS-20)', () => {
  it('keeps polling while the email is on the way, says so, then shows to whom it went, and stops', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const mock = boot('/workspace/report-runs/40', { 'GET /api/workspace/report-runs/40': sequence(RUNNING, SENDING, SENDING, SENT) });
    expect(await screen.findByText('Raportul se scrie din documente. Poate dura câteva minute.', { selector: '.ws-notice__title' })).toBeTruthy();

    // Written, its email still on the way: the report shows, and the page says it is being sent.
    await tick(RUN_POLL_MS);
    expect(await screen.findByText('Raportul se trimite pe email…', { selector: '.ws-notice__title' })).toBeTruthy();
    expect(screen.getByRole('heading', { name: 'Rezumat' })).toBeTruthy();
    await waitFor(() => expect(runStatus()).toBe('Raportul este gata și se trimite pe email…'));
    expect(screen.queryByText('Trimis pe email către')).toBeNull();

    // Still pending: still polling (the old rule stopped at "succeeded" and never saw the outcome).
    await tick(RUN_POLL_MS);
    await tick(RUN_POLL_MS);
    const meta = (await screen.findByText('Trimis pe email către')).closest('dl') as HTMLElement;
    expect(within(meta).getByText('sef@acme.ro')).toBeTruthy();
    await waitFor(() => expect(screen.queryByText('Raportul se trimite pe email…')).toBeNull());
    await waitFor(() => expect(runStatus()).toBe('Raportul a fost trimis pe email către sef@acme.ro.'));
    expect(window.location.pathname).toBe('/workspace/report-runs/40');

    // Settled: the polling stops.
    const settled = mock.find('GET', '/api/workspace/report-runs/40').length;
    await tick(RUN_POLL_MS * 4);
    expect(mock.find('GET', '/api/workspace/report-runs/40')).toHaveLength(settled);
  });

  it('opened while the email is on the way, it says so, then why it was not sent — in words, once', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const mock = boot('/workspace/report-runs/40', { 'GET /api/workspace/report-runs/40': sequence(SENDING, SENDING, NOT_SENT) });
    expect(await screen.findByText('Raportul se trimite pe email…', { selector: '.ws-notice__title' })).toBeTruthy();
    await waitFor(() => expect(runStatus()).toBe('Raportul este gata și se trimite pe email…'));

    await tick(RUN_POLL_MS);
    const notice = (await screen.findByText('Raportul este gata, dar emailul nu a fost trimis')).closest('.ws-notice') as HTMLElement;
    // A member reads the plain sentence and is told to let an admin know; what to check in the
    // email settings is the admin's (next test).
    expect(within(notice).getByText('Serverul de email a refuzat mesajul sau nu a putut fi contactat.')).toBeTruthy();
    expect(within(notice).getByText(/Destinatarii nu au primit această rulare. Anunță un administrator/)).toBeTruthy();
    expect(screen.queryByText('Raportul se trimite pe email…')).toBeNull();
    expect(screen.queryByText(/smtp_failed|connection_failed/)).toBeNull();
    await waitFor(() => expect(runStatus()).toBe('Emailul cu raportul nu a fost trimis: Serverul de email a refuzat mesajul sau nu a putut fi contactat.'));

    const settled = mock.find('GET', '/api/workspace/report-runs/40').length;
    await tick(RUN_POLL_MS * 4);
    expect(mock.find('GET', '/api/workspace/report-runs/40')).toHaveLength(settled);
    // Said once: the region still holds that one sentence, nothing was appended or repeated.
    expect(runStatus()).toBe('Emailul cu raportul nu a fost trimis: Serverul de email a refuzat mesajul sau nu a putut fi contactat.');
  });

  it('gives an admin the mail server\'s own cause, which names what to check', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    boot('/workspace/report-runs/40', { 'GET /api/workspace/report-runs/40': sequence(SENDING, SENDING, NOT_SENT) }, 'admin');
    expect(await screen.findByText('Raportul se trimite pe email…', { selector: '.ws-notice__title' })).toBeTruthy();
    await tick(RUN_POLL_MS);
    const notice = (await screen.findByText('Raportul este gata, dar emailul nu a fost trimis')).closest('.ws-notice') as HTMLElement;
    expect(within(notice).getByText('Serverul de email nu a putut fi contactat. Verifică adresa și portul.')).toBeTruthy();
    expect(within(notice).getByText(/trimite un email de test din Administrare → Email/)).toBeTruthy();
    await waitFor(() => expect(runStatus()).toBe('Emailul cu raportul nu a fost trimis: Serverul de email nu a putut fi contactat. Verifică adresa și portul.'));
  });

  it('a delivery the hub was stopped in the middle of says nobody knows whether it arrived', async () => {
    boot('/workspace/report-runs/40', {
      'GET /api/workspace/report-runs/40': run({ delivery_state: 'failed', error: 'delivery_failed', error_code: 'delivery_interrupted' }),
    });
    const notice = (await screen.findByText('Raportul este gata, dar nu se știe dacă emailul a ajuns')).closest('.ws-notice') as HTMLElement;
    expect(within(notice).getByText('Serverul Nerva s-a oprit în timp ce trimitea emailul; nu se știe dacă destinatarii l-au primit.')).toBeTruthy();
    expect(within(notice).getByText(/trimite raportul din nou cu „Trimite pe email”/)).toBeTruthy();
    // Never "the recipients did not get it": that is not known.
    expect(screen.queryByText(/Destinatarii nu au primit/)).toBeNull();
    expect(screen.queryByText('Raportul este gata, dar emailul nu a fost trimis')).toBeNull();
  });

  it('a run with no approved delivery is not waited for, and an old run without delivery_state reads as before', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const mock = boot('/workspace/report-runs/40', { 'GET /api/workspace/report-runs/40': run({ delivery_state: undefined, delivered_to: ['vechi@acme.ro'] }) });
    expect(await screen.findByText('vechi@acme.ro')).toBeTruthy();
    expect(screen.queryByText('Raportul se trimite pe email…')).toBeNull();
    const reads = mock.find('GET', '/api/workspace/report-runs/40').length;
    await tick(RUN_POLL_MS * 3);
    expect(mock.find('GET', '/api/workspace/report-runs/40')).toHaveLength(reads);
  });
});

describe('Report detail → the history follows a delivery too (NWS-20, UX-22)', () => {
  it('flags a run being emailed, polls until its outcome, and reads a delivery that may not have arrived', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    let reads = 0;
    const mock = boot('/workspace/reports/3', {
      'GET /api/workspace/reports/3/runs': () => {
        reads += 1;
        return { runs: [reads > 2 ? SENT : SENDING, run({ id: 39, created_at: NOW - 900, delivery_state: 'failed', error: 'delivery_failed', error_code: 'delivery_interrupted' })] };
      },
    });
    const table = await screen.findByRole('table', { name: 'Istoricul rulărilor' });
    expect(await within(table).findByText('Se trimite pe email')).toBeTruthy();
    expect(within(table).getByText('Email neconfirmat')).toBeTruthy();
    await tick(4000);
    await tick(4000);
    await waitFor(() => expect(within(table).queryByText('Se trimite pe email')).toBeNull());
    const settled = mock.find('GET', '/api/workspace/reports/3/runs').length;
    await tick(12_000);
    expect(mock.find('GET', '/api/workspace/reports/3/runs')).toHaveLength(settled);
  });

  it('fits four columns: the trigger under the date, "shared" next to the status, the short locality chip', async () => {
    boot('/workspace/reports/3', { 'GET /api/workspace/reports/3/runs': { runs: [run({ shared_company: true, trigger: 'schedule' })] } });
    const table = await screen.findByRole('table', { name: 'Istoricul rulărilor' });
    expect(within(table).getAllByRole('columnheader').map((th) => th.textContent)).toEqual(['Început', 'Stare', 'Durată', 'Unde a fost generat']);
    const [row] = within(table).getAllByRole('row').slice(1);
    const [when, status, , where] = within(row).getAllByRole('cell');
    expect(within(when).getByText('Programată')).toBeTruthy();
    expect(within(status).getByText('Gata')).toBeTruthy();
    expect(within(status).getByText('Partajat în companie')).toBeTruthy();
    // The cell shows „Local"; the chip's name and tooltip are the full words, and the short form
    // is not read on top of them.
    const chip = where.querySelector('.ws-locality') as HTMLElement;
    expect(chip.getAttribute('title')).toBe('Pe serverul companiei');
    expect(within(chip).getByText('Local').getAttribute('aria-hidden')).toBe('true');
    expect(within(chip).getByText('Pe serverul companiei')).toBeTruthy();
  });
});

describe('Run view → a model failure in the chat\'s words (UX-23)', () => {
  it('names the reason the model server gave and the same next step as the chat', async () => {
    boot('/workspace/report-runs/40', {
      'GET /api/workspace/report-runs/40': run({ status: 'failed', content_md: null, error: 'the model is unavailable', error_code: 'model_unavailable', error_reason: 'model_unreachable' }),
    });
    const notice = (await screen.findByText('Raportul nu a putut fi generat', { selector: '.ws-notice__title' })).closest('.ws-notice') as HTMLElement;
    expect(within(notice).getByText('Modelul AI nu este disponibil acum. Serverul modelului nu poate fi contactat (este oprit sau conexiunea s-a întrerupt).')).toBeTruthy();
    expect(within(notice).getByText('Încearcă din nou peste câteva minute. Dacă problema continuă, anunță un administrator.')).toBeTruthy();
    // The admin's fix is for admins.
    expect(within(notice).queryByText(/Administrare → Organizație/)).toBeNull();
    expect(within(notice).queryByRole('link', { name: 'Setările modelului' })).toBeNull();
    expect(screen.queryByText(/model_unreachable|model_unavailable/)).toBeNull();
  });

  it('picks the reason-specific hint when the chat has one, and gives an admin the fix and the link', async () => {
    boot('/workspace/report-runs/40', {
      'GET /api/workspace/report-runs/40': run({ status: 'failed', content_md: null, error_code: 'model_policy_blocked', error_reason: 'data_policy_unacknowledged' }),
    }, 'admin');
    const notice = (await screen.findByText('Raportul nu a putut fi generat', { selector: '.ws-notice__title' })).closest('.ws-notice') as HTMLElement;
    expect(within(notice).getByText('Politica organizației nu permite modelul disponibil acum. Proprietarul serverului Nerva nu a confirmat încă modul în care serverul modelului tratează datele.')).toBeTruthy();
    expect(within(notice).getByText(/^Proprietarul serverului Nerva trebuie să confirme pe server/)).toBeTruthy();
    expect(within(notice).getByText(/^Modelul este deja local, dar rulează pe altă mașină/)).toBeTruthy();
    expect(within(notice).getByRole('link', { name: 'Setările modelului' }).getAttribute('href')).toBe('/workspace/admin/organisation');
    expect(within(notice).getByRole('button', { name: 'Rulează din nou' })).toBeTruthy();
  });

  it('a run that fails live says why in its status region and shows the outage in the chip', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    let down = false;
    boot('/workspace/report-runs/40', {
      'GET /api/workspace/report-runs/40': () => (down
        ? run({ status: 'failed', content_md: null, error_code: 'model_unavailable', error_reason: 'model_unreachable' })
        : RUNNING),
      'GET /api/workspace/model': () => (down ? POSTURE_DOWN : POSTURE_UP),
    });
    expect(await screen.findByRole('button', { name: 'Modelul AI: Local' })).toBeTruthy();
    down = true;
    await tick(RUN_POLL_MS);
    await waitFor(() => expect(runStatus()).toBe('Raportul nu a putut fi generat: Modelul AI nu este disponibil acum. Serverul modelului nu poate fi contactat (este oprit sau conexiunea s-a întrerupt).'));
    expect(await screen.findByRole('button', { name: 'Modelul AI: Indisponibil' })).toBeTruthy();
  });

  it('a run the model wrote while the chip still said "unavailable" brings the chip back at once', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    let up = false;
    boot('/workspace/report-runs/40', {
      'GET /api/workspace/report-runs/40': () => (up ? run() : RUNNING),
      'GET /api/workspace/model': () => (up ? POSTURE_UP : POSTURE_DOWN),
    });
    expect(await screen.findByRole('button', { name: 'Modelul AI: Indisponibil' })).toBeTruthy();
    up = true;
    await tick(RUN_POLL_MS);
    expect(await screen.findByRole('heading', { name: 'Rezumat' })).toBeTruthy();
    // Long before the shell's 30 s poll.
    expect(await screen.findByRole('button', { name: 'Modelul AI: Local' })).toBeTruthy();
  });
});

describe('Assistant → the chip recovers with the first answer after an outage', () => {
  it('an answer that arrives while the chip says "unavailable" re-reads the posture', async () => {
    const channel = sseChannel();
    let up = false;
    const conversation = { id: 7, title: 'Termene de plată', department_id: 1, created_at: NOW - 600, updated_at: NOW - 60 };
    const question = {
      id: 11, role: 'user' as const, content: 'Care e termenul?', citations: [], status: 'complete' as const, error_code: null,
      model: null, locality: null, latency_ms: null, feedback: null, created_at: NOW - 30,
    };
    const answer = { ...question, id: 12, role: 'assistant' as const, content: 'Termenul este de 30 de zile.', model: 'qwen', locality: 'local' as const, latency_ms: 900 };
    const mock = boot('/workspace/assistant/7', {
      'GET /api/workspace/conversations': { conversations: [{ ...conversation, message_count: 0 }] },
      'GET /api/workspace/conversations/7': { conversation, messages: [] },
      'POST /api/workspace/conversations/7/messages': () => channel.response(),
      'GET /api/workspace/model': () => (up ? POSTURE_UP : POSTURE_DOWN),
    });
    expect(await screen.findByRole('button', { name: 'Modelul AI: Indisponibil' })).toBeTruthy();
    const reads = mock.find('GET', '/api/workspace/model').length;
    fireEvent.change(await screen.findByLabelText('Întrebarea ta'), { target: { value: 'Care e termenul?' } });
    fireEvent.keyDown(screen.getByLabelText('Întrebarea ta'), { key: 'Enter' });
    await screen.findByRole('button', { name: 'Oprește' });
    up = true;
    channel.send('start', { user_message: question, assistant_message_id: 12 });
    channel.send('done', { assistant_message: answer });
    channel.close();
    expect(await screen.findByText('Termenul este de 30 de zile.')).toBeTruthy();
    expect(await screen.findByRole('button', { name: 'Modelul AI: Local' })).toBeTruthy();
    expect(mock.find('GET', '/api/workspace/model').length).toBeGreaterThan(reads);
  });
});
