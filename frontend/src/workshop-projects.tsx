import React, { useEffect, useRef, useState } from 'react';
import { apiFetchOnce } from './api/client';
import { appUrl } from './base-path';
import './workshop-projects.css';

export type WorkshopRef = { path: string; title: string; view: 'robot' | 'house' };

// A task's Markdown link must also survive parentheses in duplicate note names.
export function projectLink(path: string) {
  return '/os/?project=' + encodeURIComponent(path).replace(/[()]/g, c => c === '(' ? '%28' : '%29');
}

function isRef(value: any): value is WorkshopRef {
  return typeof value?.path === 'string' && value.path.length > 0
    && typeof value.title === 'string' && value.title.length > 0
    && (value.view === 'robot' || value.view === 'house');
}

export async function fetchWorkshopContext(path: string, signal?: AbortSignal) {
  const res = await apiFetchOnce('/api/os/workshop/project?path=' + encodeURIComponent(path), { signal });
  if (!res.ok) throw new Error('The saved project is unavailable.');
  const item = await res.json();
  const project = item.project;
  if (item.ok !== true || item.path !== path || typeof item.title !== 'string'
      || !item.title.trim() || typeof item.summary !== 'string' || !item.summary.trim()
      || project?.version !== 1 || !['robot', 'house'].includes(project.view)) {
    throw new Error('Invalid workshop project.');
  }
  return { title: item.title as string, summary: item.summary as string, project };
}

export function WorkshopProjects({ lang = 'en', heading, actionLabel, onChoose }: {
  lang?: string; heading?: string; actionLabel?: string;
  onChoose?: (project: WorkshopRef, signal: AbortSignal) => void | Promise<void>;
}) {
  const ro = lang === 'ro';
  const [open, setOpen] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const [projects, setProjects] = useState<WorkshopRef[] | null>(null);
  const [error, setError] = useState('');
  const [choosing, setChoosing] = useState(false);
  const action = useRef<AbortController | null>(null);
  useEffect(() => {
    if (!open) return;
    const request = new AbortController();
    setProjects(null); setError(''); setChoosing(false);
    (async () => {
      try {
        const res = await apiFetchOnce('/api/os/workshop/projects', { signal: request.signal });
        if (!res.ok) throw new Error();
        const data = await res.json();
        if (data.ok !== true || !Array.isArray(data.projects) || !data.projects.every(isRef)) throw new Error();
        if (!request.signal.aborted) setProjects(data.projects);
      } catch {
        if (!request.signal.aborted) setError(ro ? 'Proiectele din seif nu sunt disponibile.' : 'Saved vault projects are unavailable.');
      }
    })();
    return () => { request.abort(); action.current?.abort(); action.current = null; };
  }, [open, refresh, ro]);

  async function choose(project: WorkshopRef) {
    if (!onChoose || action.current) return;
    const request = new AbortController();
    action.current = request;
    setChoosing(true); setError('');
    try { await onChoose(project, request.signal); }
    catch { if (!request.signal.aborted) setError(ro ? 'Proiectul nu a putut fi citit.' : 'Could not read this saved project.'); }
    finally { if (action.current === request) { action.current = null; setChoosing(false); } }
  }
  return <section className="ws-projects">
    <button type="button" className="tool-btn" aria-expanded={open} onClick={() => setOpen(v => !v)}>
      {heading || (ro ? 'Proiecte 3D salvate' : 'Saved 3D projects')}
    </button>
    {open && <div className="ws-project-list">
      <button type="button" className="tool-btn ws-project-refresh" onClick={() => setRefresh(v => v + 1)}
        disabled={choosing}>{ro ? 'Reîncarcă lista' : 'Refresh projects'}</button>
      {error && <p role="alert">{error}</p>}
      {!projects && !error && <p role="status">{ro ? 'Se încarcă…' : 'Loading projects…'}</p>}
      {projects?.length === 0 && <p>{ro ? 'Niciun proiect 3D salvat în seif.' : 'No saved 3D projects in this vault yet.'}</p>}
      {projects?.map(project => <div className="ws-project-row" key={project.path}>
        <a href={appUrl(projectLink(project.path))} target="_blank" rel="noreferrer">{project.title}</a>
        <small>{project.view === 'robot' ? 'Robot' : ro ? 'Casă' : 'House'}</small>
        {onChoose && <button type="button" className="tool-btn" disabled={choosing}
          onClick={() => void choose(project)}>{actionLabel}</button>}
      </div>)}
    </div>}
  </section>;
}
