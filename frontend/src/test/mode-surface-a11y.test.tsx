// @ts-nocheck
/* Component-level pins for the mode-surface accessibility contract.

   The browser proof is `e2e/a11y-modes.spec.ts`, and it is the real one — it runs axe
   against a live layout. But it is viewport-dependent by nature (axe's contrast rule only
   sees pixels inside the viewport) and it needs a backend, a browser and ~55s. These two
   asserts fail in milliseconds, in the PR lane, if the attributes are simply deleted —
   which is the edit that would quietly reopen both defects. */
import { describe, it, expect } from 'vitest';
import React from 'react';
import { render } from '@testing-library/react';
import { AgentsMode, MemoryMode } from '../modes';
import { V2 } from '../data';

const AGENTS = [
  { id: 'jarvis', name: 'Jarvis', tier: 'CNS', status: 'active', role: 'Prime' },
  { id: 'frigga', name: 'Frigga', tier: 'FND', status: 'idle', role: 'Memory' },
];

describe('mode surfaces keep their accessibility contract', () => {
  it('puts the AGENTS roster — a scrollable region whose cards are non-focusable divs — in the tab order, with a name', () => {
    const { container } = render(<AgentsMode agents={AGENTS} onOpen={() => {}} t={V2.I18N.en} />);
    const body = container.querySelector('.panel-body');
    expect(body).toBeTruthy();
    // The premise: the roster's own children carry click handlers, not focus.
    expect(container.querySelectorAll('.acard button, .acard a[href], .acard [tabindex]').length).toBe(0);
    expect(body.getAttribute('tabindex')).toBe('0');
    expect(body.getAttribute('aria-label')).toBe(V2.I18N.en.roster);
    // The name needs a role that PERMITS it. Without one, `aria-label` on a <div> is axe
    // `serious · aria-prohibited-attr` — which is what the first version of this fix shipped, and
    // which the mode walk could not fail on because axe files that rule under `incomplete`.
    // Pinned here so the pair cannot drift apart again in the PR lane, without a browser.
    expect(body.getAttribute('role')).toBe('group');
  });

  it('names the MEMORY time-travel slider in the active locale', () => {
    for (const loc of ['en', 'ro']) {
      const { container } = render(<MemoryMode t={V2.I18N[loc]} />);
      const slider = container.querySelector('input[type="range"]');
      expect(slider, `MemoryMode should render the time-travel slider (${loc})`).toBeTruthy();
      // An unlabelled range input is axe `critical · label`: it announced as a bare "slider".
      expect(slider.getAttribute('aria-label')).toBe(V2.I18N[loc].timeTravel);
    }
  });
});
