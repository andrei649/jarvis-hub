/* Assistant (/assistant, /assistant/:conversationId): the department's conversations beside
   the chat.

   The department comes from the sidebar switcher. Opening a conversation of another
   department (a link from a notification) switches the sidebar to it, and switching the
   sidebar away from the open conversation's department starts a new chat there, so the list
   and the chat never disagree. The model posture is polled here too: it decides the honest
   notices above the composer (model unavailable, answers arriving in one piece under
   REDACT/BLOCK guardrails); the status chip itself lives in the top bar on every page. */
import React, { useEffect, useRef, useState } from 'react';
import { getModelPosture } from '../../api/account';
import { deleteConversation, listConversations, renameConversation } from '../../api/chat';
import type { Conversation, ConversationSummary, ModelPosture } from '../../api/types';
import { describeError } from '../../app/errors';
import { useAsync, usePolling } from '../../app/hooks';
import { useWorkspace } from '../../app/workspace';
import { useI18n } from '../../i18n';
import { navigate, useDocumentTitle } from '../../router';
import { Button, ConfirmDialog, Dialog, Drawer, EmptyState, IconButton, LoadingBlock, Menu, PageHeader, TextField, useToast } from '../../ui';
import { optionalRouteId } from '../shared/routeId';
import type { PageProps } from '../types';
import { ChatPane } from './ChatPane';
import { ConversationList } from './ConversationList';
import '../../features.css';

const POSTURE_POLL_MS = 60_000;
const TITLE_MAX = 200;

function RenameDialog({ conversation, onClose, onRenamed }: { conversation: ConversationSummary; onClose: () => void; onRenamed: (c: Conversation) => void }) {
  const i18n = useI18n();
  const { t } = i18n;
  const toast = useToast();
  const [title, setTitle] = useState(conversation.title);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!title.trim()) { setError(t('assistant.rename.required')); return; }
    setBusy(true);
    setError(null);
    try {
      const saved = await renameConversation(conversation.id, title.trim());
      onRenamed({ ...saved, id: conversation.id, title: saved?.title ?? title.trim() });
      toast.success(t('assistant.rename.done'));
      onClose();
    } catch (err) {
      setError(describeError(i18n, err));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog
      open onClose={onClose} title={t('assistant.rename.title')} busy={busy} size="sm"
      footer={(
        <>
          <Button onClick={onClose} disabled={busy}>{t('common.cancel')}</Button>
          <Button variant="primary" type="submit" form="ws-rename-conversation" busy={busy}>{t('common.save')}</Button>
        </>
      )}
    >
      <form id="ws-rename-conversation" className="ws-form" onSubmit={submit} noValidate>
        <TextField label={t('field.title')} value={title} maxLength={TITLE_MAX} error={error} onChange={(e) => setTitle(e.target.value)} data-autofocus="true" />
      </form>
    </Dialog>
  );
}

export function AssistantPage({ params }: PageProps) {
  const i18n = useI18n();
  const { t } = i18n;
  const toast = useToast();
  useDocumentTitle(t('nav.assistant'));
  const { departments, departmentsLoaded, currentDepartment, setCurrentDepartmentId } = useWorkspace();
  const routeId = optionalRouteId(params.conversationId);
  const departmentId = currentDepartment?.id ?? null;
  const conversations = useAsync(
    () => (departmentId === null ? Promise.resolve([] as ConversationSummary[]) : listConversations(departmentId)),
    [departmentId],
  );
  const [posture, setPosture] = useState<ModelPosture | null>(null);
  const [search, setSearch] = useState('');
  const [listOpen, setListOpen] = useState(false);
  const [open, setOpen] = useState<Conversation | null>(null);
  const [renaming, setRenaming] = useState<ConversationSummary | null>(null);
  const [deleting, setDeleting] = useState<ConversationSummary | null>(null);

  usePolling(async () => {
    try {
      setPosture(await getModelPosture());
    } catch {
      // The notices are advisory; the chip in the top bar reports a failed read on its own.
    }
  }, POSTURE_POLL_MS);

  // The sidebar moved away from the open conversation's department: start a new chat there.
  const previousDepartment = useRef(departmentId);
  useEffect(() => {
    const before = previousDepartment.current;
    previousDepartment.current = departmentId;
    if (before === null || departmentId === null || before === departmentId) return;
    if (routeId !== null && open && open.department_id !== departmentId) {
      setOpen(null);
      navigate('/assistant');
    }
  }, [departmentId]);

  const onLoaded = (conversation: Conversation) => {
    setOpen(conversation);
    if (conversation.department_id !== departmentId && departments.some((d) => d.id === conversation.department_id)) {
      setCurrentDepartmentId(conversation.department_id);
    }
  };

  const onCreated = (conversation: Conversation) => {
    setOpen(conversation);
    navigate(`/assistant/${conversation.id}`, { replace: true, quiet: true });
    void conversations.reload();
  };

  const startNew = () => {
    setListOpen(false);
    setOpen(null);
    navigate('/assistant');
  };

  const activeId = routeId !== null && routeId > 0 ? routeId : null;
  const summary = conversations.data?.find((c) => c.id === activeId);
  const title = activeId === null ? t('assistant.list.new') : summary?.title ?? open?.title ?? t('common.loading');

  if (departmentsLoaded && departments.length === 0) {
    return (
      <>
        <PageHeader title={t('nav.assistant')} />
        <EmptyState icon="users" title={t('assistant.noDepartment')} body={t('shell.noDepartments')} />
      </>
    );
  }

  const list = (onNavigate?: () => void) => (
    <ConversationList
      conversations={conversations.data} loading={conversations.loading} error={conversations.error}
      activeId={activeId} search={search} onSearch={setSearch} onNew={startNew}
      onRetry={() => void conversations.reload()} onRename={setRenaming} onDelete={setDeleting} onNavigate={onNavigate}
    />
  );

  const current = activeId !== null ? summary ?? (open ? { ...open, message_count: 0 } : null) : null;
  const header = (
    <>
      <IconButton className="ws-chat__list-toggle" icon="menu" label={t('assistant.list.open')} onClick={() => setListOpen(true)} aria-expanded={listOpen} />
      <h2 className="ws-chat__title" id="ws-chat-title">{title}</h2>
      {current && (
        <Menu
          label={t('assistant.list.actionsFor', { title: current.title })}
          items={[
            { id: 'rename', label: t('assistant.action.rename'), icon: 'edit', onSelect: () => setRenaming(current) },
            { id: 'delete', label: t('assistant.action.delete'), icon: 'trash', danger: true, onSelect: () => setDeleting(current) },
          ]}
          trigger={(trigger) => <IconButton icon="more" label={t('assistant.list.actionsFor', { title: current.title })} {...trigger} />}
        />
      )}
    </>
  );

  return (
    <>
      <PageHeader
        eyebrow={currentDepartment?.name}
        title={t('nav.assistant')}
        description={t('assistant.description')}
      />
      {!currentDepartment ? <LoadingBlock label={t('common.loading')} lines={3} /> : (
        <div className="ws-assistant">
          <div className="ws-assistant__list">{list()}</div>
          {routeId === -1 ? (
            <section className="ws-chat" aria-label={t('chat.notFound.title')}>
              <EmptyState icon="chat" title={t('chat.notFound.title')} body={t('chat.notFound.body')} action={<Button variant="primary" icon="plus" onClick={startNew}>{t('assistant.list.new')}</Button>} />
            </section>
          ) : (
            <ChatPane
              conversationId={activeId} department={currentDepartment} posture={posture} header={header}
              onCreated={onCreated} onLoaded={onLoaded} onActivity={() => void conversations.reload()}
            />
          )}
        </div>
      )}
      <Drawer open={listOpen} onClose={() => setListOpen(false)} title={t('assistant.list.label')} side="left" size="sm">
        {list(() => setListOpen(false))}
      </Drawer>
      {renaming && (
        <RenameDialog
          conversation={renaming} onClose={() => setRenaming(null)}
          onRenamed={(saved) => {
            conversations.setData((rows) => rows?.map((c) => (c.id === saved.id ? { ...c, title: saved.title } : c)) ?? null);
            setOpen((prev) => (prev && prev.id === saved.id ? { ...prev, title: saved.title } : prev));
          }}
        />
      )}
      <ConfirmDialog
        open={deleting !== null} onClose={() => setDeleting(null)}
        title={t('assistant.delete.title')}
        body={deleting ? t('assistant.delete.body', { title: deleting.title }) : ''}
        confirmLabel={t('assistant.action.delete')}
        onConfirm={async () => {
          if (!deleting) return;
          await deleteConversation(deleting.id);
          toast.success(t('assistant.delete.done'));
          conversations.setData((rows) => rows?.filter((c) => c.id !== deleting.id) ?? null);
          if (deleting.id === activeId) startNew();
        }}
      />
    </>
  );
}
