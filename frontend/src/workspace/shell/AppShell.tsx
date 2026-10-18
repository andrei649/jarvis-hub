/* The signed-in layout: skip link, sidebar (inline ≥ 1024 px, drawer below), top bar, main.

   After every in-app navigation the new page's h1 takes focus and the window scrolls to the
   top, so keyboard and screen-reader users land on the new content instead of the link they
   clicked; the first render leaves focus alone. A page that first shows a loading heading and
   then its real one (a report, a run) would drop that focus to <body> when the heading is
   swapped, so for a few seconds after a navigation a heading that replaces the focused one
   takes focus in its place — until the person moves on themselves. */
import React, { useEffect, useRef, useState } from 'react';
import { useI18n } from '../i18n';
import { consumeQuietNavigation, useLocation } from '../router';
import { Drawer, IconButton } from '../ui';
import { ModelChip } from './ModelChip';
import { NotificationsMenu } from './NotificationsMenu';
import { Sidebar } from './Sidebar';
import { UserMenu } from './UserMenu';

const DESKTOP_QUERY = '(min-width: 1024px)';
/** How long after a navigation a replaced page heading inherits focus. */
const HEADING_HANDOVER_MS = 8000;

function useCloseOnDesktop(open: boolean, close: () => void): void {
  useEffect(() => {
    if (!open || typeof window.matchMedia !== 'function') return undefined;
    const query = window.matchMedia(DESKTOP_QUERY);
    const onChange = () => { if (query.matches) close(); };
    query.addEventListener?.('change', onChange);
    return () => query.removeEventListener?.('change', onChange);
  }, [open, close]);
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const { t } = useI18n();
  const location = useLocation();
  const [navOpen, setNavOpen] = useState(false);
  const mainRef = useRef<HTMLElement>(null);
  const firstPath = useRef(location.path);
  const closeNav = useRef(() => setNavOpen(false)).current;
  useCloseOnDesktop(navOpen, closeNav);

  useEffect(() => {
    if (location.path === firstPath.current) return;
    firstPath.current = '';
    setNavOpen(false);
    // A page that only rewrote its own URL keeps focus and scroll where the user is.
    if (consumeQuietNavigation(location.path)) return;
    document.documentElement.scrollTop = 0;
    const main = mainRef.current;
    const heading = main?.querySelector<HTMLElement>('[data-page-heading]');
    (heading ?? main)?.focus({ preventScroll: true });
    if (!main || typeof MutationObserver === 'undefined') return undefined;
    // Hand focus over to the page's final heading if the one that took it is replaced.
    const until = Date.now() + HEADING_HANDOVER_MS;
    const observer = new MutationObserver(() => {
      if (Date.now() > until) { observer.disconnect(); return; }
      const active = document.activeElement;
      if (active && active !== document.body && active !== main) return;
      const next = main.querySelector<HTMLElement>('[data-page-heading]');
      if (next) next.focus({ preventScroll: true });
    });
    observer.observe(main, { childList: true, subtree: true });
    const stop = () => observer.disconnect();
    window.addEventListener('keydown', stop, { once: true, capture: true });
    window.addEventListener('pointerdown', stop, { once: true, capture: true });
    const timer = window.setTimeout(stop, HEADING_HANDOVER_MS);
    return () => {
      observer.disconnect();
      window.clearTimeout(timer);
      window.removeEventListener('keydown', stop, { capture: true });
      window.removeEventListener('pointerdown', stop, { capture: true });
    };
  }, [location.path]);

  return (
    <div className="ws-app">
      <a
        className="ws-skip"
        href="#main"
        onClick={(event) => { event.preventDefault(); mainRef.current?.focus(); }}
      >
        {t('shell.skip')}
      </a>
      <aside className="ws-sidebar" aria-label={t('shell.sidebarLabel')}>
        <Sidebar path={location.path} />
      </aside>
      <Drawer open={navOpen} onClose={closeNav} title={t('shell.menu')} side="left" bare size="sm">
        <Sidebar path={location.path} onNavigate={closeNav} />
      </Drawer>
      <div className="ws-frame">
        <header className="ws-topbar">
          <IconButton className="ws-topbar__menu" icon="menu" label={t('shell.openMenu')} onClick={() => setNavOpen(true)} aria-expanded={navOpen} />
          <div className="ws-topbar__spacer" />
          <div className="ws-topbar__actions">
            <ModelChip />
            <NotificationsMenu />
            <UserMenu />
          </div>
        </header>
        <main id="main" ref={mainRef} tabIndex={-1} className="ws-main">
          <div className="ws-main__inner">{children}</div>
        </main>
      </div>
    </div>
  );
}
