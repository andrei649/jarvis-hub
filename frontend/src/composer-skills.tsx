import React, { useEffect, useId, useRef, useState } from 'react';
import { apiFetchOnce } from './api/client';
import { onOwnerSession } from './api/owner-session';
import { appUrl } from './base-path';
import { historyOwnerKey } from './chat-history-search';
import './composer-skills.css';

type Shortcut = { kind: 'skill'; name: string; command: string; description: string; editable_procedure?: boolean };
type Catalog = { skills: Shortcut[]; refine: boolean; truncated: boolean; unavailable: boolean };
type Revision = { skill: string; command: string; steps: string[]; original: string[]; base_hash: string; proposal_id?: string };
const SAFE_SKILL = /^\/[a-z][a-z0-9_-]{0,63}$/;
const skillSlug = (name: string) => name.trim().toLowerCase().replace(/[\s_]+/g, '-')
  .replace(/[^a-z0-9-]/g, '').replace(/-{2,}/g, '-').replace(/^-|-$/g, '');
const skillTitle = (name: string) => name.replace(/[-_]\d{6}$/, '').replace(/[-_]+/g, ' ')
  .replace(/\b[a-z]/g, letter => letter.toUpperCase());
const procedureTitle = (name: string) => skillTitle(name.replace(/[-_][0-9a-f]{12}$/i, ''));
const searchText = (text: string) => text.toLowerCase().replace(/[-_/\s]+/g, ' ').trim();

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

export function skillDraftWarning(command: string, args: string, lang: string) {
  if (Array.from((command + args).trimEnd()).length <= 4096 && Array.from(args.trim()).length <= 2000) return '';
  return lang === 'ro' ? 'Scurtează instrucțiunile la 2.000 de caractere și mesajul la 4.096 de caractere.'
    : 'Shorten the instructions to 2,000 characters and the full message to 4,096 characters.';
}

export function ComposerSkills({ agent, draft, lang, onInsert }: {
  agent: string; draft: string; lang: string; onInsert: (command: string, isSkill: boolean) => void;
}) {
  const [open, setOpen] = useState(false);
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);
  const [notice, setNotice] = useState('');
  const [query, setQuery] = useState('');
  const [panelLeft, setPanelLeft] = useState(0);
  const [revision, setRevision] = useState<Revision | null>(null);
  const [revisionError, setRevisionError] = useState('');
  const [revisionBusy, setRevisionBusy] = useState(false);
  const [ownerKey, setOwnerKey] = useState(historyOwnerKey);
  const revisionRequest = useRef<AbortController | null>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const panelId = useId();
  const ro = lang === 'ro';
  const title = ro ? 'Abilități' : 'Skills';
  const searchLabel = ro ? 'Caută o abilitate' : 'Search skills';
  const matches = catalog?.skills.filter(skill => searchText(skill.name + ' ' + skill.description).includes(searchText(query)));

  useEffect(() => {
    const check = () => setOwnerKey(historyOwnerKey());
    const unsubscribe = onOwnerSession(check);
    window.addEventListener('storage', check);
    window.addEventListener('focus', check);
    return () => { unsubscribe(); window.removeEventListener('storage', check); window.removeEventListener('focus', check); };
  }, []);

  useEffect(() => {
    revisionRequest.current?.abort();
    setRevision(null); setRevisionError(''); setRevisionBusy(false);
    setOpen(false); setCatalog(null);
  }, [agent, ownerKey]);
  useEffect(() => () => revisionRequest.current?.abort(), []);

  async function edit(skill: Shortcut) {
    if (ownerKey !== historyOwnerKey()) { setOwnerKey(historyOwnerKey()); return; }
    revisionRequest.current?.abort();
    const request = new AbortController();
    revisionRequest.current = request;
    setRevision(null); setRevisionError(''); setRevisionBusy(true);
    try {
      const response = await apiFetchOnce('/api/skills/procedures/revision?agent=' + encodeURIComponent(agent)
        + '&command=' + encodeURIComponent(skill.name), { admin: true, signal: request.signal });
      if (!response.ok) throw new Error('load failed');
      const body = await response.json();
      if (typeof body?.skill !== 'string' || skillSlug(body.skill) !== skill.name
          || !Array.isArray(body.steps) || !body.steps.length || body.steps.length > 20
          || !body.steps.every((step: unknown) => typeof step === 'string' && !!step.trim() && Array.from(step).length <= 300 && !/[\r\n]/.test(step))
          || typeof body.base_hash !== 'string' || !/^[a-f0-9]{64}$/.test(body.base_hash)) throw new Error('invalid revision');
      if (!request.signal.aborted && ownerKey === historyOwnerKey())
        setRevision({ skill: body.skill, command: skill.name, steps: body.steps, original: body.steps.slice(), base_hash: body.base_hash });
    } catch {
      if (!request.signal.aborted) setRevisionError(ro ? 'Pașii nu s-au încărcat. Reîncearcă.' : 'Steps could not be loaded. Try again.');
    } finally { if (!request.signal.aborted) setRevisionBusy(false); }
  }

  async function propose() {
    if (!revision || revisionBusy || ownerKey !== historyOwnerKey()) { setOwnerKey(historyOwnerKey()); return; }
    if (!revision.steps.length || revision.steps.some(step => !step.trim() || Array.from(step).length > 300 || /[\r\n]/.test(step))
        || revision.steps.every((step, i) => step === revision.original[i])
        && revision.steps.length === revision.original.length) return;
    const request = new AbortController();
    revisionRequest.current = request;
    setRevisionBusy(true); setRevisionError('');
    try {
      const response = await apiFetchOnce('/api/skills/procedures/revision', { method: 'POST', admin: true,
        body: { agent, command: revision.command, steps: revision.steps, base_hash: revision.base_hash }, signal: request.signal });
      if (response.status === 409) {
        const body = await response.json().catch(() => null);
        throw new Error(body?.reason === 'no_change' ? 'no_change' : 'stale');
      }
      if (response.status !== 202) throw new Error('refused');
      const body = await response.json();
      if (body?.skill !== revision.skill || typeof body.proposal_id !== 'string' || !/^[A-Za-z0-9_-]{1,128}$/.test(body.proposal_id))
        throw new Error('invalid response');
      if (!request.signal.aborted && ownerKey === historyOwnerKey()) setRevision({ ...revision, proposal_id: body.proposal_id });
    } catch (err) {
      if (!request.signal.aborted) setRevisionError(err instanceof Error && err.message === 'stale'
        ? (ro ? 'Procedura s-a schimbat. Copiază editările, redeschide pașii actuali și aplică-le din nou.'
          : 'The procedure changed. Copy your edits, reopen current steps, and reapply them.')
        : err instanceof Error && err.message === 'no_change'
          ? (ro ? 'Nu există nicio schimbare de propus.' : 'There is no change to propose.')
        : (ro ? 'Propunerea nu a fost confirmată. Verifică în Consolă înainte să reîncerci.'
          : 'Proposal was not confirmed. Check Console before retrying.'));
    } finally { if (!request.signal.aborted) setRevisionBusy(false); }
  }

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
      setNotice(review
        ? (ro ? 'Trimite sau șterge ciorna înainte să pregătești revizuirea conversației.' : 'Send or clear your draft before preparing a conversation review.')
        : (ro ? 'Ai deja o comandă în ciornă. Trimite-o sau șterge-o înainte să alegi altă abilitate.' : 'A slash command is already drafted. Send or clear it before choosing another skill.'));
      return;
    }
    const warning = !review && skillDraftWarning(command, ' ' + draft, lang);
    if (warning) { setNotice(warning); return; }
    onInsert(command, !review);
    setOpen(false); setNotice('');
  }

  function close() { setOpen(false); trigger.current?.focus(); }

  return <div className="composer-skills">
    <button ref={trigger} type="button" className="vault-trigger" aria-expanded={open} aria-controls={panelId}
      onClick={() => { if (!open) placePanel(); setOpen(value => !value); setNotice(''); setQuery(''); }}>{title}</button>
    {open && <section id={panelId} className="composer-skills-panel" style={{ left: panelLeft }} aria-label={ro ? 'Abilități disponibile în chat' : 'Available chat skills'}
      onKeyDown={event => { if (event.key === 'Escape') { event.stopPropagation(); close(); } }}>
      <div className="composer-skills-head"><strong>{title} · {agent}</strong>
        <button type="button" className="tool-btn" onClick={close} aria-label={ro ? 'Închide abilitățile' : 'Close skills'}>{ro ? 'Închide' : 'Close'}</button>
      </div>
      {loading && <p role="status">{ro ? 'Se încarcă abilitățile…' : 'Loading available skills…'}</p>}
      {error && <p role="status">{ro ? 'Abilitățile nu s-au încărcat. Verifică conexiunea și reîncearcă.' : 'Skills are unavailable. Check your connection and try again.'}</p>}
      {catalog && <>
        {catalog.skills.length > 1 && <input type="search" className="composer-skills-search" value={query}
          aria-label={searchLabel} placeholder={searchLabel} onChange={event => setQuery(event.target.value)} />}
        {matches?.length ? <ul className="composer-skills-list">{matches.map(skill =>
          <li key={skill.command}><button type="button" aria-label={`${skill.editable_procedure ? procedureTitle(skill.name) : skillTitle(skill.name)} — ${skill.command}`}
            onClick={() => choose(skill.command)}>
            <strong>{skill.editable_procedure ? procedureTitle(skill.name) : skillTitle(skill.name)}</strong><code>{skill.command}</code>
            {skill.description !== 'Skill' && <span>{skill.description}</span>}
          </button>{skill.editable_procedure === true && <button type="button" className="composer-skills-edit"
            aria-label={ro ? `Editează pașii pentru ${procedureTitle(skill.name)}` : `Edit steps for ${procedureTitle(skill.name)}`}
            onClick={() => edit(skill)}>{ro ? 'Editează pașii' : 'Edit steps'}</button>}</li>)}</ul> : <p role="status">{catalog.skills.length
            ? (ro ? 'Nicio abilitate nu corespunde căutării.' : 'No skills match your search.')
            : (ro ? 'Acest agent nu are abilități disponibile acum.' : 'No skills are available for this agent right now.')}</p>}
        {catalog.truncated && <p role="status">{ro ? 'Lista este limitată. Este posibil să mai existe abilități.' : 'The skill list is limited; more may be available.'}</p>}
        {catalog.unavailable && <p role="status">{ro ? 'Unele comenzi rapide sunt indisponibile.' : 'Some shortcuts are unavailable right now.'}</p>}
        {revisionBusy && !revision && <p role="status">{ro ? 'Se încarcă pașii…' : 'Loading steps…'}</p>}
        {revision && <div className="composer-skills-revision" aria-label={ro ? 'Revizuirea procedurii' : 'Procedure revision'}>
          <div className="composer-skills-revision-head">
            <strong>{ro ? `Editează pașii: ${procedureTitle(revision.command)}` : `Edit steps: ${procedureTitle(revision.command)}`}</strong>
            <code>{'/' + revision.command}</code>
          </div>
          <p>{ro ? 'Trimite o propunere pentru aprobare. Procedura rămâne neschimbată până la decizie.'
            : 'Submit a proposal for review. The procedure stays unchanged until a decision.'}</p>
          <p>{ro ? 'Fiecare pas: un rând, maximum 300 de caractere.' : 'Each step: one line, up to 300 characters.'}</p>
          {revision.steps.map((step, i) => <div key={i} className="composer-skills-step">
            <label htmlFor={`${panelId}-step-${i}`}>{ro ? `Pasul ${i + 1}` : `Step ${i + 1}`}</label>
            <textarea id={`${panelId}-step-${i}`} value={step} rows={2} wrap="soft" disabled={!!revision.proposal_id || revisionBusy}
              onKeyDown={event => { if (event.key === 'Enter') event.preventDefault(); }}
              onChange={event => { if (!/[\r\n]/.test(event.target.value)) setRevision(current => current ? { ...current,
                steps: current.steps.map((value, n) => n === i ? event.target.value : value) } : null); }} />
            {!revision.proposal_id && <button type="button" className="tool-btn" disabled={revisionBusy || revision.steps.length === 1}
              onClick={() => setRevision(current => current ? { ...current, steps: current.steps.filter((_, n) => n !== i) } : null)}>
              {ro ? 'Elimină pasul' : 'Remove step'}</button>}
          </div>)}
          {!revision.proposal_id && <div className="composer-skills-revision-actions">
            <button type="button" className="tool-btn" disabled={revisionBusy || revision.steps.length >= 20}
              onClick={() => setRevision(current => current ? { ...current, steps: [...current.steps, ''] } : null)}>
              {ro ? 'Adaugă pas' : 'Add step'}</button>
            <button type="button" className="tool-btn" disabled={revisionBusy || !revision.steps.length
              || revision.steps.some(step => !step.trim() || Array.from(step).length > 300 || /[\r\n]/.test(step))
              || (revision.steps.length === revision.original.length && revision.steps.every((step, i) => step === revision.original[i]))}
              onClick={propose}>{ro ? 'Propune pașii revizuiți' : 'Propose revised steps'}</button>
          </div>}
          {revision.proposal_id && <p role="status">{ro ? 'Propunere trimisă pentru aprobare.' : 'Proposal sent for review.'}
            {' '}<a href={appUrl('/v2/console/pending-skills#proposal=' + encodeURIComponent(revision.proposal_id))}>
              {ro ? `Verifică propunerea ${revision.proposal_id}` : `Review proposal ${revision.proposal_id}`}</a></p>}
        </div>}
        {revisionError && <p role="alert">{revisionError}</p>}
        {catalog.refine && <div className="composer-skills-review">
          <button type="button" className="tool-btn" onClick={() => choose('/refine', true)}>{ro ? 'Revizuiește conversația' : 'Review this conversation'}</button>
          <p>{ro ? 'Revizuirea locală poate propune amintiri și proceduri reutilizabile. Poți indica o temă după /refine.' : 'Recent turns are reviewed locally for memories and reusable skills. After you approve a new procedure, any agent can use it. You can type a focus after /refine.'}</p>
        </div>}
      </>}
      <a href={appUrl('/v2/console/pending-skills')}>{ro ? 'Verifică abilitățile propuse în Consolă' : 'Review pending skills in Console'}</a>
      {notice && <p role="status">{notice}</p>}
    </section>}
  </div>;
}
