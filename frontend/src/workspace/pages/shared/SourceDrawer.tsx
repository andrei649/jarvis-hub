/* The source drawer behind a citation chip: which document, which page, the exact passage
   the model was given, and the way to the document itself (its preview in Documents, or the
   original file). The passage is shown as plain text — it is document content, not markup.

   A report run shared company-wide is read outside its department: the server marks each of its
   citations with `can_open`, and where the reader may not open the document (another
   department's, or deleted since) the drawer keeps the excerpt and says so instead of offering
   links that could only answer "not found". */
import React from 'react';
import { documentFileUrl } from '../../api/documents';
import type { Citation } from '../../api/types';
import { useI18n } from '../../i18n';
import { Drawer, Icon, Notice } from '../../ui';
import { ButtonLink, DownloadLink } from './ButtonLink';

export function SourceDrawer({ citation, onClose }: { citation: Citation | null; onClose: () => void }) {
  const { t } = useI18n();
  const openable = citation?.can_open !== false;
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
          <p className="ws-muted ws-small">{t('source.note')}</p>
          {!openable && <Notice tone="accent">{t('source.notOpenable')}</Notice>}
        </div>
      )}
    </Drawer>
  );
}
