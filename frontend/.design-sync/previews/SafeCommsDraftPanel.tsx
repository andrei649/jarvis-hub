import React from 'react';
import { SafeCommsDraftPanel } from 'jarvis-hud-v2';

/* SafeCommsDraftPanel self-fetches GET /api/integrations/social on mount — the governed
   draft-before-send surface (queue for approval, no direct send). Stories: registered
   targets / no targets / offline (real 404, unstubbed). */
const STORY = (() => { try { return new URLSearchParams(window.location.search).get('story') || ''; } catch { return ''; } })();
function stubFetch(routesByStory: Record<string, Record<string, unknown>>, fallback: string) {
  const routes = routesByStory[STORY] || routesByStory[fallback] || {};
  const real = window.fetch.bind(window);
  (window as any).fetch = (input: any, init?: any) => {
    const url = typeof input === 'string' ? input : ((input && (input as any).url) || '');
    const path = String(url).split('?')[0];
    const hit = Object.prototype.hasOwnProperty.call(routes, url) ? routes[url]
      : Object.prototype.hasOwnProperty.call(routes, path) ? routes[path] : undefined;
    if (hit === undefined) return real(input as any, init);
    return Promise.resolve(new Response(JSON.stringify(hit), { status: 200, headers: { 'Content-Type': 'application/json' } }));
  };
}

stubFetch({
  ActionsReady: {
    '/api/integrations/social': {
      targets: [
        { platform: 'mastodon', action: 'post', label: 'Mastodon post', kind: 'mastodon.post', credential: 'MASTODON_TOKEN', required: ['text'] },
        { platform: 'mastodon', action: 'reply', label: 'Mastodon reply', kind: 'mastodon.reply', credential: 'MASTODON_TOKEN', required: ['text', 'reply_to'] },
        { platform: 'linkedin', action: 'post', label: 'LinkedIn post', kind: 'linkedin.post', credential: 'LINKEDIN_TOKEN', required: ['text'] },
        { platform: 'telegram', action: 'dm', label: 'Telegram DM', kind: 'telegram.dm', credential: 'TG_BOT_TOKEN', required: ['text', 'recipient'] },
      ],
    },
  },
  NoTargets: {
    '/api/integrations/social': { targets: [] },
  },
  Offline: {},
}, 'ActionsReady');

const wrap: React.CSSProperties = { background: 'var(--void,#04070e)', borderRadius: 8, padding: 16, width: 440 };

/** Four governed write actions registered — action picker, agent field, draft box, queue-for-approval. */
export function ActionsReady() {
  return <div className="hud-root" style={wrap}><SafeCommsDraftPanel /></div>;
}

/** No social integrations configured — "nothing yet", queue button disabled. */
export function NoTargets() {
  return <div className="hud-root" style={wrap}><SafeCommsDraftPanel /></div>;
}

/** Backend unreachable — the panel's amber offline degrade row above the draft controls. */
export function Offline() {
  return <div className="hud-root" style={wrap}><SafeCommsDraftPanel /></div>;
}
