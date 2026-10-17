/* The source drawer behind a citation chip: which document, which page, the exact passage
   the model was given, and the way to the document itself (its preview in Documents, or the
   original file). The passage is shown as plain text — it is document content, not markup.

   The server marks every citation with `can_open`, judged when the answer or the run is read: a
   report run shared company-wide is read outside its department, and a document an answer or a
   run cited can be deleted (or moved) later. Where the reader may not open the document the
   drawer keeps the excerpt, hides the links that could only answer "not found", and says why in
   the words of its context (`answer` in the assistant, `report` in a run view). A citation
   without the flag (the live `sources` event, retrieved in the reader's scope a moment ago) is
   openable. */
import React from 'react';
import { documentFileUrl } from '../../api/documents';
import type { Citation } from '../../api/types';
import { useI18n, type MessageKey } from '../../i18n';
import { Drawer, Icon, Notice } from '../../ui';
import { ButtonLink, DownloadLink } from './ButtonLink';

/** Where the cited passage was used: an assistant answer or a report run. */
export type SourceContext = 'answer' | 'report';

const COPY: Record<SourceContext, { note: MessageKey; notOpenable: MessageKey }> = {
  answer: { note: 'source.note', notOpenable: 'source.notOpenableAnswer' },
  report: { note: 'source.noteReport', notOpenable: 'source.notOpenable' },
};

export function SourceDrawer({ citation, context, onClose }: { citation: Citation | null; context: SourceContext; onClose: () => void }) {
  const { t } = useI18n();
  const openable = citation?.can_open !== false;
  const copy = COPY[context];
  return (
    <Drawer
      open={citation !== null}
      onClose={onClose}
      title={citation ? t('source.title', { n: String(citation.n) }) : ''}
      footer={citation && openable && (
        <>
          <DownloadLink href={documentFileUrl(citation.document_id)} icon="download">{t('source.download')}</DownloadLink>
          <ButtonLink to={`/documents/${citation.document_id}`} variant="primary" icon="file" onClick={onClose}>{t('source.openDocument')}</ButtonLink>
        </>
      )}
    >
      {citation && (
        <div className="ws-stack">
          <p className="ws-source-doc">
            <Icon name="file" size={18} />
            <span className="ws-strong">{citation.title}</span>
            {citation.page !== null && citation.page !== undefined && <span className="ws-muted">· {t('source.page', { page: String(citation.page) })}</span>}
          </p>
          <figure className="ws-quote">
            <figcaption className="ws-quote__label">{t('source.excerpt')}</figcaption>
            <blockquote className="ws-quote__text">{citation.excerpt}</blockquote>
          </figure>
          <p className="ws-muted ws-small">{t(copy.note)}</p>
          {!openable && <Notice tone="accent">{t(copy.notOpenable)}</Notice>}
        </div>
      )}
    </Drawer>
  );
}
