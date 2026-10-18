import { describe, expect, it } from 'vitest';
import { WorkspaceApiError } from '../api/client';
import { DICTIONARIES, makeFormatters, translate, type I18n, type MessageKey } from '../i18n';
import { describeCode, describeError } from './errors';

/** The same lookups the provider builds, without React. */
function i18nFor(locale: 'ro' | 'en'): I18n {
  return {
    locale,
    setLocale: () => undefined,
    t: (key, vars) => translate(locale, key, vars),
    tn: () => '',
    has: (key): key is MessageKey => key in DICTIONARIES[locale],
    fmt: makeFormatters(locale),
  };
}

const ro = i18nFor('ro');
const en = i18nFor('en');

describe('describeCode', () => {
  it('gives the mail server cause of an SMTP failure instead of the bare code', () => {
    expect(describeCode(ro, 'smtp_failed', 'auth_failed')).toBe('Serverul de email a refuzat autentificarea. Verifică utilizatorul și parola.');
    expect(describeCode(en, 'smtp_failed', 'timeout')).toBe('The email server did not answer in time.');
    expect(describeCode(ro, 'smtp_failed', 'something_new')).toBe('Serverul de email a refuzat mesajul sau nu a putut fi contactat.');
  });

  it('adds why the model is out after the model headline', () => {
    expect(describeCode(ro, 'model_unavailable', 'no_local_model'))
      .toBe('Modelul AI nu este disponibil acum. Niciun model local nu este configurat sau pornit pe serverul Nerva.');
    expect(describeCode(en, 'model_policy_blocked', 'provider_may_train'))
      .toBe('The organisation’s policy does not allow the model available right now. The cloud provider may use submitted data to train its models, so the organisation’s policy blocks it.');
    expect(describeCode(ro, 'model_timeout', 'ignored')).toBe('Modelul AI nu a răspuns la timp.');
  });

  it('never shows a raw code without a sentence around it', () => {
    expect(describeCode(ro, 'brand_new_code')).toBe('Operațiunea nu a reușit (cod: brand_new_code).');
    expect(describeCode(ro, null)).toBe('A apărut o eroare neașteptată. Încearcă din nou.');
  });

  it('translates every approval and run failure the server can store', () => {
    for (const code of ['already_requested', 'already_shared', 'run_in_progress', 'run_not_ready', 'stale_request',
      'requester_inactive', 'execution_failed', 'internal_error', 'smtp_password_unreadable']) {
      expect(describeCode(ro, code), code).not.toContain('cod:');
      expect(describeCode(en, code), code).not.toContain('code:');
    }
  });
});

describe('describeError', () => {
  it('names the upload limit and a content/extension mismatch', () => {
    const tooBig = new WorkspaceApiError('file_too_large', '', 413, { max_bytes: 25 * 1024 * 1024 });
    expect(describeError(ro, tooBig)).toBe(`Fișierul depășește dimensiunea maximă permisă (${ro.fmt.bytes(25 * 1024 * 1024)}).`);
    const renamed = new WorkspaceApiError('unsupported_file_type', '', 415, { reason: 'content' });
    expect(describeError(en, renamed)).toMatch(/^The file’s content does not match its extension/);
    expect(describeError(ro, new WorkspaceApiError('unsupported_file_type', '', 415, { reason: 'extension' }))).toBe('Tipul de fișier nu este acceptat.');
  });

  it('reads the reason carried by an error body', () => {
    const smtp = new WorkspaceApiError('smtp_failed', 'refused', 502, { reason: 'connection_failed' });
    expect(describeError(ro, smtp)).toBe('Serverul de email nu a putut fi contactat. Verifică adresa și portul.');
  });
});
