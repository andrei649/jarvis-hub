/* Renders the whole Workspace app at a URL, as a browser would boot it. */
import React from 'react';
import { render } from '@testing-library/react';
import { afterEach, vi } from 'vitest';
import { App } from '../App';
import { setCsrfToken, setSessionHooks } from '../api/client';
import { setLocation } from './mockApi';

export function renderApp(path = '/workspace/') {
  setLocation(path);
  return render(<App initialLocale="ro" />);
}

afterEach(() => {
  vi.unstubAllGlobals();
  setCsrfToken(null);
  setSessionHooks(null);
  try { window.localStorage.clear(); window.sessionStorage.clear(); } catch { /* storage unavailable */ }
  document.documentElement.removeAttribute('data-theme');
});
