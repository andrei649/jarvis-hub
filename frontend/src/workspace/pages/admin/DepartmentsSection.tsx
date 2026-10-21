/* Admin → Departments: create, edit (incl. the assistant's standing instructions), archive or
   restore, delete.

   Deleting is allowed only for an empty department (no members, documents, reports or
   conversations); the server refuses otherwise with `department_not_empty`, and the dialog
   explains that archiving is the way to retire a department that has history. The drawer keeps
   what was typed as a draft in this tab (app/drafts.ts) until it is saved or cancelled. */
import React, { useMemo, useState } from 'react';
import { createDepartment, deleteDepartment, listAdminDepartments, updateDepartment } from '../../api/admin';
import type { AdminDepartment } from '../../api/types';
import { draftText, useDraftMirror, useRestoredDraft } from '../../app/drafts';
import { describeError, errorField } from '../../app/errors';
import { useUser } from '../../app/session';
import { useAsync } from '../../app/hooks';
import { useWorkspace } from '../../app/workspace';
import { useI18n } from '../../i18n';
import { Badge, Button, type Column, ConfirmDialog, Drawer, EmptyState, IconButton, Menu, type MenuEntry, Notice, Switch, Table, TextArea, TextField, useInvalidFocus, useToast } from '../../ui';

const LIMITS = { name: 200, description: 4000, instructions: 4000 } as const;

interface DepartmentDraft { name: string; description: string; instructions: string }

function isArchived(d: AdminDepartment): boolean {
  return Boolean(d.archived);
}

function Counter({ value, max }: { value: string; max: number }) {
  const { t } = useI18n();
  const length = [...value].length;
  return <span className={length > max ? 'ws-counter is-over' : 'ws-counter'}>{t('common.charCount', { count: length, max })}</span>;
}

/** Create (department = null) or edit; mounted only while open. */
function DepartmentDrawer({ department, onClose, onSaved }: { department: AdminDepartment | null; onClose: () => void; onSaved: () => void }) {
  const i18n = useI18n();
  const { t } = i18n;
  const toast = useToast();
  const userId = useUser().id;
  const draftKey = `department.${department?.id ?? 'new'}`;
  const initial: DepartmentDraft = { name: department?.name ?? '', description: department?.description ?? '', instructions: department?.assistant_instructions ?? '' };
  const restored = useRestoredDraft<DepartmentDraft>(userId, draftKey);
  const [name, setName] = useState(draftText(restored?.name, initial.name));
  const [description, setDescription] = useState(draftText(restored?.description, initial.description));
  const [instructions, setInstructions] = useState(draftText(restored?.instructions, initial.instructions));
  const [errors, setErrors] = useState<{ name?: string; description?: string; assistant_instructions?: string }>({});
  const formRef = useInvalidFocus(errors);
  const [formError, setFormError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const pristine = name === initial.name && description === initial.description && instructions === initial.instructions;
  const clearDraft = useDraftMirror<DepartmentDraft>(userId, draftKey, { name, description, instructions }, pristine);
  const cancel = () => { clearDraft(); onClose(); };

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    const found: typeof errors = {};
    if (!name.trim()) found.name = t('departments.error.name');
    if ([...description].length > LIMITS.description) found.description = t('common.tooLong', { max: LIMITS.description });
    if ([...instructions].length > LIMITS.instructions) found.assistant_instructions = t('common.tooLong', { max: LIMITS.instructions });
    setErrors(found);
    setFormError(null);
    if (Object.keys(found).length) return;
    setBusy(true);
    const body = { name: name.trim(), description: description.trim(), assistant_instructions: instructions.trim() };
    try {
      if (department) await updateDepartment(department.id, body);
      else await createDepartment(body);
      clearDraft();
      toast.success(department ? t('departments.saved') : t('departments.created', { name: body.name }));
      onSaved();
      onClose();
    } catch (err) {
      const field = errorField(err);
      const message = describeError(i18n, err);
      if (field === 'name' || field === 'description' || field === 'assistant_instructions') setErrors({ [field]: message });
      else setFormError(message);
      setBusy(false);
    }
  };

  return (
    <Drawer
      open onClose={cancel} busy={busy} size="lg"
      title={department ? t('departments.editTitle', { name: department.name }) : t('departments.createTitle')}
      footer={(
        <>
          <Button onClick={cancel} disabled={busy}>{t('common.cancel')}</Button>
          <Button variant="primary" type="submit" form="ws-dept-form" busy={busy}>{department ? t('common.save') : t('departments.create')}</Button>
        </>
      )}
    >
      {restored && <Notice tone="accent">{t('draft.restored')}</Notice>}
      {formError && <Notice tone="danger" live="assertive">{formError}</Notice>}
      <form id="ws-dept-form" ref={formRef} className="ws-form" onSubmit={submit} noValidate>
        <TextField label={t('field.name')} value={name} onChange={(e) => setName(e.target.value)} error={errors.name} maxLength={LIMITS.name} required
          hint={department ? t('departments.slugHint', { slug: department.slug }) : t('departments.slugNew')} />
        <TextArea
          label={t('field.description')} optional rows={3} value={description} onChange={(e) => setDescription(e.target.value)}
          error={errors.description} aside={<Counter value={description} max={LIMITS.description} />} hint={t('departments.descriptionHint')}
        />
        <TextArea
          label={t('field.assistant_instructions')} optional rows={10} value={instructions} onChange={(e) => setInstructions(e.target.value)}
          error={errors.assistant_instructions} aside={<Counter value={instructions} max={LIMITS.instructions} />}
          hint={t('departments.instructionsHint')} placeholder={t('departments.instructionsPlaceholder')}
        />
      </form>
    </Drawer>
  );
}

export function DepartmentsSection() {
  const i18n = useI18n();
  const { t, fmt } = i18n;
  const toast = useToast();
  const { refreshDepartments } = useWorkspace();
  const list = useAsync(listAdminDepartments, []);
  const [showArchived, setShowArchived] = useState(false);
  const [drawer, setDrawer] = useState<{ department: AdminDepartment | null } | null>(null);
  const [archiving, setArchiving] = useState<AdminDepartment | null>(null);
  const [deleting, setDeleting] = useState<AdminDepartment | null>(null);

  const archivedCount = (list.data ?? []).filter(isArchived).length;
  const rows = useMemo(() => (list.data ?? []).filter((d) => showArchived || !isArchived(d)), [list.data, showArchived]);
  const afterChange = () => { void list.reload(); void refreshDepartments(); };

  const count = (value: number | undefined) => <span className="ws-num">{fmt.number(value ?? 0)}</span>;

  const rowMenu = (d: AdminDepartment): MenuEntry[] => [
    { id: 'edit', label: t('departments.action.edit'), icon: 'edit', onSelect: () => setDrawer({ department: d }) },
    isArchived(d)
      ? { id: 'restore', label: t('departments.action.restore'), icon: 'restore', onSelect: () => setArchiving(d) }
      : { id: 'archive', label: t('departments.action.archive'), icon: 'archive', onSelect: () => setArchiving(d) },
    { kind: 'separator', id: 'sep' },
    { id: 'delete', label: t('departments.action.delete'), icon: 'trash', danger: true, onSelect: () => setDeleting(d) },
  ];

  const columns: Column<AdminDepartment>[] = [
    {
      key: 'name', header: t('field.name'),
      render: (d) => (
        <span className="ws-cell-stack">
          <span className="ws-strong">{d.name} {isArchived(d) && <Badge>{t('departments.archived')}</Badge>}</span>
          <span className="ws-muted ws-small ws-mono">{d.slug}</span>
        </span>
      ),
    },
    { key: 'description', header: t('field.description'), secondary: true, render: (d) => <span className="ws-clamp">{d.description || <span className="ws-muted">—</span>}</span> },
    {
      key: 'assistant', header: t('departments.col.assistant'), secondary: true,
      render: (d) => (d.assistant_instructions ? <Badge tone="accent">{t('departments.custom')}</Badge> : <span className="ws-muted">{t('departments.default')}</span>),
    },
    { key: 'members', header: t('departments.col.members'), align: 'end', render: (d) => count(d.member_count) },
    {
      // Documents the assistant can use; failed or still-processing uploads are counted apart.
      key: 'documents', header: t('departments.col.documents'), align: 'end', secondary: true,
      render: (d) => {
        const ready = d.ready_document_count ?? d.document_count ?? 0;
        const total = d.document_count ?? 0;
        return ready === total ? count(total) : <span className="ws-num" title={t('departments.readyOfTotal', { ready, total })}>{t('departments.readyOfTotal', { ready, total })}</span>;
      },
    },
    { key: 'reports', header: t('departments.col.reports'), align: 'end', render: (d) => count(d.report_count), secondary: true },
    {
      key: 'actions', header: '', srHeader: t('common.actions'), align: 'end', width: '56px',
      render: (d) => (
        <Menu label={t('departments.actionsFor', { name: d.name })} items={rowMenu(d)}
          trigger={(props) => <IconButton icon="more" label={t('departments.actionsFor', { name: d.name })} {...props} />} />
      ),
    },
  ];

  return (
    <>
      <div className="ws-toolbar">
        {/* Offered only when there is something archived to show. */}
        {(archivedCount > 0 || showArchived) && <Switch checked={showArchived} onChange={setShowArchived} label={t('departments.showArchived', { count: archivedCount })} />}
        <div className="ws-toolbar__end">
          <Button variant="primary" icon="plus" onClick={() => setDrawer({ department: null })}>{t('departments.new')}</Button>
        </div>
      </div>
      {list.error ? (
        <Notice tone="danger" live="assertive" action={<Button size="sm" icon="refresh" onClick={() => void list.reload()}>{t('common.retry')}</Button>}>
          {describeError(i18n, list.error)}
        </Notice>
      ) : (
        <Table
          caption={t('admin.departments')} columns={columns} rows={list.data ? rows : null} rowKey={(d) => d.id} loading={list.loading}
          rowClassName={(d) => (isArchived(d) ? 'is-muted' : undefined)}
          empty={<EmptyState icon="layers" title={t('departments.empty')} body={t('departments.emptyBody')}
            action={<Button icon="plus" onClick={() => setDrawer({ department: null })}>{t('departments.new')}</Button>} />}
        />
      )}
      {drawer && <DepartmentDrawer department={drawer.department} onClose={() => setDrawer(null)} onSaved={afterChange} />}
      <ConfirmDialog
        open={archiving !== null} onClose={() => setArchiving(null)} tone={archiving && isArchived(archiving) ? 'primary' : 'danger'}
        title={archiving && isArchived(archiving) ? t('departments.restore.title') : t('departments.archive.title')}
        body={archiving ? t(isArchived(archiving) ? 'departments.restore.body' : 'departments.archive.body', { name: archiving.name }) : ''}
        confirmLabel={archiving && isArchived(archiving) ? t('departments.action.restore') : t('departments.action.archive')}
        onConfirm={async () => {
          if (!archiving) return;
          const restore = isArchived(archiving);
          await updateDepartment(archiving.id, { archived: !restore });
          toast.success(t(restore ? 'departments.restore.done' : 'departments.archive.done', { name: archiving.name }));
          afterChange();
        }}
      />
      <ConfirmDialog
        open={deleting !== null} onClose={() => setDeleting(null)}
        title={t('departments.delete.title')}
        body={deleting ? t('departments.delete.body', { name: deleting.name }) : ''}
        confirmLabel={t('departments.action.delete')}
        onConfirm={async () => {
          if (!deleting) return;
          await deleteDepartment(deleting.id);
          toast.success(t('departments.delete.done', { name: deleting.name }));
          afterChange();
        }}
      />
    </>
  );
}
