/* First-run setup: shown while the server reports `setup_required`.

   Creates the organisation and the first administrator in one step (the server also creates the
   "General" department with the admin in it), guarded by the one-time setup code the operator
   reads from the hub host — the page says exactly where to find it. */
import React, { useId, useState } from 'react';
import { setup } from '../../api/account';
import type { Locale } from '../../api/types';
import { describeError, errorCode, errorField } from '../../app/errors';
import { useSession } from '../../app/session';
import { useI18n } from '../../i18n';
import { navigate } from '../../router';
import { Button, Notice, PasswordField, Select, TextField } from '../../ui';
import { AuthLayout } from './AuthLayout';
import { PasswordPolicy, passwordProblemText } from './PasswordPolicy';

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

type Field = 'setup_code' | 'org_name' | 'name' | 'email' | 'password' | 'confirm';
type Errors = Partial<Record<Field, string>>;

export function SetupPage() {
  const i18n = useI18n();
  const { t, locale } = i18n;
  const { signIn, refresh } = useSession();
  const policyId = `p${useId().replace(/:/g, '')}`;
  const [values, setValues] = useState({ setup_code: '', org_name: '', name: '', email: '', password: '', confirm: '' });
  const [language, setLanguage] = useState<Locale>(locale);
  const [errors, setErrors] = useState<Errors>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const set = (field: Field) => (event: React.ChangeEvent<HTMLInputElement>) => setValues((v) => ({ ...v, [field]: event.target.value }));

  const validate = (): Errors => {
    const next: Errors = {};
    if (!values.setup_code.trim()) next.setup_code = t('setup.error.code');
    if (!values.org_name.trim()) next.org_name = t('setup.error.org');
    if (!values.name.trim()) next.name = t('auth.error.name');
    if (!EMAIL_PATTERN.test(values.email.trim())) next.email = t('auth.error.email');
    const weak = passwordProblemText(t, values.password, values.email);
    if (weak) next.password = weak;
    if (values.confirm !== values.password) next.confirm = t('password.mismatch');
    return next;
  };

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    const next = validate();
    setErrors(next);
    setFormError(null);
    if (Object.keys(next).length) return;
    setBusy(true);
    try {
      const result = await setup({
        setup_code: values.setup_code.trim(), org_name: values.org_name.trim(), name: values.name.trim(),
        email: values.email.trim(), password: values.password, locale: language,
      });
      signIn(result);
      navigate('/admin/users', { replace: true });
    } catch (err) {
      setBusy(false);
      const code = errorCode(err);
      const message = describeError(i18n, err);
      if (code === 'already_setup') { void refresh(); return; }
      if (code === 'invalid_setup_code') { setErrors({ setup_code: message }); return; }
      if (code === 'weak_password') { setErrors({ password: message }); return; }
      const field = errorField(err);
      if (field && field in values) { setErrors({ [field as Field]: message }); return; }
      setFormError(message);
    }
  };

  return (
    <AuthLayout title={t('setup.title')} description={t('setup.desc')} wide>
      {formError && <Notice tone="danger" live="assertive">{formError}</Notice>}
      <form className="ws-form" onSubmit={submit} noValidate>
        <TextField
          label={t('field.setup_code')} hint={t('setup.codeHint')} value={values.setup_code} onChange={set('setup_code')}
          error={errors.setup_code} autoComplete="one-time-code" spellCheck={false} autoFocus required
        />
        <fieldset className="ws-fieldset">
          <legend className="ws-fieldset__legend">{t('setup.orgSection')}</legend>
          <TextField label={t('field.org_name')} value={values.org_name} onChange={set('org_name')} error={errors.org_name} autoComplete="organization" maxLength={200} required />
          <Select
            label={t('setup.language')} hint={t('setup.languageHint')} value={language}
            onChange={(e) => setLanguage(e.target.value as Locale)}
            options={[{ value: 'ro', label: t('language.ro') }, { value: 'en', label: t('language.en') }]}
          />
        </fieldset>
        <fieldset className="ws-fieldset">
          <legend className="ws-fieldset__legend">{t('setup.adminSection')}</legend>
          <TextField label={t('field.name')} value={values.name} onChange={set('name')} error={errors.name} autoComplete="name" maxLength={200} required />
          <TextField label={t('field.email')} type="email" value={values.email} onChange={set('email')} error={errors.email} autoComplete="email" inputMode="email" maxLength={254} required />
          <PasswordField
            label={t('field.password')} value={values.password} onChange={set('password')} error={errors.password}
            autoComplete="new-password" aria-describedby={policyId} maxLength={256} required
          />
          <PasswordPolicy id={policyId} password={values.password} email={values.email} />
          <PasswordField label={t('field.confirm')} value={values.confirm} onChange={set('confirm')} error={errors.confirm} autoComplete="new-password" maxLength={256} required />
        </fieldset>
        <Button type="submit" variant="primary" block busy={busy}>{t('setup.submit')}</Button>
      </form>
    </AuthLayout>
  );
}
