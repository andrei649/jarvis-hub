/* Upload: drop files on the zone or pick them with the button (the keyboard path), then
   follow each file — bytes sent, then "extracting and indexing" while the server works, then
   ready (with how many passages were indexed) or failed with the reason and what to do.

   Once a collection has documents the drop zone shrinks to one line (the list is what a
   returning person came for), and once every upload has finished the ready ones fold into a
   one-line summary — the same files are now rows of the table — while failed ones stay listed
   with their reason. Where the person may not upload (the company-wide collection, for
   non-admins) the page shows a short note instead of this card. */
import React, { useEffect, useRef, useState } from 'react';
import { ACCEPTED_EXTENSIONS, type UploadTarget } from '../../api/documents';
import { useI18n } from '../../i18n';
import { Button, Card, Icon, IconButton } from '../../ui';
import { documentErrorText } from './errors';
import type { UploadItem, UploadQueue } from './useUploadQueue';

function ItemStatus({ item }: { item: UploadItem }) {
  const i18n = useI18n();
  const { t, tn, fmt } = i18n;
  if (item.state === 'waiting') return <span className="ws-muted">{t('documents.upload.waiting')}</span>;
  if (item.state === 'uploading') {
    return (
      <span className="ws-upload__progress">
        <progress max={100} value={item.percent} aria-label={t('documents.upload.progressLabel', { name: item.name })} />
        <span className="ws-num">{t('documents.upload.uploading', { percent: fmt.percent(item.percent / 100) })}</span>
      </span>
    );
  }
  if (item.state === 'processing') {
    return (
      <span className="ws-upload__progress">
        <progress aria-label={t('documents.upload.progressLabel', { name: item.name })} />
        <span>{t('documents.upload.processing')}</span>
      </span>
    );
  }
  if (item.state === 'ready') {
    return <span className="ws-upload__ok"><Icon name="checkCircle" size={16} /> {t('documents.upload.ready', { chunks: tn('documents.chunks', item.document?.chunk_count ?? 0) })}</span>;
  }
  return <span className="ws-upload__bad"><Icon name="alert" size={16} /> {documentErrorText(i18n, item.error)}</span>;
}

export interface UploadPanelProps {
  queue: UploadQueue;
  target: UploadTarget | null;
  targetName: string;
  /** True when the collection already lists documents: the drop zone shows as one compact line. */
  compact?: boolean;
}

export function UploadPanel({ queue, target, targetName, compact = false }: UploadPanelProps) {
  const { t, tn } = useI18n();
  const input = useRef<HTMLInputElement>(null);
  const depth = useRef(0);
  const [dragging, setDragging] = useState(false);
  const [showDone, setShowDone] = useState(false);
  const finished = queue.items.filter((item) => item.state === 'ready' || item.state === 'failed').length;
  const allFinished = queue.items.length > 0 && finished === queue.items.length;
  const ready = queue.items.filter((item) => item.state === 'ready');
  // A new batch starts folded-out again.
  useEffect(() => { if (!allFinished) setShowDone(false); }, [allFinished]);
  const listed = allFinished && !showDone ? queue.items.filter((item) => item.state !== 'ready') : queue.items;

  const take = (list: FileList | null) => {
    const files = list ? Array.from(list) : [];
    if (files.length && target !== null) queue.add(files, target);
  };

  const onDrag = (event: React.DragEvent, kind: 'enter' | 'over' | 'leave') => {
    if (!Array.from(event.dataTransfer?.types ?? []).includes('Files')) return;
    event.preventDefault();
    if (kind === 'enter') depth.current += 1;
    if (kind === 'leave') depth.current = Math.max(0, depth.current - 1);
    setDragging(kind !== 'leave' || depth.current > 0);
  };

  return (
    <Card title={t('documents.upload.title')} description={t('documents.upload.target', { target: targetName })} className="ws-print-hide ws-upload-card">
      {(
        <div
          className={['ws-dropzone', compact && 'ws-dropzone--compact', dragging && 'is-dragging'].filter(Boolean).join(' ')}
          onDragEnter={(e) => onDrag(e, 'enter')} onDragOver={(e) => onDrag(e, 'over')} onDragLeave={(e) => onDrag(e, 'leave')}
          onDrop={(event) => {
            event.preventDefault();
            depth.current = 0;
            setDragging(false);
            take(event.dataTransfer?.files ?? null);
          }}
        >
          <span className="ws-dropzone__icon"><Icon name="upload" size={compact ? 18 : 22} /></span>
          <p className="ws-dropzone__title">{t('documents.upload.drop')}</p>
          <p className="ws-muted ws-small ws-dropzone__or">{t('documents.upload.or')}</p>
          <Button icon="folder" size={compact ? 'sm' : 'md'} onClick={() => input.current?.click()} disabled={target === null}>{t('documents.upload.choose')}</Button>
          <input
            ref={input} type="file" multiple hidden accept={ACCEPTED_EXTENSIONS.join(',')} aria-label={t('documents.upload.choose')}
            onChange={(event) => { take(event.target.files); event.target.value = ''; }}
          />
          <p className="ws-muted ws-small ws-dropzone__formats">{t('documents.upload.formats')}</p>
        </div>
      )}
      {queue.items.length > 0 && (
        <div className="ws-upload">
          <div className="ws-upload__head">
            <p className="ws-strong">{t('documents.upload.queue')}</p>
            <Button size="sm" variant="ghost" onClick={queue.clearFinished} disabled={finished === 0}>{t('documents.upload.clear')}</Button>
          </div>
          {allFinished && ready.length > 0 && (
            <p className="ws-upload__summary">
              <span className="ws-upload__ok"><Icon name="checkCircle" size={16} /> {tn('documents.upload.doneSummary', ready.length)}</span>
              <Button size="sm" variant="ghost" aria-expanded={showDone} onClick={() => setShowDone((on) => !on)}>
                {t(showDone ? 'documents.upload.hideDone' : 'documents.upload.showDone')}
              </Button>
            </p>
          )}
          {listed.length > 0 && <ul className="ws-upload__list">
            {listed.map((item) => (
              <li key={item.key} className={`ws-upload__item is-${item.state}`}>
                <Icon name="file" size={18} />
                <span className="ws-upload__name">
                  <span className="ws-strong">{item.name}</span>
                  <ItemStatus item={item} />
                </span>
                {(item.state === 'waiting' || item.state === 'uploading') && (
                  <IconButton size="sm" icon="close" label={t('documents.upload.cancel', { name: item.name })} onClick={() => queue.cancel(item.key)} />
                )}
              </li>
            ))}
          </ul>}
        </div>
      )}
    </Card>
  );
}
