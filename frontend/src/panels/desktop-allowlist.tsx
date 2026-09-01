/* DESKTOP ALLOWLIST — the one inspectable route of the 0.25 Desktop Control Pack
   (`GET /api/desktop/allowlist`, agents/core/routers/multimodal.py:216), shipped with no
   client that ever read it.

   What this panel is, precisely: a window onto the vocabulary the desktop pack will PLAN
   against. It is NOT a remote control, and it deliberately carries no buttons other than
   reload. Three facts shape every line below:

   1. The route is a constant read. `allowlist()` (desktop_control.py:130-138) has no
      branches, calls no orchestrator and does no desktop I/O — the handler docstring says
      so verbatim. So this surface structurally CANNOT emit a 503, an {ok:false} or a
      `reason`. There is no "component unavailable" state to render, and inventing one
      would be exactly as dishonest as rendering a fabricated zero.
   2. The only non-200s come from the shared `user_guard` (401/403) and the per-IP rate
      limiter (429). `apiGet` throws WITHOUT a body (api/client.ts:106 attaches `status`
      but not the JSON), so the backend's `detail` string is NOT reachable from here. The
      panel prints `err.message` (e.g. "GET /api/desktop/allowlist -> 401") through
      <State/> and nothing more — it never prints "user token required" as if it had been
      received. Everything below is gated on `d`, so a refused read can never paint an
      empty allowlist.
   3. Nothing here is runnable from this Console. `tests/test_desktop_control.py:194`
      pins that every step planned from this vocabulary is REFUSED by POST
      /api/desktop/run — `launch`/`screenshot` as `unexpected_action_args` (the pack's
      steps carry args.target="desktop", which the executor's per-action rules do not
      admit) and volume/brightness/media/lock/sleep/`record` as `unsupported_action` (no
      rule at all). The shipped execution path is the in-process DesktopControl.run →
      GovernedDesktop.run composition, which has no production constructor. So: no launch
      button, no mute button, no record button. Inspectable, not actuable.

   Also deliberate: the two desktop/operator PLAN routes are not wired here. Their paths are
   spelled out only on their entries in tests/test_hud_v2_parity.py, never in this file: the
   parity matcher counts any literal occurrence in a client file as a caller, so naming them
   in this comment would fake a caller and let them leave the punch list without a UI. They
   are consumed by the agent's ToolRPC `desktop_plan` tool (autonomy_coordinator.py:492) via
   an in-process import, and BACKLOG.md:947-950 keeps a HUD form over them out of scope as
   the degenerate surface. Keys are rendered verbatim: the human labels ("Web browser", "Code editor")
   live in APPS on the backend and are NOT in this payload, so re-labelling client-side
   would be inventing text the route never sent. */
import React from 'react';
import { useApi, arr, mono, asLive, Card, State, Row, Tag } from '../panel-kit';

const ALLOWLIST_PATH = '/api/desktop/allowlist';

/* Section header: a key name plus the provenance of whatever the rows below assert. */
const Head = ({ k, note }) => (
  <div style={{ marginTop: 10, marginBottom: 2 }}>
    <div style={{ ...mono, fontSize: 10, letterSpacing: '.08em', color: 'var(--ink-2)' }}>{k}</div>
    <div style={{ fontSize: 10, color: 'var(--ink-3)' }}>{note}</div>
  </div>
);

/* A key that did not arrive as an array is NOT zero rows — `arr()` would quietly yield []
   and the group would read as "this install allows nothing here". Say what is true. */
const Missing = ({ k }) => (
  <Row><span style={{ ...mono, color: 'var(--amber)' }}>{k + ' not in payload'}</span></Row>
);

export function DesktopAllowlistPanel() {
  const { d, e, loading, reload } = useApi(ALLOWLIST_PATH);   // user tier (user_guard)

  const raw: any = d;
  const has = (k) => Array.isArray(raw && raw[k]);

  const apps = arr(d, 'apps');
  const osActions = arr(d, 'os_actions');
  const readOnly = arr(d, 'read_only');
  const recording = arr(d, 'recording');
  const total = apps.length + osActions.length + recording.length;

  /* The read-only/mutating split is the BACKEND's own rule, not a client guess:
     allowlist() builds `read_only` as the non-mutating subset of OS_ACTIONS, and
     desktop_control._step sets requires_approval = mutating. We only read that list. */
  const isReadOnly = (k) => readOnly.indexOf(k) !== -1;
  /* Defensive: read_only is documented as a subset of os_actions. If it ever isn't, the
     extra keys are shown rather than silently dropped. */
  const orphanReadOnly = readOnly.filter((k) => osActions.indexOf(k) === -1);

  return (
    <Card
      title="DESKTOP ALLOWLIST"
      live={asLive(d)}
      sub={d ? `${apps.length} apps · ${osActions.length} OS actions · ${recording.length} recording ops` : null}
      onReload={reload}
    >
      <State e={e} loading={loading} n={d ? total : 0} />
      {d && (
        <>
          <Head k="apps" note="launch keys — the host resolves a key to a vetted launcher; the pack never emits a binary path." />
          {has('apps')
            ? apps.map((a, i) => (
              <Row key={a || i}><span style={{ ...mono, color: 'var(--accent-light)' }}>{a}</span></Row>
            ))
            : <Missing k="apps" />}

          <Head k="os_actions" note={has('read_only')
            ? 'tag from this payload’s own read_only list — keys outside it are the mutating, approval-gated ones.'
            : 'read_only was not in this payload, so read-only vs mutating cannot be derived — no tag is shown.'} />
          {has('os_actions')
            ? osActions.map((a, i) => (
              <Row key={a || i}>
                <span style={{ ...mono, color: 'var(--accent-light)' }}>{a}</span>
                {has('read_only') && (
                  <span style={{ marginLeft: 'auto' }}>
                    {isReadOnly(a)
                      ? <Tag c="var(--green)">read-only</Tag>
                      : <Tag c="var(--amber)">mutating · requires approval</Tag>}
                  </span>
                )}
              </Row>
            ))
            : <Missing k="os_actions" />}
          {!has('read_only') && <Missing k="read_only" />}
          {orphanReadOnly.map((a, i) => (
            <Row key={'orphan-' + (a || i)}>
              <span style={{ ...mono, color: 'var(--amber)' }}>{a}</span>
              <span style={{ marginLeft: 'auto' }}><Tag c="var(--amber)">in read_only but not in os_actions</Tag></span>
            </Row>
          ))}

          <Head k="recording" note="screen-recording ops this pack will plan." />
          {has('recording')
            ? recording.map((r, i) => (
              <Row key={r || i}><span style={{ ...mono, color: 'var(--accent-light)' }}>{r}</span></Row>
            ))
            : <Missing k="recording" />}

          <div style={{ fontSize: 10, color: 'var(--ink-3)', marginTop: 8, lineHeight: 1.5 }}>
            User-tier read (user_guard). Constant vocabulary — no orchestrator, no desktop I/O — so this
            route has no 503 and no {'{ok:false}'} path; a blank panel above means the read itself was
            refused, not an empty allowlist.
            <br />
            This is what the pack will PLAN. Today the consumer is the agent’s <span style={mono}>desktop_plan</span> ToolRPC
            tool, not this Console — nothing here launches, mutes or records anything.
            <br />
            Planned steps are not postable to /api/desktop/run: they carry args.target="desktop" (refused
            <span style={mono}> unexpected_action_args</span>) and volume/brightness/media/lock/sleep/record have no run rule at
            all (<span style={mono}>unsupported_action</span>). Pinned by
            tests/test_desktop_control.py::test_planned_steps_are_not_postable_to_the_http_run_route.
            <br />
            The Operator panel’s desktop preview/run uses a different vocabulary
            (observe/read/locate/click/type/launch/screenshot); only launch and screenshot share a name.
          </div>
        </>
      )}
    </Card>
  );
}
