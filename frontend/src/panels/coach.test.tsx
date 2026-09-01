// @ts-nocheck
/* COACH panel — the 0.43 Learning Coach pack's client half. fetch is mocked (same idiom
   as kg-panel.test.tsx) so the REAL api/client path runs: that is what proves the refusal
   branch is live, because apiPost's failMutation is what attaches `err.body` to the throw
   that the panel's onErr renders verbatim. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { CoachPanel } from './coach';

beforeEach(() => { try { localStorage.clear(); } catch { /* ignore */ } });

const ok = (payload) => {
  const fn = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => payload });
  global.fetch = fn;
  return fn;
};
const refuse = (status, body) => {
  const fn = vi.fn().mockResolvedValue({ ok: false, status, json: async () => body });
  global.fetch = fn;
  return fn;
};
const bodyOf = (fn, path) => JSON.parse(
  fn.mock.calls.find((c) => String(c[0]).includes(path))[1].body);

/** Build a two-card deck through the panel's own UI — no hand-typed JSON, no seeded ids. */
function addCards(labels) {
  for (const l of labels) {
    fireEvent.change(screen.getByPlaceholderText('card label'), { target: { value: l } });
    fireEvent.click(screen.getByText('add card'));
  }
}

describe('CoachPanel — deck is browser-local, the three POSTs are real', () => {
  it('posts the panel-built deck to /api/coach/session and renders counts.deferred verbatim', async () => {
    const fn = ok({
      now_day: 20000,
      due: [{ id: 'alpha', label: 'Alpha', due_day: 19999 }],
      new: [{ id: 'beta', label: 'Beta' }],
      counts: { due_total: 4, due_selected: 1, new_total: 3, new_selected: 1, deferred: 5 },
    });
    render(<CoachPanel />);
    addCards(['Alpha', 'Beta']);

    fireEvent.click(screen.getByText('build session'));
    await waitFor(() => expect(screen.getByText(/deferred 5/)).toBeTruthy());

    // the request carried the operator's real deck, not a placeholder
    const sent = bodyOf(fn, '/api/coach/session');
    expect(sent.cards.map((c) => c.id)).toEqual(['alpha', 'beta']);
    expect(sent.new_limit).toBe(20);
    expect(sent.max_reviews).toBe(200);
    expect(Number.isInteger(sent.now_day)).toBe(true);

    // every count is rendered from the response, and deferred>0 gets its own amber line
    expect(screen.getByText(/due_total 4/)).toBeTruthy();
    expect(screen.getByText(/new_total 3/)).toBeTruthy();
    expect(screen.getByText(/5 deferred by the caps/)).toBeTruthy();
  });

  it('refuses to add a duplicate card id locally and says why', () => {
    ok({});
    render(<CoachPanel />);
    addCards(['Alpha', 'Alpha']);
    expect(screen.getByText(/not added · duplicate id "alpha"/)).toBeTruthy();
  });

  it('renders a 403 refusal VERBATIM and shows no session result (onErr branch is live)', async () => {
    ok({});
    render(<CoachPanel />);
    addCards(['Alpha']);

    refuse(403, { detail: 'user routes disabled from network — set JARVIS_USER_TOKEN to enable remote access' });
    fireEvent.click(screen.getByText('build session'));

    await waitFor(() => expect(screen.getByText(
      'refused · 403 · user routes disabled from network — set JARVIS_USER_TOKEN to enable remote access',
    )).toBeTruthy());
    // the success branch is NOT taken: no counts block appeared
    expect(screen.queryByText(/due_total/)).toBeNull();
  });

  it('clears a prior session result when a later call is refused (no stale success under a refusal)', async () => {
    ok({
      now_day: 1, due: [], new: [],
      counts: { due_total: 0, due_selected: 0, new_total: 0, new_selected: 0, deferred: 0 },
    });
    render(<CoachPanel />);
    addCards(['Alpha']);
    fireEvent.click(screen.getByText('build session'));
    await waitFor(() => expect(screen.getByText(/due_total 0/)).toBeTruthy());

    refuse(429, { error: 'rate limit exceeded', code: 429 });
    fireEvent.click(screen.getByText('build session'));
    await waitFor(() => expect(screen.getByText('refused · 429 · rate limit exceeded')).toBeTruthy());
    expect(screen.queryByText(/due_total/)).toBeNull();
  });

  it('grades a card and writes the returned interval/ease/due_day back into the deck', async () => {
    ok({});
    render(<CoachPanel />);
    addCards(['Alpha']);

    const fn = ok({
      id: 'alpha', label: 'Alpha', repetitions: 1, interval: 1,
      ease: 2.6, last_quality: 5, due_day: 20001, lapsed: false,
    });
    fireEvent.change(screen.getByLabelText('card to grade'), { target: { value: 'alpha' } });
    fireEvent.click(screen.getByTitle('grade 5 — perfect recall'));

    await waitFor(() => expect(screen.getByText(/last_quality 5/)).toBeTruthy());
    const sent = bodyOf(fn, '/api/coach/review');
    expect(sent.card.id).toBe('alpha');
    expect(sent.quality).toBe(5);
    // the returned card replaced the deck row (the server persists nothing)
    expect(screen.getAllByText(/ease 2.6/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/due_day 20001/).length).toBeGreaterThan(0);
  });

  it('renders lapsed:true from the response field rather than re-deriving it', async () => {
    ok({});
    render(<CoachPanel />);
    addCards(['Alpha']);

    ok({ id: 'alpha', label: 'Alpha', repetitions: 0, interval: 1, ease: 1.7, last_quality: 1, due_day: 20001, lapsed: true });
    fireEvent.change(screen.getByLabelText('card to grade'), { target: { value: 'alpha' } });
    fireEvent.click(screen.getByTitle('grade 1 — wrong; recognised the answer when shown'));

    await waitFor(() => expect(screen.getByText(/lapsed: true/)).toBeTruthy());
  });

  it('renders a 422 refusal from the review route with the pydantic detail intact', async () => {
    ok({});
    render(<CoachPanel />);
    addCards(['Alpha']);

    refuse(422, { detail: [{ type: 'less_than_equal', loc: ['body', 'quality'], msg: 'Input should be less than or equal to 5' }] });
    fireEvent.change(screen.getByLabelText('card to grade'), { target: { value: 'alpha' } });
    fireEvent.click(screen.getByTitle('grade 5 — perfect recall'));

    await waitFor(() => expect(screen.getByText(
      /refused · 422 · .*Input should be less than or equal to 5/,
    )).toBeTruthy());
    expect(screen.queryByText(/last_quality/)).toBeNull();
  });

  it('renders unknown_prereqs and cycles from the curriculum response', async () => {
    ok({});
    render(<CoachPanel />);
    fireEvent.click(screen.getByText('add topic'));
    fireEvent.change(screen.getByPlaceholderText('topic id'), { target: { value: 'sm2' } });
    fireEvent.change(screen.getByPlaceholderText('title'), { target: { value: 'SM-2' } });
    fireEvent.change(screen.getByPlaceholderText('prereqs (ids, comma-separated)'), { target: { value: 'ghost' } });

    const fn = ok({
      order: [{ id: 'sm2', title: 'SM-2' }],
      sessions: [[{ id: 'sm2', title: 'SM-2' }]],
      session_count: 1,
      unknown_prereqs: [{ topic: 'sm2', missing_prereq: 'ghost' }],
      cycles: ['loopa', 'loopb'],
    });
    fireEvent.click(screen.getByText('plan curriculum'));

    await waitFor(() => expect(screen.getByText(
      /topic sm2 → missing prereq ghost \(edge ignored, not invented\)/,
    )).toBeTruthy());
    expect(screen.getByText(/prereq cycle: loopa, loopb — planned last, not dropped/)).toBeTruthy();
    expect(screen.getByText(/session_count 1/)).toBeTruthy();

    const sent = bodyOf(fn, '/api/coach/curriculum');
    expect(sent.topics).toEqual([{ id: 'sm2', title: 'SM-2', prereqs: ['ghost'] }]);
    expect(sent.per_session).toBe(3);
  });

  it('refuses a blank topic id locally, naming the silent server-side drop, and sends nothing', () => {
    const fn = ok({});
    render(<CoachPanel />);
    fireEvent.click(screen.getByText('add topic'));
    fireEvent.click(screen.getByText('plan curriculum'));

    expect(screen.getByText(/not sent · a topic with a blank id is dropped by plan_curriculum/)).toBeTruthy();
    expect(fn.mock.calls.some((c) => String(c[0]).includes('/api/coach/curriculum'))).toBe(false);
  });

  it('shows no LIVE chip until a POST has returned, and disables build session on an empty deck', async () => {
    ok({ now_day: 1, due: [], new: [], counts: { due_total: 0, due_selected: 0, new_total: 0, new_selected: 0, deferred: 0 } });
    const { container } = render(<CoachPanel />);
    expect(screen.queryByText('LIVE')).toBeNull();
    expect(screen.getByText('build session').disabled).toBe(true);

    addCards(['Alpha']);
    expect(screen.queryByText('LIVE')).toBeNull(); // local deck state is not backend data
    expect(screen.getByText('build session').disabled).toBe(false);

    fireEvent.click(screen.getByText('build session'));
    await waitFor(() => expect(screen.getByText('LIVE')).toBeTruthy());
    expect(container.textContent).toContain('this deck lives in this browser only');
  });
  /* An empty session must DISARM grading, not silently keep the previous pick.

     Found by the adversarial review pass. The reset effect used to be guarded by
     `sessionIds.length && …`, so a session returning due: [] / new: [] skipped the reset
     entirely and `selId` kept its pre-session value. The select then rendered only the
     placeholder (gradable is empty), while `selected` still resolved the stale id out of
     the deck — so the grade buttons stayed live and POSTed a review for a card the session
     does not contain and the operator cannot see selected. Worse than a dead control: an
     ARMED one, aimed at something invisible. */
  it('an empty session clears the pick and disables grading', async () => {
    ok({});
    render(<CoachPanel />);
    addCards(['Alpha', 'Beta']);

    const sel = screen.getByLabelText('card to grade');
    fireEvent.change(sel, { target: { value: sel.options[1].value } });
    expect(sel.value).toBeTruthy();
    // Select by the unique title ('grade N — …'); filtering on digit text also caught
    // unrelated buttons in the deck rows.
    const gradeBtns = () => screen.getAllByRole('button')
      .filter((b) => /^grade [0-5] /.test(b.getAttribute('title') || ''));
    expect(gradeBtns().length).toBeGreaterThan(0);
    expect(gradeBtns().every((b) => b.disabled)).toBe(false);   // armed while a card is picked

    // the session says nothing is due and nothing is new
    ok({ now_day: 20000, due: [], new: [],
         counts: { due_total: 0, due_selected: 0, new_total: 0, new_selected: 0, deferred: 0 } });
    fireEvent.click(screen.getByText('build session'));

    // Wait for the SESSION to actually render before asserting. A select whose value
    // matches no option reports '' in the DOM even while React state still holds the stale
    // id, so `select.value === ''` is not on its own evidence the pick was cleared.
    await waitFor(() => expect(screen.getByText(/due_total 0/)).toBeTruthy());
    // Wait for the DISABLED state, not just the session text: clearing the pick is a state
    // update that flushes on a later render than the one that paints the counts, so asserting
    // immediately after the counts appear tests the gap rather than the behaviour.
    await waitFor(() => expect(gradeBtns().every((b) => b.disabled)).toBe(true));
    expect(screen.getByLabelText('card to grade').value).toBe('');
  });
});
