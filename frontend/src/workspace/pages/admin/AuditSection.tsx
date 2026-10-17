/* Admin → Audit: the tamper-evident trail of who did what.

   Filters apply on demand (not per keystroke). Paging walks backwards with the server's
   `before_id` cursor; the cursors already visited are kept so "newer" returns exactly to the
   previous page. The CSV export is a plain link with the same filters (the browser downloads
   it with the session cookie), and "verify chain" recomputes every HMAC link on the server. */
import React, { useMemo, useState } from 'react';
import { auditExportUrl, listAdminDepartments, listAudit, listUsers, verifyAudit } from '../../api/admin';
import type { AuditEntry, AuditFilters, AuditVerifyResult } from '../../api/types';
import { describeError } from '../../app/errors';
import { useAsync } from '../../app/hooks';
import { AUDIT_ACTIONS } from '../../app/labels';
import { useI18n } from '../../i18n';
import { Button, Card, EmptyState, Icon, Notice, Select, Table, TextField, type Column } from '../../ui';

const PAGE_SIZE = 50;

interface Draft { actor: string; action: string; since: string; until: string }
const EMPTY: Draft = { actor: '', action: '', since: '', until: '' };

/** Local calendar days → epoch seconds: `since` from 00:00, `until` through 23:59:59. */
export function draftToFilters(draft: Draft): AuditFilters {
  const day = (value: string, end: boolean) => {
    if (!value) return undefined;
    const ms = new Date(`${value}T${end ? '23:59:59.999' : '00:00:00'}`).getTime();
    return Number.isNaN(ms) ? undefined : ms / 1000;
  };
  return {
    actor_id: draft.actor ? Number(draft.actor) : undefined,
    action: draft.action || undefined,
    since: day(draft.since, false),
    until: day(draft.until, true),
  };
}

function compactDetails(details: Record<string, unknown> | undefined): string {
  if (!details || Object.keys(details).length === 0) return '';
  return Object.entries(details).map(([key, value]) => `${key}=${typeof value === 'string' ? value : JSON.stringify(value)}`).join(' · ');
}

function VerifyResult({ result }: { result: AuditVerifyResult }) {
  const { t, fmt } = useI18n();
  if (result.key_mismatch) return <Notice tone="warning" live="polite" title={t('audit.verify.keyMismatch')}>{t('audit.verify.keyMismatchBody')}</Notice>;
  if (!result.ok) {
    return (
      <Notice tone="danger" live="assertive" title={t('audit.verify.broken', { id: result.broken_at ?? '?' })}>
        {t('audit.verify.brokenBody', { count: fmt.number(result.checked) })}
      </Notice>
    );
  }
  return <Notice tone="success" live="polite" title={t('audit.verify.ok')}>{t('audit.verify.okBody', { count: fmt.number(result.checked) })}</Notice>;
}

export function AuditSection() {
  const i18n = useI18n();
  const { t, has, fmt } = i18n;
  const users = useAsync(listUsers, []);
  const departments = useAsync(listAdminDepartments, []);
  const [draft, setDraft] = useState<Draft>(EMPTY);
  const [applied, setApplied] = useState<AuditFilters>({});
  const [cursors, setCursors] = useState<(number | undefined)[]>([undefined]);
  const [rangeError, setRangeError] = useState<string | null>(null);
  const [verifying, setVerifying] = useState(false);
  const [verify, setVerify] = useState<AuditVerifyResult | null>(null);
  const [verifyError, setVerifyError] = useState<string | null>(null);
  const cursor = cursors[cursors.length - 1];
  const page = useAsync(() => listAudit({ ...applied, limit: PAGE_SIZE, before_id: cursor }), [applied, cursor]);

  const deptName = useMemo(() => new Map((departments.data ?? []).map((d) => [d.id, d.name])), [departments.data]);

  const actionLabel = (action: string): string => {
    const key = `audit.action.${action}`;
    return has(key) ? t(key) : action;
  };

  const apply = (event: React.FormEvent) => {
    event.preventDefault();
    const filters = draftToFilters(draft);
    if (filters.since !== undefined && filters.until !== undefined && filters.since > filters.until) {
      setRangeError(t('audit.error.range'));
      return;
    }
    setRangeError(null);
    setApplied(filters);
    setCursors([undefined]);
  };

  const reset = () => { setDraft(EMPTY); setApplied({}); setCursors([undefined]); setRangeError(null); };

  const runVerify = async () => {
    setVerifying(true);
    setVerify(null);
    setVerifyError(null);
    try {
      setVerify(await verifyAudit());
    } catch (err) {
      setVerifyError(describeError(i18n, err));
    } finally {
      setVerifying(false);
    }
  };

  const actorCell = (entry: AuditEntry) => {
    if (entry.actor_email === 'cli') return <span>{t('audit.actor.cli')}</span>;
    if (entry.actor_name && entry.actor_email) {
      return (
        <span className="ws-cell-stack">
          <span className="ws-nowrap">{entry.actor_name}</span>
          <span className="ws-muted ws-small ws-nowrap">{entry.actor_email}</span>
        </span>
      );
    }
    return <span className="ws-nowrap">{entry.actor_email || (entry.actor_user_id === null ? t('audit.actor.system') : `#${entry.actor_user_id}`)}</span>;
  };

  const columns: Column<AuditEntry>[] = [
    { key: 'ts', header: t('audit.col.time'), render: (e) => <time className="ws-mono ws-small ws-nowrap" dateTime={new Date(e.ts * 1000).toISOString()}>{fmt.dateTime(e.ts)}</time> },
    { key: 'actor', header: t('audit.col.actor'), render: actorCell },
    {
      key: 'action', header: t('audit.col.action'),
      render: (e) => (
        <span className="ws-cell-stack">
          <span>{actionLabel(e.action)}</span>
          <span className="ws-mono ws-small ws-muted">{e.action}</span>
        </span>
      ),
    },
    {
      key: 'target', header: t('audit.col.target'), secondary: true,
      render: (e) => (e.target_type ? <span className="ws-mono ws-small">{e.target_type}{e.target_id ? ` #${e.target_id}` : ''}</span> : <span className="ws-muted">—</span>),
    },
    { key: 'department', header: t('audit.col.department'), secondary: true, render: (e) => (e.department_id ? deptName.get(e.department_id) ?? `#${e.department_id}` : <span className="ws-muted">—</span>) },
    { key: 'ip', header: t('audit.col.ip'), secondary: true, render: (e) => <span className="ws-mono ws-small">{e.ip || '—'}</span> },
    {
      key: 'details', header: t('audit.col.details'), secondary: true,
      render: (e) => {
        const text = compactDetails(e.details);
        return text ? <span className="ws-mono ws-small ws-clamp" title={text}>{text}</span> : <span className="ws-muted">—</span>;
      },
    },
  ];

  const actorOptions = [{ value: '', label: t('audit.filter.anyone') },
    ...(users.data ?? []).map((u) => ({ value: String(u.id), label: `${u.name} (${u.email})` }))];
  const actionOptions = [{ value: '', label: t('audit.filter.anyAction') },
    ...AUDIT_ACTIONS.map((a) => ({ value: a, label: actionLabel(a) }))];
  const nextCursor = page.data?.next_before_id ?? null;
  const filtered = Object.values(applied).some((v) => v !== undefined);

  return (
    <div className="ws-stack ws-stack--loose">
      <Card title={t('audit.filters')} as="div">
        <form className="ws-filters" onSubmit={apply} noValidate>
          <Select label={t('audit.col.actor')} value={draft.actor} onChange={(e) => setDraft({ ...draft, actor: e.target.value })} options={actorOptions} />
          <Select label={t('audit.col.action')} value={draft.action} onChange={(e) => setDraft({ ...draft, action: e.target.value })} options={actionOptions} />
          <TextField label={t('audit.since')} type="date" value={draft.since} onChange={(e) => setDraft({ ...draft, since: e.target.value })} error={rangeError} />
          <TextField label={t('audit.until')} type="date" value={draft.until} onChange={(e) => setDraft({ ...draft, until: e.target.value })} />
          <div className="ws-filters__actions">
            <Button type="submit" variant="primary" icon="filter">{t('audit.apply')}</Button>
            <Button onClick={reset} disabled={!filtered && draft === EMPTY}>{t('audit.reset')}</Button>
          </div>
        </form>
      </Card>
      <div className="ws-toolbar">
        <p className="ws-muted ws-small">{t('audit.hint')}</p>
        <div className="ws-toolbar__end">
          <a className="ws-btn ws-btn--secondary ws-btn--md" href={auditExportUrl(applied)} download>
            <span className="ws-btn__content"><Icon name="download" /><span className="ws-btn__label">{t('audit.export')}</span></span>
          </a>
          <Button icon="shield" onClick={runVerify} busy={verifying}>{t('audit.verify')}</Button>
        </div>
      </div>
      {verify && <VerifyResult result={verify} />}
      {verifyError && <Notice tone="danger" live="assertive">{verifyError}</Notice>}
      {page.error ? (
        <Notice tone="danger" live="assertive" action={<Button size="sm" icon="refresh" onClick={() => void page.reload()}>{t('common.retry')}</Button>}>
          {describeError(i18n, page.error)}
        </Notice>
      ) : (
        <Table
          caption={t('admin.audit')} columns={columns} rows={page.data?.items ?? null} rowKey={(e) => e.id} loading={page.loading}
          empty={<EmptyState icon="audit" title={filtered ? t('audit.emptyFiltered') : t('audit.empty')} />}
          footer={(
            <nav className="ws-pager" aria-label={t('audit.pager')}>
              <Button size="sm" icon="chevronLeft" disabled={cursors.length <= 1 || page.loading} onClick={() => setCursors(cursors.slice(0, -1))}>{t('audit.newer')}</Button>
              <span className="ws-muted ws-small">{t('audit.page', { page: cursors.length })}</span>
              <Button size="sm" iconAfter="chevronRight" disabled={nextCursor === null || page.loading} onClick={() => nextCursor !== null && setCursors([...cursors, nextCursor])}>{t('audit.older')}</Button>
            </nav>
          )}
        />
      )}
    </div>
  );
}

