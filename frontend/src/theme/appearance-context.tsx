/**
 * One owner instance of the appearance state, shared with any component (contract v1, §7).
 *
 * `App` creates `useAppearance()` once and wraps the tree in `<AppearanceProvider value={…}>`.
 * A component that needs to read or change appearance (Personalisation, the palette, a theme
 * preview) calls `useAppearanceContext()`. Outside the provider it gets `null` and must render
 * a read-only or empty state — never create a second `useAppearance()` instance, because two
 * writers would race on the same synced document.
 */
import { createContext, useContext, type ReactNode } from 'react';

export interface AppearanceApi {
  /** Normalised values for every appearance field, e.g. { look: 'ledger', scheme: 'dark', … }. */
  preferences: Record<string, string>;
  /** Journal, apply and sync one field; unknown values are coerced to the default. */
  setPreference: (key: string, value: string) => void;
  status: string;
  error: string;
  retry: () => void;
  /** `motion` with `system` resolved from prefers-reduced-motion. */
  motion: string;
}

const AppearanceContext = createContext<AppearanceApi | null>(null);

export function AppearanceProvider({ value, children }: { value: AppearanceApi; children?: ReactNode }) {
  return <AppearanceContext.Provider value={value}>{children}</AppearanceContext.Provider>;
}

export function useAppearanceContext(): AppearanceApi | null {
  return useContext(AppearanceContext);
}
