import React, { useEffect, useId, useRef } from 'react';
import { JobBuilder } from './job-builder';

/** Native modal supplies background inertness; keyboard handling also excludes shell shortcuts. */
export function JobCreateDialog({ onClose, onSave, error }: {
  onClose: () => void;
  onSave: (body: Record<string, unknown>) => void;
  error?: string | null;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const title = useId();
  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    const dialog = ref.current!;
    dialog.showModal();
    dialog.querySelector<HTMLInputElement>('input')?.focus();
    return () => { dialog.close(); if (opener?.isConnected) opener.focus(); };
  }, []);
  return <dialog className="job-create-dialog" ref={ref} aria-labelledby={title} aria-modal="true"
    style={{ width: 'min(760px, calc(100vw - 32px))', maxHeight: '90vh', overflowY: 'auto',
      boxSizing: 'border-box', padding: 24, border: '1px solid var(--panel-line)',
      borderRadius: 8, background: 'var(--void)' , color: 'var(--ink)' }}
    onCancel={e => { e.preventDefault(); onClose(); }}
    onKeyDown={e => {
      e.stopPropagation();
      if (e.key === 'Escape') { e.preventDefault(); onClose(); return; }
      if (e.key !== 'Tab') return;
      const controls = Array.from(ref.current!.querySelectorAll<HTMLElement>(
        'button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex="0"]'));
      const first = controls[0], last = controls[controls.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last?.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first?.focus(); }
    }}>
    <header style={{ display: 'flex', alignItems: 'center', gap: 16, justifyContent: 'space-between' }}>
      <h2 id={title} style={{ margin: 0 }}>Create scheduled job</h2>
      <button className="tool-btn" aria-label="Cancel creation" onClick={onClose}>Cancel</button>
    </header>
    <p>Choose what should run and when. Actions retain the existing approval and delivery rules.</p>
    {error && <div role="alert" style={{ color: 'var(--red)' }}>{error}</div>}
    <JobBuilder onSave={onSave} />
  </dialog>;
}
