/* HOST READINESS — what this machine can honestly offer the computer operator, and
   exactly what stands in the way (GET /api/host/probe, user-guarded, observe-only).

   The probe is the evidence behind every "Nerva can drive this box" claim. It never
   prompts, never installs, never escalates: it reads what is already true and reports
   it. This panel renders that verbatim.

   Honesty contract:
   · Permissions are TRI-STATE. `true`/`false` are established facts; `null` means the
     probe could not establish it without prompting or without an absent dependency.
     `null` renders as "unknown" in grey — never as a red "no" and never as a green
     "yes", because a guess here would be a claim about the owner's machine.
   · Every refusal is drawn from the backend's closed vocabulary and is shown with the
     backend's own hint text, unedited. The panel adds no advice of its own.
   · `ok` means "nothing in the vocabulary is blocking", not "the operator is enabled":
     the desktop flags are shown separately, so a green readiness chip next to an unset
     flag reads as what it is — capable but switched off.
   · A probe that could not run answers `probed:false` with `reason:"probe_failed"` and
     no facts. That renders as its own state, never as a host with zero capabilities.

   NOTE: never spell a route path in this comment unless the panel calls it —
   tests/test_hud_v2_parity.py:_has_caller matches comment text as a caller. */
import React from 'react';
import { useApi, mono, asLive, Card, State, Row, Tag } from '../panel-kit';

const PROBE_PATH = '/api/host/probe';

const EM = '—';

const Head = ({ k }: { k: any }) => (
  <div style={{ ...mono, fontSize: 10, letterSpacing: '.08em', color: 'var(--ink-2)', marginTop: 10, marginBottom: 2 }}>{k}</div>
);

const Note = ({ c, children }: { c?: any; children?: any }) => (
  <div style={{ fontSize: 10, lineHeight: 1.5, color: c || 'var(--ink-2)', padding: '3px 0 5px' }}>{children}</div>
);

/* A tri-state fact. `null`/`undefined` is "unknown", which is neither pass nor fail. */
const TriTag = ({ v }: { v: any }) => {
  if (v === true) return <Tag c="var(--green)">yes</Tag>;
  if (v === false) return <Tag c="var(--red)">no</Tag>;
  return <Tag c="var(--ink-3)">unknown</Tag>;
};

const PLATFORM_LABEL: Record<string, string> = {
  windows: 'Windows',
  macos: 'macOS',
  'linux-x11': 'Linux · X11',
  'linux-wayland': 'Linux · Wayland',
  headless: 'headless (no graphical session)',
};

/* Permission keys the probe always reports, in a fixed order so the card does not
   reshuffle between reloads. Anything the backend adds later still renders, below. */
const PERMISSION_ORDER = [
  'accessibility_trusted',
  'screen_capture',
  'atspi_available',
  'portal_remote_desktop_version',
  'xdg_session_type',
  'process_elevated',
  'uinput_writable',
  'vlm_proven_local',
];

const isPlain = (v: any) => typeof v === 'string' || typeof v === 'number';

export function HostReadinessPanel() {
  const { d, e, loading, reload } = useApi(PROBE_PATH);
  const raw: any = d;
  const probed = !!(raw && raw.probed);
  const deps: Record<string, any> = (raw && raw.deps) || {};
  const binaries: Record<string, any> = (raw && raw.binaries) || {};
  const flags: Record<string, any> = (raw && raw.flags) || {};
  const permissions: Record<string, any> = (raw && raw.permissions) || {};
  const refusals: string[] = Array.isArray(raw && raw.refusals) ? raw.refusals : [];
  const warnings: string[] = Array.isArray(raw && raw.warnings) ? raw.warnings : [];
  const hints: Record<string, string> = (raw && raw.hints) || {};
  const ready = !!(raw && raw.ok);
  const platform = String((raw && raw.platform) || '');
  const anyFlagOn = Object.values(flags).some(Boolean);

  const permKeys = [
    ...PERMISSION_ORDER.filter((k) => k in permissions),
    ...Object.keys(permissions).filter((k) => !PERMISSION_ORDER.includes(k)),
  ];

  return (
    <Card
      title="HOST READINESS"
      live={asLive(d)}
      sub={probed ? PLATFORM_LABEL[platform] || platform || null : null}
      onReload={reload}
    >
      <State e={e} loading={loading} n={d ? 1 : 0} />
      {raw && !probed && (
        <>
          <Row>
            <span style={mono}>probe</span>
            <span style={{ marginLeft: 'auto' }}>
              <Tag c="var(--red)">{String(raw.reason || 'probe_failed')}</Tag>
            </span>
          </Row>
          <Note c="var(--ink-2)">
            The probe did not run on this host, so nothing is known about it. This is not
            the same as a host with no capabilities: no facts were collected at all.
          </Note>
        </>
      )}
      {raw && probed && (
        <>
          <Row>
            <span style={mono}>operator</span>
            <span style={{ marginLeft: 'auto', display: 'flex', gap: 5, alignItems: 'center' }}>
              <Tag c={ready ? 'var(--green)' : 'var(--amber)'}>
                {ready ? 'nothing blocking' : `${refusals.length} blocker(s)`}
              </Tag>
              <Tag c={anyFlagOn ? 'var(--green)' : 'var(--ink-3)'}>
                {anyFlagOn ? 'a host rail is armed' : 'all host rails off'}
              </Tag>
            </span>
          </Row>
          {ready && !anyFlagOn && (
            <Note c="var(--ink-2)">
              Capable but switched off: nothing in the refusal vocabulary blocks the
              operator here, and no host rail is armed. Readiness is not enablement.
            </Note>
          )}

          {refusals.length > 0 && <Head k="BLOCKING" />}
          {refusals.map((r) => (
            <div key={r} style={{ padding: '3px 0 5px' }}>
              <Row>
                <span style={{ ...mono, color: 'var(--red)' }}>{r}</span>
              </Row>
              {hints[r] && <Note c="var(--ink-2)">{hints[r]}</Note>}
            </div>
          ))}

          {warnings.length > 0 && <Head k="WARNINGS" />}
          {warnings.map((w, i) => (
            <Note key={i} c="var(--amber)">{w}</Note>
          ))}

          {permKeys.length > 0 && <Head k="PERMISSIONS" />}
          {permKeys.map((k) => (
            <Row key={k}>
              <span style={mono}>{k}</span>
              <span style={{ marginLeft: 'auto' }}>
                {isPlain(permissions[k]) && permissions[k] !== ''
                  ? <Tag>{String(permissions[k])}</Tag>
                  : <TriTag v={permissions[k]} />}
              </span>
            </Row>
          ))}

          {Object.keys(deps).length > 0 && <Head k="LIBRARIES" />}
          {Object.keys(deps).length > 0 && (
            <Row>
              <span style={{ display: 'flex', gap: 5, flexWrap: 'wrap' }}>
                {Object.keys(deps).map((k) => (
                  <Tag key={k} c={deps[k] ? 'var(--green)' : 'var(--ink-3)'}>{k}</Tag>
                ))}
              </span>
            </Row>
          )}

          {Object.keys(binaries).length > 0 && <Head k="TOOLS" />}
          {Object.keys(binaries).length > 0 && (
            <Row>
              <span style={{ display: 'flex', gap: 5, flexWrap: 'wrap' }}>
                {Object.keys(binaries).map((k) => (
                  <Tag key={k} c={binaries[k] ? 'var(--green)' : 'var(--ink-3)'}>{k}</Tag>
                ))}
              </span>
            </Row>
          )}

          {Object.keys(flags).length > 0 && <Head k="HOST RAILS" />}
          {Object.keys(flags).map((k) => (
            <Row key={k}>
              <span style={{ ...mono, fontSize: 10 }}>{k}</span>
              <span style={{ marginLeft: 'auto' }}>
                <Tag c={flags[k] ? 'var(--green)' : 'var(--ink-3)'}>{flags[k] ? 'on' : 'off'}</Tag>
              </span>
            </Row>
          ))}

          <Row>
            <span style={mono}>fingerprint</span>
            <span style={{ ...mono, marginLeft: 'auto', fontSize: 10, color: 'var(--ink-2)' }}>
              {String((raw && raw.fingerprint) || EM).slice(0, 16)}
            </span>
          </Row>
          <Note>
            Observe-only: this probe never prompts for a permission, installs a library or
            escalates. An <b>unknown</b> permission means it could not be established
            without doing one of those things, so Nerva declines to guess.
          </Note>
        </>
      )}
    </Card>
  );
}

export default HostReadinessPanel;
