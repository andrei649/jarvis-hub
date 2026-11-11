// @ts-nocheck
/* H348 — the owner asks which skills overlap; drafting proposes batches that wait for the
   owner's card. fetch is mocked. */
import { describe, it, expect, vi } from 'vitest';
import React from 'react';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { SkillConsolidation } from '../panels/skill-batches';
import { originLabel } from '../panels/skill-changes';

function mockFetch(payload) {
  const fn = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => payload });
  global.fetch = fn;
  return fn;
}

describe('SkillConsolidation', () => {
  it('finds overlaps without drafting', async () => {
    const fn = mockFetch({ ok: true, groups: [{ members: ['docker-build', 'docker-push'], score: 0.61, status: 'found' }] });
    render(<SkillConsolidation />);
    fireEvent.click(screen.getByText('find overlaps'));
    await waitFor(() => expect(screen.getByText('docker-build + docker-push')).toBeTruthy());
    const [url, init] = fn.mock.calls[0];
    expect(String(url)).toContain('/api/skills/consolidation/analyze');
    expect(JSON.parse(init.body)).toEqual({ draft: false });
  });

  it('drafting proposes and reloads the batch inbox', async () => {
    mockFetch({ ok: true, groups: [{ members: ['a', 'b'], umbrella: 'ab', score: 0.5, status: 'proposed' }] });
    const reload = vi.fn();
    render(<SkillConsolidation onProposed={reload} />);
    fireEvent.click(screen.getByText('draft umbrellas (local model)'));
    await waitFor(() => expect(screen.getByText('awaiting your approval')).toBeTruthy());
    expect(reload).toHaveBeenCalled();
    expect(screen.getByText('a + b → ab')).toBeTruthy();
  });

  it('labels a consolidation batch', () => {
    expect(originLabel('agent:consolidation')).toBe('skill consolidation (local model)');
  });
});
