import React, { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { apiEditOffice, apiPostBlenderPreview, apiPostOfficePreview, getAdminToken, getToken } from './api/client';
import { isNetworkedOrigin, loadOwnerSession, onOwnerSession, ownerSession } from './api/owner-session';
import './composer-office.css';

type Kind = 'docx' | 'xlsx' | 'blend' | 'godot';
type Segment = { label: string; text: string; truncated: boolean; offset?: number; total_characters?: number };
type Preview = { kind: Kind; segments: Segment[]; total_segments: number; thumbnail_png?: string | null };
export type OfficeAttachment = { name: string; text: string };
type OfficeEntry = { attachment: OfficeAttachment; file: File; kind: Kind; preview: Preview; index: number };

const MAX_BYTES = 8 * 1024 * 1024;
const MAX_BLEND_BYTES = 64 * 1024 * 1024;
const MAX_GODOT_BYTES = 1024 * 1024;
const MAX_ATTACHMENTS = 8;
const MAX_PASSAGE_BYTES = 64_000;
const MAX_TOTAL_BYTES = 128_000;
const bytes = (value: string) => new TextEncoder().encode(value).byteLength;
const credentials = () => JSON.stringify([getToken(), getAdminToken(), ownerSession()?.signed_in || false, ownerSession()?.signed_in ? ownerSession()?.csrf : null]);
const length = (value: string) => Array.from(value).length;
const clean = (value: string) => value.normalize('NFC').replace(/[\u0000-\u001f\u007f\u200b-\u200f\u202a-\u202e\u2060-\u2069\ufeff]/g, ' ').replace(/\s+/g, ' ').trim();
const basename = (name: string) => clean(name.split(/[\\/]/).pop() || '') || 'document';
function validThumbnail(value: unknown): boolean {
  if (typeof value !== 'string' || value.length > 1_000_000 || !/^iVBORw0KGgo[A-Za-z0-9+/]*={0,2}$/.test(value)) return false;
  try {
    const png = atob(value);
    if (png.length < 33 || png.slice(12, 16) !== 'IHDR' || png.charCodeAt(11) !== 13) return false;
    const dimension = (at: number) => ((png.charCodeAt(at) * 0x1000000) + (png.charCodeAt(at + 1) << 16) +
      (png.charCodeAt(at + 2) << 8) + png.charCodeAt(at + 3)) >>> 0;
    return dimension(16) >= 1 && dimension(16) <= 256 && dimension(20) >= 1 && dimension(20) <= 256;
  } catch { return false; }
}

function validPreview(data: unknown, kind: Kind): data is Preview {
  if (!data || typeof data !== 'object' || Array.isArray(data)) return false;
  const result = data as Record<string, unknown>;
  if (result.kind !== kind || !Array.isArray(result.segments) || !result.segments.length || result.segments.length > 32 ||
      !Number.isInteger(result.total_segments) || (result.total_segments as number) < result.segments.length) return false;
  if (kind === 'blend' && result.thumbnail_png != null && !validThumbnail(result.thumbnail_png)) return false;
  return result.segments.every(item => item && typeof item === 'object' && !Array.isArray(item) &&
    typeof item.label === 'string' && !!clean(item.label) && length(item.label) <= 200 && !/[\u0000-\u001f\u007f]/.test(item.label) &&
    typeof item.text === 'string' && (kind === 'blend' || !!item.text.trim()) && length(item.text) <= 12000 && typeof item.truncated === 'boolean' &&
    (item.offset === undefined && item.total_characters === undefined || kind === 'docx' &&
      Number.isInteger(item.offset) && item.offset >= 0 && item.offset % 12000 === 0 &&
      Number.isInteger(item.total_characters) && item.total_characters <= 10_000_000 &&
      item.total_characters > item.offset && item.offset + length(item.text) <= item.total_characters));
}

function attachmentName(fileName: string, segment: Segment, kind: Kind): string {
  const sheetLabel = Array.from(clean(segment.label));
  const sheet = kind !== 'docx' ? ` · ${sheetLabel.slice(0, 100).join('')}${sheetLabel.length > 100 ? '…' : ''}` : '';
  return Array.from(kind === 'blend' ? 'Blender' : basename(fileName)).slice(0, 200 - length(sheet)).join('') + sheet;
}

async function readGodot(file: File, pageLabel: string): Promise<Preview> {
  const text = new TextDecoder('utf-8', { fatal: true }).decode(await file.arrayBuffer());
  if (!text.trim() || text.includes('\u0000')) throw new Error('godot-text');
  const characters = Array.from(text);
  const segments: Segment[] = [];
  for (let start = 0; start < characters.length; start += 12000) {
    segments.push({ label: `${pageLabel} ${segments.length + 1}`, text: characters.slice(start, start + 12000).join(''), truncated: false });
  }
  return { kind: 'godot', segments, total_segments: segments.length };
}

const labels = {
  en: { attach: 'Attach document', files: 'Files', filesHint: 'Accepts DOCX, XLSX, Blender .blend, and local Godot project.godot, .tscn, or .gd text.', close: 'Close document preview', closeBlend: 'Close Blender inspection', closeGodot: 'Close Godot source review', previewGodot: 'Review Godot source', chooseGodot: 'Choose source page', page: 'Page', godotLoading: 'Reading Godot source in your browser…', godotBounds: 'This source is read in your browser. Only the passage you attach goes with your message; the file and its path are not uploaded.', godotSize: 'Choose a Godot text file up to 1 MiB.', godotInvalid: 'Choose a nonempty Godot text file encoded as UTF-8.',
    retry: 'Retry preview', inspect: 'Inspect with Blender', fileSize: 'Choose a DOCX or XLSX file up to 8 MiB, or a .blend file up to 64 MiB.',
    blendSize: 'Choose a .blend file up to 64 MiB.', blendIntent: 'Inspect uploads this file to the connected hub, where Blender lists datablock names without rendering or editing. When you send, the chosen agent receives only the passage you attach.',
    blendUnavailable: 'Blender is unavailable on the connected hub. Install or enable Blender there, then retry.', blendInvalid: 'The hub cannot inspect this .blend file. Choose a valid Blender file.',
    destination: 'Destination', previewBlend: 'Blender inspection', chooseBlend: 'Choose a datablock group',
    loading: 'Reading document preview…', failed: 'Document preview failed. Check the connection and retry.', invalid: 'Document preview was invalid. Retry or choose another file.',
    tooLarge: 'The hub rejected this file as too large. Choose a smaller file.', unsupported: 'The hub cannot read this file. Choose another DOCX or XLSX file.',
    busy: 'The hub is busy. Retry the preview shortly.', auth: 'Sign in or refresh your session, then retry the preview.',
    choose: 'Choose a sheet or document', select: 'Select a passage', useSelection: 'Attach selected text', useShown: 'Attach shown text',
    noSelection: 'Select text in the preview, or attach all shown text.', selected: 'Passage attached to this message.',
    remove: 'Remove passage', bounds: 'The connected hub reads this file for preview. On Transmit, the selected agent receives only the attached passage, not the original file.',
    truncated: 'This preview is truncated.', included: 'Selected passage to send', unavailable: 'Close the image or vault review before attaching a document.',
    sheets: 'sheets', sections: 'sections', characters: 'characters', pageOf: 'Page', of: 'of', previousPage: 'Previous page', nextPage: 'Next page', done: 'Done reviewing', review: 'Review attached passage',
    addAnother: 'Add another document', staged: 'Passages selected for this message', maxCount: 'You can attach up to 8 passages. Remove one before adding another.',
    maxBytes: 'A passage may use up to 64,000 UTF-8 bytes; all passages together may use up to 128,000 bytes.',
    duplicate: 'This file and sheet already have a passage. Review that passage or choose a distinct source.', cancel: 'Keep selected passages', limits: '64,000 UTF-8 bytes per passage; 128,000 bytes total', officeOnly: 'Add another document accepts DOCX or XLSX. Your selected passages are still here.',
    editCopy: 'Edit a copy', textToReplace: 'Text to replace', cellToEdit: 'Cell (A1)', replacementText: 'Replacement text', replacementValue: 'New value', downloadEditedCopy: 'Download edited copy',
    editHint: 'The original file and selected passage stay unchanged. Only the revised copy downloads; nothing is sent to the agent.',
    editInvalid: 'Choose exact text shown here or an A1 cell, and keep the replacement within 8,192 characters.', editWorking: 'Preparing edited copy…',
    editFailed: 'The edited copy could not be downloaded. Review the target and try again.', editDownloaded: 'Edited copy downloaded. Original file and selected passage are unchanged.' },
  ro: { attach: 'Atașează document', files: 'Fișiere', filesHint: 'Acceptă DOCX, XLSX, Blender .blend și fișiere text Godot locale project.godot, .tscn sau .gd.', close: 'Închide previzualizarea documentului', closeBlend: 'Închide inspecția Blender', closeGodot: 'Închide revizuirea sursei Godot', previewGodot: 'Revizuiește sursa Godot', chooseGodot: 'Alege pagina sursei', page: 'Pagină', godotLoading: 'Se citește sursa Godot în browser…', godotBounds: 'Sursa este citită în browser. Doar pasajul atașat însoțește mesajul; fișierul și calea lui nu sunt încărcate.', godotSize: 'Alege un fișier text Godot de cel mult 1 MiB.', godotInvalid: 'Alege un fișier text Godot nevid, codificat UTF-8.',
    retry: 'Reîncearcă previzualizarea', inspect: 'Inspectează cu Blender', fileSize: 'Alege un fișier DOCX sau XLSX de cel mult 8 MiB sau un fișier .blend de cel mult 64 MiB.',
    blendSize: 'Alege un fișier .blend de cel mult 64 MiB.', blendIntent: 'Inspecția încarcă fișierul în hubul conectat, unde Blender listează numele blocurilor de date fără să randeze sau să editeze scena. Când trimiți, agentul ales primește doar pasajul pe care îl atașezi.',
    blendUnavailable: 'Blender nu este disponibil pe hubul conectat. Instalează-l sau activează-l acolo, apoi reîncearcă.', blendInvalid: 'Hubul nu poate inspecta acest fișier .blend. Alege un fișier Blender valid.',
    destination: 'Destinație', previewBlend: 'Inspecție Blender', chooseBlend: 'Alege grupul de blocuri de date',
    loading: 'Se citește previzualizarea documentului…', failed: 'Previzualizarea a eșuat. Verifică conexiunea și reîncearcă.', invalid: 'Previzualizarea nu este validă. Reîncearcă sau alege alt fișier.',
    tooLarge: 'Hubul a respins fișierul ca fiind prea mare. Alege un fișier mai mic.', unsupported: 'Hubul nu poate citi acest fișier. Alege alt fișier DOCX sau XLSX.',
    busy: 'Hubul este ocupat. Reîncearcă previzualizarea în curând.', auth: 'Autentifică-te sau reînnoiește sesiunea, apoi reîncearcă previzualizarea.',
    choose: 'Alege foaia sau documentul', select: 'Selectează un pasaj', useSelection: 'Atașează textul selectat', useShown: 'Atașează textul afișat',
    noSelection: 'Selectează textul din previzualizare sau atașează tot textul afișat.', selected: 'Pasaj atașat acestui mesaj.',
    remove: 'Elimină pasajul', bounds: 'Hubul conectat citește fișierul pentru previzualizare. La trimitere, agentul selectat primește doar pasajul atașat, nu fișierul original.',
    truncated: 'Această previzualizare este trunchiată.', included: 'Pasajul selectat pentru trimitere', unavailable: 'Închide previzualizarea imaginilor sau a notițelor înainte de a atașa un document.',
    sheets: 'foi', sections: 'secțiuni', characters: 'caractere', pageOf: 'Pagina', of: 'din', previousPage: 'Pagina precedentă', nextPage: 'Pagina următoare', done: 'Am terminat revizuirea', review: 'Revizuiește pasajul atașat',
    addAnother: 'Adaugă alt document', staged: 'Pasaje selectate pentru acest mesaj', maxCount: 'Poți atașa cel mult 8 pasaje. Elimină unul înainte de a adăuga altul.',
    maxBytes: 'Un pasaj poate avea cel mult 64.000 de octeți UTF-8; toate pasajele împreună pot avea cel mult 128.000 de octeți.',
    duplicate: 'Acest fișier și această foaie au deja un pasaj. Revizuiește pasajul sau alege altă sursă.', cancel: 'Păstrează pasajele selectate', limits: '64.000 octeți UTF-8 per pasaj; 128.000 de octeți în total', officeOnly: 'Poți adăuga doar DOCX sau XLSX. Pasajele selectate sunt păstrate.',
    editCopy: 'Editează o copie', textToReplace: 'Textul de înlocuit', cellToEdit: 'Celula (A1)', replacementText: 'Text nou', replacementValue: 'Valoare nouă', downloadEditedCopy: 'Descarcă copia editată',
    editHint: 'Fișierul original și pasajul ales rămân neschimbate. Se descarcă doar copia revizuită; nimic nu este trimis agentului.',
    editInvalid: 'Alege textul exact afișat sau o celulă A1 și limitează valoarea nouă la 8.192 de caractere.', editWorking: 'Se pregătește copia editată…',
    editFailed: 'Copia editată nu a putut fi descărcată. Verifică ținta și reîncearcă.', editDownloaded: 'Copia editată a fost descărcată. Originalul și pasajul ales sunt neschimbate.' },
} as const;

export function useOfficeDocument(agent: string, session: string, demo: boolean, blocked: boolean, lang: string) {
  const l = labels[lang === 'ro' ? 'ro' : 'en'];
  const [file, setFile] = useState<File | null>(null);
  const [kind, setKind] = useState<Kind>('docx');
  const [preview, setPreview] = useState<Preview | null>(null);
  const [index, setIndex] = useState(0);
  const [attachment, setAttachment] = useState<OfficeAttachment | null>(null);
  const [entries, setEntries] = useState<OfficeEntry[]>([]);
  const [editing, setEditing] = useState<number | null>(null);
  const [status, setStatus] = useState('');
  const [busy, setBusy] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [editOpen, setEditOpen] = useState(false);
  const [editTarget, setEditTarget] = useState('');
  const [editReplacement, setEditReplacement] = useState('');
  const [editStatus, setEditStatus] = useState('');
  const [editBusy, setEditBusy] = useState(false);
  const editPending = useRef<AbortController | null>(null);
  const pending = useRef<AbortController | null>(null);
  const fileCredentials = useRef('');
  const serial = useRef(0);
  const input = useRef<HTMLInputElement>(null);
  const passage = useRef<HTMLTextAreaElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);

  function resetEdit() {
    editPending.current?.abort(); editPending.current = null;
    setEditOpen(false); setEditTarget(''); setEditReplacement(''); setEditStatus(''); setEditBusy(false);
  }

  function clear() {
    serial.current++;
    resetEdit();
    pending.current?.abort(); pending.current = null;
    fileCredentials.current = '';
    setFile(null); setPreview(null); setAttachment(null); setEntries([]); setEditing(null); setStatus(''); setBusy(false); setIndex(0); setExpanded(false);
    if (input.current) input.current.value = '';
  }
  function closePreview() {
    serial.current++;
    resetEdit();
    pending.current?.abort(); pending.current = null;
    setFile(null); setPreview(null); setAttachment(null); setEditing(null); setStatus(''); setBusy(false); setIndex(0); setExpanded(false);
    if (input.current) input.current.value = '';
  }
  useLayoutEffect(() => { clear(); return () => { pending.current?.abort(); editPending.current?.abort(); }; }, [agent, session, demo, blocked]);
  useEffect(() => onOwnerSession((current, wanted) => {
    if ((current && !current.signed_in && (wanted || (!getToken() && !getAdminToken()))) || fileCredentials.current && fileCredentials.current !== credentials()) clear();
  }), []);

  async function load(selected: File, selectedKind: Kind) {
    if (fileCredentials.current !== credentials()) { clear(); return; }
    if (selectedKind === 'blend' && pending.current) return;
    pending.current?.abort();
    resetEdit();
    const controller = new AbortController();
    const request = ++serial.current;
    pending.current = controller;
    setFile(selected); setKind(selectedKind); setPreview(null); setAttachment(null); setEditing(null); setIndex(0); setBusy(true); setExpanded(true); setStatus(selectedKind === 'godot' ? l.godotLoading : l.loading);
    try {
      if (selectedKind === 'blend' && isNetworkedOrigin() && !ownerSession()) await loadOwnerSession();
      if (fileCredentials.current !== credentials()) { clear(); return; }
      if (selectedKind === 'godot') {
        const data = await readGodot(selected, l.page);
        if (fileCredentials.current !== credentials()) { clear(); return; }
        if (request === serial.current && !controller.signal.aborted) { setPreview(data); setStatus(''); }
        return;
      }
      const response = selectedKind === 'blend'
        ? await apiPostBlenderPreview(selected, controller.signal)
        : await apiPostOfficePreview(selected, selectedKind, controller.signal);
      if (!response.ok) throw new Error(String(response.status));
      const body = await response.text();
      if (body.length > 2_000_000) throw new Error('shape');
      const data: unknown = JSON.parse(body);
      if (!validPreview(data, selectedKind)) throw new Error('shape');
       if (fileCredentials.current !== credentials()) { clear(); return; }
      if (request === serial.current && !controller.signal.aborted) { setPreview(data); setStatus(''); }
    } catch (error) {
       if (fileCredentials.current !== credentials()) { clear(); return; }
      if (request === serial.current && !controller.signal.aborted) {
        const code = error instanceof Error ? error.message : '';
        if (code === '401' || code === '403') { clear(); setExpanded(true); setStatus(l.auth); return; }
        setStatus(selectedKind === 'godot' ? l.godotInvalid : code === 'shape' ? l.invalid : code === '413' ? l.tooLarge :
          code === '415' || code === '422' ? selectedKind === 'blend' ? l.blendInvalid : l.unsupported : code === '429' ? l.busy :
          code === '503' && selectedKind === 'blend' ? l.blendUnavailable :
          code === '401' || code === '403' ? l.auth : l.failed);
      }
    } finally {
      if (request === serial.current) { pending.current = null; setBusy(false); }
    }
  }
  async function pageDocx(offset: number) {
    if (!file || kind !== 'docx' || !preview || busy || !readyToSend()) return;
    resetEdit();
    pending.current?.abort();
    const controller = new AbortController();
    const request = ++serial.current;
    pending.current = controller;
    setBusy(true); setStatus(l.loading);
    try {
      const response = await apiPostOfficePreview(file, 'docx', controller.signal, offset);
      if (!response.ok) throw new Error(String(response.status));
      const body = await response.text();
      if (body.length > 2_000_000) throw new Error('shape');
      const data: unknown = JSON.parse(body);
      if (!validPreview(data, 'docx') || data.segments[0].offset !== offset ||
          data.segments[0].total_characters !== preview.segments[0].total_characters) throw new Error('shape');
      if (fileCredentials.current !== credentials()) { clear(); return; }
      if (request === serial.current && !controller.signal.aborted) {
        setPreview(data); setIndex(0); setAttachment(null); setStatus('');
      }
    } catch (error) {
      if (fileCredentials.current !== credentials()) { clear(); return; }
      if (request === serial.current && !controller.signal.aborted) {
        const code = error instanceof Error ? error.message : '';
        if (code === '401' || code === '403') { clear(); setExpanded(true); setStatus(l.auth); return; }
        setStatus(code === '429' ? l.busy : code === 'shape' ? l.invalid : l.failed);
      }
    } finally {
      if (request === serial.current) { pending.current = null; setBusy(false); }
    }
  }
  function choose(selected: File | undefined) {
    if (!selected || blocked || demo) return;
    if (fileCredentials.current && fileCredentials.current !== credentials()) { clear(); return; }
    const match = /\.(docx|xlsx|blend|godot|tscn|gd)$/i.exec(selected.name);
    const extension = match?.[1].toLowerCase();
    const selectedKind: Kind | undefined = extension === 'godot' || extension === 'tscn' || extension === 'gd' ? 'godot' : extension as Kind | undefined;
    if (entries.some(item => item.kind === 'docx' || item.kind === 'xlsx') && selectedKind !== 'docx' && selectedKind !== 'xlsx') {
      closePreview(); setKind('docx'); setStatus(l.officeOnly); setExpanded(true); return;
    }
    if (selectedKind === 'blend' || selectedKind === 'godot' || entries.some(item => item.kind === 'blend' || item.kind === 'godot')) clear();
    else closePreview();
    if (!selectedKind || !selected.size || selected.size > (selectedKind === 'blend' ? MAX_BLEND_BYTES : selectedKind === 'godot' ? MAX_GODOT_BYTES : MAX_BYTES)) {
      setExpanded(true); setStatus(selectedKind === 'blend' ? l.blendSize : selectedKind === 'godot' ? l.godotSize : l.fileSize); return;
    }
    if ((selectedKind === 'docx' || selectedKind === 'xlsx') && entries.length >= MAX_ATTACHMENTS) {
      setStatus(l.maxCount); setExpanded(true); return;
    }
    fileCredentials.current = credentials();
    if (selectedKind === 'blend') {
      setFile(selected); setKind(selectedKind); setExpanded(true);
      return;
    }
    void load(selected, selectedKind);
  }
  function setPassage(text: string) {
    if (fileCredentials.current !== credentials()) { clear(); return; }
    if (!file || !preview || !text.trim()) { setStatus(l.noSelection); return; }
    const next = { name: attachmentName(file.name, preview.segments[index], kind), text };
    if ((kind === 'docx' || kind === 'xlsx') && entries.some((item, i) => i !== editing && item.attachment.name === next.name)) {
      setStatus(l.duplicate); return;
    }
    if (bytes(text) > MAX_PASSAGE_BYTES || bytes(text) + entries.reduce((total, item, i) => total + (i === editing ? 0 : bytes(item.attachment.text)), 0) > MAX_TOTAL_BYTES) {
      setStatus(l.maxBytes); return;
    }
    if (editing === null && entries.length >= MAX_ATTACHMENTS) { setStatus(l.maxCount); return; }
    const entry = { attachment: next, file, kind, preview, index };
    setEntries(current => editing === null ? [...current, entry] : current.map((item, i) => i === editing ? entry : item));
    if (editing === null) setEditing(entries.length);
    setAttachment(next);
    setStatus(l.selected);
  }
  const readyToSend = () => {
    if ((file || entries.length) && fileCredentials.current !== credentials()) { clear(); return false; }
    return true;
  };
  function edit(itemIndex: number) {
    if (!readyToSend()) return;
    const item = entries[itemIndex];
    if (!item) return;
    resetEdit();
    setFile(item.file); setKind(item.kind); setPreview(item.preview); setIndex(item.index); setAttachment(item.attachment); setEditing(itemIndex); setStatus(''); setExpanded(true);
  }
  function remove(itemIndex: number) {
    if (itemIndex < 0 || itemIndex >= entries.length) return;
    setEntries(current => current.filter((_, i) => i !== itemIndex));
    if (entries.length === 1) { clear(); return; }
    if (editing === itemIndex) { setAttachment(null); setEditing(null); }
    else if (editing !== null && editing > itemIndex) setEditing(editing - 1);
  }
  function beginEdit() {
    if (!file || !preview || (kind !== 'docx' && kind !== 'xlsx') || !readyToSend()) return;
    const area = passage.current;
    const selection = area?.value.slice(area.selectionStart, area.selectionEnd) || '';
    setEditTarget(kind === 'xlsx' ? 'A1' : selection || (attachment?.text.length && attachment.text.length <= 2048 ? attachment.text : ''));
    setEditReplacement(''); setEditStatus(''); setEditOpen(true);
  }
  async function downloadEdit() {
    if (!file || !preview || (kind !== 'docx' && kind !== 'xlsx') || editBusy || busy || !readyToSend()) return;
    const source = file;
    const selectedKind = kind;
    const target = editTarget;
    const replacement = editReplacement;
    const sheet = selectedKind === 'xlsx' ? preview.segments[index]?.label : undefined;
    if (!source.size || source.size > MAX_BYTES || !target ||
        (selectedKind === 'docx' ? target.length > 2048 || !preview.segments[index].text.includes(target)
          : !/^[A-Z]+[1-9][0-9]*$/.test(target) || !sheet) || replacement.length > 8192) {
      setEditStatus(l.editInvalid); return;
    }
    const controller = new AbortController();
    editPending.current = controller;
    const request = serial.current;
    const originalCredential = fileCredentials.current;
    setEditBusy(true); setEditStatus(l.editWorking);
    try {
      const buffer = new Uint8Array(await source.arrayBuffer());
      if (buffer.length !== source.size || buffer.length > MAX_BYTES) throw new Error('size');
      if (originalCredential !== credentials()) { clear(); return; }
      if (controller.signal.aborted || request !== serial.current) return;
      const chunks: string[] = [];
      for (let at = 0; at < buffer.length; at += 32768)
        chunks.push(String.fromCharCode(...buffer.subarray(at, at + 32768)));
      const body = { kind: selectedKind, source_base64: btoa(chunks.join('')), target, replacement,
        ...(sheet ? { sheet } : {}) };
      const blob = await apiEditOffice(body, controller.signal);
      if (originalCredential !== credentials()) { clear(); return; }
      if (controller.signal.aborted || request !== serial.current) return;
      const url = URL.createObjectURL(blob);
      try {
        const link = document.createElement('a');
        link.href = url;
        link.download = `${basename(source.name).replace(/\.(docx|xlsx)$/i, '')} edited.${selectedKind}`;
        document.body.appendChild(link); link.click(); link.remove();
      } finally { const revoke = URL.revokeObjectURL.bind(URL); setTimeout(() => revoke(url), 1000); }
      setEditStatus(l.editDownloaded);
    } catch (error) {
      if (originalCredential !== credentials()) { clear(); return; }
      if (!controller.signal.aborted && request === serial.current) {
        if (error && typeof error === 'object' && 'status' in error && (error.status === 401 || error.status === 403)) {
          clear(); setExpanded(true); setStatus(l.auth);
        } else setEditStatus(l.editFailed);
      }
    } finally {
      if (editPending.current === controller) { editPending.current = null; setEditBusy(false); }
    }
  }
  return { file, kind, preview, index, attachment, attachments: entries.map(item => item.attachment), entries, totalBytes: entries.reduce((total, item) => total + bytes(item.attachment.text), 0), status, busy, expanded, input, passage, trigger, labels: l, destination: agent, clear, closePreview, dismiss: () => (kind === 'docx' || kind === 'xlsx') && entries.length ? closePreview() : clear(), choose, readyToSend, edit, remove,
    editOpen, editTarget, editReplacement, editStatus, editBusy, setEditTarget, setEditReplacement, beginEdit, downloadEdit,
    finish: () => { if (readyToSend() && attachment) { setExpanded(false); trigger.current?.focus(); } },
    reopen: () => { if (entries.length) edit(entries.length - 1); else if (readyToSend()) setExpanded(true); },
    retry: () => { if (file && !busy) void load(file, kind); },
    inspect: () => { if (file && kind === 'blend' && !busy && !preview) void load(file, kind); },
    pageDocx: (offset: number) => { void pageDocx(offset); },
    select: (next: number) => { if (readyToSend()) { resetEdit(); setIndex(next); setAttachment(null); setStatus(''); } },
    useSelection: () => { const area = passage.current; setPassage(area?.value.slice(area.selectionStart, area.selectionEnd) || ''); },
    useShown: () => setPassage(preview?.segments[index].text || '') };
}

export type OfficeDraft = ReturnType<typeof useOfficeDocument>;

export function OfficeButton({ draft, disabled }: { draft: OfficeDraft; disabled: boolean }) {
  return <>
    <input ref={draft.input} type="file" accept={draft.entries.some(item => item.kind === 'docx' || item.kind === 'xlsx') ? '.docx,.xlsx,application/vnd.openxmlformats-officedocument.wordprocessingml.document,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' : '.docx,.xlsx,.blend,.godot,.tscn,.gd,application/vnd.openxmlformats-officedocument.wordprocessingml.document,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'}
      className="office-file-input" tabIndex={-1} aria-label={draft.labels.attach}
      onChange={event => { draft.choose(event.target.files?.[0]); event.target.value = ''; }}/>
    <button ref={draft.trigger} type="button" className="office-trigger" disabled={disabled}
      title={disabled ? draft.labels.unavailable : draft.labels.filesHint}
      aria-label={draft.labels.attach}
      aria-description={draft.labels.filesHint}
      onClick={() => draft.attachments.length ? draft.reopen() : draft.input.current?.click()}>{draft.labels.files}</button>
  </>;
}

export function OfficeReview({ draft }: { draft: OfficeDraft }) {
  const closeButton = useRef<HTMLButtonElement>(null);
  useEffect(() => { if (draft.expanded) closeButton.current?.focus(); }, [draft.expanded]);
  const segment = draft.preview?.segments[draft.index];
  if (!draft.expanded) return null;
  return createPortal(<div className="office-overlay"><section className="office-review" role="dialog" aria-modal="true" aria-label={draft.kind === 'blend' ? draft.labels.previewBlend : draft.kind === 'godot' ? draft.labels.previewGodot : draft.labels.attach}
    onKeyDown={event => {
      if (event.key === 'Escape') { event.preventDefault(); draft.dismiss(); draft.trigger.current?.focus(); }
      if (event.key !== 'Tab') return;
      const controls = Array.from(event.currentTarget.querySelectorAll<HTMLElement>('button, select, textarea')).filter(item => !item.hasAttribute('disabled'));
      if (event.shiftKey && document.activeElement === controls[0]) { event.preventDefault(); controls[controls.length - 1]?.focus(); }
      else if (!event.shiftKey && document.activeElement === controls[controls.length - 1]) { event.preventDefault(); controls[0]?.focus(); }
    }}>
    <div className="office-review-head"><strong>{draft.file ? basename(draft.file.name) : draft.labels.attach}</strong>
      <button ref={closeButton} type="button" className="tool-btn" aria-label={draft.kind === 'blend' ? draft.labels.closeBlend : draft.kind === 'godot' ? draft.labels.closeGodot : draft.labels.close} onClick={() => { draft.dismiss(); draft.trigger.current?.focus(); }}>×</button>
    </div>
    <p>{draft.kind === 'blend' && draft.file ? draft.labels.blendIntent : draft.kind === 'godot' ? draft.labels.godotBounds : draft.labels.bounds}</p>
    {draft.file && <p>{draft.labels.destination}: <strong>{draft.destination}</strong></p>}
    {draft.entries.length > 0 && (draft.kind === 'docx' || draft.kind === 'xlsx') && <div className="office-staged">
      <strong>{draft.labels.staged} ({draft.entries.length}/{MAX_ATTACHMENTS})</strong>
      <p>{draft.totalBytes.toLocaleString()} / {MAX_TOTAL_BYTES.toLocaleString()} · {draft.labels.limits}</p>
      <ul>{draft.entries.map((item, i) => <li key={i}><span>{item.attachment.name}</span>
        <button type="button" className="tool-btn" aria-label={`${draft.labels.review}: ${item.attachment.name}`} onClick={() => draft.edit(i)}>{draft.labels.review}</button>
        <button type="button" className="tool-btn" aria-label={`${draft.labels.remove}: ${item.attachment.name}`} onClick={() => draft.remove(i)}>{draft.labels.remove}</button>
      </li>)}</ul>
      <button type="button" className="tool-btn" disabled={draft.entries.length >= MAX_ATTACHMENTS} onClick={() => draft.input.current?.click()}>{draft.labels.addAnother}</button>
    </div>}
    {draft.status && <p role={draft.preview ? 'status' : 'alert'}>{draft.status}</p>}
    {draft.file && draft.kind === 'blend' && !draft.preview && !draft.busy && !draft.status &&
      <button type="button" className="tool-btn" onClick={draft.inspect}>{draft.labels.inspect}</button>}
    {draft.file && !draft.preview && !draft.busy && <button type="button" className="tool-btn"
      onClick={() => { closeButton.current?.focus(); draft.retry(); }}>{draft.labels.retry}</button>}
    {draft.preview && <>
      {draft.kind === 'blend' && draft.preview.thumbnail_png &&
        <img className="office-thumbnail" src={`data:image/png;base64,${draft.preview.thumbnail_png}`} alt="Blender thumbnail"/>}
      <label>{draft.kind === 'blend' ? draft.labels.chooseBlend : draft.kind === 'godot' ? draft.labels.chooseGodot : draft.labels.choose}
        <select value={draft.index} onChange={event => draft.select(Number(event.target.value))}>
          {draft.preview.segments.map((item, i) => <option value={i} key={i}>{item.label}</option>)}
        </select>
      </label>
      <p>{draft.preview.segments.length} / {draft.preview.total_segments} {draft.kind === 'xlsx' ? draft.labels.sheets : draft.labels.sections} · {length(segment!.text).toLocaleString()} / 12,000 {draft.labels.characters}
        {segment!.truncated && (draft.kind !== 'docx' || segment!.offset === undefined) && <> · {draft.labels.truncated}</>}</p>
      {draft.kind === 'docx' && segment!.offset !== undefined && segment!.total_characters !== undefined &&
        <div className="office-review-actions">
          <button type="button" className="tool-btn" disabled={draft.busy || segment!.offset === 0}
            onClick={() => draft.pageDocx(segment!.offset! - 12000)}>{draft.labels.previousPage}</button>
          <span>{draft.labels.pageOf} {segment!.offset / 12000 + 1} {draft.labels.of} {Math.ceil(segment!.total_characters / 12000)}</span>
          <button type="button" className="tool-btn" disabled={draft.busy || !segment!.truncated}
            onClick={() => draft.pageDocx(segment!.offset! + 12000)}>{draft.labels.nextPage}</button>
        </div>}
      <label>{draft.labels.select}
        <textarea ref={draft.passage} readOnly rows={7} value={segment!.text}/>
      </label>
      <div className="office-review-actions">
        <button type="button" className="tool-btn" disabled={draft.busy} onClick={draft.useSelection}>{draft.labels.useSelection}</button>
        <button type="button" className="tool-btn" disabled={draft.busy} onClick={draft.useShown}>{draft.labels.useShown}</button>
      </div>
      {(draft.kind === 'docx' || draft.kind === 'xlsx') && <div className="office-copy-edit">
        <button type="button" className="tool-btn" disabled={draft.busy || draft.editBusy} onClick={draft.beginEdit}>{draft.labels.editCopy}</button>
        {draft.editOpen && <>
          <p>{draft.labels.editHint}</p>
          {draft.kind === 'xlsx' && <p>{draft.labels.sheets}: <strong>{segment!.label}</strong></p>}
          <label>{draft.kind === 'docx' ? draft.labels.textToReplace : draft.labels.cellToEdit}
            <textarea rows={draft.kind === 'docx' ? 2 : 1} maxLength={2048} value={draft.editTarget} disabled={draft.editBusy}
              onChange={event => draft.setEditTarget(event.target.value)} />
          </label>
          <label>{draft.kind === 'docx' ? draft.labels.replacementText : draft.labels.replacementValue}
            <textarea rows={2} maxLength={8192} value={draft.editReplacement} disabled={draft.editBusy}
              onChange={event => draft.setEditReplacement(event.target.value)} />
          </label>
          <button type="button" className="tool-btn" disabled={draft.editBusy || draft.busy || !draft.editTarget}
            onClick={draft.downloadEdit}>{draft.labels.downloadEditedCopy}</button>
          {draft.editStatus && <p role={draft.editStatus === draft.labels.editFailed || draft.editStatus === draft.labels.editInvalid ? 'alert' : 'status'}>{draft.editStatus}</p>}
        </>}
      </div>}
      {draft.attachment && <div className="office-selected"><strong>{draft.labels.included}: {draft.attachment.name}</strong>
        <p>{draft.attachment.text}</p>
        <button type="button" className="tool-btn" onClick={() => draft.remove(draft.entries.findIndex(item => item.attachment === draft.attachment))}>{draft.labels.remove}</button>
        <button type="button" className="tool-btn" onClick={draft.finish}>{draft.labels.done}</button>
      </div>}
    </>}
    {!draft.preview && draft.entries.length > 0 && <button type="button" className="tool-btn" onClick={() => { draft.closePreview(); draft.trigger.current?.focus(); }}>{draft.labels.cancel}</button>}
  </section></div>, document.body);
}

export function OfficeAttached({ draft }: { draft: OfficeDraft }) {
  if (!draft.attachments.length || draft.expanded) return null;
  return <div className="office-attached"><span>{draft.labels.destination}: {draft.destination}</span>
    {(draft.kind === 'docx' || draft.kind === 'xlsx') && <p>{draft.attachments.length}/{MAX_ATTACHMENTS} · {draft.totalBytes.toLocaleString()} / {MAX_TOTAL_BYTES.toLocaleString()} · {draft.labels.limits}</p>}
    {draft.attachments.map((item, i) => <div className="office-attached-item" key={i}>
      <strong>{draft.labels.included}: {item.name}</strong>
      <p>{item.text}</p>
      <button type="button" className="tool-btn" aria-label={draft.attachments.length === 1 ? draft.labels.review : `${draft.labels.review}: ${item.name}`} onClick={() => draft.edit(i)}>{draft.labels.review}</button>
      <button type="button" className="tool-btn" aria-label={draft.attachments.length === 1 ? draft.labels.remove : `${draft.labels.remove}: ${item.name}`} onClick={() => draft.remove(i)}>{draft.labels.remove}</button>
    </div>)}
    {(draft.kind === 'docx' || draft.kind === 'xlsx') && <button type="button" className="tool-btn" disabled={draft.attachments.length >= MAX_ATTACHMENTS} onClick={() => draft.input.current?.click()}>{draft.labels.addAnother}</button>}
  </div>;
}
