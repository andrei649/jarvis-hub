/* Entry point of the Workspace bundle (workspace.html). The last theme and language are applied
   before the first paint so the sign-in screen does not flash light-then-dark; the server
   values replace them as soon as the session loads. */
import React from 'react';
import { createRoot } from 'react-dom/client';
import { App } from './App';
import { cachedLocale, cachedTheme } from './app/storage';
import './workspace.css';

document.documentElement.dataset.theme = cachedTheme();
const locale = cachedLocale() ?? 'ro';
document.documentElement.lang = locale;

const root = document.getElementById('root');
if (root) {
  createRoot(root).render(
    <React.StrictMode>
      <App initialLocale={locale} />
    </React.StrictMode>,
  );
}
