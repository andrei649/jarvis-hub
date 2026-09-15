import React, { lazy } from 'react';
import { act, render, screen } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import { RouteBoundary } from '../route-boundary';

it('shows a loading fallback until a route chunk resolves', async () => {
  let resolve: (module: { default: () => React.ReactNode }) => void;
  const Page = lazy(() => new Promise<{ default: () => React.ReactNode }>(done => { resolve = done; }));
  render(<RouteBoundary><Page /></RouteBoundary>);
  expect(screen.getByRole('status').textContent).toBe('Loading page…');
  await act(async () => resolve({ default: () => <div>Page ready</div> }));
  expect(screen.getByText('Page ready')).toBeTruthy();
  expect(screen.queryByRole('status')).toBeNull();
});
it('offers recovery after chunk failure and resets the error on route change', async () => {
  vi.spyOn(console, 'error').mockImplementation(() => {});
  const Broken = lazy(() => Promise.reject(new Error('chunk unavailable')));
  const view = render(<RouteBoundary routeKey="broken"><Broken /></RouteBoundary>);
  expect(await screen.findByRole('alert')).toBeTruthy();
  expect(screen.getByRole('button', { name: 'Reload page' })).toBeTruthy();
  view.rerender(<RouteBoundary routeKey="working"><div>Working page</div></RouteBoundary>);
  expect(screen.getByText('Working page')).toBeTruthy();
});
