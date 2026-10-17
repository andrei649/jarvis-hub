/* The account menu: profile, language, theme, sign out.

   Language and theme apply at once (optimistically) and are saved to the account with
   PATCH /me, so they follow the user to every device; a failed save reverts and says why. */
import React from 'react';
import { updateMe } from '../api/account';
import type { Locale, Theme } from '../api/types';
import { useErrorText } from '../app/errors';
import { useSession, useUser } from '../app/session';
import { applyTheme } from '../app/theme';
import { useI18n } from '../i18n';
import { navigate } from '../router';
import { Avatar, Icon, Menu, useToast, type MenuEntry } from '../ui';

export const THEMES: Theme[] = ['light', 'dark', 'system'];
export const LANGUAGES: Locale[] = ['ro', 'en'];

/** Saves a preference with an optimistic apply and a revert on failure. */
export function usePreferenceSaver() {
  const { setUser } = useSession();
  const user = useUser();
  const { setLocale } = useI18n();
  const toast = useToast();
  const errorText = useErrorText();

  const saveTheme = async (theme: Theme) => {
    if (theme === user.theme) return;
    applyTheme(theme);
    try {
      setUser((await updateMe({ theme })).user);
    } catch (err) {
      applyTheme(user.theme);
      toast.error(errorText(err));
    }
  };

  const saveLocale = async (locale: Locale) => {
    if (locale === user.locale) return;
    setLocale(locale);
    try {
      setUser((await updateMe({ locale })).user);
    } catch (err) {
      setLocale(user.locale);
      toast.error(errorText(err));
    }
  };

  return { saveTheme, saveLocale };
}

export function UserMenu() {
  const { t } = useI18n();
  const user = useUser();
  const { signOut } = useSession();
  const toast = useToast();
  const errorText = useErrorText();
  const { saveTheme, saveLocale } = usePreferenceSaver();

  const items: MenuEntry[] = [
    { id: 'profile', label: t('userMenu.profile'), icon: 'user', onSelect: () => navigate('/profile') },
    { kind: 'separator', id: 's1' },
    {
      kind: 'group', id: 'lang', label: t('userMenu.language'),
      items: LANGUAGES.map((locale) => ({
        kind: 'radio' as const, id: `lang-${locale}`, label: t(`language.${locale}`), checked: user.locale === locale,
        onSelect: () => void saveLocale(locale),
      })),
    },
    { kind: 'separator', id: 's2' },
    {
      kind: 'group', id: 'theme', label: t('userMenu.theme'),
      items: THEMES.map((theme) => ({
        kind: 'radio' as const, id: `theme-${theme}`, label: t(`theme.${theme}`), checked: user.theme === theme,
        onSelect: () => void saveTheme(theme),
      })),
    },
    { kind: 'separator', id: 's3' },
    {
      id: 'logout', label: t('userMenu.logout'), icon: 'logout',
      onSelect: () => { signOut().catch((err) => toast.error(errorText(err))); },
    },
  ];

  return (
    <Menu
      label={t('userMenu.label')}
      items={items}
      trigger={(props) => (
        <button type="button" className="ws-user-btn" {...props} aria-label={t('userMenu.trigger', { name: user.name })}>
          <Avatar name={user.name} size={30} />
          <span className="ws-user-btn__name">{user.name}</span>
          <Icon name="chevronDown" size={16} />
        </button>
      )}
    />
  );
}
