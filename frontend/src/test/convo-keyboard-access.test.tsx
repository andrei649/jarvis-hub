// @ts-nocheck
/* WCAG 2.1.1 — the chat transcript must be reachable by keyboard.

   `.convo` is `overflow-y:auto` (styles.css), so once the transcript is taller than its
   box it is a scrollable region. Its only focusable descendants — the ⧉ save-artifact and
   🔊 replay controls — are rendered on AGENT bubbles, so a transcript of user turns whose
   replies never arrived is a scrollable region with no way in: axe reports
   `serious · scrollable-region-focusable` and the content below the fold is unreadable
   without a mouse. The scheduled HUD E2E matrix failed on exactly that
   (a11y.spec.ts:33, target `.convo`, mobile-chrome 3/3 + webkit 1/3).

   The browser-level proof lives in `e2e/a11y.spec.ts` (real layout, real axe). This is the
   component-level pin: it fails fast, with no browser or backend, if the attributes are
   dropped from the render — which is the edit that would silently reopen the defect. */
import { describe, it, expect } from 'vitest';
import React from 'react';
import { render } from '@testing-library/react';
import { Conversation } from '../cockpit';
import { V2 } from '../data';

const USER_ONLY = [
  { role: 'user', text: 'first', ts: '09:00' },
  { role: 'user', text: 'second', ts: '09:01' },
];

describe('the chat transcript is keyboard-reachable', () => {
  it('puts the scrollable transcript in the sequential focus order', () => {
    const { container } = render(<Conversation messages={USER_ONLY} thinking={null} t={V2.I18N.en} />);
    const convo = container.querySelector('.convo');
    expect(convo).toBeTruthy();
    // The premise: no agent bubble, so nothing inside can take focus…
    expect(convo.querySelectorAll('button, a[href], input, [tabindex]').length).toBe(0);
    // …therefore the region itself must be focusable, and named.
    expect(convo.getAttribute('tabindex')).toBe('0');
    expect(convo.getAttribute('role')).toBe('log');
    expect(convo.getAttribute('aria-label')).toBe(V2.I18N.en.convoRegion);
  });

  it('names the region in the active locale', () => {
    const { container } = render(<Conversation messages={USER_ONLY} thinking={null} t={V2.I18N.ro} />);
    expect(container.querySelector('.convo').getAttribute('aria-label')).toBe(V2.I18N.ro.convoRegion);
  });

  it('still names the region when no dictionary is passed', () => {
    // ChatMode and the cockpit both pass `t`, but the fallback must never render an
    // unnamed focusable region if a future caller forgets.
    const { container } = render(<Conversation messages={USER_ONLY} thinking={null} />);
    expect(container.querySelector('.convo').getAttribute('aria-label')).toBeTruthy();
  });
});
