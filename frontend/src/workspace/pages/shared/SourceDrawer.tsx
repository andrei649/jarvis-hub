/* The source drawer behind a citation chip: which document, which page, the exact passage
   the model was given, and the way to the document itself (its preview in Documents, or the
   original file). The passage is shown as plain text — it is document content, not markup. */
import React from 'react';
import { documentFileUrl } from '../../api/documents';
import type { Citation } from '../../api/types';
import { useI18n } from '../../i18n';
import { Drawer, Icon } from '../../ui';
import { ButtonLink, DownloadLink } from './ButtonLink';

export function SourceDrawer({ citation, onClose }: { citation: Citation | null; onClose: () => void }) {
  const { t } = useI18n();
  return (
    <Drawer
      open={citation !== null}
      onClose={onClose}
      title={citation ? t('source.title', { n: String(citation.n) }) : ''}
      footer={citation && (
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
        </div>
      )}
    </Drawer>
  );
}
