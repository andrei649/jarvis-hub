/* H206 — the memory graph explorer: a star-map of what Nerva has stored.

   Canvas of the real graph (entities as diamonds, skills as circles, relations as
   lines) with camera controls, a legend, a timeline scrubber that answers "what did
   Nerva know at T", a node context menu, an editor and delete that go only through
   the kernel-mediated knowledge-graph routes, skills sourced from GET /skills (the
   governed off-switch is the existing skill switch), and a share/import map code.
   No sample data: an empty store says "Nothing learned yet", a failed read says
   "Could not load memory graph". Demo mode keeps its own sample star-map elsewhere. */
import React, { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import {
  loadFacts, loadMemoryMap, loadSkills, switchSkill,
  type FactsPage, type MemoryMapData, type SkillInfo, type TimelineAxis, type TimelineBounds,
} from '../api/memory-graph';
import { MAP_CODE_LIMITS, decodeMapCode, encodeMapCode, type MapContent } from '../api/memory-map-code';
import { DeleteEntityDialog, EditEntityDialog, describeError } from './memory-graph-dialogs';
import {
  VIEW, fit, layout, neighbourhood, typeColour, viewBox, zoomBy,
  type Camera, type GEdge, type GNode,
} from './memory-graph-layout';
import { inpS } from '../panel-kit';

const PAN_STEP = 40;
const PLAY_STEPS = 40;
const PLAY_MS = 350;
const DEBOUNCE_MS = 120;

const fmt = (seconds: number) => new Date(seconds * 1000).toISOString().slice(0, 16).replace('T', ' ') + ' UTC';
const shorten = (text: string, max = 18) => (Array.from(text).length > max ? Array.from(text).slice(0, max - 1).join('') + '…' : text);

type MenuState = { id: string; x: number; y: number };
type Imported = { nodes: GNode[]; edges: GEdge[] };
type Dialog = { kind: 'edit' | 'delete'; name: string } | null;

function loadErrorText(error: any): string {
  if (error?.code === 'auth') return 'Memory access requires your current user credentials.';
  if (error?.code === 'denied') return error.detail || 'The request was refused.';
  return 'The memory graph could not be read. No sample data is shown.';
}

function toContent(nodes: GNode[], edges: GEdge[]): MapContent {
  const stamps = nodes.map(n => n.ts).filter((t): t is number => t !== null);
  const lo = Math.min(...stamps), span = Math.max(...stamps) - lo;
  const index = new Map(nodes.map((n, i) => [n.id, i]));
  return {
    nodes: nodes.map(n => ({
      kind: n.kind, label: n.label, category: n.type === 'unknown' ? '' : n.type, state: n.state,
      t: n.ts !== null ? (span > 0 ? Math.round(((n.ts - lo) / span) * MAP_CODE_LIMITS.timeSteps) : 0) : n.rel,
    })),
    edges: edges.filter(e => index.has(e.from) && index.has(e.to)).map(e => ({ from: index.get(e.from) as number, to: index.get(e.to) as number, label: e.label })),
  };
}

export function MemoryGraphExplorer() {
  /* ── data ─────────────────────────────────────────────────────────────── */
  const [phase, setPhase] = useState<'loading' | 'error' | 'ready'>('loading');
  const [loadError, setLoadError] = useState('');
  const [map, setMap] = useState<MemoryMapData | null>(null);
  const [skills, setSkills] = useState<SkillInfo[]>([]);
  const [skillsFailed, setSkillsFailed] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  const [note, setNote] = useState('');
  const hasData = useRef(false);

  useEffect(() => {
    const controller = new AbortController();
    if (!hasData.current) { setPhase('loading'); setLoadError(''); }
    Promise.all([
      loadMemoryMap(controller.signal),
      loadSkills(controller.signal).then(list => ({ list }), () => ({ list: null })),
    ]).then(([data, skillResult]) => {
      if (controller.signal.aborted) return;
      hasData.current = true;
      setMap(data); setSkills(skillResult.list || []); setSkillsFailed(skillResult.list === null); setPhase('ready');
    }).catch(error => {
      if (controller.signal.aborted) return;
      if (hasData.current) { setNote('Could not refresh the memory graph. ' + loadErrorText(error)); return; }
      setLoadError(loadErrorText(error)); setPhase('error');
    });
    return () => controller.abort();
  }, [reloadKey]);

  /* ── timeline ─────────────────────────────────────────────────────────── */
  const [axis, setAxis] = useState<TimelineAxis>('known');
  const [at, setAt] = useState<number | null>(null);            // null = live, now
  const [bounds, setBounds] = useState<TimelineBounds | null>(null);
  const [timelineFailed, setTimelineFailed] = useState(false);
  const [facts, setFacts] = useState<FactsPage | null>(null);
  const [factsFor, setFactsFor] = useState<string>('');
  const [playing, setPlaying] = useState(false);
  const [imported, setImported] = useState<Imported | null>(null);
  const [importPos, setImportPos] = useState<number>(MAP_CODE_LIMITS.timeSteps);

  useEffect(() => {
    const controller = new AbortController();
    loadFacts('known', null, controller.signal).then(page => {
      if (!controller.signal.aborted) { setBounds(page.bounds); setTimelineFailed(false); }
    }).catch(() => { if (!controller.signal.aborted) { setBounds(null); setTimelineFailed(true); } });
    return () => controller.abort();
  }, [reloadKey]);

  useEffect(() => {
    if (at === null || imported) { setFacts(null); setFactsFor(''); return; }
    const controller = new AbortController();
    const timer = setTimeout(() => {
      loadFacts(axis, at, controller.signal).then(page => {
        if (!controller.signal.aborted) { setFacts(page); setFactsFor(`${axis}:${at}`); }
      }).catch(error => {
        if (!controller.signal.aborted) { setFacts(null); setFactsFor(''); setNote('Could not read the timeline. ' + loadErrorText(error)); }
      });
    }, DEBOUNCE_MS);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [axis, at, imported, reloadKey]);

  const first = bounds ? (axis === 'valid' ? bounds.firstValid : bounds.firstIngested) ?? bounds.firstIngested : null;
  const last = bounds ? Math.max(bounds.lastChange ?? 0, bounds.lastIngested ?? 0) : null;
  const lo = first !== null ? Math.floor(first) : 0;
  const hi = last !== null && first !== null ? Math.max(Math.ceil(last), lo + 1) : 1;
  const timelineOff = !imported && (!bounds || bounds.count === 0);
  const tl = imported ? { lo: 0, hi: MAP_CODE_LIMITS.timeSteps, value: importPos } : { lo, hi, value: at ?? hi };
  const setPosition = (value: number) => { if (imported) setImportPos(value); else setAt(value >= hi ? null : value); };
  const posRef = useRef(tl);
  posRef.current = tl;
  const positionSetter = useRef(setPosition);
  positionSetter.current = setPosition;

  useEffect(() => {
    if (!playing) return;
    const timer = setInterval(() => {
      const { lo: a, hi: b, value } = posRef.current;
      const next = value + Math.max(1, Math.ceil((b - a) / PLAY_STEPS));   // whole seconds, at least one: a short span must still advance
      posRef.current = { lo: a, hi: b, value: next };       // several ticks can land before a render
      if (next >= b) { positionSetter.current(b); setPlaying(false); } else positionSetter.current(next);
    }, PLAY_MS);
    return () => clearInterval(timer);
  }, [playing]);

  const togglePlay = () => {
    if (playing) { setPlaying(false); return; }
    if (tl.value >= tl.hi) positionSetter.current(tl.lo);
    setPlaying(true);
  };

  /* ── the view model: live graph, a past moment, or an imported map ────── */
  const view = useMemo(() => {
    if (imported) {
      const shown = new Set(imported.nodes.filter(n => n.rel === null || n.rel <= importPos).map(n => n.id));
      return { mode: 'imported' as const, nodes: imported.nodes.filter(n => shown.has(n.id)),
        edges: imported.edges.filter(e => shown.has(e.from) && shown.has(e.to)) };
    }
    if (at !== null) {
      const types = new Map((map?.entities || []).map(e => [e.name, e.type]));
      const names = new Set<string>();
      for (const f of facts?.facts || []) { names.add(f.subject); names.add(f.object); }
      const nodes: GNode[] = [...names].map(name => ({ id: 'm:' + name, kind: 'memory', label: name, type: types.get(name) || 'unknown', ts: null, rel: null, state: 'active' }));
      const edges: GEdge[] = (facts?.facts || []).map(f => ({ id: 'f:' + f.id, from: 'm:' + f.subject, to: 'm:' + f.object, label: f.predicate, fact: true }));
      return { mode: 'timeline' as const, nodes, edges };
    }
    const nodes: GNode[] = [
      ...(map?.entities || []).map((e): GNode => ({ id: 'm:' + e.name, kind: 'memory', label: e.name, type: e.type, ts: e.firstSeen, rel: null, state: 'active' })),
      ...skills.map((s): GNode => ({ id: 's:' + s.name, kind: 'skill', label: s.name, type: s.category || 'skill', ts: null, rel: null, state: s.disabled ? 'disabled' : 'active', essential: s.essential })),
    ];
    const edges: GEdge[] = (map?.relations || []).map((r, i) => ({ id: 'r:' + i, from: 'm:' + r.source, to: 'm:' + r.target, label: r.relation, fact: false }));
    return { mode: 'live' as const, nodes, edges };
  }, [imported, importPos, at, facts, map, skills]);

  /* ── selection, focus, camera ─────────────────────────────────────────── */
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [focusId, setFocusId] = useState<string | null>(null);
  const positions = useMemo(() => layout(view.nodes, view.edges, focusId), [view, focusId]);
  const [cam, setCam] = useState<Camera>({ x: 0, y: 0, k: 1 });
  const camRef = useRef(cam);
  camRef.current = cam;
  const positionsRef = useRef(positions);
  positionsRef.current = positions;
  const reset = useCallback(() => setCam(fit(positionsRef.current.values())), []);
  /* `positions.size > 0` refits when the first nodes of a view arrive late (the timeline's facts load after the mode switch). */
  const fitKey = `${phase}|${view.mode}|${focusId || ''}|${positions.size > 0}`;
  useLayoutEffect(() => { reset(); }, [fitKey, reset]);

  const svgRef = useRef<SVGSVGElement>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const scaleOf = (c: Camera, rect: DOMRect) => Math.min(rect.width / (VIEW.w / c.k), rect.height / (VIEW.h / c.k));

  useEffect(() => {
    const svg = svgRef.current;
    if (!svg) return;
    const onWheel = (event: WheelEvent) => {
      event.preventDefault();
      const factor = event.deltaY < 0 ? 1.1 : 0.9;
      const c = camRef.current, rect = svg.getBoundingClientRect();
      const next = zoomBy(c, factor);
      if (next.k === c.k) return;
      if (rect.width > 0 && rect.height > 0) {      // keep the point under the cursor fixed
        const dx = event.clientX - (rect.left + rect.width / 2), dy = event.clientY - (rect.top + rect.height / 2);
        const s = scaleOf(c, rect), s2 = scaleOf(next, rect);
        setCam({ k: next.k, x: c.x + dx / s - dx / s2, y: c.y + dy / s - dy / s2 });
      } else setCam(next);
    };
    svg.addEventListener('wheel', onWheel, { passive: false });
    return () => svg.removeEventListener('wheel', onWheel);
  }, [phase]);

  const drag = useRef<{ x: number; y: number; cam: Camera } | null>(null);
  const onPointerDown = (event: React.PointerEvent<SVGSVGElement>) => {
    if (event.button !== 0 || (event.target as Element).closest('[data-node-id]')) return;
    drag.current = { x: event.clientX, y: event.clientY, cam: camRef.current };
    event.currentTarget.setPointerCapture?.(event.pointerId);
  };
  const onPointerMove = (event: React.PointerEvent<SVGSVGElement>) => {
    const d = drag.current;
    if (!d) return;
    const rect = event.currentTarget.getBoundingClientRect();
    const s = rect.width > 0 ? scaleOf(d.cam, rect) : 1;
    setCam({ ...d.cam, x: d.cam.x - (event.clientX - d.x) / s, y: d.cam.y - (event.clientY - d.y) / s });
  };
  const endDrag = () => { drag.current = null; };
  const onCanvasKey = (event: React.KeyboardEvent) => {
    const step = PAN_STEP / camRef.current.k;
    const c = camRef.current;
    const move: Record<string, () => void> = {
      ArrowLeft: () => setCam({ ...c, x: c.x - step }), ArrowRight: () => setCam({ ...c, x: c.x + step }),
      ArrowUp: () => setCam({ ...c, y: c.y - step }), ArrowDown: () => setCam({ ...c, y: c.y + step }),
      '+': () => setCam(zoomBy(c, 1.25)), '=': () => setCam(zoomBy(c, 1.25)), '-': () => setCam(zoomBy(c, 0.8)), '0': reset,
    };
    if (move[event.key]) { event.preventDefault(); move[event.key](); }
  };

  /* ── context menu ─────────────────────────────────────────────────────── */
  const [menu, setMenu] = useState<MenuState | null>(null);
  const [dialog, setDialog] = useState<Dialog>(null);
  const nodeById = useMemo(() => new Map(view.nodes.map(n => [n.id, n])), [view]);
  const focusNode = (id: string) => svgRef.current?.querySelector<SVGElement>(`[data-node-id="${CSS.escape(id)}"]`)?.focus();
  const openMenu = (id: string, x: number, y: number) => { setSelectedId(id); setMenu({ id, x, y }); };
  const closeMenu = (restore = true) => { const id = menu?.id; setMenu(null); if (restore && id) focusNode(id); };
  const relativeTo = (x: number, y: number) => {
    const rect = wrapRef.current?.getBoundingClientRect();
    return { x: Math.max(0, x - (rect?.left || 0)), y: Math.max(0, y - (rect?.top || 0)) };
  };
  useEffect(() => {
    if (!menu) return;
    const away = (event: MouseEvent) => { if (!(event.target as Element).closest?.('[role="menu"]')) setMenu(null); };
    document.addEventListener('mousedown', away);
    return () => document.removeEventListener('mousedown', away);
  }, [menu]);

  /* ── share / import ───────────────────────────────────────────────────── */
  const [shareOpen, setShareOpen] = useState(false);
  const [codeText, setCodeText] = useState('');
  const [shareMsg, setShareMsg] = useState('');
  const [shareError, setShareError] = useState('');
  const dirty = useRef(false);
  const ownCode = useMemo(() => {
    if (view.nodes.length === 0) return '';
    try { return encodeMapCode(toContent(view.nodes, view.edges)); } catch { return ''; }
  }, [view]);
  useEffect(() => { if (shareOpen && !dirty.current) setCodeText(ownCode); }, [shareOpen, ownCode]);
  const copyCode = async () => {
    const code = codeText || ownCode;
    if (!code) { setShareError('There is nothing on the map to copy.'); return; }
    try { await navigator.clipboard.writeText(code); setShareMsg('Map code copied.'); setShareError(''); }
    catch { setShareMsg(''); setShareError('Copying is not available here. Select the code and copy it by hand.'); }
  };
  const importCode = () => {
    try {
      const content = decodeMapCode(codeText);
      const nodes: GNode[] = content.nodes.map((n, i) => ({ id: 'i:' + i, kind: n.kind, label: n.label, type: n.category || (n.kind === 'skill' ? 'skill' : 'unknown'), ts: null, rel: n.t, state: n.state }));
      const edges: GEdge[] = content.edges.map((e, i) => ({ id: 'i:e' + i, from: 'i:' + e.from, to: 'i:' + e.to, label: e.label, fact: false }));
      setImported({ nodes, edges }); setImportPos(MAP_CODE_LIMITS.timeSteps);
      setSelectedId(null); setFocusId(null); setMenu(null); setPlaying(false);
      setShareError(''); setShareMsg(`Loaded a map with ${nodes.length} node${nodes.length === 1 ? '' : 's'}.`);
    } catch (error: any) { setShareMsg(''); setShareError(String(error?.message || 'Not a valid map code.')); }
  };
  const backToMine = () => {
    setImported(null); setSelectedId(null); setFocusId(null); setPlaying(false); setShareMsg(''); setShareError('');
    dirty.current = false;
  };

  /* ── actions ──────────────────────────────────────────────────────────── */
  const canWrite = view.mode === 'live';
  const runSkill = async (node: GNode, enabled: boolean) => {
    try {
      const result = await switchSkill(node.label, enabled);
      if (result.pending) setNote(`Switching ${node.label} on needs owner approval · task ${result.taskId || 'created'}.`);
      else if (result.changed.length) setNote(enabled ? `Enabled skill ${node.label}.` : `Disabled skill ${node.label}. It stays installed; switching it back on needs owner approval.`);
      else if (result.essential.length) setNote(`${node.label} is essential and stays on.`);
      else setNote('Nothing to change.');
      setReloadKey(k => k + 1);
    } catch (error) { setNote(describeError(error, enabled ? 'Enabling a skill' : 'Disabling a skill')); }
  };
  const act = (action: string, node: GNode) => {
    setMenu(null);
    if (action === 'explore') { setSelectedId(node.id); setFocusId(node.id); }
    else if (action === 'edit') setDialog({ kind: 'edit', name: node.label });
    else if (action === 'delete') setDialog({ kind: 'delete', name: node.label });
    else if (action === 'disable') void runSkill(node, false);
    else if (action === 'enable') void runSkill(node, true);
    else if (action === 'copy') { setShareOpen(true); setCodeText(ownCode); dirty.current = false; void (async () => {
      try { await navigator.clipboard.writeText(ownCode); setShareMsg('Map code copied.'); setShareError(''); }
      catch { setShareError('Copying is not available here. Select the code and copy it by hand.'); } })(); }
  };
  const menuItems = (node: GNode): [string, string][] => {
    const items: [string, string][] = [];
    if (node.kind === 'memory') {
      items.push(['explore', 'Explore neighbours']);
      if (canWrite) items.push(['edit', 'Edit…'], ['delete', 'Delete…']);
    } else if (canWrite) {
      if (node.state === 'disabled') items.push(['enable', 'Enable skill']);
      else if (!node.essential) items.push(['disable', 'Disable skill']);
    }
    items.push(['copy', 'Copy map code']);
    return items;
  };
  const afterWrite = (message: string) => { setDialog(null); setNote(message); setReloadKey(k => k + 1); };

  /* ── render ───────────────────────────────────────────────────────────── */
  const selected = selectedId ? nodeById.get(selectedId) : undefined;
  const near = focusId && positions.has(focusId) ? neighbourhood(view.edges, focusId) : null;
  const nodeList = view.nodes.filter(n => positions.has(n.id));
  const edgeList = view.edges.filter(e => positions.has(e.from) && positions.has(e.to));
  const labelAll = edgeList.length <= 30 || view.mode === 'timeline';
  const types = useMemo(() => {
    const counts = new Map<string, number>();
    for (const n of view.nodes) if (n.kind === 'memory') counts.set(n.type || 'unknown', (counts.get(n.type || 'unknown') || 0) + 1);
    return [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
  }, [view]);
  const skillCount = view.nodes.filter(n => n.kind === 'skill').length;
  /* Skill circles are not memory: an empty graph on an install with skills is still "nothing learned yet". */
  const isEmptyLive = phase === 'ready' && view.mode === 'live' && !view.nodes.some(n => n.kind === 'memory');
  const noun = axis === 'known' ? 'believed' : 'true';

  let timelineText: string;
  if (imported) timelineText = `imported map · position ${Math.round((importPos / MAP_CODE_LIMITS.timeSteps) * 100)}% of its own span`;
  else if (timelineFailed) timelineText = 'Timeline unavailable: the bi-temporal store could not be read.';
  else if (timelineOff) timelineText = bounds ? 'No timeline facts yet. Facts appear as Nerva learns from conversations.' : 'Reading the timeline…';
  else if (at === null) timelineText = 'live · now';
  else if (factsFor !== `${axis}:${at}`) timelineText = `Reading what the store ${axis === 'known' ? 'believed' : 'held as true'} at ${fmt(at)}…`;
  else if (!facts || facts.facts.length === 0) timelineText = axis === 'known' ? `Nothing was known by ${fmt(at)}.` : `Nothing was true at ${fmt(at)}.`;
  else timelineText = `${facts.facts.length} fact${facts.facts.length === 1 ? '' : 's'} ${noun} at ${fmt(at)}${facts.clipped ? ' · newest only, older ones clipped' : ''}${facts.skipped ? ` · ${facts.skipped} could not be shown` : ''}`;

  const btn: React.CSSProperties = { padding: '4px 8px' };
  return <section aria-label="Memory graph" style={{ border: '1px solid var(--panel-line)', borderRadius: 'var(--radius)', padding: 14, marginBottom: 14 }}>
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
      <h3 style={{ fontSize: 13, margin: 0 }}>Memory graph</h3>
      {imported && <span style={{ fontSize: 10, border: '1px solid var(--amber)', color: 'var(--amber)', borderRadius: 3, padding: '1px 5px' }}>imported map</span>}
      {imported && <button className="tool-btn" style={btn} onClick={backToMine}>Back to my map</button>}
      {focusId && <button className="tool-btn" style={btn} onClick={() => setFocusId(null)}>Show whole map</button>}
      <button className="tool-btn" style={{ ...btn, marginLeft: 'auto' }} aria-expanded={shareOpen} onClick={() => setShareOpen(open => !open)}>Share / import map</button>
    </div>
    <p style={{ fontSize: 11, color: 'var(--ink-2)', margin: '6px 0' }}>
      {imported ? 'Showing someone else\'s map. Its labels are text they wrote: shown as plain text, never fetched, run or saved.'
        : 'What Nerva has stored: entities, relations and installed skills. Right-click a node for actions.'}
    </p>

    <div className="kg-wrap" ref={wrapRef} style={{ height: 380 }}>
      {phase === 'ready' && <svg ref={svgRef} className="kg-svg" viewBox={viewBox(cam)} preserveAspectRatio="xMidYMid meet"
        role="group" aria-label="Memory graph canvas. Arrow keys pan, plus and minus zoom, zero resets." tabIndex={0}
        style={{ touchAction: 'none', userSelect: 'none', cursor: drag.current ? 'grabbing' : 'grab' }}
        onKeyDown={onCanvasKey} onDoubleClick={reset} onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={endDrag} onPointerCancel={endDrag}>
        {edgeList.map(e => {
          const a = positions.get(e.from)!, b = positions.get(e.to)!;
          const dim = near ? !(near.has(e.from) && near.has(e.to) && (e.from === focusId || e.to === focusId)) : false;
          const touches = selectedId !== null && (e.from === selectedId || e.to === selectedId);
          return <g key={e.id}>
            <line className={'kg-edge' + (e.fact ? ' fact' : '') + (dim ? ' faded' : '')} x1={a.x} y1={a.y} x2={b.x} y2={b.y} strokeDasharray={e.fact ? '4 3' : undefined} />
            {!dim && (labelAll || touches) && e.label && <text className="kg-edge-label" x={(a.x + b.x) / 2} y={(a.y + b.y) / 2 - 2} textAnchor="middle">{shorten(e.label, 24)}</text>}
          </g>;
        })}
        {nodeList.map((n, index) => {
          const p = positions.get(n.id)!;
          const colour = n.kind === 'skill' ? 'var(--accent)' : typeColour(n.type);
          const faded = near ? !near.has(n.id) : false;
          const r = n.id === focusId ? 15 : 10;
          const roving = n.id === selectedId || (!selected && index === 0);
          return <g key={n.id} data-node-id={n.id} data-label={n.label} role="button" tabIndex={roving ? 0 : -1} aria-pressed={n.id === selectedId} aria-haspopup="menu"
            aria-label={n.kind === 'skill' ? `${n.label}, skill${n.state === 'disabled' ? ' (disabled)' : ''}` : `${n.label}, ${n.type}`}
            className={'kg-node' + (n.kind === 'skill' ? ' kg-skill' : '') + (faded ? ' faded' : '')} transform={`translate(${p.x},${p.y})`} style={{ cursor: 'pointer', outline: 'none' }}
            onClick={event => { event.stopPropagation(); setSelectedId(n.id); }}
            onDoubleClick={event => { event.stopPropagation(); if (n.kind === 'memory') { setSelectedId(n.id); setFocusId(n.id); } }}
            onContextMenu={event => { event.preventDefault(); const q = relativeTo(event.clientX, event.clientY); openMenu(n.id, q.x, q.y); }}
            onKeyDown={event => {
              if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); setSelectedId(n.id); }
              else if (event.key === 'ContextMenu' || (event.key === 'F10' && event.shiftKey)) {
                event.preventDefault(); const rect = event.currentTarget.getBoundingClientRect(); const q = relativeTo(rect.left + rect.width / 2, rect.top + rect.height / 2); openMenu(n.id, q.x, q.y);
              } else if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
                event.preventDefault(); event.stopPropagation();
                const all = Array.from(svgRef.current?.querySelectorAll<SVGElement>('[data-node-id]') || []);
                const i = all.indexOf(event.currentTarget as unknown as SVGElement);
                all[(i + (event.key === 'ArrowRight' ? 1 : all.length - 1)) % all.length]?.focus();
              }
            }}>
            {n.kind === 'skill'
              ? <circle r={r} style={{ fill: 'var(--surface-2)', stroke: colour, strokeDasharray: n.state === 'disabled' ? '3 2' : undefined, opacity: n.state === 'disabled' ? 0.55 : 1 }} />
              : <polygon points={`0,${-r - 2} ${r + 2},0 0,${r + 2} ${-r - 2},0`} style={{ fill: colour, fillOpacity: 0.22, stroke: colour, strokeWidth: n.id === selectedId ? 2.6 : 1.4 }} />}
            <text y={r + 13} textAnchor="middle">{shorten(n.label)}</text>
          </g>;
        })}
      </svg>}

      {phase === 'loading' && <div role="status" style={overlay}>Loading memory graph…</div>}
      {phase === 'error' && <div role="alert" style={overlay}>
        <strong>Could not load memory graph</strong><span style={{ color: 'var(--ink-2)' }}>{loadError}</span>
        <button className="tool-btn" onClick={() => setReloadKey(k => k + 1)}>Retry</button></div>}
      {isEmptyLive && <div style={{ ...overlay, pointerEvents: 'none' }}><strong>Nothing learned yet</strong>
        <span style={{ color: 'var(--ink-2)' }}>As Nerva learns from your conversations, entities and relations appear here.</span></div>}
      {phase === 'ready' && imported && imported.nodes.length === 0 && <div style={{ ...overlay, pointerEvents: 'none' }}>This imported map has no nodes.</div>}

      {phase === 'ready' && <>
        <div style={{ position: 'absolute', top: 8, right: 8, display: 'flex', gap: 4 }}>
          <button className="tool-btn" style={btn} aria-label="Zoom in" onClick={() => setCam(zoomBy(cam, 1.25))}>+</button>
          <button className="tool-btn" style={btn} aria-label="Zoom out" onClick={() => setCam(zoomBy(cam, 0.8))}>−</button>
          <button className="tool-btn" style={btn} aria-label="Reset view" onClick={reset}>⌂</button>
        </div>
        <ul role="group" aria-label="Legend" style={{ position: 'absolute', left: 8, bottom: 8, margin: 0, padding: '6px 8px', listStyle: 'none', fontSize: 10, background: 'rgba(0,0,0,.45)', borderRadius: 4, maxWidth: '55%', maxHeight: '60%', overflowY: 'auto', pointerEvents: 'none' }}>
          {types.map(([type, count]) => <li key={type} style={{ display: 'flex', gap: 5, alignItems: 'center' }}>
            <i style={{ width: 8, height: 8, transform: 'rotate(45deg)', background: typeColour(type), display: 'inline-block' }} /><span>{type}</span> <b>{count}</b></li>)}
          {skillCount > 0 && <li style={{ display: 'flex', gap: 5, alignItems: 'center' }}>
            <i style={{ width: 8, height: 8, borderRadius: '50%', background: 'var(--accent)', display: 'inline-block' }} /><span>skills</span> <b>{skillCount}</b></li>}
          {edgeList.some(e => e.fact) && <li style={{ color: 'var(--ink-2)' }}>dashed line = fact the store held at that time</li>}
          {edgeList.some(e => !e.fact) && <li style={{ color: 'var(--ink-2)' }}>solid line = stored relation</li>}
          {view.mode === 'live' && <li style={{ color: 'var(--ink-2)' }}>core = oldest · outer = newer · skills outermost</li>}
        </ul>
        {menu && nodeById.get(menu.id) && <div role="menu" aria-label={`Actions for ${nodeById.get(menu.id)!.label}`} ref={el => { if (el && !el.contains(document.activeElement)) el.querySelector<HTMLElement>('[role="menuitem"]')?.focus(); }}
          onKeyDown={event => {
            const items = Array.from(event.currentTarget.querySelectorAll<HTMLElement>('[role="menuitem"]'));
            const i = items.indexOf(document.activeElement as HTMLElement);
            if (event.key === 'Escape') { event.preventDefault(); closeMenu(); }
            else if (event.key === 'Tab') closeMenu(false);
            else if (event.key === 'ArrowDown') { event.preventDefault(); items[(i + 1) % items.length]?.focus(); }
            else if (event.key === 'ArrowUp') { event.preventDefault(); items[(i + items.length - 1) % items.length]?.focus(); }
          }}
          style={{ position: 'absolute', left: Math.min(menu.x, 9999), top: menu.y, zIndex: 20, background: 'var(--void-2, var(--surface))', border: '1px solid var(--panel-line)', borderRadius: 4, padding: 4, display: 'flex', flexDirection: 'column', minWidth: 160 }}>
          {menuItems(nodeById.get(menu.id)!).map(([action, text]) => <button key={action} role="menuitem" className="tool-btn" style={{ border: 0, justifyContent: 'flex-start', background: 'transparent' }}
            onClick={() => act(action, nodeById.get(menu.id)!)}>{text}</button>)}
        </div>}
        {dialog?.kind === 'edit' && <EditEntityDialog name={dialog.name} onClose={() => setDialog(null)} onRefresh={() => setReloadKey(k => k + 1)} onSaved={name => afterWrite(`Saved ${name}.`)} />}
        {dialog?.kind === 'delete' && <DeleteEntityDialog name={dialog.name} onClose={() => setDialog(null)} onRefresh={() => setReloadKey(k => k + 1)}
          onDeleted={(name, n) => { setSelectedId(id => (id === 'm:' + name ? null : id)); setFocusId(id => (id === 'm:' + name ? null : id));
            afterWrite(`Deleted ${name} · ${n} timeline fact${n === 1 ? '' : 's'} closed. A later mention can create it again.`); }} />}
      </>}
    </div>

    {phase === 'ready' && <div className="timeslider" style={{ border: '1px solid var(--panel-line)', borderTop: 0, borderRadius: '0 0 var(--radius) var(--radius)', flexWrap: 'wrap', gap: 10 }}>
      <button className="tool-btn" style={btn} aria-label={playing ? 'Pause' : 'Play timeline'} disabled={timelineOff} onClick={togglePlay}>{playing ? '❚❚' : '▶'}</button>
      {!imported && <div role="radiogroup" aria-label="Timeline meaning" style={{ display: 'flex', gap: 4 }}>
        {([['known', 'What it knew'], ['valid', 'What was true']] as const).map(([value, text]) =>
          <button key={value} role="radio" aria-checked={axis === value} aria-label={text} className={'tool-btn' + (axis === value ? ' on' : '')} style={btn} onClick={() => setAxis(value)}>{text}</button>)}
      </div>}
      <input type="range" aria-label="Timeline scrubber" min={tl.lo} max={tl.hi} step={1} value={tl.value} disabled={timelineOff}
        onChange={event => { setPlaying(false); setPosition(Number(event.target.value)); }} />
      <span className="asof" style={{ fontSize: 11, whiteSpace: 'normal' }}>{timelineText}</span>
      {at !== null && !imported && <button className="tool-btn" style={btn} onClick={() => { setPlaying(false); setAt(null); }}>Back to now</button>}
    </div>}

    <div role="status" aria-live="polite" style={{ fontSize: 11, color: 'var(--accent-light)', minHeight: 14, marginTop: 6, overflowWrap: 'anywhere' }}>{note}</div>
    {phase === 'ready' && map?.clipped && !imported && <p style={{ fontSize: 11, margin: '4px 0' }}>Showing the first {500} entities. More are stored.</p>}
    {phase === 'ready' && map?.relationsClipped && !imported && <p style={{ fontSize: 11, margin: '4px 0' }}>Some relations are not drawn: the relation read is capped.</p>}
    {phase === 'ready' && map && map.skipped > 0 && !imported && <p style={{ fontSize: 11, margin: '4px 0' }}>{map.skipped} stored entr{map.skipped === 1 ? 'y' : 'ies'} could not be shown (names with control characters or over 256 characters).</p>}
    {skillsFailed && !imported && <p style={{ fontSize: 11, margin: '4px 0' }}>Skills could not be read, so they are not on the map.</p>}

    {selected && <div role="region" aria-label="Selected node" style={{ fontSize: 12, borderTop: '1px solid var(--panel-line)', paddingTop: 8, marginTop: 6 }}>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
        <strong style={{ color: 'var(--accent-light)', overflowWrap: 'anywhere' }}>{selected.label}</strong>
        <span style={{ color: 'var(--ink-2)' }}>{selected.kind === 'skill' ? `skill${selected.type !== 'skill' ? ' · ' + selected.type : ''}${selected.state === 'disabled' ? ' · disabled' : ''}${selected.essential ? ' · essential' : ''}` : selected.type}</span>
        {selected.ts !== null && <span style={{ color: 'var(--ink-2)' }}>first seen {fmt(selected.ts)}</span>}
        <button className="tool-btn" style={{ ...btn, marginLeft: 'auto' }} aria-label={`Actions for ${selected.label}`} aria-haspopup="menu"
          onClick={event => { const rect = event.currentTarget.getBoundingClientRect(); const q = relativeTo(rect.left, rect.top); openMenu(selected.id, q.x, q.y); }}>⋯</button>
      </div>
      {(() => {
        const rows = view.edges.filter(e => e.from === selected.id || e.to === selected.id).slice(0, 12);
        return rows.length > 0 && <ul aria-label="Relations of the selected node" style={{ margin: '6px 0 0', paddingLeft: 18, overflowWrap: 'anywhere' }}>
          {rows.map(e => <li key={e.id}>{nodeById.get(e.from)?.label} <span style={{ color: 'var(--accent-light)' }}>— {e.label} —</span> {nodeById.get(e.to)?.label}</li>)}
        </ul>;
      })()}
    </div>}

    {shareOpen && <div style={{ borderTop: '1px solid var(--panel-line)', marginTop: 8, paddingTop: 8 }}>
      <p style={{ fontSize: 11, color: 'var(--ink-2)', margin: '0 0 6px' }}>
        Copy the code to share this map, or paste one to load. It holds entity names, relation names, skill names and rough timing, not property values or memory text.
        A map you load is shown read-only and replaces the view until you go back.</p>
      <textarea aria-label="Map code" value={codeText} spellCheck={false} placeholder="Paste a map code…" rows={4}
        onChange={event => { dirty.current = true; setCodeText(event.target.value); }} style={{ ...inpS, width: '100%', boxSizing: 'border-box', resize: 'vertical', wordBreak: 'break-all' }} />
      <div style={{ display: 'flex', gap: 6, marginTop: 6 }}>
        <button className="tool-btn" onClick={copyCode}>Copy map code</button>
        <button className="tool-btn" onClick={importCode}>Load</button>
      </div>
      {shareMsg && <div role="status" style={{ fontSize: 11, color: 'var(--accent-light)', marginTop: 4 }}>{shareMsg}</div>}
      {shareError && <div role="alert" style={{ fontSize: 11, color: 'var(--amber)', marginTop: 4 }}>{shareError}</div>}
    </div>}
  </section>;
}

const overlay: React.CSSProperties = {
  position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
  gap: 8, textAlign: 'center', padding: 16, fontSize: 12, zIndex: 5,
};
