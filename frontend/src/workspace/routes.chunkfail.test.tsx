import React from 'react';
import { render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { I18nProvider } from './i18n';
import { setLocation } from './test/mockApi';

vi.mock('./pages/reports', () => { throw new Error('Failed to fetch dynamically imported module'); });

import { SignedInRoutes } from './routes';

afterEach(() => setLocation('/'));

describe('lazy routes: a chunk that fails to download', () => {
  it('shows a reload prompt instead of unmounting the app', async () => {
    const quiet = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    render(<I18nProvider initialLocale="ro"><SignedInRoutes path="/reports" /></I18nProvider>);
    expect(await screen.findByText('Pagina nu s-a putut încărca')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Încearcă din nou' })).toBeTruthy();
    quiet.mockRestore();
  });
});
