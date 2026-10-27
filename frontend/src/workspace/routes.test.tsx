import React from 'react';
import { act, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { I18nProvider } from './i18n';
import { setLocation } from './test/mockApi';

const gate = vi.hoisted(() => {
  const state: { release: () => void; fail: (e: Error) => void; ready: Promise<void> } = {
    release: () => undefined, fail: () => undefined, ready: Promise.resolve(),
  };
  state.ready = new Promise<void>((resolve, reject) => {
    state.release = resolve;
    state.fail = reject;
  });
  return state;
});

vi.mock('./pages/reports', async () => {
  await gate.ready;
  return { ReportsPage: () => <h1 data-page-heading tabIndex={-1}>Reports loaded</h1> };
});
vi.mock('./pages/assistant', () => ({
  AssistantPage: () => <h1 data-page-heading tabIndex={-1}>Assistant page</h1>,
}));

import { SignedInRoutes } from './routes';

afterEach(() => setLocation('/'));

function Harness({ path }: { path: string }) {
  return <I18nProvider initialLocale="ro"><SignedInRoutes path={path} /></I18nProvider>;
}

describe('lazy routes (NWS-12)', () => {
  it('drops the previous page while a route chunk loads, then shows the page', async () => {
    const view = render(<Harness path="/assistant" />);
    expect(screen.getByText('Assistant page')).toBeTruthy();
    view.rerender(<Harness path="/reports" />);
    // No hidden stale heading is left behind for the shell's focus handover to pick.
    expect(screen.queryByText('Assistant page')).toBeNull();
    expect(screen.getByText('Se încarcă…')).toBeTruthy();
    await act(async () => { gate.release(); await gate.ready; });
    expect(await screen.findByText('Reports loaded')).toBeTruthy();
  });
});
