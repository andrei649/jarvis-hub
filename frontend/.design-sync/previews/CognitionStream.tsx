import React from 'react';
import { CognitionStream, buildTrace, V2 } from 'jarvis-hud-v2';

const T = V2.I18N.en;
const wrap: React.CSSProperties = { width: 520, background: 'var(--void, #04070e)', borderRadius: 8, padding: 16 };
/* the app marks stage progress on the trace it builds; mirror that here */
const withStates = (trace: any, states: string[]) => ({
  ...trace,
  stages: trace.stages.map((s: any, i: number) => ({ ...s, state: states[i] || '' })),
});

/** Completed trace — keyword chips, scored routing table with winner, all stages done. */
export function RoutedTrace() {
  const trace = withStates(
    buildTrace('draft the churn slide report before the raiffeisen meeting'),
    ['done', 'done', 'done', 'done'],
  );
  return (
    <div className="hud-root" style={wrap}>
      <CognitionStream trace={trace} t={T} />
    </div>
  );
}

/** In-flight, low confidence — escalation marker on ROUTE, later stages still dim. */
export function LowConfidence() {
  const trace = withStates(buildTrace('are you awake'), ['done', 'done', 'on', '']);
  return (
    <div className="hud-root" style={wrap}>
      <CognitionStream trace={trace} t={T} />
    </div>
  );
}

/** No trace yet — the brain empty state inviting the first message. */
export function Empty() {
  return (
    <div className="hud-root" style={wrap}>
      <div style={{ height: 280, display: 'flex', flexDirection: 'column' }}>
        <CognitionStream trace={null} t={T} />
      </div>
    </div>
  );
}
