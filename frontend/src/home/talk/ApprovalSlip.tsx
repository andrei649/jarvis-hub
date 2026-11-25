/* ApprovalSlip: a reply that queued actions for the owner carries a ruled slip
   (PHASE_B_PLAN.md §5.3; ledger README §4 "Talk"): "⊛ 1 action waits for your decision —
   <title> · On the docket". It links; it never decides.

   The ids are the end frame's `pending_approvals` (turn-tools.tsx approvalIds). For each, the
   docket says whether it holds the request (docket/links.ts useDocketTitle): when it does, the
   slip shows the entry's title — plain text, verbatim, from a queue that may hold untrusted
   producers — and links to the entry; when the feed answered without it (decided, special, or
   held elsewhere) or did not answer, the slip says so and links to the Decisions page on that
   card. Links are ready hrefs navigated in the app (docketHref + openDocketEntry, decisionsHref +
   openDecisionsCard), never through navigateHud, which would encode their `#` and `?`.

   The floating desktop window (§5.1: "sign in the main window", no signing there in Phase B)
   always shows the conversation alone, whatever its address, so a link there must not navigate in
   place: the route would change and nothing on screen would. There the slip names the requests,
   says they are decided in the main window and offers the window's own "Open in app" handoff (the
   bridge's fixed `handoff` action: the main window comes forward, the floating one hides). Without
   the bridge, its links load the full HUD instead (a full navigation, without desktop=floating). */
import React, { useState } from 'react';
import { hasDesktopBridge, isFloatingDesktop } from '../../desktop';
import { decisionsHref, docketHref, openDecisionsCard, openDocketEntry, useDocketTitle } from '../../docket/links';
import { Mark } from '../../frame/kit';
import { fmt, langOf, plural } from '../../frame/strings';
import { talkStrings } from './strings';

/** A plain left click navigates in the app; a modified or middle click keeps the browser's own. */
export function inAppClick(go: () => void) {
  return (event: React.MouseEvent<HTMLAnchorElement>) => {
    if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    go();
  };
}

/** A ready href for a full navigation out of the floating window: the same page, without
 *  `desktop=floating` (which would load the conversation-only window again). */
export function leaveFloatingHref(href: string): string {
  const url = new URL(href, window.location.origin);
  url.searchParams.delete('desktop');
  return `${url.pathname}${url.search}${url.hash}`;
}

/** The bridge's fixed "Open in app" action (desktop.tsx DesktopControls sends the same one). */
function desktopHandoff(): Promise<void> {
  const core = (window as unknown as { __TAURI__?: { core?: { invoke?: (cmd: string, args: unknown) => unknown } } }).__TAURI__?.core;
  if (!core || typeof core.invoke !== 'function') return Promise.reject(new Error('no desktop bridge'));
  return Promise.resolve(core.invoke('desktop_action', { action: 'handoff' })).then(() => undefined);
}

/** app: links navigate in the app · navigate: full-navigation links out of the floating window ·
 *  handoff: no links; the slip sends the owner to the main window. */
type SlipMode = 'app' | 'navigate' | 'handoff';

function SlipRow({ id, lang, mode }: { id: number; lang: string; mode: SlipMode }) {
  const s = talkStrings(lang);
  const title = useDocketTitle(id, { lang: langOf(lang) });
  const known = typeof title.value === 'string' && title.value.trim() !== '';
  const link = (href: string, open: () => void, words: string) => mode === 'handoff' ? null
    : <a className="n-link n-slip__link" href={mode === 'navigate' ? leaveFloatingHref(href) : href}
        onClick={mode === 'navigate' ? undefined : inAppClick(open)}>{words}</a>;
  if (known) {
    return (
      <li className="n-slip__row" data-slip-entry={id} data-docket-state={title.state}>
        <span className="n-slip__title">{title.value}</span>
        {link(docketHref(id), () => openDocketEntry(id), s.onDocket)}
      </li>
    );
  }
  const why = title.state === 'empty' ? s.notOnDocket
    : title.state === 'refused' ? s.docketRefused
    : title.state === 'demo' ? s.docketDemo
    : title.state === 'unknown' && title.reason === 'checking' ? s.docketChecking
    : s.docketUnknown;
  return (
    <li className="n-slip__row" data-slip-entry={id} data-docket-state={title.state}>
      <span className="n-slip__title">{fmt(s.slipRequest, { id })}</span>
      <span className="n-slip__why">{why}</span>
      {link(decisionsHref(id), () => openDecisionsCard(id), s.openInDecisions)}
    </li>
  );
}

function HandOff({ lang }: { lang: string }) {
  const s = talkStrings(lang);
  const [failed, setFailed] = useState<string | null>(null);
  const open = () => {
    setFailed(null);
    desktopHandoff().catch((error: unknown) => setFailed(error instanceof Error ? error.message : String(error)));
  };
  return (
    <p className="n-slip__away" data-slip-away="">
      <span>{s.slipMainWindow}</span>
      <button type="button" className="n-btn n-btn--sm n-btn--quiet n-slip__handoff" onClick={open}>{s.openInApp}</button>
      {failed !== null && <span className="n-slip__failed" role="alert">{s.handoffFailed} <code>{failed}</code></span>}
    </p>
  );
}

export function ApprovalSlip({ ids, lang, floating = false }: { ids: readonly number[]; lang: string; floating?: boolean }) {
  const s = talkStrings(lang);
  if (!ids.length) return null;
  const away = floating || isFloatingDesktop();
  const mode: SlipMode = !away ? 'app' : hasDesktopBridge() ? 'handoff' : 'navigate';
  return (
    <div className="n-slip" role="note" data-slip="" data-count={ids.length} data-slip-mode={mode}>
      <p className="n-slip__head">
        <Mark kind="seal-open" lang={lang} />
        <b>{plural(lang, s.slipHead, ids.length)}</b>
      </p>
      <ul className="n-slip__list">
        {ids.map((id) => <SlipRow key={id} id={id} lang={lang} mode={mode} />)}
      </ul>
      {mode === 'handoff' && <HandOff lang={lang} />}
    </div>
  );
}
