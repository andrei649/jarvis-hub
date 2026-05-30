'use strict';
/* enhancements.js — second-wave HUD components */
/* Copied from design_handoff_jarvis_hub/design/enhancements.jsx */

/* h, useState, useEffect, useRef, useMemo, useCallback — from components.js */

function SituationTicker({ items, agentMap, voiceState }) {
  const PRI_CLASS = { hi: 'tk-hi', mid: 'tk-mid', warn: 'tk-warn', ok: 'tk-ok' };

  const loop = useMemo(() => [...items, ...items], [items]);

  return h('div', { className: 'situation' },
    h('div', { className: 'situation-head' },
      h('span', { className: 'situation-pulse' }),
      h('span', { className: 'situation-title' }, 'LIVE'),
      h('span', { className: 'situation-sub' }, `SITUATION · ${voiceState.toUpperCase()}`),
    ),
    h('div', { className: 'situation-rail' },
      h('div', { className: 'situation-marquee' },
        loop.map((it, i) => {
          const a = agentMap[it.agent];
          return h('div', { key: i, className: `tk ${PRI_CLASS[it.pri] || 'tk-mid'}` },
            h('span', { className: 'tk-glyph' },
              h('svg', { viewBox: '-12 -12 24 24', width: '14', height: '14' },
                h('path', { d: a?.glyph || 'M0,-6 L6,3 L-6,3 Z', fill: 'none', stroke: 'currentColor', 'stroke-width': '1.4', 'stroke-linejoin': 'round' }),
              ),
            ),
            h('span', { className: 'tk-agent' }, a?.name?.toUpperCase() || it.agent.toUpperCase()),
            h('span', { className: 'tk-verb' }, it.verb),
            h('span', { className: 'tk-obj' }, it.obj),
            typeof it.pct === 'number' && h('span', { className: 'tk-pct' },
              h('span', { className: 'tk-pct-bar' },
                h('span', { style: { width: `${it.pct}%` } }),
              ),
              h('span', { className: 'tk-pct-val' }, `${it.pct}%`),
            ),
            h('span', { className: 'tk-sep' }, '·'),
          );
        }),
      ),
    ),
  );
}

function CommandPalette({ open, onClose, agents, tasks, projects, onAction }) {
  const inputRef = useRef(null);
  const [query, setQuery] = useState('');
  const [idx, setIdx] = useState(0);

  useEffect(() => {
    if (open) {
      setQuery('');
      setIdx(0);
      requestAnimationFrame(() => inputRef.current?.focus());
    }
  }, [open]);

  const corpus = useMemo(() => {
    const out = [];
    agents.forEach((a) => out.push({
      kind: 'agent', id: a.id, label: a.name, sub: a.role,
      tags: [a.id, a.name, a.role, a.tier, a.model].join(' ').toLowerCase(),
      glyph: a.glyph, status: a.status,
      action: { type: 'focus_agent', agent: a.id },
    }));
    tasks.forEach((t) => {
      const owner = agents.find((a) => a.id === t.owner);
      out.push({
        kind: 'task', id: t.id, label: t.label, sub: `${owner?.name || t.owner} · ${t.project}`,
        tags: [t.label, t.project, t.owner, t.state, owner?.name].join(' ').toLowerCase(),
        state: t.state,
        action: { type: 'focus_agent', agent: t.owner },
      });
    });
    projects.forEach((p) => out.push({
      kind: 'project', id: p.id, label: p.label || p.id, sub: 'project · ' + (p.color || ''),
      tags: [p.id, p.label].join(' ').toLowerCase(),
      action: { type: 'filter_project', project: p.id },
    }));
    out.push({
      kind: 'cmd', id: 'cmd_idle',   label: 'Set voice → idle',       sub: 'voice state',
      tags: 'voice state idle standby', action: { type: 'voice_state', value: 'idle' },
    });
    out.push({
      kind: 'cmd', id: 'cmd_listen', label: 'Set voice → listening',  sub: 'voice state',
      tags: 'voice state listening wake', action: { type: 'voice_state', value: 'listening' },
    });
    out.push({
      kind: 'cmd', id: 'cmd_proc',   label: 'Set voice → processing', sub: 'voice state',
      tags: 'voice state processing', action: { type: 'voice_state', value: 'processing' },
    });
    out.push({
      kind: 'cmd', id: 'cmd_speak',  label: 'Set voice → speaking',   sub: 'voice state',
      tags: 'voice state speaking respond', action: { type: 'voice_state', value: 'speaking' },
    });
    out.push({
      kind: 'cmd', id: 'cmd_focus_clear', label: 'Clear focus',       sub: 'view',
      tags: 'clear focus view reset', action: { type: 'clear_focus' },
    });
    return out;
  }, [agents, tasks, projects]);

  const results = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) {
      return corpus.filter((c) => c.kind === 'agent' || c.kind === 'cmd').slice(0, 12);
    }
    const tokens = q.split(/\s+/).filter(Boolean);
    return corpus
      .map((c) => {
        let score = 0;
        tokens.forEach((t) => {
          if (c.tags.includes(t)) score += 10;
          if (c.label.toLowerCase().startsWith(t)) score += 8;
          if (c.label.toLowerCase().includes(t))   score += 4;
        });
        if (c.kind === 'agent') score += 1;
        return { c, score };
      })
      .filter((r) => r.score > 0)
      .sort((a, b) => b.score - a.score)
      .slice(0, 14)
      .map((r) => r.c);
  }, [query, corpus]);

  useEffect(() => { setIdx(0); }, [query]);

  const run = (item) => {
    if (!item) return;
    onAction?.(item.action, item);
    onClose();
  };

  const handleKey = (e) => {
    if (e.key === 'Escape')    { e.preventDefault(); onClose(); return; }
    if (e.key === 'ArrowDown') { e.preventDefault(); setIdx((i) => Math.min(i + 1, results.length - 1)); return; }
    if (e.key === 'ArrowUp')   { e.preventDefault(); setIdx((i) => Math.max(i - 1, 0)); return; }
    if (e.key === 'Enter')     { e.preventDefault(); run(results[idx]); return; }
  };

  if (!open) return null;

  return h('div', { className: 'palette-backdrop', onMouseDown: onClose },
    h('div', { className: 'palette', onMouseDown: (e) => e.stopPropagation() },
      h('span', { className: 'bk-corner bk-tl' }),
      h('span', { className: 'bk-corner bk-tr' }),
      h('span', { className: 'bk-corner bk-bl' }),
      h('span', { className: 'bk-corner bk-br' }),

      h('div', { className: 'palette-head' },
        h('span', { className: 'palette-prompt' }, '›'),
        h('input', {
          ref: inputRef,
          className: 'palette-input',
          type: 'text',
          value: query,
          onChange: (e) => setQuery(e.target.value),
          onKeyDown: handleKey,
          placeholder: 'Search agents · tasks · projects · commands',
          autoFocus: true,
        }),
        h('span', { className: 'palette-hint' }, '↑↓ navigate · ↵ run · esc close'),
      ),

      h('div', { className: 'palette-list' },
        results.length === 0 && h('div', { className: 'palette-empty' }, `No matches for "${query}"`),
        results.map((c, i) => h('div', {
          key: c.kind + ':' + c.id,
          className: `palette-row palette-row-${c.kind} ${idx === i ? 'is-active' : ''}`,
          onMouseEnter: () => setIdx(i),
          onClick: () => run(c),
        },
          h('span', { className: `palette-kind palette-kind-${c.kind}` },
            c.kind === 'agent'   && '◈',
            c.kind === 'task'    && '○',
            c.kind === 'project' && '▤',
            c.kind === 'cmd'     && '⌘',
          ),
          c.glyph && h('svg', { viewBox: '-12 -12 24 24', width: '14', height: '14', className: 'palette-glyph' },
            h('path', { d: c.glyph, fill: 'none', stroke: 'currentColor', 'stroke-width': '1.4', 'stroke-linejoin': 'round' }),
          ),
          h('span', { className: 'palette-label' }, c.label),
          h('span', { className: 'palette-sub' }, c.sub),
          c.status && h('span', { className: `dot dot-${c.status} palette-dot` }),
          c.state  && h('span', { className: `palette-state palette-state-${c.state}` }, c.state),
        )),
      ),

      h('div', { className: 'palette-foot' },
        h('span', null, _t('comp.brand')),
        h('span', { className: 'palette-foot-spacer' }),
        h('span', null, `${results.length} matches`),
        h('span', { className: 'palette-foot-spacer' }),
        h('span', null, '⌘K'),
      ),
    ),
  );
}

function useLiveSys(baseSys) {
  const [s, setS] = useState(baseSys);
  useEffect(() => {
    let t = 0;
    const id = setInterval(() => {
      t += 1;
      const n = () => (Math.random() - 0.5) * 0.6;
      const ram_used  = clamp(baseSys.ram_used  + Math.sin(t * 0.21) * 6  + n(), 60, baseSys.ram_total - 8);
      const vram_used = clamp(baseSys.vram_used + Math.sin(t * 0.37) * 1.8 + n() * 0.3, 8, baseSys.vram_total - 1);
      const gpu_load  = clamp(baseSys.gpu_load  + Math.sin(t * 0.55) * 18 + n() * 6, 5, 96);
      const latency   = clamp(baseSys.latency   + Math.sin(t * 0.18) * 0.9 + n() * 0.2, 1.6, 7.2);
      setS((prev) => ({ ...prev, ram_used: round1(ram_used), vram_used: round2(vram_used), gpu_load: Math.round(gpu_load), latency: round1(latency) }));
    }, 1400);
    return () => clearInterval(id);
  }, [baseSys]);
  return s;
}

function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }
function round1(v) { return Math.round(v * 10) / 10; }
function round2(v) { return Math.round(v * 100) / 100; }

function useHotkey(combo, handler) {
  useEffect(() => {
    const onKey = (e) => {
      const isMac = navigator.platform.toLowerCase().includes('mac');
      const want = combo.toLowerCase();
      const ctrl = (isMac ? e.metaKey : e.ctrlKey);
      if (want === 'cmdk' && ctrl && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        handler(e);
      } else if (want === 'esc' && e.key === 'Escape') {
        handler(e);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [combo, handler]);
}

Object.assign(window, { SituationTicker, CommandPalette, useLiveSys, useHotkey });
