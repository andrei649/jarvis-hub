import React, { useRef, useState } from 'react';
import { apiExportOffice } from './api/client';

type OfficeExport = { format: 'docx'; text: string } | { format: 'xlsx'; rows: string[][] };

export function OfficeExportButton({ data, lang }: { data: OfficeExport; lang?: string }) {
  const [failure, setFailure] = useState<'retry' | 'content' | null>(null);
  const [busy, setBusy] = useState(false);
  const pending = useRef(false);
  const word = data.format === 'docx';
  const ro = lang === 'ro';
  const label = word ? (ro ? 'Descarcă Word' : 'Download Word') : (ro ? 'Descarcă Excel' : 'Download Excel');
  const download = async () => {
    if (pending.current) return;
    pending.current = true;
    setBusy(true);
    setFailure(null);
    try {
      const blob = await apiExportOffice(data);
      const url = URL.createObjectURL(blob);
      try {
        const link = document.createElement('a');
        link.href = url;
        link.download = word ? 'Nerva reply.docx' : 'Nerva table.xlsx';
        document.body.appendChild(link);
        link.click();
        link.remove();
      } finally {
        // A browser may cancel the download if its URL is revoked in the click task.
        setTimeout(() => URL.revokeObjectURL(url), 1000);
      }
    } catch (error) {
      setFailure([413, 422].includes((error as { status?: number })?.status || 0) ? 'content' : 'retry');
    } finally {
      pending.current = false;
      setBusy(false);
    }
  };
  const errorLabel = failure === 'content' ? (ro ? 'Conținut prea mare sau neacceptat' : 'Content too large or unsupported')
    : failure === 'retry' ? `${label} — ${ro ? 'eșuat, reîncearcă' : 'failed, retry'}` : label;
  return <button type="button" className="tool-btn" disabled={busy || failure === 'content'} onClick={download}
    aria-label={errorLabel}>
    {busy ? (ro ? 'Se pregătește…' : 'Preparing…') : errorLabel}
  </button>;
}
