import React from 'react';
import { render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { PageSection } from './PageSection';

/* PageSection is a register (frame/kit Register), with none of the HUD v2 panel markup: the
   legacy wrapper it also wrote while the classic shell lived went with that shell (stage 5). */
describe('PageSection is a register', () => {
  it('draws a titled register with the source label and meta, and none of the legacy markup', () => {
    const { container } = render(
      <PageSection id="sec" title="Roster" source={{ state: 'live', value: null, checkedAt: 1, lastGoodAt: Date.now() }} meta="3 agents"
        headExtra={<button>+ New agent</button>} lead={<p>lead</p>} bodyProps={{ role: 'group', 'aria-label': 'Roster' }}>rows</PageSection>);
    expect(container.querySelector('.panel, .panel-head, .bk, .panel-body')).toBeNull();
    expect(container.querySelector('#sec .n-register')).not.toBeNull();
    expect(container.querySelector('.n-register__title')?.textContent).toBe('Roster');
    const meta = container.querySelector('.n-register__meta') as HTMLElement;
    expect(meta.querySelector('[data-source-state="live"]')).not.toBeNull();
    expect(meta.textContent).toContain('3 agents');
    expect(meta.querySelector('button')?.textContent).toBe('+ New agent');
    const body = container.querySelector('.n-register__body') as HTMLElement;
    expect(body.getAttribute('role')).toBe('group');
    expect(body.textContent).toBe('leadrows');
  });

  it('says what a source that did not answer means, by its label', () => {
    const { container } = render(<PageSection title="Memory" source={{ state: 'refused', value: null, checkedAt: 1, lastGoodAt: null, reason: 'credential' }}>x</PageSection>);
    expect(container.querySelector('[data-source-state="refused"]')?.textContent).toMatch(/Refused/);
  });

  it('draws no meta for a section without one, and keeps the meta colour a page sets (Trust, a broken chain)', () => {
    const { container, unmount } = render(<PageSection title="Finance">x</PageSection>);
    expect(container.querySelector('.n-pagesection__meta')).toBeNull();
    expect(container.querySelector('.n-register__title')?.textContent).toBe('Finance');
    unmount();
    const trust = render(<PageSection title="Trust" meta="chain broken" metaStyle={{ color: 'var(--red)' }}>x</PageSection>);
    expect((trust.container.querySelector('.n-pagesection__meta') as HTMLElement).style.color).toBe('var(--red)');
  });
});
