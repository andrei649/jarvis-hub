/* The account menu: profile, language, theme, sign out.

   Language and theme apply at once (optimistically) and are saved to the account with
   PATCH /me, so they follow the user to every device; a failed save reverts and says why. */
import React, { useRef } from 'react';
import { updateMe } from '../api/account';
import type { Locale, Theme, WorkspaceUser } from '../api/types';
import { useErrorText } from '../app/errors';
import { useSession, useUser } from '../app/session';
import { useI18n } from '../i18n';
import { navigate } from '../router';
import { Icon, Menu, useToast, type MenuEntry } from '../ui';

export const THEMES: Theme[] = ['light', 'dark', 'system'];
export const LANGUAGES: Locale[] = ['ro', 'en'];

/** Saves a preference with an optimistic apply and a revert on failure.

    The optimistic value goes into the signed-in user itself, not only onto <html> and the
    i18n provider: the controls that show the preference (the profile's theme radios and
    language select, the menu's radio items) read the user, so they reflect the choice at once
    instead of springing back until the server answers. Only the latest save's answer is
    applied, so two quick changes cannot finish in the wrong order. */
export function usePreferenceSaver() {
  const { setUser } = useSession();
  const user = useUser();
  const toast = useToast();
  const errorText = useErrorText();
  const latest = useRef(0);

  const save = async (change: Pick<WorkspaceUser, 'theme'> | Pick<WorkspaceUser, 'locale'>) => {
    const request = ++latest.current;
    const before = user;
    setUser({ ...user, ...change });
    try {
      const saved = (await updateMe(change)).user;
      if (request === latest.current) setUser(saved);
    } catch (err) {
      if (request === latest.current) setUser(before);
      toast.error(errorText(err));
    }
  };

  const saveTheme = async (theme: Theme) => {
    if (theme !== user.theme) await save({ theme });
  };

  const saveLocale = async (locale: Locale) => {
    if (locale !== user.locale) await save({ locale });
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
        kind: 'radio' as const, id: `lang-${locale}`, label: t(`language.${locale}`), checked: user.locale === locale, lang: locale,
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
          <Icon name="user" size={30} />
          <span className="ws-user-btn__name">{user.name}</span>
          <Icon name="chevronDown" size={16} />
        </button>
      )}
    />
  );
}
