import React, { useEffect, useRef, useState } from 'react';
import { apiFetchOnce } from './api/client';
import { appUrl } from './base-path';
import './composer-skills.css';

type Shortcut = { kind: 'skill'; name: string; command: string; description: string };
type Catalog = { skills: Shortcut[]; refine: boolean; truncated: boolean; unavailable: boolean };
const SAFE_SKILL = /^\/[a-z][a-z0-9_-]{0,63}$/;
const skillTitle = (name: string) => name.replace(/[-_]\d{6}$/, '').replace(/[-_]+/g, ' ')
  .replace(/\b[a-z]/g, letter => letter.toUpperCase());

async function loadCatalog(agent: string, signal: AbortSignal): Promise<Catalog> {
  const response = await apiFetchOnce('/api/commands?agent=' + encodeURIComponent(agent), { admin: true, signal });
  if (!response.ok) throw new Error('catalog unavailable');
  const body = await response.json();
  if (body?.ok !== true || !Array.isArray(body.commands) || !Array.isArray(body.shortcuts) ||
      body.commands.length > 256 || body.shortcuts.length > 256) throw new Error('invalid catalog');
  const skills = body.shortcuts.filter((item: any): item is Shortcut =>
    item?.kind === 'skill' && item.tier === 'admin' &&
    typeof item.name === 'string' && typeof item.command === 'string' &&
    SAFE_SKILL.test(item.command) && item.command === '/' + item.name &&
    typeof item.description === 'string');
  const refine = body.commands.some((item: any) =>
    item?.name === 'refine' && item.command === '/refine' && item.tier === 'admin');
  return { skills, refine, truncated: body.truncated === true,
    unavailable: body.shortcuts_unavailable === true };
}

export function ComposerSkills({ agent, draft, onInsert }: {
  agent: string; draft: string; onInsert: (command: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);
  const [notice, setNotice] = useState('');
  const [panelLeft, setPanelLeft] = useState(0);
  const trigger = useRef<HTMLButtonElement>(null);

  function placePanel() {
    const box = trigger.current?.getBoundingClientRect();
    if (!box) return;
    const width = Math.min(360, window.innerWidth - 24);
    setPanelLeft(Math.max(12, Math.min(box.left, window.innerWidth - width - 12)) - box.left);
  }

  useEffect(() => {
    if (!open) return;
    window.addEventListener('resize', placePanel);
    return () => window.removeEventListener('resize', placePanel);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const request = new AbortController();
    setLoading(true); setError(false); setCatalog(null);
    loadCatalog(agent, request.signal).then(data => {
      if (!request.signal.aborted) setCatalog(data);
    }).catch(() => {
      if (!request.signal.aborted) setError(true);
    }).finally(() => {
      if (!request.signal.aborted) setLoading(false);
    });
    return () => request.abort();
  }, [open, agent]);

  function choose(command: string, review = false) {
    if (draft.trimStart().startsWith('/') || (review && draft.trim())) {
      setNotice(review ? 'Send or clear your draft before preparing a conversation review.'
        : 'A slash command is already drafted. Send or clear it before choosing another skill.');
      return;
    }
    onInsert(command);
    setOpen(false); setNotice('');
  }

  function close() { setOpen(false); trigger.current?.focus(); }

  return <div className="composer-skills">
    <button ref={trigger} type="button" className="vault-trigger" aria-expanded={open} aria-controls="composer-skills-panel"
      onClick={() => { if (!open) placePanel(); setOpen(value => !value); setNotice(''); }}>Skills</button>
    {open && <section id="composer-skills-panel" className="composer-skills-panel" style={{ left: panelLeft }} aria-label="Available chat skills"
      onKeyDown={event => { if (event.key === 'Escape') { event.stopPropagation(); close(); } }}>
      <div className="composer-skills-head"><strong>Skills</strong>
        <button type="button" className="tool-btn" onClick={close} aria-label="Close skills">Close</button>
      </div>
      <p>Choose a skill to prepare a message. Only Transmit sends it.</p>
      {loading && <p role="status">Loading available skills…</p>}
      {error && <p role="status">Skills are unavailable. Check your connection and try again.</p>}
      {catalog && <>
        {catalog.skills.length ? <ul className="composer-skills-list">{catalog.skills.map(skill =>
          <li key={skill.command}><button type="button" aria-label={`${skillTitle(skill.name)} — ${skill.command}`}
            onClick={() => choose(skill.command)}>
            <strong>{skillTitle(skill.name)}</strong><code>{skill.command}</code>
            {skill.description !== 'Skill' && <span>{skill.description}</span>}
          </button></li>)}</ul> : <p role="status">No skills are available for this agent right now.</p>}
        {catalog.truncated && <p role="status">The skill list is limited; more may be available.</p>}
        {catalog.unavailable && <p role="status">Some shortcuts are unavailable right now.</p>}
        {catalog.refine && <div className="composer-skills-review">
          <button type="button" className="tool-btn" onClick={() => choose('/refine', true)}>Review this conversation</button>
          <p>Recent turns are reviewed locally for memories and reusable skills. After you approve a new procedure, any agent can use it. You can type a focus after /refine.</p>
        </div>}
      </>}
      <a href={appUrl('/v2/console/pending-skills')}>Review pending skills in Console</a>
      {notice && <p role="status">{notice}</p>}
    </section>}
  </div>;
}
