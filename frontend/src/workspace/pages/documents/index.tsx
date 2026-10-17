/* Documents (/documents, /documents/:documentId): the knowledge base the assistant and the
   reports answer from.

   The collection shown is the sidebar's department, or the company-wide documents (visible to
   everyone; only admins upload there — everyone else asks for a department document to be
   published). Search, the status filter and the collection run on the server. While a document
   is still being processed the list refreshes itself. The preview drawer has its own URL
   (/documents/<id>, or ?document=<id> as the publish notification links it), so a citation or
   a notification opens it directly. */
import React, { useEffect, useMemo, useRef, useState } from 'react';
import { deleteDocument, documentFileUrl, listDocuments, reindexDocument, type UploadTarget } from '../../api/documents';
import type { DocumentStatus, WorkspaceDocument } from '../../api/types';
import { describeError } from '../../app/errors';
import { useAsync, usePolling } from '../../app/hooks';
import { useSession, useUser } from '../../app/session';
import { useWorkspace } from '../../app/workspace';
import { useI18n } from '../../i18n';
import { navigate, useDocumentTitle, useLocation } from '../../router';
import {
  Badge, Button, ConfirmDialog, EmptyState, Icon, IconButton, Menu, Notice, PageHeader, Select, Table, TextField,
  useToast, type Column, type MenuEntry,
} from '../../ui';
import { CompanyRequestDialog } from '../shared/ApprovalDialogs';
import { DOCUMENT_STATUS } from '../shared/labels';
import { optionalRouteId } from '../shared/routeId';
import { useDebounced } from '../shared/useDebounced';
import type { PageProps } from '../types';
import { DocumentDrawer } from './DocumentDrawer';
import { documentErrorText } from './errors';
import { UploadPanel } from './UploadPanel';
import { useUploadQueue, type UploadItem } from './useUploadQueue';
import '../../features.css';

const PROCESSING_POLL_MS = 5000;
const STATUSES: DocumentStatus[] = ['ready', 'processing', 'failed'];

type Scope = 'department' | 'company';

export function DocumentsPage({ params }: PageProps) {
  const i18n = useI18n();
  const { t, fmt } = i18n;
  const toast = useToast();
  useDocumentTitle(t('nav.documents'));
  const isAdmin = useUser().role === 'admin';
  const { refresh: refreshSession } = useSession();
  const { departments, currentDepartment, setCurrentDepartmentId, refreshDepartments } = useWorkspace();
  const departmentId = currentDepartment?.id ?? null;
  const [scope, setScope] = useState<Scope>('department');
  const [search, setSearch] = useState('');
  const [status, setStatus] = useState<'' | DocumentStatus>('');
  const q = useDebounced(search.trim(), 300);
  const location = useLocation();
  const linkedId = params.documentId ?? new URLSearchParams(location.search).get('document') ?? undefined;
  const [openId, setOpenId] = useState<number | null>(() => optionalRouteId(linkedId));
  const [drawerVersion, setDrawerVersion] = useState(0);
  const [deleting, setDeleting] = useState<WorkspaceDocument | null>(null);
  const [publishing, setPublishing] = useState<WorkspaceDocument | null>(null);
  const [reindexingId, setReindexingId] = useState<number | null>(null);
  const [announcement, setAnnouncement] = useState('');

  const documents = useAsync(async () => {
    if (scope === 'department' && departmentId === null) return [] as WorkspaceDocument[];
    return listDocuments({ departmentId: scope === 'company' ? 'company' : departmentId ?? undefined, q, status: status || undefined });
  }, [scope, departmentId, q, status]);

  const processing = (documents.data ?? []).some((d) => d.status === 'processing');
  usePolling(() => documents.reload(), PROCESSING_POLL_MS, processing);

  // A department picked in the sidebar always wins over the company-wide view.
  const previousDepartment = useRef(departmentId);
  useEffect(() => {
    if (previousDepartment.current !== null && previousDepartment.current !== departmentId) setScope('department');
    previousDepartment.current = departmentId;
  }, [departmentId]);

  useEffect(() => { setOpenId(optionalRouteId(linkedId)); }, [linkedId]);

  const deptName = useMemo(() => {
    const names = new Map(departments.map((d) => [d.id, d.name]));
    return (id: number | null) => (id === null ? t('documents.scope.company') : names.get(id) ?? `#${id}`);
  }, [departments, t]);

  const target: UploadTarget | null = scope === 'company' ? 'company' : departmentId;
  const targetName = scope === 'company' ? t('documents.scope.company') : currentDepartment?.name ?? '';

  const onFinished = (item: UploadItem) => {
    setAnnouncement(item.state === 'ready'
      ? t('documents.upload.announceReady', { name: item.name })
      : t('documents.upload.announceFailed', { name: item.name, reason: documentErrorText(i18n, item.error) }));
    if (item.document) {
      void documents.reload();
      void refreshDepartments();
    }
  };
  const queue = useUploadQueue(onFinished, refreshSession);

  const openDrawer = (doc: WorkspaceDocument) => {
    setOpenId(doc.id);
    navigate(`/documents/${doc.id}`, { quiet: true });
  };
  const closeDrawer = () => {
    setOpenId(null);
    if (linkedId !== undefined) navigate('/documents', { quiet: true });
  };

  const replaceRow = (doc: WorkspaceDocument) => {
    documents.setData((rows) => rows?.map((d) => (d.id === doc.id ? { ...d, ...doc } : d)) ?? null);
  };

  const reindex = async (doc: WorkspaceDocument) => {
    setReindexingId(doc.id);
    try {
      const saved = await reindexDocument(doc.id);
      replaceRow(saved);
      setDrawerVersion((v) => v + 1);
      if (saved.status === 'failed') toast.error(t('documents.reindex.failed', { reason: documentErrorText(i18n, saved.error) }));
      else toast.success(t('documents.reindex.ready'));
    } catch (err) {
      toast.error(describeError(i18n, err));
    } finally {
      setReindexingId(null);
    }
  };

  const rowMenu = (doc: WorkspaceDocument): MenuEntry[] => {
    const entries: MenuEntry[] = [{ id: 'preview', label: t('documents.action.preview'), icon: 'eye', onSelect: () => openDrawer(doc) }];
    if (doc.can_reindex) entries.push({ id: 'reindex', label: t('documents.action.reindex'), icon: 'refresh', disabled: reindexingId === doc.id, onSelect: () => void reindex(doc) });
    if (doc.can_publish && doc.visibility !== 'company') entries.push({ id: 'publish', label: t('documents.action.publish'), icon: 'globe', onSelect: () => setPublishing(doc) });
    if (doc.can_delete) {
      entries.push({ kind: 'separator', id: 'sep' });
      entries.push({ id: 'delete', label: t('documents.action.delete'), icon: 'trash', danger: true, onSelect: () => setDeleting(doc) });
    }
    return entries;
  };

  const columns: Column<WorkspaceDocument>[] = [
    {
      key: 'title', header: t('documents.col.document'),
      render: (doc) => (
        <span className="ws-cell-stack">
          <button type="button" className="ws-linklike ws-strong" onClick={() => openDrawer(doc)}>{doc.title}</button>
          <span className="ws-muted ws-small"><span className="ws-mono">{doc.filename}</span> · {fmt.bytes(doc.size_bytes)}</span>
        </span>
      ),
    },
    {
      key: 'status', header: t('documents.col.status'),
      render: (doc) => (
        <span className="ws-cell-stack">
          <Badge tone={DOCUMENT_STATUS[doc.status].tone} dot>{t(DOCUMENT_STATUS[doc.status].label)}</Badge>
          {doc.status === 'failed' && <span className="ws-small ws-danger-text ws-clamp">{documentErrorText(i18n, doc.error)}</span>}
        </span>
      ),
    },
    {
      key: 'scope', header: t('documents.col.scope'), secondary: true,
      render: (doc) => (
        <span className="ws-cell-stack">
          {doc.visibility === 'company' ? <Badge tone="accent">{t('documents.scope.company')}</Badge> : <span>{doc.department_name || deptName(doc.department_id)}</span>}
          {doc.publish_pending && <Badge tone="warning">{t('documents.publishPending')}</Badge>}
        </span>
      ),
    },
    {
      key: 'uploaded', header: t('documents.col.uploaded'), secondary: true,
      render: (doc) => (
        <span className="ws-cell-stack">
          <span title={fmt.dateTime(doc.created_at)}>{fmt.relative(doc.created_at)}</span>
          {doc.uploader && <span className="ws-muted ws-small">{t('documents.by', { name: doc.uploader.name })}</span>}
        </span>
      ),
    },
    {
      key: 'actions', header: '', srHeader: t('common.actions'), align: 'end', width: '96px',
      render: (doc) => (
        <span className="ws-row-actions">
          <a className="ws-icon-btn ws-icon-btn--ghost ws-icon-btn--md" href={documentFileUrl(doc.id)} download aria-label={t('documents.action.downloadNamed', { title: doc.title })} title={t('documents.action.download')}>
            <Icon name="download" />
          </a>
          <Menu
            label={t('documents.actionsFor', { title: doc.title })} items={rowMenu(doc)}
            trigger={(trigger) => <IconButton icon="more" label={t('documents.actionsFor', { title: doc.title })} {...trigger} />}
          />
        </span>
      ),
    },
  ];

  const filtered = Boolean(q || status);
  const empty = filtered
    ? <EmptyState compact icon="search" title={t('documents.noMatch')} />
    : scope === 'company'
      ? <EmptyState icon="globe" title={t('documents.emptyCompany')} body={t('documents.emptyCompanyBody')} />
      : <EmptyState icon="file" title={t('documents.empty')} body={t('documents.emptyBody')} />;

  return (
    <>
      <PageHeader eyebrow={targetName} title={t('nav.documents')} description={t('documents.description')} />
      <UploadPanel queue={queue} target={target} targetName={targetName} allowed={scope === 'department' || isAdmin} />
      <p className="ws-sr-only" role="status" aria-live="polite">{announcement}</p>
      <div className="ws-toolbar">
        <TextField
          className="ws-toolbar__search" label={t('documents.search')} type="search" value={search}
          onChange={(e) => setSearch(e.target.value)} placeholder={t('documents.searchPlaceholder')}
        />
        <Select
          className="ws-toolbar__filter" label={t('documents.filter.status')} value={status}
          onChange={(e) => setStatus(e.target.value as '' | DocumentStatus)}
          options={[{ value: '', label: t('documents.filter.all') }, ...STATUSES.map((s) => ({ value: s, label: t(DOCUMENT_STATUS[s].label) }))]}
        />
        <Select
          className="ws-toolbar__filter" label={t('documents.scope.label')}
          value={scope === 'company' ? 'company' : String(departmentId ?? '')}
          onChange={(e) => {
            if (e.target.value === 'company') { setScope('company'); return; }
            setScope('department');
            setCurrentDepartmentId(Number(e.target.value));
          }}
          options={[...departments.map((d) => ({ value: String(d.id), label: d.name })), { value: 'company', label: t('documents.scope.company') }]}
        />
      </div>
      {documents.error ? (
        <Notice tone="danger" live="assertive" action={<Button size="sm" icon="refresh" onClick={() => void documents.reload()}>{t('common.retry')}</Button>}>
          {describeError(i18n, documents.error)}
        </Notice>
      ) : (
        <Table
          caption={t('nav.documents')} columns={columns} rows={documents.data} rowKey={(d) => d.id}
          loading={documents.loading} empty={empty}
        />
      )}
      <DocumentDrawer
        id={openId} version={drawerVersion} departmentName={deptName} onClose={closeDrawer}
        onReindex={(doc) => void reindex(doc)} onPublish={setPublishing} onDelete={setDeleting} reindexing={reindexingId === openId}
      />
      <ConfirmDialog
        open={deleting !== null} onClose={() => setDeleting(null)}
        title={t('documents.delete.title')}
        body={deleting ? t('documents.delete.body', { title: deleting.title }) : ''}
        confirmLabel={t('documents.action.delete')}
        onConfirm={async () => {
          if (!deleting) return;
          await deleteDocument(deleting.id);
          toast.success(t('documents.delete.done'));
          documents.setData((rows) => rows?.filter((d) => d.id !== deleting.id) ?? null);
          if (openId === deleting.id) closeDrawer();
          void refreshDepartments();
        }}
      />
      {publishing && (
        <CompanyRequestDialog
          onClose={() => setPublishing(null)}
          kind="document.company_publish" payload={{ document_id: publishing.id }} departmentId={publishing.department_id}
          title={t('publish.title')} body={t('publish.body', { title: publishing.title })}
          adminNote={t('publish.adminNow')} requestNote={t('publish.needsAdmin')} adminSubmitLabel={t('publish.submitNow')}
          doneText={t('publish.done', { title: publishing.title })}
          onDone={() => { void documents.reload(); setDrawerVersion((v) => v + 1); }}
        />
      )}
    </>
  );
}
