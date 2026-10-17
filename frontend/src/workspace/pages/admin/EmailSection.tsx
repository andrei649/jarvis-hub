/* Admin → Email: the SMTP server used for invitations, report delivery and approved emails.

   The stored password is never sent back (`has_password`); the form keeps it unless the admin
   types a new one or explicitly clears it (PUT `password: null` keeps, `""` clears). Saving
   without a host turns outgoing email off (the server's rule), so a sender is required only
   with a host. The test sends a real message through the saved settings and shows the
   server's verdict in plain words. */
import React, { useState } from 'react';
import { getSmtp, saveSmtp, smtpConfigured as isConfigured, testSmtp } from '../../api/admin';
import type { SmtpSecurity, SmtpSettings, SmtpTestResult } from '../../api/types';
import { describeCode, describeError, errorField } from '../../app/errors';
import { useAsync } from '../../app/hooks';
import { useUser } from '../../app/session';
import { useI18n } from '../../i18n';
import { Badge, Button, Card, Checkbox, LoadingBlock, Notice, PasswordField, Select, TextArea, TextField, useToast } from '../../ui';

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const DOMAIN_PATTERN = /^(?=.{1,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$/i;
const DEFAULT_PORT: Record<SmtpSecurity, number> = { starttls: 587, ssl: 465, none: 25 };

type Field = 'host' | 'port' | 'from_address' | 'from_name' | 'allowed_domains' | 'username' | 'password';

export function parseDomains(text: string): string[] {
  return [...new Set(text.split(/[\s,;]+/).map((d) => d.trim().toLowerCase().replace(/^@/, '')).filter(Boolean))];
}

function SmtpForm({ settings, onSaved }: { settings: SmtpSettings; onSaved: (s: SmtpSettings) => void }) {
  const i18n = useI18n();
  const { t } = i18n;
  const toast = useToast();
  const [host, setHost] = useState(settings.host);
  const [port, setPort] = useState(String(settings.port || DEFAULT_PORT[settings.security || 'starttls']));
  const [security, setSecurity] = useState<SmtpSecurity>(settings.security || 'starttls');
  const [username, setUsername] = useState(settings.username);
  const [password, setPassword] = useState('');
  const [clearPassword, setClearPassword] = useState(false);
  const [fromAddress, setFromAddress] = useState(settings.from_address);
  const [fromName, setFromName] = useState(settings.from_name);
  const [domains, setDomains] = useState(settings.allowed_domains.join('\n'));
  const [errors, setErrors] = useState<Partial<Record<Field, string>>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const changeSecurity = (next: SmtpSecurity) => {
    if (Number(port) === DEFAULT_PORT[security]) setPort(String(DEFAULT_PORT[next]));
    setSecurity(next);
  };

  const validate = (): Partial<Record<Field, string>> => {
    const found: Partial<Record<Field, string>> = {};
    const portNumber = Number(port);
    if (!Number.isInteger(portNumber) || portNumber < 1 || portNumber > 65535) found.port = t('smtp.error.port');
    if ((host.trim() || fromAddress.trim()) && !EMAIL_PATTERN.test(fromAddress.trim())) found.from_address = t('auth.error.email');
    const bad = parseDomains(domains).find((d) => !DOMAIN_PATTERN.test(d));
    if (bad) found.allowed_domains = t('smtp.error.domain', { domain: bad });
    return found;
  };

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    const found = validate();
    setErrors(found);
    setFormError(null);
    if (Object.keys(found).length) return;
    setBusy(true);
    try {
      const saved = await saveSmtp({
        host: host.trim(), port: Number(port), security, username: username.trim(),
        password: password ? password : clearPassword ? '' : null,
        from_address: fromAddress.trim(), from_name: fromName.trim(), allowed_domains: parseDomains(domains),
      });
      setPassword('');
      setClearPassword(false);
      onSaved(saved);
      toast.success(t('smtp.saved'));
    } catch (err) {
      const field = errorField(err) as Field | null;
      const message = describeError(i18n, err);
      if (field && ['host', 'port', 'from_address', 'from_name', 'allowed_domains', 'username', 'password'].includes(field)) setErrors({ [field]: message });
      else setFormError(message);
    } finally {
      setBusy(false);
    }
  };

  const passwordHint = settings.has_password
    ? (clearPassword ? t('smtp.password.willClear') : t('smtp.password.kept'))
    : t('smtp.password.none');

  return (
    <Card
      title={t('smtp.card')} description={t('smtp.cardDesc')}
      actions={isConfigured(settings) ? <Badge tone="success" dot>{t('smtp.configured')}</Badge> : <Badge tone="warning" dot>{t('smtp.notConfigured')}</Badge>}
    >
      {formError && <Notice tone="danger" live="assertive">{formError}</Notice>}
      <form className="ws-form" onSubmit={submit} noValidate>
        <div className="ws-grid ws-grid--3 ws-grid--tight">
          <TextField className="ws-span-2" label={t('field.host')} value={host} onChange={(e) => setHost(e.target.value)} error={errors.host} hint={t('smtp.hostHint')} placeholder="smtp.example.com" autoComplete="off" spellCheck={false} />
          <TextField label={t('field.port')} type="number" inputMode="numeric" min={1} max={65535} value={port} onChange={(e) => setPort(e.target.value)} error={errors.port} required />
        </div>
        <Select
          label={t('smtp.security')} value={security} onChange={(e) => changeSecurity(e.target.value as SmtpSecurity)}
          hint={t(`smtp.security.${security}.desc`)}
          options={(['starttls', 'ssl', 'none'] as const).map((s) => ({ value: s, label: t(`smtp.security.${s}`) }))}
        />
        {security === 'none' && (username.trim() || settings.has_password || password) && <Notice tone="warning">{t('smtp.insecureCredentials')}</Notice>}
        <div className="ws-grid ws-grid--2 ws-grid--tight">
          <TextField label={t('field.username')} optional value={username} onChange={(e) => setUsername(e.target.value)} error={errors.username} autoComplete="off" spellCheck={false} />
          <PasswordField
            label={t('field.password')} optional value={password} onChange={(e) => { setPassword(e.target.value); if (e.target.value) setClearPassword(false); }}
            error={errors.password} hint={passwordHint} autoComplete="new-password"
            placeholder={settings.has_password && !clearPassword ? '••••••••' : undefined}
          />
        </div>
        {settings.has_password && (
          <Checkbox label={t('smtp.password.clear')} checked={clearPassword} disabled={Boolean(password)} onChange={(e) => setClearPassword(e.target.checked)} />
        )}
        <div className="ws-grid ws-grid--2 ws-grid--tight">
          <TextField label={t('field.from_address')} type="email" value={fromAddress} onChange={(e) => setFromAddress(e.target.value)} error={errors.from_address} placeholder="nerva@firma.ro" required={Boolean(host.trim())} />
          <TextField label={t('field.from_name')} optional value={fromName} onChange={(e) => setFromName(e.target.value)} error={errors.from_name} placeholder="Nerva Workspace" maxLength={200} />
        </div>
        <TextArea
          label={t('field.allowed_domains')} optional rows={3} value={domains} onChange={(e) => setDomains(e.target.value)}
          error={errors.allowed_domains} hint={t('smtp.domainsHint')} placeholder="firma.ro" spellCheck={false}
        />
        <div><Button type="submit" variant="primary" busy={busy}>{t('common.save')}</Button></div>
      </form>
    </Card>
  );
}

function TestCard({ configured }: { configured: boolean }) {
  const i18n = useI18n();
  const { t } = i18n;
  const user = useUser();
  const [to, setTo] = useState(user.email);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<SmtpTestResult | null>(null);
  const [failure, setFailure] = useState<string | null>(null);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!EMAIL_PATTERN.test(to.trim())) { setError(t('auth.error.email')); return; }
    setError(null);
    setResult(null);
    setFailure(null);
    setBusy(true);
    try {
      setResult(await testSmtp(to.trim()));
    } catch (err) {
      if (errorField(err) === 'to') setError(describeError(i18n, err));
      else setFailure(describeError(i18n, err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card title={t('smtp.test')} description={t('smtp.testDesc')}>
      {!configured && <Notice tone="accent">{t('smtp.testNeedsConfig')}</Notice>}
      <form className="ws-form ws-form--inline" onSubmit={submit} noValidate>
        <TextField label={t('smtp.testTo')} type="email" value={to} onChange={(e) => setTo(e.target.value)} error={error} disabled={!configured} />
        <Button type="submit" icon="send" busy={busy} disabled={!configured}>{t('smtp.testSend')}</Button>
      </form>
      {result?.ok && <Notice tone="success" live="polite">{t('smtp.testOk', { email: to.trim() })}</Notice>}
      {result && !result.ok && (
        <Notice tone="danger" live="assertive" title={t('smtp.testFailed')}>
          <p>{describeCode(i18n, result.error, result.reason)}</p>
        </Notice>
      )}
      {failure && <Notice tone="danger" live="assertive">{failure}</Notice>}
    </Card>
  );
}

export function EmailSection() {
  const i18n = useI18n();
  const { t } = i18n;
  const smtp = useAsync(getSmtp, []);
  if (smtp.error) {
    return (
      <Notice tone="danger" live="assertive" action={<Button size="sm" icon="refresh" onClick={() => void smtp.reload()}>{t('common.retry')}</Button>}>
        {describeError(i18n, smtp.error)}
      </Notice>
    );
  }
  if (!smtp.data) return <Card title={t('smtp.card')}><LoadingBlock label={t('common.loading')} /></Card>;
  const settings = smtp.data;
  return (
    <div className="ws-grid ws-grid--main-aside">
      <SmtpForm key={JSON.stringify(settings)} settings={settings} onSaved={(saved) => smtp.setData(saved)} />
      <TestCard configured={isConfigured(settings)} />
    </div>
  );
}
