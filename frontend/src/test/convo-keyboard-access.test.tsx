// @ts-nocheck
/* WCAG 2.1.1 — the chat transcript must be reachable by keyboard.

   The transcript scrolls (talk.css `.n-transcript`), so once it is taller than its box it is a
   scrollable region. Its focusable descendants — a reply's actions — sit on REPLIES, so a
   transcript of owner turns whose replies never arrived is a scrollable region with no way in:
   axe reports `serious · scrollable-region-focusable` and the content below the fold is
   unreadable without a mouse. The scheduled HUD E2E matrix failed on exactly that (a11y.spec.ts,
   then on the classic `.convo`, mobile-chrome 3/3 + webkit 1/3).

   The browser-level proof lives in `e2e/a11y.spec.ts` (real layout, real axe). This is the
   component-level pin, on the transcript the owner sees since the Ledger cutover (PHASE_B_PLAN.md
   §8.3: `getByRole('log')`): it fails fast, with no browser or backend, if the attributes are
   dropped from the render — which is the edit that would silently reopen the defect. */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import React from 'react';
import { cleanup, render, screen, within } from '@testing-library/react';
import { Conversation } from '../cockpit';
import { TalkRegister } from '../home/talk/TalkRegister';
import { V2 } from '../data';
import { resetPolling } from '../signals/poll';

const USER_ONLY = [
  { role: 'user', text: 'first', ts: '09:00' },
  { role: 'user', text: 'second', ts: '09:01' },
];

/** Home's conversation register, as App draws it: its `t` is the active language's table. Message
 *  actions off, as in the demo sample (App: messageActionsAllowed = !demo): an owner turn then
 *  carries no More menu, so nothing inside the transcript can take focus. */
function home(lang: 'en' | 'ro') {
  return render(<TalkRegister variant="home" turns={[]} messages={USER_ONLY} thinking={null} onStop={vi.fn()} onProv={vi.fn()}
    lang={lang} t={V2.I18N[lang]} messageScope="jarvis:s" messageActionsAllowed={false} exportAllowed={false} onSubmit={vi.fn()}
    agent="jarvis" agents={[{ id: 'jarvis', name: 'Jarvis', rosterSource: 'api', chat_routing: 'orchestrated' }]}
    recipientStatus="ready" sessionId="s" selectedTurn onSelectAgent={vi.fn()} />);
}

beforeEach(() => { resetPolling(); vi.stubGlobal('fetch', vi.fn(async () => Response.json({}))); });
afterEach(() => { cleanup(); resetPolling(); vi.unstubAllGlobals(); });

describe('the chat transcript is keyboard-reachable', () => {
  it('puts the scrollable transcript in the sequential focus order', () => {
    home('en');
    const log = screen.getByRole('log', { name: V2.I18N.en.convoRegion });
    // the transcript of Home's conversation register, not a classic bubble list
    expect(log.closest('[data-register="talk"]')).not.toBeNull();
    expect(log.hasAttribute('data-transcript')).toBe(true);
    expect(within(log).getAllByText(/first|second/)).toHaveLength(2);
    // The premise: no reply, so nothing inside can take focus…
    expect(log.querySelectorAll('button, a[href], input, select, textarea, [tabindex]').length).toBe(0);
    // …therefore the region itself must be focusable, and named (role="log" permits the name).
    expect(log.getAttribute('tabindex')).toBe('0');
    expect(log.getAttribute('role')).toBe('log');
    expect(log.getAttribute('aria-label')).toBe(V2.I18N.en.convoRegion);
  });

  it('names the region in the active locale', () => {
    home('ro');
    const log = screen.getByRole('log', { name: V2.I18N.ro.convoRegion });
    expect(V2.I18N.ro.convoRegion).not.toBe(V2.I18N.en.convoRegion);
    expect(log.getAttribute('tabindex')).toBe('0');
    expect(screen.queryByRole('log', { name: V2.I18N.en.convoRegion })).toBeNull();
  });

  it('still names the region when no dictionary is passed', () => {
    // App and TalkRegister always pass `t`, but the fallback must never render an unnamed
    // focusable region if a future caller forgets.
    render(<Conversation messages={USER_ONLY} thinking={null} />);
    const log = screen.getByRole('log');
    expect(log.getAttribute('aria-label')).toBeTruthy();
    expect(log.getAttribute('tabindex')).toBe('0');
  });
});
