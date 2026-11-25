import React, { useEffect, useId, useRef, useState } from 'react';
import { apiFetchOnce } from './api/client';
import { isNetworkedOrigin, requireSignIn } from './api/owner-session';
import { appUrl } from './base-path';
import './chat-task-dialog.css';
import './teach-procedure-dialog.css';

type Proposal = { agent: string; description: string; steps: string[]; request_id: string };
const unresolved = new WeakMap<object, Proposal>();
const drafts = new WeakMap<object, { description: string; stepsText: string }>();

function count(text: string) { return Array.from(text).length; }

function validate(description: string, text: string, ro: boolean): string {
  if (!description.trim()) return ro ? 'Adaugă o descriere scurtă a utilizării.' : 'Add a brief description of when this skill is useful.';
  if (/\r|\n/.test(description)) return ro ? 'Păstrează descrierea pe un singur rând.' : 'Keep the description on one line.';
  if (count(description) > 300) return ro ? 'Scurtează descrierea la cel mult 300 de caractere.' : 'Shorten the description to 300 characters or fewer.';
  const lines = text.split(/\r?\n/);
  if (lines.length > 20) return ro ? `Folosește 1–20 de pași, câte unul pe rând. Răspunsul are ${lines.length} de rânduri; editează-l înainte de trimitere.` : `Use 1–20 steps, one per line. This reply has ${lines.length} lines; edit it before submitting.`;
  const blank = lines.findIndex(line => !line.trim());
  if (blank !== -1) return ro ? `Pasul ${blank + 1} este gol. Elimină rândul gol sau scrie un pas.` : `Step ${blank + 1} is empty. Remove the blank line or write a step.`;
  const long = lines.findIndex(line => count(line) > 300);
  if (long !== -1) return ro ? `Pasul ${long + 1} depășește 300 de caractere. Scurtează-l înainte de trimitere.` : `Step ${long + 1} exceeds 300 characters. Shorten it before submitting.`;
  return '';
}

function requestId() {
  return Array.from(crypto.getRandomValues(new Uint8Array(16)), byte => byte.toString(16).padStart(2, '0')).join('');
}

export function TeachProcedureDialog({ message, agent, lang, opener, onClose }: {
  message: { text: string }; agent: string; lang?: string; opener: HTMLElement; onClose: () => void;
}) {
  const ro = lang === 'ro';
  const previous = unresolved.get(message);
  const draft = drafts.get(message);
  const [description, setDescription] = useState(previous?.description ?? draft?.description ?? '');
  const [stepsText, setStepsText] = useState(previous ? previous.steps.join('\n') : draft?.stepsText ?? message.text);
  const [uncertain, setUncertain] = useState(!!previous);
  const [touched, setTouched] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [skill, setSkill] = useState('');
  const [decided, setDecided] = useState(false);
  const [conflict, setConflict] = useState(false);
  const inFlight = useRef(false);
  const dialog = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const validation = validate(description, stepsText, ro);

  useEffect(() => {
    dialog.current!.showModal();
    dialog.current!.querySelector<HTMLInputElement>('input')?.focus();
    return () => { dialog.current?.close(); if (opener.isConnected) opener.focus(); };
  }, [opener]);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (validation || inFlight.current || skill || decided || conflict) return;
    const retryingUnconfirmed = uncertain;
    const proposal = unresolved.get(message) || {
      agent, description, steps: stepsText.split(/\r?\n/), request_id: requestId(),
    };
    unresolved.set(message, proposal);
    inFlight.current = true;
    setBusy(true);
    setError('');
    try {
      const response = await apiFetchOnce('/api/skills/procedures', { method: 'POST', admin: true, body: proposal });
      let body: any;
      try { body = await response.json(); } catch { /* An unreadable response cannot establish the outcome. */ }
      if (response.status === 202 && body?.ok === true && body?.pending === true && typeof body.skill === 'string' && body.skill.trim()) {
        unresolved.delete(message);
        drafts.delete(message);
        setSkill(body.skill);
      } else if (response.status === 409 && (body?.reason || body?.detail?.reason) === 'procedure_decided') {
        unresolved.delete(message);
        setDecided(true);
      } else if (response.status === 409 && (body?.reason || body?.detail?.reason) === 'request_conflict') {
        unresolved.delete(message);
        setConflict(true);
      } else if (response.status === 409 && body?.reason === 'generation_refused') {
        unresolved.delete(message);
        setUncertain(false);
        setError(ro ? 'Generatorul a refuzat această procedură. Editează descrierea sau pașii și încearcă din nou.' : 'The skill generator refused this procedure. Edit the description or steps and try again.');
      } else if (response.status === 422 && body?.reason === 'agent_unavailable') {
        unresolved.delete(message);
        setUncertain(false);
        setError(ro ? `${agent} nu este activ sau este dezactivat. Reactivează agentul înainte de a trimite din nou.` : `${agent} is inactive or disabled. Enable that agent before submitting again.`);
      } else if (response.status === 401 || response.status === 403) {
        if (!retryingUnconfirmed) {
          unresolved.delete(message);
          setUncertain(false);
        }
        const networked = isNetworkedOrigin();
        if (networked) requireSignIn();
        const preserve = retryingUnconfirmed
          ? (ro ? ' Cererea inițială și ID-ul ei sunt păstrate; reîncearcă după autentificare.' : ' The original request and ID are preserved; retry after signing in.')
          : (ro ? ' Textul editat este păstrat.' : ' Your edited draft is preserved.');
        setError(response.status === 401
          ? (networked
            ? (ro ? 'Autentifică-te ca proprietar pentru a trimite această abilitate.' : 'Sign in as the owner to submit this skill.')
            : (ro ? 'Este necesar un token de administrator valid pentru această abilitate.' : 'A valid admin token is required to submit this skill.')) + preserve
          : (ro ? 'Este necesar accesul proprietarului. Autentifică-te sau verifică accesul de administrator al hub-ului.' : 'Owner access is required. Sign in or check the hub’s admin access.') + preserve);
      } else if ((response.status === 400 || response.status === 422) && body) {
        unresolved.delete(message);
        setUncertain(false);
        setError(ro ? `Hub-ul a respins datele${typeof body.detail === 'string' ? `: ${body.detail}` : '.'} Editează-le și trimite din nou.` : `The hub rejected this input${typeof body.detail === 'string' ? `: ${body.detail}` : '.'} Edit it and submit again.`);
      } else {
        setUncertain(true);
        setError(ro ? `Rezultatul nu a putut fi confirmat (HTTP ${response.status}). Reîncercarea trimite aceeași cerere.` : `The result could not be confirmed (HTTP ${response.status}). Retry sends the same request.`);
      }
    } catch {
      setUncertain(true);
      setError(ro ? 'Rezultatul nu a putut fi confirmat. Reîncercarea trimite aceeași cerere.' : 'The result could not be confirmed. Retry sends the same request.');
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  }

  return <dialog ref={dialog} className="chat-task-dialog teach-procedure-dialog" aria-modal="true" aria-labelledby={titleId}
    style={{ width: 'min(520px, calc(100vw - 32px))', boxSizing: 'border-box' }}
    onCancel={event => { event.preventDefault(); if (!inFlight.current) onClose(); }}
    onKeyDown={event => { event.stopPropagation(); if (event.key === 'Escape') { event.preventDefault(); if (!inFlight.current) onClose(); } }}>
    <h2 id={titleId}>{ro ? `Învață o abilitate din răspunsul lui ${agent}` : `Teach skill from ${agent}`}</h2>
    {skill ? <>
      <p role="status">{ro ? `${skill} așteaptă verificarea proprietarului. Nu este activă încă.` : `${skill} is pending owner review. It is not active yet.`}</p>
      <p><a href={`${appUrl('/v2/console/pending-skills')}#skill=${encodeURIComponent(skill)}`}>{ro ? 'Verifică abilitățile în așteptare' : 'Review pending skills'}</a></p>
      <button type="button" onClick={onClose}>{ro ? 'Închide' : 'Close'}</button>
    </> : decided ? <>
      <p role="status">{ro ? 'Această cerere a fost deja aprobată sau respinsă. Verifică starea abilității înainte de a crea alta.' : 'This request was already approved or discarded. Check the skill before creating another.'}</p>
      <button type="button" onClick={onClose}>{ro ? 'Închide' : 'Close'}</button>
    </> : conflict ? <>
      <p role="alert">{ro ? 'Acest ID de cerere a fost folosit cu alt conținut. Verifică propunerile existente înainte de a crea o cerere nouă.' : 'This request ID was used with different content. Check existing proposals before creating a new request.'}</p>
      <button type="button" onClick={onClose}>{ro ? 'Închide' : 'Close'}</button>
    </> : <form onSubmit={event => void submit(event)} noValidate>
      <p>{ro ? 'Editează răspunsul în pași reutilizabili. Fiecare rând devine un pas.' : 'Edit the reply into reusable steps. Each line becomes one step.'}</p>
      <label>{ro ? 'Când este utilă această abilitate?' : 'When is this skill useful?'}
        <input value={description} onChange={event => { setDescription(event.target.value); drafts.set(message, { description: event.target.value, stepsText }); setTouched(true); }} disabled={busy || uncertain} placeholder={ro ? 'Descriere reutilizabilă scurtă' : 'Brief reusable description'} />
      </label>
      <label>{ro ? `Pași din răspunsul lui ${agent}` : `Steps from ${agent}'s reply`}
        <textarea value={stepsText} onChange={event => { setStepsText(event.target.value); drafts.set(message, { description, stepsText: event.target.value }); setTouched(true); }} disabled={busy || uncertain} rows={10} />
      </label>
      {validation && !uncertain && <p role={touched ? 'alert' : 'status'}>{validation}</p>}
      {error && <p role="alert">{error}</p>}
      {uncertain && !error && <p role="status">{ro ? 'Rezultatul cererii este necunoscut. Reîncercarea trimite același conținut și ID de cerere.' : 'This request has an unconfirmed outcome. Retry sends the same content and request ID.'}</p>}
      <footer>
        <button type="button" onClick={onClose} disabled={busy}>{ro ? 'Anulează' : 'Cancel'}</button>
        <button type="submit" disabled={busy || !!validation}>{busy ? (ro ? 'Se trimite…' : 'Submitting…') : uncertain ? (ro ? 'Reîncearcă aceeași cerere' : 'Retry same request') : (ro ? 'Învață abilitatea' : 'Teach skill')}</button>
      </footer>
    </form>}
  </dialog>;
}
