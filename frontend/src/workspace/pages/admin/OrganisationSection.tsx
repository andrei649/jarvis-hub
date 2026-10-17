/* Admin → Organisation: name, default language, model policy, live model status and a test.

   The policy choice is explained in place because it is the decision with data-protection
   weight: "local only" never leaves the hub host; "allow cloud" permits a cloud route only for a
   provider that does not train on inputs, and blocks everything else. The status card reads
   the same posture the assistant uses, and the test sends a tiny real prompt to the model. */
import React, { useState } from 'react';
import { getModelPosture } from '../../api/account';
import { getOrg, testModel, updateOrg } from '../../api/admin';
import type { Locale, ModelPolicy, ModelTestResult, Org } from '../../api/types';
import { describeCode, describeError, errorField } from '../../app/errors';
import { useAsync } from '../../app/hooks';
import { useSession } from '../../app/session';
import { useI18n } from '../../i18n';
import { ModelDetails, useModelReason } from '../../shell/ModelChip';
import { Button, Card, LoadingBlock, Notice, RadioCards, Select, TextField, useToast } from '../../ui';

function OrgForm({ org, onSaved }: { org: Org; onSaved: (org: Org) => void }) {
  const i18n = useI18n();
  const { t } = i18n;
  const toast = useToast();
  const [name, setName] = useState(org.name);
  const [locale, setLocale] = useState<Locale>(org.default_locale);
  const [policy, setPolicy] = useState<ModelPolicy>(org.model_policy);
  const [errors, setErrors] = useState<{ name?: string }>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const dirty = name.trim() !== org.name || locale !== org.default_locale || policy !== org.model_policy;

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!name.trim()) { setErrors({ name: t('org.error.name') }); return; }
    setErrors({});
    setFormError(null);
    setBusy(true);
    try {
      const saved = await updateOrg({ name: name.trim(), default_locale: locale, model_policy: policy });
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
      {formError && <Notice tone="danger" live="assertive">{formError}</Notice>}
      <form className="ws-form" onSubmit={submit} noValidate>
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

function TestResult({ result }: { result: ModelTestResult }) {
  const i18n = useI18n();
  const { t, fmt } = i18n;
  if (result.ok) {
    return (
      <Notice tone="success" live="polite" title={t('org.test.ok', { time: fmt.durationMs(result.latency_ms ?? 0) })}>
        {[result.model, result.route, result.locality && t(`locality.${result.locality}`)].filter(Boolean).join(' · ')}
      </Notice>
    );
  }
  return (
    <Notice tone="danger" live="assertive" title={t('org.test.failed')}>
      <p>{describeCode(i18n, result.error, result.reason)}</p>
      {(result.model || result.route) && <p className="ws-mono ws-small">{[result.model, result.route].filter(Boolean).join(' · ')}</p>}
    </Notice>
  );
}

function ModelCard({ refreshKey }: { refreshKey: number }) {
  const i18n = useI18n();
  const { t } = i18n;
  const reasonText = useModelReason();
  const posture = useAsync(getModelPosture, [refreshKey]);
  const [testing, setTesting] = useState(false);
  const [result, setResult] = useState<ModelTestResult | null>(null);
  const [testError, setTestError] = useState<string | null>(null);

  const runTest = async () => {
    setTesting(true);
    setResult(null);
    setTestError(null);
    try {
      setResult(await testModel());
      void posture.reload();
    } catch (err) {
      setTestError(describeError(i18n, err));
    } finally {
      setTesting(false);
    }
  };

  return (
    <Card
      title={t('org.model')} description={t('org.modelDesc')}
      actions={<Button size="sm" variant="ghost" icon="refresh" onClick={() => void posture.reload()} disabled={posture.loading}>{t('common.refresh')}</Button>}
    >
      {posture.loading && !posture.data && <LoadingBlock label={t('common.loading')} />}
      {posture.error && <Notice tone="danger">{describeError(i18n, posture.error)}</Notice>}
      {posture.data && (
        <>
          <ModelDetails posture={posture.data} />
          {!posture.data.available && <Notice tone="warning" title={t('org.model.unavailable')}>{reasonText(posture.data.reason)}</Notice>}
        </>
      )}
      <div className="ws-stack ws-stack--top">
        <div><Button icon="zap" onClick={runTest} busy={testing}>{t('org.test.run')}</Button></div>
        <p className="ws-muted ws-small">{t('org.test.hint')}</p>
        {result && <TestResult result={result} />}
        {testError && <Notice tone="danger" live="assertive">{testError}</Notice>}
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
