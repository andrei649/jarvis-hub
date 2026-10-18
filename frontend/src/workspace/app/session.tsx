/* The signed-in state of this browser, read from GET /api/workspace/session.

   Responsibilities: hand the CSRF token to the API client; apply the user's language and theme;
   recover from an expired or revoked session (the client reports `auth_required` → re-read the
   session → the app shows the login screen with an explanation); refresh a rotated CSRF token;
   and attempt proxy SSO once when the server offers it — except right after a deliberate
   logout, otherwise the proxy would sign the user straight back in. */
import React, { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import { getSession, loginSso, logout as logoutRequest } from '../api/account';
import { setCsrfToken, setSessionHooks, WorkspaceApiError } from '../api/client';
import type { AuthResult, Locale, Org, SessionInfo, WorkspaceUser } from '../api/types';
import { useI18n } from '../i18n';
import { toAppPath } from '../router';
import { clearAllDrafts } from './drafts';
import { cachedLocale, cachedTheme, readSessionFlag, writePref, writeSessionFlag } from './storage';
import { applyTheme } from './theme';

export type SessionStatus = 'loading' | 'ready' | 'disabled' | 'unreachable';

export interface SessionContextValue {
  status: SessionStatus;
  session: SessionInfo | null;
  user: WorkspaceUser | null;
  org: Org | null;
  /** True after the server ended the session under the user (shown on the login screen). */
  expired: boolean;
  /** A failed automatic SSO attempt worth explaining (e.g. no Workspace account for that email). */
  ssoError: WorkspaceApiError | null;
  refresh: () => Promise<SessionInfo | null>;
  signIn: (result: AuthResult) => void;
  signOut: () => Promise<void>;
  setUser: (user: WorkspaceUser) => void;
  setOrg: (org: Org) => void;
}

const SessionContext = createContext<SessionContextValue | null>(null);
const LOGGED_OUT_FLAG = 'logged-out';

function isInvitePath(): boolean {
  return toAppPath(window.location.pathname) === '/invite';
}

export function SessionProvider({ children }: { children: React.ReactNode }) {
  const { setLocale } = useI18n();
  const [status, setStatus] = useState<SessionStatus>('loading');
  const [session, setSession] = useState<SessionInfo | null>(null);
  const [expired, setExpired] = useState(false);
  const [ssoError, setSsoError] = useState<WorkspaceApiError | null>(null);
  const inflight = useRef<Promise<SessionInfo | null> | null>(null);
  const ssoTried = useRef(false);

  const applyPreferences = useCallback((info: SessionInfo) => {
    const user = info.authenticated ? info.user : undefined;
    const locale: Locale = user?.locale ?? cachedLocale() ?? info.org?.default_locale ?? 'ro';
    setLocale(locale);
    if (user) {
      writePref('locale', user.locale);
      applyTheme(user.theme);
    } else {
      applyTheme(cachedTheme());
    }
  }, [setLocale]);

  const accept = useCallback((info: SessionInfo) => {
    setCsrfToken(info.authenticated ? info.csrf_token : null);
    setSession(info);
    setStatus('ready');
    applyPreferences(info);
  }, [applyPreferences]);

  const refresh = useCallback((): Promise<SessionInfo | null> => {
    if (inflight.current) return inflight.current;
    const run = (async () => {
      try {
        const info = await getSession();
        accept(info);
        return info;
      } catch (err) {
        if (err instanceof WorkspaceApiError && err.code === 'workspace_disabled') setStatus('disabled');
        else setStatus((prev) => (prev === 'ready' ? prev : 'unreachable'));
        return null;
      } finally {
        inflight.current = null;
      }
    })();
    inflight.current = run;
    return run;
  }, [accept]);

  const signIn = useCallback((result: AuthResult) => {
    writeSessionFlag(LOGGED_OUT_FLAG, false);
    setExpired(false);
    setSsoError(null);
    accept({
      enabled: true, setup_required: false, sso_available: session?.sso_available ?? false,
      authenticated: true, user: result.user, org: result.org, csrf_token: result.csrf_token,
    });
  }, [accept, session?.sso_available]);

  const signOut = useCallback(async () => {
    try {
      await logoutRequest();
    } catch (err) {
      // Already signed out server-side (expired or revoked): finish the local sign-out anyway.
      if (!(err instanceof WorkspaceApiError && err.status === 401)) throw err;
    }
    writeSessionFlag(LOGGED_OUT_FLAG, true);
    clearAllDrafts();
    setExpired(false);
    setCsrfToken(null);
    await refresh();
  }, [refresh]);

  const setUser = useCallback((user: WorkspaceUser) => {
    setSession((prev) => (prev ? { ...prev, user } : prev));
    setLocale(user.locale);
    writePref('locale', user.locale);
    applyTheme(user.theme);
  }, [setLocale]);

  const setOrg = useCallback((org: Org) => {
    setSession((prev) => (prev ? { ...prev, org } : prev));
  }, []);

  useEffect(() => {
    setSessionHooks({
      onAuthRequired: () => {
        setExpired(true);
        void refresh();
      },
      refreshCsrf: async () => {
        const info = await refresh();
        return info?.authenticated ? info.csrf_token ?? null : null;
      },
    });
    void refresh();
    return () => setSessionHooks(null);
  }, [refresh]);

  // Proxy SSO: one silent attempt per page load when offered and not just logged out.
  useEffect(() => {
    if (!session || session.authenticated || session.setup_required || !session.sso_available) return;
    if (ssoTried.current || readSessionFlag(LOGGED_OUT_FLAG) || isInvitePath()) return;
    ssoTried.current = true;
    loginSso().then(signIn).catch((err) => {
      if (err instanceof WorkspaceApiError && err.code !== 'sso_no_identity') setSsoError(err);
    });
  }, [session, signIn]);

  const value = useMemo<SessionContextValue>(() => ({
    status,
    session,
    user: session?.authenticated ? session.user ?? null : null,
    org: session?.org ?? null,
    expired,
    ssoError,
    refresh,
    signIn,
    signOut,
    setUser,
    setOrg,
  }), [status, session, expired, ssoError, refresh, signIn, signOut, setUser, setOrg]);

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionContextValue {
  const ctx = useContext(SessionContext);
  if (!ctx) throw new Error('useSession outside SessionProvider');
  return ctx;
}

/** The signed-in user; only for components rendered inside the authenticated shell. */
export function useUser(): WorkspaceUser {
  const { user } = useSession();
  if (!user) throw new Error('useUser without a signed-in user');
  return user;
}
