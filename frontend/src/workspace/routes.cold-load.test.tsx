import { act, screen } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import { makeUser, mockFetch, shellRoutes, signedIn } from './test/mockApi';
import { renderApp } from './test/render';

const gate = vi.hoisted(() => {
  let release = () => undefined;
  const ready = new Promise<void>((resolve) => { release = resolve; });
  return { ready, release };
});

vi.mock('./pages/reports', async (importOriginal) => {
  await gate.ready;
  return importOriginal();
});

it('keeps actual report content absent until the cold route module resolves', async () => {
  const mock = mockFetch({
    'GET /api/workspace/session': signedIn(makeUser()),
    ...shellRoutes(),
    'GET /api/workspace/reports': { reports: [] },
  });
  renderApp('/workspace/reports');
  await screen.findByRole('complementary', { name: 'Bara laterală' });
  expect(screen.getByText('Se încarcă…')).toBeTruthy();
  expect(screen.queryByText('Niciun raport încă')).toBeNull();
  await expect(screen.findByText('Niciun raport încă')).rejects.toThrow();
  expect(mock.find('GET', '/api/workspace/reports')).toHaveLength(0);

  await act(async () => {
    gate.release();
    await import('./pages/reports');
  });
  expect(await screen.findByText('Niciun raport încă')).toBeTruthy();
  expect(mock.find('GET', '/api/workspace/reports')).toHaveLength(1);
});
