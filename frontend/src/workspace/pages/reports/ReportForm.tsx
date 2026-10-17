/* Create or edit a report: what it should contain (with worked examples), which documents it
   reads, when it runs, and who receives it by email.

   The document picker lists only documents the report may read — ready ones of the report's
   department plus the company-wide ones (spec §9); in an edited report, a document that has
   since been deleted or failed is named and dropped, since the server refuses ids it cannot
   use. Email delivery is explained up front: it needs a department approver's yes and a
   configured mail server, and changing the recipients asks for a new approval. */
import React, { useEffect, useMemo, useRef, useState } from 'react';
import { listDocuments } from '../../api/documents';
import { createReport, updateReport } from '../../api/reports';
import type { Report, ReportRequest, ScheduleKind, WorkspaceDocument } from '../../api/types';
import { describeError, errorCode, errorField } from '../../app/errors';
import { useAsync } from '../../app/hooks';
import { useWorkspace } from '../../app/workspace';
import { useI18n, type MessageKey } from '../../i18n';
import { Button, Checkbox, Drawer, focusFirstInvalid, LoadingBlock, Notice, RadioCards, Select, TextArea, TextField, useToast } from '../../ui';
import { SCHEDULE_KINDS } from '../shared/labels';
import { MAX_RECIPIENTS, parseRecipients } from '../shared/recipients';
import { useApprovalReadiness } from '../shared/useApprovalReadiness';
import { DEFAULT_TIME, DEFAULT_TIMEZONE, TIME_PATTERN, timezoneOptions, WEEKDAYS, weekdayOption } from './schedule';

const NAME_MAX = 200;
const INSTRUCTIONS_MAX = 4000;
const EXAMPLES: MessageKey[] = ['reports.example.1', 'reports.example.2', 'reports.example.3'];

type FormErrors = Partial<Record<'name' | 'instructions' | 'documents' | 'time' | 'timezone' | 'delivery', string>>;

function inScope(doc: WorkspaceDocument, departmentId: number): boolean {
  return doc.status === 'ready' && (doc.visibility === 'company' || doc.department_id === departmentId);
}

function sameRecipients(a: string[], b: string[]): boolean {
  const norm = (list: string[]) => list.map((e) => e.toLowerCase()).sort().join(',');
  return norm(a) === norm(b);
}

export interface ReportFormProps {
  /** The report being edited; null creates one in *defaultDepartmentId*. */
  report: Report | null;
  defaultDepartmentId: number;
  onClose: () => void;
  onSaved: (report: Report, created: boolean) => void;
}

export function ReportForm({ report, defaultDepartmentId, onClose, onSaved }: ReportFormProps) {
  const i18n = useI18n();
  const { t, tn } = i18n;
  const toast = useToast();
  const { departments } = useWorkspace();
  const [departmentId, setDepartmentId] = useState(report?.department_id ?? defaultDepartmentId);
  const [name, setName] = useState(report?.name ?? '');
  const [instructions, setInstructions] = useState(report?.instructions ?? '');
  const [documentIds, setDocumentIds] = useState<number[]>(report?.document_ids ?? []);
  const [docSearch, setDocSearch] = useState('');
  const [kind, setKind] = useState<ScheduleKind>(report?.schedule_kind ?? 'manual');
  const [time, setTime] = useState(report?.schedule_time || DEFAULT_TIME);
  const [weekday, setWeekday] = useState(report?.schedule_weekday ?? 0);
  const [timezone, setTimezone] = useState(report?.timezone || DEFAULT_TIMEZONE);
  const [emails, setEmails] = useState((report?.delivery_emails ?? []).join(', '));
  const [errors, setErrors] = useState<FormErrors>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const formRef = useRef<HTMLFormElement>(null);
  const zones = useMemo(() => timezoneOptions(timezone), [timezone]);
  const documents = useAsync(() => listDocuments({ status: 'ready' }), []);
  const delivery = useApprovalReadiness('report.delivery', departmentId);

  const available = useMemo(() => (documents.data ?? []).filter((d) => inScope(d, departmentId)), [documents.data, departmentId]);
  const availableIds = useMemo(() => new Set(available.map((d) => d.id)), [available]);
  const missing = documents.data ? documentIds.filter((id) => !availableIds.has(id)) : [];
  const shown = useMemo(() => {
    const needle = docSearch.trim().toLocaleLowerCase();
    return needle ? available.filter((d) => `${d.title} ${d.filename}`.toLocaleLowerCase().includes(needle)) : available;
  }, [available, docSearch]);
  const parsedEmails = parseRecipients(emails);
  const recipientsChanged = report !== null && !sameRecipients(parsedEmails.emails, report.delivery_emails ?? []);

  useEffect(() => { if (Object.keys(errors).length) focusFirstInvalid(formRef.current); }, [errors]);

  const toggleDocument = (id: number, on: boolean) => setDocumentIds((ids) => (on ? [...ids, id] : ids.filter((x) => x !== id)));

  const validate = (): FormErrors => {
    const found: FormErrors = {};
    if (!name.trim()) found.name = t('reports.form.error.name');
    if (!instructions.trim()) found.instructions = t('reports.form.error.instructions');
    else if (instructions.length > INSTRUCTIONS_MAX) found.instructions = t('common.tooLong', { max: INSTRUCTIONS_MAX });
    if (kind !== 'manual' && !TIME_PATTERN.test(time)) found.time = t('schedule.error.time');
    if (parsedEmails.invalid) found.delivery = t('emailRequest.error.invalid', { email: parsedEmails.invalid });
    else if (parsedEmails.emails.length > MAX_RECIPIENTS) found.delivery = t('emailRequest.error.tooMany', { max: MAX_RECIPIENTS });
    return found;
  };

  const body = (): ReportRequest => ({
    department_id: departmentId,
    name: name.trim(),
    instructions: instructions.trim(),
    document_ids: documentIds.filter((id) => availableIds.has(id)),
    schedule: kind === 'manual' ? { kind, timezone } : { kind, time, weekday: kind === 'weekly' ? weekday : null, timezone },
    delivery_emails: parsedEmails.emails,
  });

  const mapServerError = (err: unknown) => {
    const code = errorCode(err);
    const field = errorField(err) ?? '';
    const message = describeError(i18n, err);
    if (code === 'invalid_timezone' || field.includes('timezone')) setErrors({ timezone: message });
    else if (code === 'not_found' || field === 'document_ids') setErrors({ documents: t('reports.form.error.documents') });
    else if (['smtp_not_configured', 'no_eligible_approver', 'recipient_not_allowed'].includes(code ?? '') || field === 'delivery_emails') setErrors({ delivery: message });
    else if (field === 'name') setErrors({ name: message });
    else if (field === 'instructions') setErrors({ instructions: message });
    else if (field.startsWith('schedule')) setErrors({ time: message });
    else setFormError(message);
  };

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    const found = validate();
    setErrors(found);
    setFormError(null);
    if (Object.keys(found).length) return;
    setBusy(true);
    try {
      const payload = body();
      if (report) {
        const { department_id: _unchanged, ...changes } = payload;
        const saved = await updateReport(report.id, changes);
        toast.success(t('reports.form.saved'));
        onSaved({ ...report, ...saved }, false);
      } else {
        const saved = await createReport(payload);
        toast.success(t('reports.form.created', { name: payload.name }));
        onSaved(saved, true);
      }
      onClose();
    } catch (err) {
      mapServerError(err);
    } finally {
      setBusy(false);
    }
  };

  const deliveryUnavailable = delivery.smtpReady === false;
  return (
    <Drawer
      open onClose={onClose} busy={busy} size="lg"
      title={report ? t('reports.form.editTitle') : t('reports.form.createTitle')}
      footer={(
        <>
          <Button onClick={onClose} disabled={busy}>{t('common.cancel')}</Button>
          <Button variant="primary" type="submit" form="ws-report-form" busy={busy}>{report ? t('common.save') : t('reports.form.submitCreate')}</Button>
        </>
      )}
    >
      <p className="ws-muted">{t('reports.form.desc')}</p>
      {formError && <Notice tone="danger" live="assertive">{formError}</Notice>}
      <form id="ws-report-form" ref={formRef} className="ws-form" onSubmit={submit} noValidate>
        {!report && (
          <Select
            label={t('shell.department')} value={String(departmentId)}
            onChange={(e) => { setDepartmentId(Number(e.target.value)); setDocumentIds([]); }}
            options={departments.map((d) => ({ value: String(d.id), label: d.name }))}
          />
        )}
        <TextField label={t('field.name')} value={name} maxLength={NAME_MAX} error={errors.name} onChange={(e) => setName(e.target.value)} required data-autofocus="true" />
        <TextArea
          label={t('reports.form.instructions')} hint={t('reports.form.instructionsHint')} value={instructions} rows={6}
          error={errors.instructions} onChange={(e) => setInstructions(e.target.value)}
          aside={t('common.charCount', { count: instructions.length, max: INSTRUCTIONS_MAX })}
        />
        <details className="ws-details ws-examples">
          <summary>{t('reports.form.examples')}</summary>
          <ul className="ws-examples__list">
            {EXAMPLES.map((key) => (
              <li key={key} className="ws-example">
                <p>{t(key)}</p>
                <Button size="sm" variant="ghost" onClick={() => setInstructions(t(key))}>{t('reports.form.useExample')}</Button>
              </li>
            ))}
          </ul>
        </details>

        <fieldset className={['ws-fieldset', 'ws-picker', errors.documents && 'has-error'].filter(Boolean).join(' ')} aria-describedby="ws-picker-hint">
          <legend className="ws-field__label">{t('reports.form.documents')}</legend>
          <p className="ws-field__hint" id="ws-picker-hint">{t('reports.form.documentsHint')}</p>
          {documents.loading && !documents.data && <LoadingBlock label={t('common.loading')} lines={2} />}
          {documents.error ? <Notice tone="danger">{describeError(i18n, documents.error)}</Notice> : null}
          {documents.data && available.length === 0 && <p className="ws-muted">{t('reports.form.documentsNone')}</p>}
          {available.length > 0 && (
            <>
              <div className="ws-picker__bar">
                <TextField label={t('reports.form.documentsSearch')} type="search" value={docSearch} onChange={(e) => setDocSearch(e.target.value)} />
                <span className="ws-muted ws-small" aria-live="polite">{tn('reports.form.documentsSelected', documentIds.filter((id) => availableIds.has(id)).length)}</span>
              </div>
              <div className="ws-picker__list">
                {shown.map((d) => (
                  <Checkbox
                    key={d.id} label={d.title} checked={documentIds.includes(d.id)}
                    description={d.visibility === 'company' ? `${d.filename} · ${t('documents.scope.company')}` : d.filename}
                    onChange={(e) => toggleDocument(d.id, e.target.checked)}
                  />
                ))}
              </div>
            </>
          )}
          {missing.length > 0 && <Notice tone="warning">{tn('reports.form.documentsMissing', missing.length)}</Notice>}
          {errors.documents && <p className="ws-field__error">{errors.documents}</p>}
        </fieldset>

        <div className="ws-stack">
          <RadioCards<ScheduleKind>
            name="schedule" legend={t('schedule.field.kind')} value={kind} onChange={setKind}
            options={SCHEDULE_KINDS.map((k) => ({ value: k, label: t(`schedule.${k}`), description: t(`schedule.${k}.desc`) }))}
          />
          {kind !== 'manual' && (
            <div className="ws-grid ws-grid--3 ws-grid--tight">
              <TextField label={t('schedule.field.time')} type="time" value={time} error={errors.time} onChange={(e) => setTime(e.target.value)} />
              {kind === 'weekly' && (
                <Select
                  label={t('schedule.field.weekday')} value={String(weekday)} onChange={(e) => setWeekday(Number(e.target.value))}
                  options={WEEKDAYS.map((day) => ({ value: String(day), label: weekdayOption(i18n, day) }))}
                />
              )}
              <Select
                label={t('schedule.field.timezone')} value={timezone} error={errors.timezone} onChange={(e) => setTimezone(e.target.value)}
                options={zones.map((zone) => ({ value: zone, label: zone.replace(/_/g, ' ') }))}
              />
            </div>
          )}
          {kind !== 'manual' && <p className="ws-field__hint">{t('schedule.timezoneHint')} {t('schedule.nextRunNote')}</p>}
        </div>

        <TextArea
          label={t('reports.form.delivery')} optional value={emails} rows={2} error={errors.delivery}
          hint={t('reports.form.deliveryHint')} onChange={(e) => setEmails(e.target.value)}
          disabled={deliveryUnavailable && !emails} autoComplete="off" spellCheck={false}
        />
        {deliveryUnavailable && <Notice tone="warning">{t('error.smtp_not_configured')}</Notice>}
        {!deliveryUnavailable && delivery.count === 0 && parsedEmails.emails.length > 0 && (
          <Notice tone="warning" title={t('request.noApprover.title')}>
            {t('request.noApprover.department', { department: departments.find((d) => d.id === departmentId)?.name ?? '' })}
          </Notice>
        )}
        {recipientsChanged && parsedEmails.emails.length > 0 && <Notice tone="accent">{t('reports.form.deliveryChanged')}</Notice>}
      </form>
    </Drawer>
  );
}
