// @ts-nocheck
/* HUD-v3 · BRIEFING WALL + NEURAL BURST — the wall-screen briefing surface built from the
   owner-supplied reference video (docs/design/JARVIS_PRESENCE_GAP.md).

   The reference's cards carry a marketing agency's KPIs. Nerva has no such numbers, so the
   contract pinned here is: every cell is either a figure this hub can prove, or an em dash
   with the reason — never a plausible-looking value. The field obeys the same rule: an empty
   roster draws an empty field, and firing is driven by real executing agents / running tasks
   / a measured mic level. */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import React from 'react';
import { render, fireEvent } from '@testing-library/react';
import { BriefingWall, wallState, wallClock, readTranscriptPref } from '../wall';
import { NeuralBurst, burstRegions, burstEnergy } from '../burst';
import { CinemaMesh } from '../shell';

let rafCb: any = null;
beforeEach(() => {
  rafCb = null;
  HTMLCanvasElement.prototype.getContext = vi.fn(() => null);
  vi.spyOn(globalThis, 'requestAnimationFrame').mockImplementation((cb) => { rafCb = cb; return 1; });
  vi.spyOn(globalThis, 'cancelAnimationFrame').mockImplementation(() => {});
});
afterEach(() => { vi.restoreAllMocks(); });

/* Read one stat cell by its label. Assertions target the cell, never the whole wall —
   the wall renders a live clock and a date, so a DOM-wide substring check on a digit is
   an assertion about the time of day. */
function cellValue(container: any, label: string) {
  const row = Array.from(container.querySelectorAll('.wl-row'))
    .find((r: any) => r.querySelector('.wl-k') && r.querySelector('.wl-k').textContent === label);
  return row ? (row as any).querySelector('.wl-v').textContent.trim() : null;
}

const AGENTS = [
  { id: 'jarvis', name: 'Jarvis', tier: 'CNS', status: 'active' },
  { id: 'pepper', name: 'Pepper', tier: 'CNS', status: 'idle' },
  { id: 'athena', name: 'Athena', tier: 'BUS', status: 'busy' },
  { id: 'frigga', name: 'Frigga', tier: 'FND', status: 'idle' },
];
const TASKS = [
  { id: 't1', owner: 'athena', state: 'running' },
  { id: 't2', owner: 'frigga', state: 'waiting' },
];

describe('burstRegions — real roster → real regions', () => {
  it('groups by tier with the true agent count and only counts executing agents as firing', () => {
    const regions = burstRegions({ agents: AGENTS, tasks: TASKS });
    const byKey = Object.fromEntries(regions.map((r) => [r.key, r]));
    expect(byKey.cns.nodes).toBe(2);
    expect(byKey.cns.firing).toBe(1);          // active counts, idle does not
    expect(byKey.bus.nodes).toBe(1);
    expect(byKey.bus.firing).toBe(1);          // busy counts
    expect(byKey.fnd.firing).toBe(0);
  });

  it('attributes running tasks to the owning tier, and ignores non-running ones', () => {
    const byKey = Object.fromEntries(burstRegions({ agents: AGENTS, tasks: TASKS }).map((r) => [r.key, r]));
    expect(byKey.bus.tasks).toBe(1);           // athena's running task
    expect(byKey.fnd.tasks).toBe(0);           // frigga's task is waiting, not running
  });

  it('draws nothing from an empty roster', () => {
    expect(burstRegions({ agents: [], tasks: [] })).toEqual([]);
    expect(burstRegions()).toEqual([]);
  });
});

describe('burstEnergy — the light has to come from somewhere', () => {
  it('uses the measured mic level only while listening', () => {
    const loud = burstEnergy({ voice: { status: 'listening', level: 0.25 } });
    const quiet = burstEnergy({ voice: { status: 'listening', level: 0 } });
    expect(loud.source).toBe('mic');
    expect(loud.level).toBeGreaterThan(quiet.level);
    // the same loud mic must not leak into a state the mic isn't measuring
    expect(burstEnergy({ voice: { status: 'speaking', level: 0.25 } }).source).toBe('voice');
  });

  it('falls back to live cabinet work, then to a quiet idle', () => {
    const work = burstEnergy({ agents: AGENTS, tasks: TASKS });
    expect(work.source).toBe('work');
    expect(work.detail).toContain('executing');
    const idle = burstEnergy({ agents: [{ id: 'a', tier: 'CNS', status: 'idle' }], tasks: [] });
    expect(idle.source).toBe('idle');
    expect(idle.level).toBeLessThan(0.1);
  });

  it('labels demo choreography as demo, never as evidence', () => {
    expect(burstEnergy({ demo: true }).source).toBe('demo');
  });
});

describe('NeuralBurst — canvas', () => {
  it('mounts, reports its region count, and survives a null 2D context', () => {
    const { container } = render(<NeuralBurst agents={AGENTS} tasks={TASKS} />);
    const el = container.querySelector('.nburst');
    expect(el).toBeTruthy();
    expect(el.getAttribute('data-regions')).toBe('3');
    expect(el.getAttribute('data-energy-source')).toBe('work');
    expect(() => rafCb && rafCb()).not.toThrow();
  });

  it('says so when there is no roster instead of drawing a decorative field', () => {
    const { container } = render(<NeuralBurst agents={[]} tasks={[]} />);
    expect(container.querySelector('.nburst').getAttribute('data-regions')).toBe('0');
    expect(container.textContent).toContain('no agents reported');
  });
});

describe('wallState — the word on the wall', () => {
  it('prefers the voice loop, then live work, then connectivity', () => {
    expect(wallState({ voice: { status: 'listening' }, serverUp: true }).word).toBe('listening');
    expect(wallState({ voice: { status: 'speaking' }, serverUp: true }).word).toBe('speaking');
    expect(wallState({ voice: { error: 'no mic' }, serverUp: true }).tone).toBe('bad');
    expect(wallState({ agents: AGENTS, tasks: TASKS, serverUp: true }).word).toBe('working');
    expect(wallState({ serverUp: false }).word).toBe('offline');
    expect(wallState({ serverUp: true }).word).toBe('standing by');
  });
  it('pads the clock', () => {
    expect(wallClock(new Date(2026, 7, 6, 9, 5, 3))).toBe('09:05:03');
  });
});

describe('BriefingWall — every cell is proven or blank', () => {
  const LIVE = {
    agents: AGENTS, tasks: TASKS, decisions: [{}, {}], calendar: [{}], heartbeat: [{}],
    llm: { state: 'ready', model: 'gemma-4-26b', residents: [] },
    trust: { mic: 'on', strict_local: true },
    sources: { tasks: true, trust: true, agents: true }, localPct: 94,
    voice: { status: 'listening', level: 0.1, transcript: 'give me a recap', caps: { stt: true, tts: true } },
    serverUp: true, clock: new Date(2026, 7, 6, 22, 31, 23),
  };

  it('shows the real figures it has', () => {
    const { container } = render(<BriefingWall {...LIVE} />);
    expect(container.textContent).toContain('94%');
    expect(container.textContent).toContain('gemma-4-26b');
    expect(container.textContent).not.toContain('give me a recap');   // redacted by default
    fireEvent.click(container.querySelector('.wl-said-toggle'));
    expect(container.textContent).toContain('give me a recap');
    localStorage.removeItem('hud.wall.transcript');
    expect(container.textContent).toContain('22:31:23');
    expect(container.querySelector('.wl-state-word').textContent).toBe('listening');
  });

  it('renders an em dash with a reason — never a number — where there is no evidence', () => {
    const { container } = render(
      <BriefingWall agents={[]} tasks={[]} llm={{ state: 'unknown', residents: [] }}
        trust={null} sources={{ tasks: false, trust: false }} localPct={null}
        voice={{ status: 'off', caps: null }} serverUp={false} clock={new Date()} />,
    );
    const missing = Array.from(container.querySelectorAll('.wl-miss'));
    expect(missing.length).toBeGreaterThan(4);
    missing.forEach((m) => {
      expect(m.textContent.trim()).toBe('—');
      expect(m.getAttribute('title')).toBeTruthy();      // the reason is always attached
    });
    // no fabricated locality/model figure in the cells that would carry them
    expect(cellValue(container, 'ON-DEVICE')).toBe('—');
    expect(cellValue(container, 'LOCAL MODEL')).toBe('—');
    expect(cellValue(container, 'CLOUD LANE')).toBe('—');
    expect(container.textContent).toContain('BACKEND OFFLINE');
    expect(container.textContent).toContain('room mode');            // spoken line redacted by default
  });

  it('badges demo mode instead of passing seeded data off as live', () => {
    const { container } = render(<BriefingWall {...LIVE} demo={true} />);
    expect(container.textContent).toContain('DEMO');
    expect(container.textContent).toContain('seeded data');
  });

  it('exits on the esc control', () => {
    const onExit = vi.fn();
    const { container } = render(<BriefingWall {...LIVE} onExit={onExit} />);
    fireEvent.click(container.querySelector('.wl-exit'));
    expect(onExit).toHaveBeenCalled();
  });
});

describe('BriefingWall — hold to talk', () => {
  const base = {
    agents: AGENTS, tasks: TASKS, sources: { tasks: true, trust: true },
    serverUp: true, clock: new Date(), llm: null, localPct: null,
  };

  it('drives the real voice loop: press starts, release stops', () => {
    const voice = { status: 'off', supported: true, caps: null, start: vi.fn(), stop: vi.fn() };
    const { container } = render(<BriefingWall {...base} trust={{ mic: 'on' }} sources={{ tasks: true, trust: true }} voice={voice} />);
    const btn = container.querySelector('.wl-ptt');
    expect(btn.textContent).toContain('hold to talk');
    fireEvent.pointerDown(btn);
    expect(voice.start).toHaveBeenCalled();
    expect(container.querySelector('.wl-ptt.on')).toBeTruthy();
    fireEvent.pointerUp(btn);
    expect(voice.stop).toHaveBeenCalled();
    expect(container.querySelector('.wl-ptt.on')).toBeNull();
  });

  it('refuses honestly when the mic is muted, and never calls start', () => {
    const voice = { status: 'off', supported: true, caps: null, start: vi.fn(), stop: vi.fn() };
    const { container } = render(<BriefingWall {...base} trust={{ mic: 'off' }} sources={{ tasks: true, trust: true }} voice={voice} />);
    const btn = container.querySelector('.wl-ptt');
    expect(btn.textContent).toContain('mic muted');
    expect(btn.disabled).toBe(true);
    fireEvent.pointerDown(btn);
    expect(voice.start).not.toHaveBeenCalled();
  });

  it('says voice is unavailable when the browser cannot capture audio', () => {
    const { container } = render(<BriefingWall {...base} trust={{ mic: 'on' }} sources={{ tasks: true, trust: true }} voice={{ status: 'off', supported: false, caps: null }} />);
    expect(container.querySelector('.wl-ptt').textContent).toContain('voice unavailable');
    expect(container.querySelector('.wl-ptt').disabled).toBe(true);
  });
});

describe('BriefingWall — edge tabs', () => {
  it('carries live counts so a narrow screen still reports load', () => {
    const { container } = render(
      <BriefingWall agents={AGENTS} tasks={TASKS} sources={{ tasks: true }} serverUp={true} clock={new Date()} />,
    );
    expect(container.querySelector('.wl-tab-left').textContent).toContain('1');   // one running task (the other is waiting)
    expect(container.querySelector('.wl-tab-right').textContent).toContain('4');  // roster size
  });

  it('drops the badge rather than showing 0 when the task feed is unavailable', () => {
    const { container } = render(
      <BriefingWall agents={[]} tasks={[]} sources={{ tasks: false }} serverUp={false} clock={new Date()} />,
    );
    expect(container.querySelector('.wl-tab-left .wl-tab-badge')).toBeNull();
    expect(container.querySelector('.wl-tab-right .wl-tab-badge')).toBeNull();
  });
});

/* Hostile regressions from the 2026-08-06 integration review. Both are about evidence
   outliving its proof: a task array retained from an earlier poll, and a `trust` object
   that app.tsx deliberately KEEPS across polls (`if (d.trust) setTrust(d.trust)`). Neither
   may drive a claim — or a microphone — once its `sources` flag goes away. */
describe('BriefingWall — stale evidence drives nothing', () => {
  const STALE = {
    agents: AGENTS,
    tasks: [
      { id: 't1', owner: 'athena', state: 'running' },
      { id: 't2', owner: 'jarvis', state: 'running' },
    ],
    sources: { tasks: false, trust: false },      // the feed did NOT answer this load
    serverUp: true, clock: new Date(), llm: null, localPct: null,
    voice: { status: 'off', caps: null },
    agentsAllIdle: true,
  };

  it('a stale non-empty task array cannot make the wall claim work', () => {
    const idleAgents = AGENTS.map((a) => ({ ...a, status: 'idle' }));
    const { container } = render(<BriefingWall {...STALE} agents={idleAgents} trust={null} />);
    // the wall must not say "working" on evidence it cannot prove
    expect(container.querySelector('.wl-state-word').textContent).toBe('standing by');
    // …nor count them (assert the exact cells: the wall also renders a live clock,
    // so scanning the whole DOM for a digit is a time-of-day-dependent assertion)
    expect(cellValue(container, 'TASKS RUNNING')).toBe('—');
    expect(cellValue(container, 'TASKS WAITING')).toBe('—');
    // …nor badge them
    expect(container.querySelector('.wl-tab-left .wl-tab-badge')).toBeNull();
    // …and the field must be told there are no tasks, so nothing fires on their account
    expect(container.querySelector('.nburst').getAttribute('data-energy-source')).toBe('idle');
  });

  it('the same array DOES drive the wall once its source flag is present', () => {
    const idleAgents = AGENTS.map((a) => ({ ...a, status: 'idle' }));
    const { container } = render(
      <BriefingWall {...STALE} agents={idleAgents} trust={null} sources={{ tasks: true, trust: false }} />,
    );
    expect(container.querySelector('.wl-state-word').textContent).toBe('working');
    expect(container.querySelector('.nburst').getAttribute('data-energy-source')).toBe('work');
  });

  it('burstEnergy and wallState agree with the wall about an empty task set', () => {
    expect(burstEnergy({ agents: AGENTS.map((a) => ({ ...a, status: 'idle' })), tasks: [] }).source).toBe('idle');
    expect(wallState({ agents: AGENTS.map((a) => ({ ...a, status: 'idle' })), tasks: [], serverUp: true }).word).toBe('standing by');
  });
});

describe('BriefingWall — the mic fails closed without current trust evidence', () => {
  const base = {
    agents: AGENTS, tasks: [], serverUp: true, clock: new Date(), llm: null, localPct: null,
  };

  it('refuses to open the mic when trust evidence is missing, even with a retained mic:on', () => {
    const voice = { status: 'off', supported: true, caps: null, start: vi.fn(), stop: vi.fn() };
    const { container } = render(
      <BriefingWall {...base} trust={{ mic: 'on' }} sources={{ tasks: true, trust: false }} voice={voice} />,
    );
    const btn = container.querySelector('.wl-ptt');
    expect(btn.textContent).toContain('trust status unavailable');
    expect(btn.disabled).toBe(true);
    fireEvent.pointerDown(btn);
    expect(voice.start).not.toHaveBeenCalled();
  });

  it('refuses with no trust object at all', () => {
    const voice = { status: 'off', supported: true, caps: null, start: vi.fn(), stop: vi.fn() };
    const { container } = render(<BriefingWall {...base} trust={null} sources={{ tasks: true, trust: false }} voice={voice} />);
    expect(container.querySelector('.wl-ptt').disabled).toBe(true);
    fireEvent.pointerDown(container.querySelector('.wl-ptt'));
    expect(voice.start).not.toHaveBeenCalled();
  });

  it('the rail refuses to report mic/strict-local state without that same evidence', () => {
    const { container } = render(
      <BriefingWall {...base} trust={{ mic: 'on', strict_local: true }} sources={{ tasks: true, trust: false }} voice={{ status: 'off' }} />,
    );
    const rows = Array.from(container.querySelectorAll('.wl-rail-row'));
    const micRow = rows.find((r) => r.textContent.startsWith('mic'));
    const localRow = rows.find((r) => r.textContent.startsWith('strict-local'));
    expect(micRow.querySelector('.wl-miss')).toBeTruthy();
    expect(localRow.querySelector('.wl-miss')).toBeTruthy();
  });

  it('opens only when the trust proof is current', () => {
    const voice = { status: 'off', supported: true, caps: null, start: vi.fn(), stop: vi.fn() };
    const { container } = render(
      <BriefingWall {...base} trust={{ mic: 'on' }} sources={{ tasks: true, trust: true }} voice={voice} />,
    );
    const btn = container.querySelector('.wl-ptt');
    expect(btn.disabled).toBe(false);
    fireEvent.pointerDown(btn);
    expect(voice.start).toHaveBeenCalled();
  });
});

describe('BriefingWall — the spoken line is room-facing', () => {
  const base = {
    agents: AGENTS, tasks: [], sources: { tasks: true, trust: true, agents: true }, trust: { mic: 'on' },
    serverUp: true, clock: new Date(),
    voice: { status: 'listening', supported: true, caps: null, transcript: 'my private sentence', start() {}, stop() {} },
  };

  it('opens REDACTED by default — a wall screen has an audience', () => {
    const { container } = render(<BriefingWall {...base} />);
    expect(container.textContent).not.toContain('my private sentence');
    expect(container.textContent).toContain('room mode');
  });

  it('shows the line only on an explicit opt-in, which persists', () => {
    const { container } = render(<BriefingWall {...base} />);
    fireEvent.click(container.querySelector('.wl-said-toggle'));
    expect(container.textContent).toContain('my private sentence');
    expect(localStorage.getItem('hud.wall.transcript')).toBe('shown');
    localStorage.removeItem('hud.wall.transcript');
  });

  it('defaults to hidden with no stored preference', () => {
    localStorage.removeItem('hud.wall.transcript');
    expect(readTranscriptPref()).toBe(false);
  });
});

/* Second review round: the mic must fail closed across its whole LIFECYCLE, not just at
   first render — unknown permission, permission lost mid-capture, and the wall going away
   while held are all ways an open microphone could outlive its authorization. */
describe('BriefingWall — push-to-talk lifecycle', () => {
  const ok = {
    agents: AGENTS, tasks: [], serverUp: true, clock: new Date(),
    sources: { tasks: true, trust: true, agents: true },
  };
  const mkVoice = () => ({ status: 'off', supported: true, caps: null, start: vi.fn(), stop: vi.fn() });

  it.each([
    ['missing', {}],
    ['unknown', { mic: 'unknown' }],
    ['malformed', { mic: 42 }],
    ['empty', { mic: '' }],
  ])('refuses capture when the mic state is %s — only an exact "on" authorizes', (_label, trust) => {
    const voice = mkVoice();
    const { container } = render(<BriefingWall {...ok} trust={trust} voice={voice} />);
    const btn = container.querySelector('.wl-ptt');
    expect(btn.disabled).toBe(true);
    fireEvent.pointerDown(btn);
    expect(voice.start).not.toHaveBeenCalled();
  });

  it('cuts an in-flight capture the moment permission is lost', () => {
    const voice = mkVoice();
    const { container, rerender } = render(<BriefingWall {...ok} trust={{ mic: 'on' }} voice={voice} />);
    fireEvent.pointerDown(container.querySelector('.wl-ptt'));
    expect(voice.start).toHaveBeenCalled();
    expect(voice.stop).not.toHaveBeenCalled();
    // the mic goes muted underneath a held button
    rerender(<BriefingWall {...ok} trust={{ mic: 'off' }} voice={voice} />);
    expect(voice.stop).toHaveBeenCalled();
    expect(container.querySelector('.wl-ptt.on')).toBeNull();
  });

  it('cuts an in-flight capture when trust evidence expires', () => {
    const voice = mkVoice();
    const { container, rerender } = render(<BriefingWall {...ok} trust={{ mic: 'on' }} voice={voice} />);
    fireEvent.pointerDown(container.querySelector('.wl-ptt'));
    expect(voice.stop).not.toHaveBeenCalled();
    rerender(<BriefingWall {...ok} sources={{ tasks: true, trust: false, agents: true }} trust={{ mic: 'on' }} voice={voice} />);
    expect(voice.stop).toHaveBeenCalled();
  });

  it('never leaves the loop running when the wall unmounts mid-hold', () => {
    const voice = mkVoice();
    const { container, unmount } = render(<BriefingWall {...ok} trust={{ mic: 'on' }} voice={voice} />);
    fireEvent.pointerDown(container.querySelector('.wl-ptt'));
    expect(voice.stop).not.toHaveBeenCalled();
    unmount();                       // Esc out of the wall, or a stage switch
    expect(voice.stop).toHaveBeenCalled();
  });

  it('is operable from the keyboard, and ignores key repeat', () => {
    const voice = mkVoice();
    const { container } = render(<BriefingWall {...ok} trust={{ mic: 'on' }} voice={voice} />);
    const btn = container.querySelector('.wl-ptt');
    fireEvent.keyDown(btn, { key: ' ' });
    expect(voice.start).toHaveBeenCalledTimes(1);
    fireEvent.keyDown(btn, { key: ' ', repeat: true });
    expect(voice.start).toHaveBeenCalledTimes(1);       // held, not re-triggered
    fireEvent.keyUp(btn, { key: ' ' });
    expect(voice.stop).toHaveBeenCalledTimes(1);
  });

  it('reports an unknown mic as UNKNOWN in the footer, not idle or muted', () => {
    const { container } = render(
      <BriefingWall {...ok} sources={{ tasks: true, trust: false }} trust={{ mic: 'on' }} voice={{ status: 'off' }} />,
    );
    expect(container.textContent).toContain('MIC · UNKNOWN');
  });
});

describe('BriefingWall — no metric cell claims a zero it cannot prove', () => {
  it('withholds roster/executing without agent evidence, and decisions without a feed', () => {
    const { container } = render(
      <BriefingWall agents={AGENTS} tasks={[]} decisions={[]} serverUp={true} clock={new Date()}
        sources={{ tasks: false, trust: false, agents: false }} voice={{ status: 'off' }} />,
    );
    expect(cellValue(container, 'AGENTS IN ROSTER')).toBe('—');
    expect(cellValue(container, 'EXECUTING')).toBe('—');
    expect(cellValue(container, 'DECISIONS PENDING')).toBe('—');
  });

  it('shows them once the evidence is there', () => {
    const { container } = render(
      <BriefingWall agents={AGENTS} tasks={[]} decisions={[{}, {}]} demo={true} serverUp={true} clock={new Date()}
        sources={{ tasks: true, trust: true, agents: true }} voice={{ status: 'off' }} />,
    );
    expect(cellValue(container, 'AGENTS IN ROSTER')).toBe('4');
    expect(cellValue(container, 'EXECUTING')).toBe('2');
    expect(cellValue(container, 'DECISIONS PENDING')).toBe('2');
  });

  it('every unmeasured cell carries its reason', () => {
    const { container } = render(
      <BriefingWall agents={[]} tasks={[]} decisions={[]} serverUp={false} clock={new Date()}
        sources={{}} trust={null} llm={null} localPct={null} voice={{ status: 'off' }} />,
    );
    const missing = Array.from(container.querySelectorAll('.wl-v.wl-miss'));
    expect(missing.length).toBeGreaterThanOrEqual(9);
    missing.forEach((m: any) => expect(m.getAttribute('title')).toBeTruthy());
  });
});

describe('CinemaMesh — brain stage', () => {
  it('switches to the briefing wall and back, and Esc still exits', () => {
    const onExit = vi.fn();
    const { container, getByTitle } = render(
      <CinemaMesh agents={AGENTS} tasks={TASKS} serverUp={true} voice={{ status: 'idle' }} onExit={onExit} t={{}} />,
    );
    expect(container.querySelector('.cin-stage .nmesh')).toBeTruthy();   // mesh is still default
    fireEvent.click(getByTitle('briefing wall (b)'));
    expect(container.querySelector('.wall')).toBeTruthy();
    expect(container.querySelector('.cinema')).toBeNull();               // the wall owns the screen
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(onExit).toHaveBeenCalled();
  });
});
