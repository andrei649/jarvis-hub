/* Admin → Organisation: name, default language, model policy, live model status and a test.

   The policy choice is explained in place because it is the decision with data-protection
   weight: "local only" never leaves the hub host; "allow cloud" permits a cloud route only for a
   provider that does not train on inputs, and blocks everything else. The status card reads
   the shell's shared posture (the same the chip and the assistant use) and re-reads it after
   a save or a test, and the test sends a tiny real prompt to the model. Its result is also
   written into an always-present status region, since a notice inserted with its text already
   inside is not reliably announced. Unsaved changes to the form are kept as a draft in this tab
   (app/drafts.ts), so a session that ends under the admin does not lose them; the restored
   form says so and offers to discard them. */
import React, { useEffect, useRef, useState } from 'react';
import { getOrg, testModel, updateOrg } from '../../api/admin';
import type { Locale, ModelPolicy, ModelTestResult, Org } from '../../api/types';
import { draftText, useDraftMirror, useRestoredDraft } from '../../app/drafts';
import { describeCode, describeError, errorField } from '../../app/errors';
import { useAsync } from '../../app/hooks';
import { useSession, useUser } from '../../app/session';
import { useWorkspace } from '../../app/workspace';
import { useI18n } from '../../i18n';
import { ModelDetails, useModelReason, useWhereText } from '../../shell/ModelChip';
import { Button, Card, focusFirstInvalid, LoadingBlock, Notice, RadioCards, Select, TextField, useToast } from '../../ui';

interface OrgDraft { name: string; locale: Locale; policy: ModelPolicy }

function OrgForm({ org, onSaved }: { org: Org; onSaved: (org: Org) => void }) {
  const i18n = useI18n();
  const { t } = i18n;
  const toast = useToast();
  const userId = useUser().id;
  const restored = useRestoredDraft<OrgDraft>(userId, 'org');
  const [name, setName] = useState(draftText(restored?.name, org.name));
  const [locale, setLocale] = useState<Locale>(restored?.locale === 'ro' || restored?.locale === 'en' ? restored.locale : org.default_locale);
  const [policy, setPolicy] = useState<ModelPolicy>(restored?.policy === 'local_only' || restored?.policy === 'allow_cloud' ? restored.policy : org.model_policy);
  const [errors, setErrors] = useState<{ name?: string }>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [showRestored, setShowRestored] = useState(restored !== null);
  const formRef = useRef<HTMLFormElement>(null);
  const dirty = name.trim() !== org.name || locale !== org.default_locale || policy !== org.model_policy;
  const clearDraft = useDraftMirror<OrgDraft>(userId, 'org', { name, locale, policy }, !dirty);
  const discard = () => {
    clearDraft();
    setName(org.name);
    setLocale(org.default_locale);
    setPolicy(org.model_policy);
    setErrors({});
    setShowRestored(false);
  };
  useEffect(() => { if (errors.name) focusFirstInvalid(formRef.current); }, [errors]);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!name.trim()) { setErrors({ name: t('org.error.name') }); return; }
    setErrors({});
    setFormError(null);
    setBusy(true);
    try {
      const saved = await updateOrg({ name: name.trim(), default_locale: locale, model_policy: policy });
      clearDraft();
      onSaved(saved);
      toast.success(t('org.saved'));
    } catch (err) {
      if (errorField(err) === 'name') setErrors({ name: describeError(i18n, err) });
      else setFormError(describeError(i18n, err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card title={t('org.card')} description={t('org.cardDesc')}>
      {showRestored && dirty && (
        <Notice tone="accent" action={<Button size="sm" onClick={discard}>{t('draft.discard')}</Button>}>{t('draft.restoredPage')}</Notice>
      )}
      {formError && <Notice tone="danger" live="assertive">{formError}</Notice>}
      <form ref={formRef} className="ws-form" onSubmit={submit} noValidate>
        <div className="ws-grid ws-grid--2 ws-grid--tight">
          <TextField label={t('field.org_name')} value={name} onChange={(e) => setName(e.target.value)} error={errors.name} maxLength={200} required />
          <Select
            label={t('org.defaultLanguage')} hint={t('org.defaultLanguageHint')} value={locale}
            onChange={(e) => setLocale(e.target.value as Locale)}
            options={[{ value: 'ro', label: t('language.ro') }, { value: 'en', label: t('language.en') }]}
          />
        </div>
        <RadioCards<ModelPolicy>
          name="model-policy" legend={t('org.policy')} value={policy} onChange={setPolicy}
          options={[
            { value: 'local_only', label: t('org.policy.local_only'), description: t('org.policy.local_only.desc') },
            { value: 'allow_cloud', label: t('org.policy.allow_cloud'), description: t('org.policy.allow_cloud.desc') },
          ]}
        />
        {policy !== org.model_policy && <Notice tone="warning">{t('org.policy.changeNote')}</Notice>}
        <div><Button type="submit" variant="primary" busy={busy} disabled={!dirty}>{t('common.save')}</Button></div>
      </form>
    </Card>
  );
}

/** The test result in words: what answered and where (the route and the locality say the
    same thing, so it is said once), or why nothing answered. */
function useTestText(): (result: ModelTestResult) => { title: string; body: string; detail: string } {
  const i18n = useI18n();
  const { t, fmt } = i18n;
  const whereText = useWhereText();
  return (result) => {
    const where = whereText({ locality: result.locality ?? null, route: result.route ?? null }) ?? '';
    if (result.ok) {
      return { title: t('org.test.ok', { time: fmt.durationMs(result.latency_ms ?? 0) }), body: [result.model, where].filter(Boolean).join(' · '), detail: '' };
    }
    return { title: t('org.test.failed'), body: describeCode(i18n, result.error, result.reason), detail: [result.model, where].filter(Boolean).join(' · ') };
  };
}

function ModelCard({ refreshKey }: { refreshKey: number }) {
  const i18n = useI18n();
  const { t } = i18n;
  const reasonText = useModelReason();
  const testText = useTestText();
  const { posture, postureFailed, refreshPosture } = useWorkspace();
  const [reading, setReading] = useState(false);
  const [testing, setTesting] = useState(false);
  const [result, setResult] = useState<ModelTestResult | null>(null);
  const [testError, setTestError] = useState<string | null>(null);
  const [announcement, setAnnouncement] = useState('');

  const reread = async () => {
    setReading(true);
    try { await refreshPosture(); } finally { setReading(false); }
  };
  useEffect(() => { void reread(); }, [refreshKey]);

  const runTest = async () => {
    setTesting(true);
    setResult(null);
    setTestError(null);
    setAnnouncement('');
    try {
      const outcome = await testModel();
      setResult(outcome);
      const text = testText(outcome);
      setAnnouncement(`${text.title}. ${text.body}`);
    } catch (err) {
      const message = describeError(i18n, err);
      setTestError(message);
      setAnnouncement(message);
    } finally {
      setTesting(false);
      // A failed test has just marked a dead model server down on the server: the status
      // above (and the chip in the top bar) must not keep saying it is available.
      void refreshPosture();
    }
  };

  const shown = result ? testText(result) : null;
  return (
    <Card
      title={t('org.model')} description={t('org.modelDesc')}
      actions={<Button size="sm" variant="ghost" icon="refresh" onClick={() => void reread()} disabled={reading}>{t('common.refresh')}</Button>}
    >
      {!posture && !postureFailed && <LoadingBlock label={t('common.loading')} />}
      {!posture && postureFailed && <Notice tone="danger">{t('model.loadFailed')}</Notice>}
      {posture && (
        <>
          <ModelDetails posture={posture} technical />
          {!posture.available && <Notice tone="warning" title={t('org.model.unavailable')}>{reasonText(posture.reason)}</Notice>}
        </>
      )}
      <div className="ws-stack ws-stack--top">
        <div><Button icon="zap" onClick={runTest} busy={testing}>{t('org.test.run')}</Button></div>
        <p className="ws-muted ws-small">{t('org.test.hint')}</p>
        <p className="ws-sr-only" role="status" aria-live="polite">{announcement}</p>
        {result && shown && (
          <Notice tone={result.ok ? 'success' : 'danger'} title={shown.title}>
            <p>{shown.body}</p>
            {shown.detail && <p className="ws-small ws-muted">{shown.detail}</p>}
          </Notice>
        )}
        {testError && <Notice tone="danger">{testError}</Notice>}
      </div>
    </Card>
  );
}

export function OrganisationSection() {
  const i18n = useI18n();
  const { t } = i18n;
  const { setOrg } = useSession();
  const org = useAsync(getOrg, []);
  const [modelKey, setModelKey] = useState(0);

  if (org.error) {
    return (
      <Notice tone="danger" live="assertive" action={<Button size="sm" icon="refresh" onClick={() => void org.reload()}>{t('common.retry')}</Button>}>
        {describeError(i18n, org.error)}
      </Notice>
    );
  }
  return (
    <div className="ws-grid ws-grid--2 ws-grid--start">
      {org.data
        ? <OrgForm key={`${org.data.name}|${org.data.default_locale}|${org.data.model_policy}`} org={org.data}
            onSaved={(saved) => { org.setData(saved); setOrg(saved); setModelKey((k) => k + 1); }} />
        : <Card title={t('org.card')}><LoadingBlock label={t('common.loading')} /></Card>}
      <ModelCard refreshKey={modelKey} />
    </div>
  );
}
