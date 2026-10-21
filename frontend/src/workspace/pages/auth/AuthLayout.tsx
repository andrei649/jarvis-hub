/* The frame of the public screens (sign-in, first-run setup, invite/reset): the wordmark with
   its "by Digitaholic" line, a language switch that works before sign-in (remembered in this
   browser), and one centred card. */
import React from 'react';
import type { Locale } from '../../api/types';
import { writePref } from '../../app/storage';
import { useI18n } from '../../i18n';
import { useDocumentTitle } from '../../router';
import { Wordmark } from '../../shell/Wordmark';

function LanguageSwitch() {
  const { t, locale, setLocale } = useI18n();
  const choose = (next: Locale) => { setLocale(next); writePref('locale', next); };
  return (
    <div className="ws-lang-switch" role="group" aria-label={t('userMenu.language')}>
      {(['ro', 'en'] as const).map((value) => (
        <button
          key={value} type="button" className="ws-lang-switch__btn" aria-pressed={locale === value}
          lang={value} onClick={() => choose(value)}
        >
          {t(`language.${value}`)}
        </button>
      ))}
    </div>
  );
}

export function AuthLayout({ title, description, children, wide = false }: {
  title: string;
  description?: React.ReactNode;
  children: React.ReactNode;
  wide?: boolean;
}) {
  const { t } = useI18n();
  useDocumentTitle(title);
  return (
    <div className="ws-auth">
      <header className="ws-auth__top"><LanguageSwitch /></header>
      <main className="ws-auth__main">
        <div className="ws-auth__brand"><Wordmark subline /></div>
        <div className={['ws-auth__card', wide && 'ws-auth__card--wide'].filter(Boolean).join(' ')}>
          <h1 className="ws-auth__title">{title}</h1>
          {description && <p className="ws-auth__desc">{description}</p>}
          {children}
        </div>
      </main>
      <footer className="ws-auth__foot">{t('brand.footer')}</footer>
    </div>
  );
}
