/* Approvals (/approvals, /approvals/:approvalId): requests waiting for this person's decision,
   the requests they made, and — for admins — every request.

   The inbox opens on what is pending; "my requests" opens on everything, so a decision made
   while away is visible. Members decide nothing (spec §6), so they get their own requests
   only, instead of an inbox that could never fill. The drawer follows the URL, so a
   notification lands on the request itself. Every decision or cancel refreshes the list and
   the sidebar's pending badge. */
import React, { useEffect, useMemo, useState } from 'react';
import { listApprovals } from '../../api/approvals';
import type { Approval, ApprovalBox, ApprovalStatus } from '../../api/types';
import { describeError } from '../../app/errors';
import { useAsync } from '../../app/hooks';
import { useUser } from '../../app/session';
import { useWorkspace } from '../../app/workspace';
import { useI18n } from '../../i18n';
import { navigate, useDocumentTitle } from '../../router';
import { Avatar, Badge, Button, CountBadge, EmptyState, Notice, PageHeader, Select, Table, Tabs, type Column } from '../../ui';
import { approvalKindLabel, APPROVAL_STATUS, APPROVAL_STATUSES } from '../shared/labels';
import { optionalRouteId } from '../shared/routeId';
import type { PageProps } from '../types';
import { ApprovalDrawer } from './ApprovalDrawer';
import '../../features.css';

const DEFAULT_STATUS: Record<ApprovalBox, '' | ApprovalStatus> = { inbox: 'pending', mine: '', all: '' };

export function ApprovalsPage({ params }: PageProps) {
  const i18n = useI18n();
  const { t, tn, fmt } = i18n;
  useDocumentTitle(t('nav.approvals'));
  const role = useUser().role;
  const isAdmin = role === 'admin';
  const decides = role !== 'member';
  const { departments, pendingApprovals, refreshPendingApprovals } = useWorkspace();
  const [box, setBox] = useState<ApprovalBox>(decides ? 'inbox' : 'mine');
  const [status, setStatus] = useState<'' | ApprovalStatus>(DEFAULT_STATUS[decides ? 'inbox' : 'mine']);
  const [openId, setOpenId] = useState<number | null>(() => optionalRouteId(params.approvalId));
  const approvals = useAsync(() => listApprovals(box, status || undefined), [box, status]);

  useEffect(() => { setOpenId(optionalRouteId(params.approvalId)); }, [params.approvalId]);

  // The server names the department; the sidebar's list is the fallback for an older reply.
  const deptName = useMemo(() => {
    const names = new Map(departments.map((d) => [d.id, d.name]));
    return (approval: Pick<Approval, 'department_id' | 'department_name'>) => {
      if (approval.department_id === null) return t('approvals.companyWide');
      return approval.department_name || names.get(approval.department_id) || `#${approval.department_id}`;
    };
  }, [departments, t]);

  const changeBox = (next: ApprovalBox) => {
    setBox(next);
    setStatus(DEFAULT_STATUS[next]);
  };

  const open = (approval: Approval) => {
    setOpenId(approval.id);
    navigate(`/approvals/${approval.id}`, { quiet: true });
  };
  const close = () => {
    setOpenId(null);
    if (params.approvalId !== undefined) navigate('/approvals', { quiet: true });
  };

  const columns: Column<Approval>[] = [
    {
      key: 'request', header: t('approvals.col.request'),
      render: (a) => (
        <span className="ws-cell-stack">
          <span className="ws-muted ws-small">{approvalKindLabel(i18n, a.kind)}</span>
          <button type="button" className="ws-linklike ws-strong" onClick={() => open(a)}>{a.summary}</button>
        </span>
      ),
    },
    {
      key: 'requester', header: t('approvals.col.requester'), secondary: true,
      render: (a) => <span className="ws-person"><Avatar name={a.requester?.name ?? '?'} size={24} /><span>{a.requester?.name}</span></span>,
    },
    { key: 'department', header: t('approvals.col.department'), secondary: true, render: (a) => deptName(a) },
    {
      key: 'created', header: t('approvals.col.created'),
      render: (a) => <time dateTime={new Date(a.created_at * 1000).toISOString()} title={fmt.dateTime(a.created_at)}>{fmt.relative(a.created_at)}</time>,
    },
    {
      key: 'status', header: t('approvals.col.status'),
      render: (a) => (
        <span className="ws-cell-stack">
          <Badge tone={APPROVAL_STATUS[a.status].tone} dot>{t(APPROVAL_STATUS[a.status].label)}</Badge>
          {a.status === 'pending' && <span className="ws-muted ws-small">{t('approvals.expiresIn', { when: fmt.relative(a.expires_at) })}</span>}
        </span>
      ),
    },
  ];

  const tabs = [
    ...(decides ? [{ value: 'inbox' as const, label: t('approvals.tab.inbox'), badge: <CountBadge count={pendingApprovals} label={tn('shell.pendingApprovals', pendingApprovals)} /> }] : []),
    { value: 'mine' as const, label: t('approvals.tab.mine') },
    ...(isAdmin ? [{ value: 'all' as const, label: t('approvals.tab.all') }] : []),
  ];

  const emptyTitle = status && status !== DEFAULT_STATUS[box] ? t('approvals.empty.filtered') : t(`approvals.empty.${box}`);
  const content = (
    <div className="ws-stack ws-stack--loose">
      <div className="ws-toolbar">
        <Select
          className="ws-toolbar__filter" label={t('approvals.filter.status')} value={status}
          onChange={(e) => setStatus(e.target.value as '' | ApprovalStatus)}
          options={[{ value: '', label: t('approvals.filter.all') }, ...APPROVAL_STATUSES.map((s) => ({ value: s, label: t(APPROVAL_STATUS[s].label) }))]}
        />
        <div className="ws-toolbar__end">
          <Button icon="refresh" onClick={() => { void approvals.reload(); void refreshPendingApprovals(); }}>{t('common.refresh')}</Button>
        </div>
      </div>
      {approvals.error ? (
        <Notice tone="danger" live="assertive" action={<Button size="sm" icon="refresh" onClick={() => void approvals.reload()}>{t('common.retry')}</Button>}>
          {describeError(i18n, approvals.error)}
        </Notice>
      ) : (
        <Table
          caption={tabs.find((tab) => tab.value === box)?.label ?? t('nav.approvals')} columns={columns}
          rows={approvals.data?.items ?? null} rowKey={(a) => a.id} loading={approvals.loading}
          empty={<EmptyState icon="approvals" title={emptyTitle} body={status && status !== DEFAULT_STATUS[box] ? undefined : t(`approvals.empty.${box}.body`)} />}
        />
      )}
    </div>
  );
  return (
    <>
      <PageHeader title={t('nav.approvals')} description={t(decides ? 'approvals.description' : 'approvals.descriptionMember')} />
      {tabs.length > 1
        ? <Tabs<ApprovalBox> label={t('approvals.tabs')} items={tabs} value={box} onChange={changeBox}>{content}</Tabs>
        : content}
      <ApprovalDrawer
        id={openId} departmentName={deptName} onClose={close}
        onChanged={() => { void approvals.reload(); void refreshPendingApprovals(); }}
      />
    </>
  );
}
