/* The document preview drawer: what the file is, who added it and where it is visible, how it
   was indexed, the first characters of its extracted text, and the actions the caller is
   allowed (the server says which: can_delete, can_reindex, can_publish). The extracted text is
   Markdown (the extractor writes tables, sheets and headings that way), so the preview renders
   it through the shared safe renderer instead of showing pipes and "---" rows. */
import React from 'react';
import { documentFileUrl, getDocument } from '../../api/documents';
import type { DocumentDetail, WorkspaceDocument } from '../../api/types';
import { describeError, errorCode } from '../../app/errors';
import { useAsync } from '../../app/hooks';
import { useI18n } from '../../i18n';
import { Badge, Button, Drawer, EmptyState, LoadingBlock, Notice } from '../../ui';
import { DownloadLink } from '../shared/ButtonLink';
import { CitedMarkdown } from '../shared/CitedMarkdown';
import { DOCUMENT_STATUS } from '../shared/labels';
import { documentErrorText } from './errors';

export interface DocumentDrawerProps {
  id: number | null;
  /** Bumped by the page after a change (reindex) so the drawer re-reads the document. */
  version: number;
  departmentName: (id: number | null) => string;
  onClose: () => void;
  onReindex: (doc: WorkspaceDocument) => void;
  onPublish: (doc: WorkspaceDocument) => void;
  onDelete: (doc: WorkspaceDocument) => void;
  reindexing: boolean;
}

function fileKind(doc: WorkspaceDocument): string {
  const dot = doc.filename.lastIndexOf('.');
  return dot >= 0 ? doc.filename.slice(dot + 1).toUpperCase() : doc.mime;
}

export function DocumentDrawer({ id, version, departmentName, onClose, onReindex, onPublish, onDelete, reindexing }: DocumentDrawerProps) {
  const i18n = useI18n();
  const { t, tn, fmt } = i18n;
  const detail = useAsync<DocumentDetail | null>(() => (id !== null && id > 0 ? getDocument(id) : Promise.resolve(null)), [id, version]);
  const doc = detail.data && detail.data.id === id ? detail.data : null;
  const notFound = id === -1 || errorCode(detail.error) === 'not_found';

  return (
    <Drawer
      open={id !== null} onClose={onClose} size="lg"
      title={doc?.title ?? t('documents.drawer.title')}
      footer={doc && (
        <>
          {doc.can_delete && <Button variant="danger-ghost" icon="trash" onClick={() => onDelete(doc)}>{t('documents.action.delete')}</Button>}
          <span className="ws-footer-spacer" />
          {doc.can_reindex && <Button icon="refresh" busy={reindexing} onClick={() => onReindex(doc)}>{t('documents.action.reindex')}</Button>}
          {doc.can_publish && doc.visibility !== 'company' && <Button icon="globe" onClick={() => onPublish(doc)}>{t('documents.action.publish')}</Button>}
          <DownloadLink href={documentFileUrl(doc.id)} variant="primary" icon="download">{t('documents.action.download')}</DownloadLink>
        </>
      )}
    >
      {notFound && <EmptyState icon="file" title={t('error.not_found')} />}
      {!notFound && detail.error !== null && detail.error !== undefined && (
        <Notice tone="danger" live="assertive" action={<Button size="sm" icon="refresh" onClick={() => void detail.reload()}>{t('common.retry')}</Button>}>
          {describeError(i18n, detail.error)}
        </Notice>
      )}
      {!notFound && !detail.error && !doc && <LoadingBlock label={t('common.loading')} lines={5} />}
      {doc && (
        <>
          <div className="ws-doc-head">
            <Badge tone={DOCUMENT_STATUS[doc.status].tone} dot>{t(DOCUMENT_STATUS[doc.status].label)}</Badge>
            {doc.visibility === 'company' ? <Badge tone="accent">{t('documents.scope.company')}</Badge> : <Badge>{doc.department_name || departmentName(doc.department_id)}</Badge>}
            {doc.publish_pending && <Badge tone="warning">{t('documents.publishPending')}</Badge>}
          </div>
          {doc.status === 'failed' && (
            <Notice tone="danger" title={t('documents.field.error')}>{documentErrorText(i18n, doc.error)}</Notice>
          )}
          <dl className="ws-dl">
            <dt>{t('documents.field.filename')}</dt><dd className="ws-mono">{doc.filename}</dd>
            <dt>{t('documents.field.type')}</dt><dd>{fileKind(doc)}</dd>
            <dt>{t('documents.field.size')}</dt><dd>{fmt.bytes(doc.size_bytes)}</dd>
            {doc.page_count !== null && doc.page_count !== undefined && <><dt>{t('documents.field.pages')}</dt><dd>{fmt.number(doc.page_count)}</dd></>}
            <dt>{t('documents.field.chunks')}</dt><dd>{tn('documents.chunks', doc.chunk_count ?? 0)}</dd>
            <dt>{t('documents.field.uploader')}</dt><dd>{doc.uploader?.name ?? '—'}</dd>
            <dt>{t('documents.field.uploaded')}</dt><dd>{fmt.dateTime(doc.created_at)}</dd>
          </dl>
          <section className="ws-doc-preview" aria-labelledby="ws-doc-preview-title">
            <h3 id="ws-doc-preview-title" className="ws-doc-preview__title">{t('documents.drawer.preview')}</h3>
            {doc.preview
              ? (
                <div className="ws-doc-preview__text" tabIndex={0} role="group" aria-labelledby="ws-doc-preview-title">
                  {/* Under the drawer's h2 and this section's h3, the text's own headings start at h4. */}
                  <CitedMarkdown text={doc.preview} citations={[]} onCite={() => undefined} headingOffset={3} />
                </div>
              )
              : <p className="ws-muted">{t('documents.drawer.noPreview')}</p>}
            {doc.preview && <p className="ws-muted ws-small">{t('documents.drawer.previewNote')}</p>}
          </section>
        </>
      )}
    </Drawer>
  );
}
