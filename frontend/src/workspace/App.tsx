/* The Workspace application: providers, then the one decision of what this browser sees.

   Order of precedence: server state first (loading, disabled, unreachable), then the public
   invite/reset page (it must work whether or not someone is signed in on this browser), then
   first-run setup when the server says no organisation exists, then sign-in, then the shell.
   Signing in never changes the URL, so a deep link survives the login screen. */
import React from 'react';
import { SessionProvider, useSession } from './app/session';
import { WorkspaceProvider } from './app/workspace';
import { I18nProvider } from './i18n';
import type { Locale } from './api/types';
import { InvitePage } from './pages/auth/InvitePage';
import { LoginPage } from './pages/auth/LoginPage';
import { SetupPage } from './pages/auth/SetupPage';
import { DisabledScreen, NotFoundPage, SplashScreen, UnreachableScreen } from './pages/system';
import { SignedInRoutes } from './routes';
import { isOutsideApp, useLocation } from './router';
import { AppShell } from './shell/AppShell';
import { ToastProvider } from './ui';

function Gate() {
  const { status, session, refresh } = useSession();
  const location = useLocation();

  if (status === 'loading') return <SplashScreen />;
  if (status === 'disabled') return <DisabledScreen />;
  if (status === 'unreachable' || !session) return <UnreachableScreen onRetry={() => void refresh()} />;
  if (location.path === '/invite') return <InvitePage />;
  if (session.setup_required) return <SetupPage />;
  if (!session.authenticated) return <LoginPage />;
  return (
    <WorkspaceProvider>
      <AppShell>
        {isOutsideApp(location) ? <NotFoundPage /> : <SignedInRoutes path={location.path} />}
      </AppShell>
    </WorkspaceProvider>
  );
}

export function App({ initialLocale }: { initialLocale: Locale }) {
  return (
    <I18nProvider initialLocale={initialLocale}>
      <ToastProvider>
        <SessionProvider>
          <Gate />
        </SessionProvider>
      </ToastProvider>
    </I18nProvider>
  );
}
