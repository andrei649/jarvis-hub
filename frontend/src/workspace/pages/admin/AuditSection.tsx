/* Admin → Audit: the tamper-evident trail of who did what.

   The table reads as sentences: when, who, what was done to which object, in which department.
   Everything else an entry carries — the IP address, the recorded details with their field
   names and coded values translated, and the technical action code for support — opens in a drawer per entry,
   reachable by keyboard and touch (nothing lives only in a hover tooltip). A preference-only
   change (theme, language) is named as such rather than as "user changed".

   Filters apply on demand (not per keystroke). Paging walks backwards with the server's
   `before_id` cursor; the cursors already visited are kept so "newer" returns exactly to the
   previous page. The CSV export is a plain link with the same filters (the browser downloads
   it with the session cookie), and "verify chain" recomputes every HMAC link on the server;
   its result is also written into an always-present status region. */
import React, { useMemo, useState } from 'react';
import { auditExportUrl, listAdminDepartments, listAudit, listUsers, verifyAudit } from '../../api/admin';
import type { AuditEntry, AuditFilters, AuditVerifyResult } from '../../api/types';
import { describeCode, describeError } from '../../app/errors';
import { useAsync } from '../../app/hooks';
import { AUDIT_ACTIONS, ROLE_LABEL, STATUS_LABEL } from '../../app/labels';
import { useI18n, type I18n } from '../../i18n';
import { Button, Card, Drawer, EmptyState, Icon, Notice, Select, Table, TextField, type Column } from '../../ui';
import { approvalKindLabel } from '../shared/labels';

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

const PREFERENCE_FIELDS = new Set(['locale', 'theme']);

/** "Preferences changed" for a person's own theme/language change, else the action's label. */
export function auditActionLabel(i18n: I18n, entry: Pick<AuditEntry, 'action' | 'details'>): string {
  const details = entry.details ?? {};
  const fields = Array.isArray(details.fields) ? (details.fields as unknown[]) : null;
  if (entry.action === 'user.updated' && details.self === true && fields && fields.length > 0
      && fields.every((f) => typeof f === 'string' && PREFERENCE_FIELDS.has(f))) {
    return i18n.t('audit.action.user.preferences');
  }
  const key = `audit.action.${entry.action}`;
  return i18n.has(key) ? i18n.t(key) : entry.action;
}

/** The object of an entry in words ("Rularea de raport #1", "Ana Popescu", "Organizația"); empty
    when there is nothing to add (no object, an object with no id, a person acting on themselves). */
export function auditTargetText(i18n: I18n, entry: Pick<AuditEntry, 'target_type' | 'target_id' | 'actor_user_id'>, names: { user: Map<number, string>; department: Map<number, string> }): string {
  const { target_type: type, target_id: id } = entry;
  if (!type) return '';
  const numeric = Number(id);
  if (type === 'user' && (!id || numeric === entry.actor_user_id)) return '';
  if (type === 'user' && names.user.has(numeric)) return names.user.get(numeric) ?? '';
  if (type === 'department' && names.department.has(numeric)) return names.department.get(numeric) ?? '';
  const key = `audit.target.${type}`;
  if (!i18n.has(key)) return id ? `${type} #${id}` : type;
  const template = i18n.t(key);
  if (template.includes('{id}') && !id) return '';
  return i18n.t(key, { id });
}

/** `t(key)` when the dictionary has it, else *fallback*. */
function known(i18n: I18n, key: string, fallback: string): string {
  return i18n.has(key) ? i18n.t(key) : fallback;
}

/** A role, account status or model policy in words (the values a `from` / `to` change records). */
function changeValue(i18n: I18n, text: string): string {
  if (text in ROLE_LABEL) return i18n.t(ROLE_LABEL[text as keyof typeof ROLE_LABEL]);
  if (text in STATUS_LABEL) return i18n.t(STATUS_LABEL[text as keyof typeof STATUS_LABEL]);
  return known(i18n, `org.policy.${text}`, text);
}

/** One recorded detail as a readable value: dates, sizes and durations formatted, known codes
    named — a code the server records (`via: password`, `reason: wrong_password`, `scope: ip`…)
    reads as words through `audit.value.<key>[<code>]`, never raw (review UX-13). */
export function detailValue(i18n: I18n, key: string, value: unknown): string {
  const { t, fmt, has } = i18n;
  if (value === null || value === undefined || value === '') return '—';
  if (typeof value === 'boolean') return t(value ? 'common.yes' : 'common.no');
  const coded = typeof value === 'string' || typeof value === 'number' ? `audit.value.${key}[${value}]` : '';
  if (coded && has(coded)) return t(coded);
  if (typeof value === 'number') {
    if (key.endsWith('_at')) return fmt.dateTime(value);
    if (key === 'latency_ms') return fmt.durationMs(value);
    if (key === 'size_bytes') return fmt.bytes(value);
    return fmt.number(value);
  }
  if (Array.isArray(value)) {
    return value.map((item) => (typeof item !== 'string' ? JSON.stringify(item) : key === 'fields' ? known(i18n, `field.${item}`, item) : item)).join(', ') || '—';
  }
  if (typeof value === 'object') {
    // The email's source: {type: 'message' | 'report_run', id}.
    const source = value as { type?: unknown; id?: unknown };
    const sourceKey = typeof source.type === 'string' ? `audit.target.${source.type}` : '';
    if (sourceKey && has(sourceKey)) return t(sourceKey, { id: String(source.id ?? '') });
    return JSON.stringify(value);
  }
  const text = String(value);
  if (key === 'kind') return approvalKindLabel(i18n, text);
  if (key === 'from' || key === 'to') return changeValue(i18n, text);
  if (key === 'trigger') return known(i18n, `run.trigger.${text}`, text);
  if (key === 'schedule_kind') return known(i18n, `schedule.${text}`, text);
  if (key === 'security') return known(i18n, `smtp.security.${text}`, text);
  if (key === 'role' || key === 'from_role') return text in ROLE_LABEL ? t(ROLE_LABEL[text as keyof typeof ROLE_LABEL]) : text;
  if (key.endsWith('status') && text in STATUS_LABEL) return t(STATUS_LABEL[text as keyof typeof STATUS_LABEL]);
  if (key === 'locale') return known(i18n, `language.${text}`, text);
  if (key === 'locality') return known(i18n, `locality.${text}`, text);
  if (key === 'model_policy') return known(i18n, `org.policy.${text}`, text);
  if ((key === 'error_code' || key === 'error') && has(`error.${text}`)) return describeCode(i18n, text);
  return text;
}

/** A detail's name in words. `from` / `to` record a change (a role, a status, the model policy)
    when both are present — „Înainte" / „După"; a lone `to` is a list of recipients. */
export function detailLabel(i18n: I18n, key: string, details: Record<string, unknown>): string {
  if (key === 'to' && 'from' in details) return i18n.t('audit.detail.changedTo');
  return known(i18n, `audit.detail.${key}`, key);
}

/** Rows signed by a lost key before a re-key (`audit-rekey`): pinned, but no longer checkable. */
function unverifiedText(i18n: I18n, result: AuditVerifyResult): string {
  const count = result.unverified ?? 0;
  if (count <= 0) return '';
  return i18n.tn('audit.verify.unverified', count, { id: String(result.rekeyed_at ?? '?') });
}

function VerifyResult({ result }: { result: AuditVerifyResult }) {
  const i18n = useI18n();
  const { t, tn } = i18n;
  if (result.key_mismatch) return <Notice tone="warning" title={t('audit.verify.keyMismatch')}>{t('audit.verify.keyMismatchBody')}</Notice>;
  if (!result.ok) {
    return (
      <Notice tone="danger" title={t('audit.verify.broken', { id: result.broken_at ?? '?' })}>
        {tn('audit.verify.brokenBody', result.checked)}
      </Notice>
    );
  }
  const unverified = unverifiedText(i18n, result);
  return (
    <Notice tone="success" title={t('audit.verify.ok')}>
      <p>{tn('audit.verify.okBody', result.checked)}</p>
      {unverified && <p>{unverified}</p>}
    </Notice>
  );
}

function verifyText(i18n: I18n, result: AuditVerifyResult): string {
  const { t, tn } = i18n;
  if (result.key_mismatch) return `${t('audit.verify.keyMismatch')}. ${t('audit.verify.keyMismatchBody')}`;
  if (!result.ok) return `${t('audit.verify.broken', { id: result.broken_at ?? '?' })}. ${tn('audit.verify.brokenBody', result.checked)}`;
  return [`${t('audit.verify.ok')}.`, tn('audit.verify.okBody', result.checked), unverifiedText(i18n, result)].filter(Boolean).join(' ');
}

/** Everything one entry recorded, with translated field names; the action code is for support. */
function EntryDrawer({ entry, actor, target, department, onClose }: {
  entry: AuditEntry | null; actor: React.ReactNode; target: string; department: string; onClose: () => void;
}) {
  const i18n = useI18n();
  const { t, fmt } = i18n;
  const details = Object.entries(entry?.details ?? {});
  return (
    <Drawer open={entry !== null} onClose={onClose} title={entry ? t('audit.entry.title', { id: String(entry.id) }) : ''}>
      {entry && (
        <dl className="ws-dl">
          <dt>{t('audit.col.time')}</dt><dd><time dateTime={new Date(entry.ts * 1000).toISOString()}>{fmt.dateTime(entry.ts)}</time></dd>
          <dt>{t('audit.col.actor')}</dt><dd>{actor}</dd>
          <dt>{t('audit.col.action')}</dt><dd>{auditActionLabel(i18n, entry)}</dd>
          {target && <><dt>{t('audit.col.target')}</dt><dd>{target}</dd></>}
          {department && <><dt>{t('audit.col.department')}</dt><dd>{department}</dd></>}
          <dt>{t('audit.col.ip')}</dt><dd className="ws-mono">{entry.ip || '—'}</dd>
          {details.map(([key, value]) => (
            <React.Fragment key={key}>
              <dt>{detailLabel(i18n, key, entry?.details ?? {})}</dt>
              <dd className="ws-prewrap">{detailValue(i18n, key, value)}</dd>
            </React.Fragment>
          ))}
          <dt>{t('audit.entry.code')}</dt><dd className="ws-mono ws-small">{entry.action}</dd>
        </dl>
      )}
    </Drawer>
  );
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
  const [announcement, setAnnouncement] = useState('');
  const [openEntry, setOpenEntry] = useState<AuditEntry | null>(null);
  const cursor = cursors[cursors.length - 1];
  const page = useAsync(() => listAudit({ ...applied, limit: PAGE_SIZE, before_id: cursor }), [applied, cursor]);

  const deptName = useMemo(() => new Map((departments.data ?? []).map((d) => [d.id, d.name])), [departments.data]);
  const userName = useMemo(() => new Map((users.data ?? []).map((u) => [u.id, u.name])), [users.data]);
  const names = useMemo(() => ({ user: userName, department: deptName }), [userName, deptName]);

  const actionLabel = (action: string): string => {
    const key = `audit.action.${action}`;
    return has(key) ? t(key) : action;
  };
  const departmentText = (entry: AuditEntry) => (entry.department_id ? deptName.get(entry.department_id) ?? `#${entry.department_id}` : '');

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
    setAnnouncement('');
    try {
      const result = await verifyAudit();
      setVerify(result);
      setAnnouncement(verifyText(i18n, result));
    } catch (err) {
      const message = describeError(i18n, err);
      setVerifyError(message);
      setAnnouncement(message);
    } finally {
      setVerifying(false);
    }
  };

  const actorCell = (entry: AuditEntry) => {
    if (entry.actor_email === 'cli') return <span>{t('audit.actor.cli')}</span>;
    if (entry.actor_email === 'scheduler' && entry.actor_user_id === null) return <span>{t('audit.actor.scheduler')}</span>;
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
    { key: 'ts', header: t('audit.col.time'), nowrap: true, render: (e) => <time className="ws-mono ws-small ws-nowrap" dateTime={new Date(e.ts * 1000).toISOString()}>{fmt.dateTime(e.ts)}</time> },
    { key: 'actor', header: t('audit.col.actor'), render: actorCell },
    {
      key: 'action', header: t('audit.col.action'),
      render: (e) => {
        const target = auditTargetText(i18n, e, names);
        return (
          <span className="ws-cell-stack">
            <span>{auditActionLabel(i18n, e)}</span>
            {target && <span className="ws-small ws-muted">{target}</span>}
          </span>
        );
      },
    },
    { key: 'department', header: t('audit.col.department'), secondary: true, render: (e) => departmentText(e) || <span className="ws-muted">—</span> },
    {
      key: 'actions', header: '', srHeader: t('audit.col.details'), align: 'end',
      render: (e) => (
        <Button size="sm" variant="ghost" onClick={() => setOpenEntry(e)} aria-label={t('audit.entry.open', { action: auditActionLabel(i18n, e), date: fmt.dateTime(e.ts) })}>
          {t('audit.col.details')}
        </Button>
      ),
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
      <p className="ws-sr-only" role="status" aria-live="polite">{announcement}</p>
      {verify && <VerifyResult result={verify} />}
      {verifyError && <Notice tone="danger">{verifyError}</Notice>}
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
      <EntryDrawer
        entry={openEntry} actor={openEntry ? actorCell(openEntry) : null}
        target={openEntry ? auditTargetText(i18n, openEntry, names) : ''}
        department={openEntry ? departmentText(openEntry) : ''} onClose={() => setOpenEntry(null)}
      />
    </div>
  );
}

