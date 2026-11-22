import React, { useEffect, useId, useLayoutEffect, useRef, useState } from 'react';
import { encodePhotoshopLayout, renderPhotoshopLayout, PhotoshopLayoutError, type PhotoshopLayoutInput } from './photoshop-document';
import { getAdminToken, getToken } from './api/client';
import { onOwnerSession, ownerSession } from './api/owner-session';
import './chat-task-dialog.css';
import './photoshop-layout.css';

const MAX_IMAGE_BYTES = 16 * 1024 * 1024;
const MAX_SIDE = 4096;
const MAX_PIXELS = 16_000_000;
const credential = () => JSON.stringify([getToken(), getAdminToken(), ownerSession()?.signed_in || false,
  ownerSession()?.signed_in ? ownerSession()?.csrf || '' : '']);

const copy = {
  en: {
    heading: 'Photoshop layout', title: 'Artwork title', body: 'Reply text', image: 'Optional local image',
    hint: 'PNG or JPEG, up to 16 MiB and 16 million pixels. The image stays in this browser.',
    preview: 'Layout preview', noImage: 'No image selected', remove: 'Remove image', close: 'Close', loadingImage: 'Checking image…',
    download: 'Download PSD', preparing: 'Preparing PSD…', invalidImage: 'Choose a valid PNG or JPEG image.',
    largeImage: 'Image exceeds 16 MiB.', dimensions: 'Image dimensions exceed 4096 px per side or 16 million pixels.',
    decode: 'The image could not be decoded.', failed: 'The PSD could not be prepared. Review the layout and try again.',
    titleDefault: 'Chat reply', previewDescription: 'Preview of the editable Photoshop document',
  },
  ro: {
    heading: 'Machetă Photoshop', title: 'Titlul lucrării', body: 'Textul răspunsului', image: 'Imagine locală opțională',
    hint: 'PNG sau JPEG, cel mult 16 MiB și 16 milioane de pixeli. Imaginea rămâne în acest browser.',
    preview: 'Previzualizarea machetei', noImage: 'Nicio imagine selectată', remove: 'Elimină imaginea', close: 'Închide', loadingImage: 'Se verifică imaginea…',
    download: 'Descarcă PSD', preparing: 'Se pregătește PSD…', invalidImage: 'Alege o imagine PNG sau JPEG validă.',
    largeImage: 'Imaginea depășește 16 MiB.', dimensions: 'Dimensiunile depășesc 4096 px pe latură sau 16 milioane de pixeli.',
    decode: 'Imaginea nu a putut fi decodată.', failed: 'Fișierul PSD nu a putut fi pregătit. Verifică macheta și încearcă din nou.',
    titleDefault: 'Răspuns din chat', previewDescription: 'Previzualizarea documentului Photoshop editabil',
  },
};

function imageDimensions(bytes: Uint8Array): { width: number; height: number } | null {
  if (bytes.length >= 24 && [137, 80, 78, 71, 13, 10, 26, 10].every((v, i) => bytes[i] === v)
    && bytes[12] === 73 && bytes[13] === 72 && bytes[14] === 68 && bytes[15] === 82) {
    const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
    if (view.getUint32(8) !== 13) return null;
    return { width: view.getUint32(16), height: view.getUint32(20) };
  }
  if (bytes.length < 4 || bytes[0] !== 0xff || bytes[1] !== 0xd8) return null;
  let at = 2;
  while (at + 3 < bytes.length) {
    if (bytes[at++] !== 0xff) return null;
    while (bytes[at] === 0xff) at++;
    const marker = bytes[at++];
    if (marker === 0xd9 || marker === 0xda) break;
    if (marker === 0x01 || marker >= 0xd0 && marker <= 0xd7) continue;
    if (at + 2 > bytes.length) break;
    const length = (bytes[at] << 8) | bytes[at + 1];
    if (length < 2 || at + length > bytes.length) return null;
    if ([0xc0, 0xc1, 0xc2, 0xc3, 0xc5, 0xc6, 0xc7, 0xc9, 0xca, 0xcb, 0xcd, 0xce, 0xcf].includes(marker)) {
      if (length < 7) return null;
      return { height: (bytes[at + 3] << 8) | bytes[at + 4], width: (bytes[at + 5] << 8) | bytes[at + 6] };
    }
    at += length;
  }
  return null;
}

function withinImageBounds(size: { width: number; height: number }): boolean {
  return size.width > 0 && size.height > 0 && size.width <= MAX_SIDE && size.height <= MAX_SIDE
    && size.width * size.height <= MAX_PIXELS;
}

function filename(text: string): string {
  const words = Array.from(text.trim().split(/\r?\n/, 1)[0] || 'reply').slice(0, 70).join('');
  const stem = words.normalize('NFKD').replace(/[\u0300-\u036f]/g, '').replace(/[^a-zA-Z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 64);
  return `nerva-${stem || 'reply'}.psd`;
}

function PhotoshopLayoutDialog({ text, lang, opener, onClose }: {
  text: string; lang: 'en' | 'ro'; opener: HTMLElement; onClose: () => void;
}) {
  const k = copy[lang];
  const errorMessage = (problem: unknown) => problem instanceof PhotoshopLayoutError
    ? (lang === 'ro' ? problem.romanian : problem.message) : k.failed;
  const headingId = useId();
  const hintId = useId();
  const dialog = useRef<HTMLDialogElement>(null);
  const previewHost = useRef<HTMLDivElement>(null);
  const selectedUrl = useRef<string | null>(null);
  const imageStatus = useRef<'none' | 'pending' | 'invalid' | 'ready'>('none');
  const selectionVersion = useRef(0);
  const contentVersion = useRef(0);
  const alive = useRef(false);
  const initialCredential = useRef(credential());
  const downloading = useRef(false);
  const [title, setTitle] = useState(k.titleDefault);
  const [body, setBody] = useState(text);
  const [image, setImage] = useState<HTMLImageElement | undefined>();
  const [imageName, setImageName] = useState('');
  const [imageLoading, setImageLoading] = useState(false);
  const [imageProblem, setImageProblem] = useState('');
  const [error, setError] = useState('');
  const [previewError, setPreviewError] = useState('');
  const [previewReady, setPreviewReady] = useState(false);
  const [busy, setBusy] = useState(false);

  function releaseImage() {
    if (selectedUrl.current) URL.revokeObjectURL(selectedUrl.current);
    selectedUrl.current = null;
  }

  useLayoutEffect(() => {
    const node = dialog.current!;
    alive.current = true;
    node.showModal();
    node.querySelector<HTMLInputElement>('input[type="text"]')?.focus();
    const checkCredential = () => {
      if (credential() === initialCredential.current) return;
      alive.current = false;
      selectionVersion.current++;
      contentVersion.current++;
      onClose();
    };
    const unsubscribe = onOwnerSession(checkCredential);
    const onStorage = (event: StorageEvent) => {
      if (event.key === null || event.key === 'hud.user_token' || event.key === 'hud.admin_token') checkCredential();
    };
    window.addEventListener('storage', onStorage);
    window.addEventListener('focus', checkCredential);
    const timer = window.setInterval(checkCredential, 250);
    return () => {
      alive.current = false;
      selectionVersion.current++;
      contentVersion.current++;
      releaseImage();
      unsubscribe();
      window.removeEventListener('storage', onStorage);
      window.removeEventListener('focus', checkCredential);
      window.clearInterval(timer);
      node.close();
      if (opener.isConnected) opener.focus();
    };
  }, [opener]);

  useEffect(() => {
    const host = previewHost.current;
    if (!host) return;
    host.replaceChildren();
    setPreviewReady(false);
    try {
      const input: PhotoshopLayoutInput = { title, body, ...(image ? { image } : {}) };
      const canvas = renderPhotoshopLayout(input);
      canvas.setAttribute('role', 'img');
      canvas.setAttribute('aria-label', k.previewDescription);
      host.append(canvas);
      setPreviewError('');
      setPreviewReady(true);
    } catch (problem) {
      setPreviewError(errorMessage(problem));
    }
    return () => { host.replaceChildren(); };
  }, [title, body, image, k.previewDescription, k.failed]);

  async function chooseImage(file?: File) {
    const version = ++selectionVersion.current;
    ++contentVersion.current;
    releaseImage();
    imageStatus.current = file ? 'pending' : 'none';
    setImage(undefined); setImageName(file?.name || ''); setError(''); setImageProblem(''); setImageLoading(!!file);
    if (!file) return;
    if (!file.size || file.size > MAX_IMAGE_BYTES) {
      imageStatus.current = 'invalid';
      setImageProblem(file.size > MAX_IMAGE_BYTES ? k.largeImage : k.invalidImage); setImageLoading(false); return;
    }
    let url: string | null = null;
    try {
      const bytes = new Uint8Array(await file.arrayBuffer());
      if (!alive.current || credential() !== initialCredential.current || version !== selectionVersion.current) return;
      const size = imageDimensions(bytes);
      if (!size) { imageStatus.current = 'invalid'; setImageProblem(k.invalidImage); return; }
      if (!withinImageBounds(size)) { imageStatus.current = 'invalid'; setImageProblem(k.dimensions); return; }
      url = URL.createObjectURL(file);
      const decoded = new Image();
      decoded.src = url;
      await decoded.decode();
      if (!alive.current || credential() !== initialCredential.current || version !== selectionVersion.current) return;
      if (!withinImageBounds({ width: decoded.naturalWidth, height: decoded.naturalHeight })) {
        imageStatus.current = 'invalid';
        setImageProblem(k.dimensions); return;
      }
      selectedUrl.current = url;
      url = null;
      imageStatus.current = 'ready';
      setImage(decoded); setImageName(file.name || k.image);
    } catch { if (alive.current && version === selectionVersion.current) { imageStatus.current = 'invalid'; setImageProblem(k.decode); } }
    finally {
      if (url) URL.revokeObjectURL(url);
      if (alive.current && version === selectionVersion.current) setImageLoading(false);
    }
  }

  async function download() {
    if (downloading.current || imageStatus.current === 'pending' || imageStatus.current === 'invalid'
      || imageLoading || imageProblem || !previewReady || previewError || !title.trim()
      || credential() !== initialCredential.current) return;
    downloading.current = true;
    setBusy(true); setError('');
    const version = contentVersion.current;
    const input: PhotoshopLayoutInput = { title, body, ...(image ? { image } : {}) };
    try {
      const blob = await encodePhotoshopLayout(input);
      if (!alive.current || credential() !== initialCredential.current || version !== contentVersion.current) return;
      if (!(blob instanceof Blob) || !blob.size) throw new Error(k.failed);
      const url = URL.createObjectURL(blob);
      try {
        const link = document.createElement('a');
        link.href = url;
        link.download = filename(title);
        document.body.append(link);
        link.click();
        link.remove();
      } finally { window.setTimeout(() => URL.revokeObjectURL(url), 1000); }
    } catch (problem) {
      if (alive.current && version === contentVersion.current) setError(errorMessage(problem));
    } finally {
      downloading.current = false;
      if (alive.current) setBusy(false);
    }
  }

  return <dialog ref={dialog} className="chat-task-dialog photoshop-layout" aria-modal="true" aria-labelledby={headingId}
    onCancel={event => { event.preventDefault(); event.stopPropagation(); onClose(); }}
    onKeyDown={event => { event.stopPropagation(); if (event.key === 'Escape') { event.preventDefault(); onClose(); } }}>
    <h2 id={headingId}>{k.heading}</h2>
    <div className="photoshop-layout-grid">
      <div className="photoshop-layout-fields">
        <label>{k.title}<input type="text" value={title} onChange={event => { ++contentVersion.current; setTitle(event.target.value); setError(''); }} /></label>
        <label>{k.body}<textarea value={body} rows={9} onChange={event => { ++contentVersion.current; setBody(event.target.value); setError(''); }} /></label>
        <label>{k.image}<input type="file" accept="image/png,image/jpeg,.png,.jpg,.jpeg" aria-describedby={hintId}
          onChange={event => { void chooseImage(event.target.files?.[0]); event.target.value = ''; }} /></label>
        <p id={hintId} className="photoshop-layout-hint">{k.hint}</p>
        {(imageName || imageLoading || imageProblem) && <div className="photoshop-layout-selection">{imageName || k.image}{imageLoading && ` · ${k.loadingImage}`}
          <button type="button" onClick={() => void chooseImage()}>{k.remove}</button></div>}
      </div>
      <div className="photoshop-layout-preview"><h3>{k.preview}</h3>
        <div ref={previewHost} className="photoshop-layout-canvas" />
        {!image && <p className="photoshop-layout-hint">{k.noImage}</p>}
      </div>
    </div>
    {(imageProblem || error || previewError) && <p role="alert">{imageProblem || error || previewError}</p>}
    <footer><button type="button" onClick={onClose}>{k.close}</button>
      <button type="button" className="photoshop-download" disabled={busy || imageLoading || !!imageProblem || !previewReady || !!previewError || !title.trim()}
        onClick={() => void download()}>{busy ? k.preparing : k.download}</button></footer>
  </dialog>;
}

export function PhotoshopLayoutButton({ text, lang }: { text: string; lang: 'en' | 'ro' }) {
  const [opener, setOpener] = useState<HTMLElement | null>(null);
  const button = useRef<HTMLButtonElement>(null);
  const wasOpen = useRef(false);
  useLayoutEffect(() => {
    if (wasOpen.current && !opener) button.current?.focus();
    wasOpen.current = !!opener;
  }, [opener]);
  return <><button ref={button} type="button" className="tool-btn" onClick={event => setOpener(event.currentTarget)}>
    Photoshop</button>{opener && <PhotoshopLayoutDialog text={text} lang={lang} opener={opener} onClose={() => setOpener(null)} />}</>;
}
