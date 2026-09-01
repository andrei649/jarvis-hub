/* PRESENCE & INBOX — two shipped user-tier reads that no client has ever called:

     · GET /api/presence/owner        (agents/core/routers/presence.py:34)
     · GET /api/channels/inbox/status (agents/core/routers/integrations.py:120)

   Both are pure reads. This panel writes nothing, and the reasons it writes nothing are
   the product, not an omission:

   1. NO PRESENCE SETTER. The sibling POST /api/presence/owner is admin-guarded and exists
      for the owner-side host daemon (a Windows idle/lock watcher, or the 0.64 Tauri host
      overlay — presence.py:1-14 says so in the module docstring). The entire value of the
      signal is that a daemon OBSERVED it; a textarea letting a human type "away" would
      forge exactly that, and would forge it into the one input that decides whether
      decision cards escalate to the owner's phone. So there is no setter here.
   2. NO INBOX ENABLE TOGGLE. `orch.channel_inbox` is bound in process by
      agents/web.py:334-337; no route binds or unbinds it. A switch here would drive
      nothing.

   Three honesty traps specific to these payloads, each handled explicitly below:

   a) `away:false` IS NOT "the owner is at the desk". _compute_away (autonomy/presence.py)
      fails calm: it returns False whenever the signal is stale AND whenever state is
      'unknown', so a dead daemon reads as away:false. It is also never True for 'idle',
      because idle_is_away is never enabled in production — orchestrator.py:503-505 passes
      ttl_seconds only. The away row therefore says "not known to be away", never
      "present".
   b) `idle_seconds:null` IS NOT 0. null means the daemon attached no hint (the POST body's
      field is Optional). "idle for 0s" would be a measurement that was never taken.
   c) The inbox's unbound branch RETURNS 200, NOT 503, and its threads/messages zeros are
      LITERALS typed into integrations.py:132-133 — not a count of an empty store — while
      max_messages is absent from that branch entirely. Rendering them as plain numbers is
      the silent-zero lie; they are tagged '(placeholder)' and the cap renders as an em
      dash. And because the branch is a 200, it belongs in an amber unavailable tag, never
      in <State e=.../>.

   Why this is not a duplicate of anything shipped. GET /api/swarm/summary embeds the same
   presence snapshot (swarm.py:277-280), but the shipped SwarmPanel (gap.tsx) reads only
   agents/autonomy/missions/workflows/subagents/a2a/dev_locks and never touches `presence`.
   The house presence panel in gap.tsx is agents/core/house/presence.py — per-room,
   consent-gated occupancy, which autonomy/presence.py:1-23 explicitly disclaims any
   relationship to. And the shipped COMMS inbox calls the SIBLING route
   /api/channels/inbox, which answers {"threads": []} both when the store is empty and when
   it is unbound (integrations.py:141-142) — so /api/channels/inbox/status carries the one
   flag that tells "nobody messaged you" apart from "nothing is being persisted".

   On the 503: apiGet (api/client.ts:106) throws `GET <path> -> <status>` and does NOT read
   the response body — unlike failMutation, which attaches err.body. So the handler's own
   words "presence not available" are UNREACHABLE from here. The panel prints the thrown
   message verbatim and, separately, CITES the handler source for what a 503 means. It
   never presents that string as something it received. */
import React from 'react';
import { useApi, mono, asLive, Card, State, Row, Tag } from '../panel-kit';

const PRESENCE_PATH = '/api/presence/owner';
const INBOX_STATUS_PATH = '/api/channels/inbox/status';

const EM = '—';

/* Canonical states only — presence.py normalizes OS aliases ('locked', 'active', …) at
   WRITE time, so a read can only ever carry one of these four. Anything else is rendered
   verbatim with the neutral colour rather than being mapped to a guess. */
const STATE_COLOR = {
  present: 'var(--green)',
  idle: 'var(--amber)',
  away: 'var(--accent)',
  unknown: 'var(--ink-3)',
};

/* since/updated_at are float UNIX SECONDS, not milliseconds. */
const stamp = (v) => (typeof v === 'number' && isFinite(v) ? new Date(v * 1000).toLocaleString() : EM);

const ageOf = (v) => {
  if (typeof v !== 'number' || !isFinite(v)) return '';
  const s = Math.max(0, Math.round(Date.now() / 1000 - v));
  if (s < 60) return s + 's ago';
  if (s < 3600) return Math.floor(s / 60) + 'm ago';
  if (s < 86400) return Math.floor(s / 3600) + 'h ago';
  return Math.floor(s / 86400) + 'd ago';
};

/* A provenance/consequence line. Everything on screen that is not a payload value is one
   of these, so a claim and the file it was read from stay attached to each other. */
const Note = ({ c, children }: { c?: any; children?: any }) => (
  <div style={{ fontSize: 10, lineHeight: 1.5, color: c || 'var(--ink-3)', padding: '3px 0 5px' }}>{children}</div>
);

const Head = ({ k, note }: { k: any; note?: any }) => (
  <div style={{ marginTop: 10, marginBottom: 2 }}>
    <div style={{ ...mono, fontSize: 10, letterSpacing: '.08em', color: 'var(--ink-2)' }}>{k}</div>
    {note != null && <div style={{ fontSize: 10, color: 'var(--ink-3)' }}>{note}</div>}
  </div>
);

const Right = ({ children }) => (
  <span style={{ marginLeft: 'auto', display: 'flex', gap: 5, alignItems: 'center', flexWrap: 'wrap', justifyContent: 'flex-end' }}>{children}</span>
);

export function PresenceInboxPanel() {
  const pres = useApi(PRESENCE_PATH);          // user tier (user_guard) — no admin flag
  const inbox = useApi(INBOX_STATUS_PATH);     // user tier (user_guard) — no admin flag

  const p: any = pres.d;
  const ib: any = inbox.d;
  const st: any = (ib && ib.stats) || {};

  /* `enabled` is a tri-state to this panel: true, false, or "we do not have the payload".
     Only an actual `false` licenses the words "not bound". */
  const bound = !!(ib && ib.enabled === true);
  const unbound = !!(ib && ib.enabled === false);
  const reported = !!(p && p.ever_reported === true);

  /* The 503 is the handler's ONLY refusal branch; the guard's 401/403 are the only other
     non-200s. This flag only decides whether to show the source citation — the operator
     sees the thrown message either way, via <State/>. */
  const presence503 = String(pres.e || '').endsWith('-> 503');

  const channels: any[] = Array.isArray(st.channels) ? st.channels : [];

  const presSub = p ? String(p.state) : pres.e ? 'presence read failed' : null;
  const inboxSub = ib ? (bound ? `${st.threads} threads` : 'inbox unbound') : inbox.e ? 'inbox read failed' : null;
  const sub = presSub || inboxSub ? [presSub, inboxSub].filter(Boolean).join(' · ') : null;

  return (
    <Card
      title="PRESENCE & INBOX"
      /* LIVE only when a daemon has actually reported AND the store is actually bound.
         Either half missing is SEED — the surface is up, the feed behind it is not. */
      live={asLive(pres.d && inbox.d, bound && reported)}
      sub={sub}
      onReload={() => { pres.reload(); inbox.reload(); }}
    >
      <Head k="OWNER DESK PRESENCE" note="GET /api/presence/owner — is the owner at the machine, as reported by the host daemon" />
      <State e={pres.e} loading={pres.loading} n={p ? 1 : 0} />

      {presence503 && (
        <Note c="var(--amber)">
          503 is this route&rsquo;s only refusal branch &mdash; agents/core/routers/presence.py:37 answers
          {' '}{'{"error": "presence not available"}'} when orch.owner_presence is unbound. apiGet does not
          deliver GET error bodies (api/client.ts:106), so that string is quoted from the handler source
          here, not received from this response.
        </Note>
      )}

      {p && (
        <>
          <Row>
            <span style={mono}>state</span>
            <Right><Tag c={STATE_COLOR[p.state] || 'var(--ink-3)'}>{String(p.state)}</Tag></Right>
          </Row>

          <Row>
            <span style={mono}>away</span>
            <Right>
              {p.away === true
                ? <Tag c="var(--accent)">AWAY &middot; cards also escalate</Tag>
                : <Tag c="var(--ink-3)">not known to be away</Tag>}
            </Right>
          </Row>
          {p.away === true ? (
            <Note>
              Decision cards also fan out to the governed escalation channels, inside the same budget-gated
              push &mdash; no extra interrupt slot (autonomy/escalation.py AwayNotifier).
            </Note>
          ) : (
            <Note>
              away is COMPUTED, not reported: _compute_away returns false for a stale signal and for state
              &lsquo;unknown&rsquo; (fail-calm), and idle never counts as away because idle_is_away is not enabled in
              production (orchestrator.py:503-505). false therefore means &ldquo;not known to be away&rdquo; and nothing
              more &mdash; it is not evidence the owner is at the desk.
            </Note>
          )}

          <Row>
            <span style={mono}>freshness</span>
            <Right>
              {p.stale === true
                ? <Tag c="var(--amber)">STALE</Tag>
                : <Tag c="var(--ink-3)">fresh</Tag>}
              <Tag>ttl {p.ttl_seconds}s</Tag>
            </Right>
          </Row>
          {p.stale === true && (
            <Note c="var(--amber)">
              Signal older than ttl_seconds ({String(p.ttl_seconds)}s), or never reported at all. A stale signal
              computes away=false by design (fail-calm), so this reads as &ldquo;unknown&rdquo;, not &ldquo;at the desk&rdquo;.
            </Note>
          )}

          <Row>
            <span style={mono}>daemon</span>
            <Right>
              {p.ever_reported === false
                ? <Tag c="var(--amber)">NEVER REPORTED</Tag>
                : <Tag>{p.source ? String(p.source) : `${EM} no source label`}</Tag>}
            </Right>
          </Row>
          {p.ever_reported === false && (
            <Note c="var(--amber)">
              No owner-side host daemon has ever posted. The state above is the constructor default and the
              timestamps below are when the tracker was CONSTRUCTED (orchestrator boot), not when a signal
              arrived.
            </Note>
          )}

          <Row>
            <span style={mono}>idle_seconds</span>
            <Right>
              {p.idle_seconds == null
                ? <Tag>{EM} not reported</Tag>
                : <Tag>{String(p.idle_seconds)}s since last input</Tag>}
            </Right>
          </Row>

          <Row>
            <span style={mono}>{reported ? 'last signal' : 'tracker created'}</span>
            <Right>
              <Tag>{stamp(p.updated_at)}</Tag>
              <Tag>{ageOf(p.updated_at)}</Tag>
            </Right>
          </Row>
          <Row>
            <span style={mono}>{reported ? 'in state since' : 'default state since'}</span>
            <Right>
              <Tag>{stamp(p.since)}</Tag>
              <Tag>{ageOf(p.since)}</Tag>
            </Right>
          </Row>
        </>
      )}

      <Note>
        Read-only by design: POST /api/presence/owner is admin-guarded and is written by the owner-side host
        daemon (Windows idle/lock watcher, or the Tauri host overlay &mdash; presence.py:1-14). A hand-set presence
        would forge the one signal whose whole value is that a daemon observed it, so this panel offers no setter.
      </Note>

      <Head k="CHANNEL INBOX STORE" note="GET /api/channels/inbox/status — is anything being persisted at all" />
      <State e={inbox.e} loading={inbox.loading} n={ib ? 1 : 0} />
      {inbox.e && (
        <Note c="var(--amber)">
          This route has no 503 branch, so the failure above is transport or the user guard (401/403), never
          component availability. It is shown exactly as thrown, uninterpreted.
        </Note>
      )}

      {ib && (
        <>
          <Row>
            <span style={mono}>store</span>
            <Right>
              {bound
                ? <Tag c="var(--green)">BOUND</Tag>
                : unbound
                  ? <Tag c="var(--amber)">NOT BOUND</Tag>
                  : <Tag c="var(--amber)">{EM} no enabled flag in payload</Tag>}
            </Right>
          </Row>
          {unbound && (
            <Note c="var(--amber)">
              orch.channel_inbox is unbound &mdash; nothing is being persisted. The threads/messages figures below
              are the handler&rsquo;s hardcoded placeholders (integrations.py:132-133), not a measurement, and the
              ring-buffer cap is absent from this branch entirely.
            </Note>
          )}

          <Row>
            <span style={mono}>threads</span>
            <Right>
              <Tag c={unbound ? 'var(--ink-3)' : undefined}>
                {st.threads == null ? EM : String(st.threads)}{unbound ? ' (placeholder)' : ''}
              </Tag>
            </Right>
          </Row>
          <Row>
            <span style={mono}>messages</span>
            <Right>
              <Tag c={unbound ? 'var(--ink-3)' : undefined}>
                {st.messages == null ? EM : String(st.messages)}{unbound ? ' (placeholder)' : ''}
              </Tag>
            </Right>
          </Row>
          <Row>
            <span style={mono}>cap</span>
            <Right>
              <Tag c={st.max_messages == null ? 'var(--ink-3)' : undefined}>
                {st.max_messages == null
                  ? `${EM} not in payload`
                  : `${st.max_messages} (ring buffer — older messages drop)`}
              </Tag>
            </Right>
          </Row>

          <Row>
            <span style={mono}>channels</span>
            <Right>
              {channels.length === 0
                ? <Tag c="var(--amber)">{EM} no channels key</Tag>
                : channels.map((c) => <Tag key={String(c)}>{String(c)}</Tag>)}
            </Right>
          </Row>
          <Note>
            Persisted channels exactly as the store reports them. The handler notes that only telegram/web are
            live reply transports in this wave (integrations.py:124) while SUPPORTED_INBOX_CHANNELS also contains
            email &mdash; so a channel listed here is not automatically replyable.
          </Note>
        </>
      )}

      <Note>
        This is the flag the shipped COMMS inbox cannot see: GET /api/channels/inbox answers {'{"threads": []}'}
        both when the store is empty and when it is unbound, so only this status read tells the two apart. Both
        reads on this panel are user tier (user_guard); neither sends an admin token.
      </Note>
    </Card>
  );
}
