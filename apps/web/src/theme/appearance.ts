import type { AppearanceSettingsDto } from '@chives/server/protocol';

import { fetchAppearance } from '../api/client';

export const DEFAULT_APPEARANCE: AppearanceSettingsDto = {
  theme: 'system',
  changeColor: 'red-up'
};

function prefersLight(): boolean {
  return (
    typeof window !== 'undefined' &&
    typeof window.matchMedia === 'function' &&
    window.matchMedia('(prefers-color-scheme: light)').matches
  );
}

export function resolvedTheme(theme: AppearanceSettingsDto['theme']): 'dark' | 'light' {
  if (theme === 'system') return prefersLight() ? 'light' : 'dark';
  return theme;
}

/** Applies theme and price-colour mode to `<html>` before the first paint. */
export function applyAppearance(settings: AppearanceSettingsDto): void {
  if (typeof document === 'undefined') return;
  const theme = resolvedTheme(settings.theme);
  const root = document.documentElement;
  root.dataset['theme'] = theme;
  root.dataset['themePreference'] = settings.theme;
  root.dataset['changeColor'] = settings.changeColor;
  root.style.colorScheme = theme;
}

export async function loadAndApplyAppearance(): Promise<AppearanceSettingsDto> {
  try {
    const settings = await fetchAppearance();
    applyAppearance(settings);
    return settings;
  } catch {
    applyAppearance(DEFAULT_APPEARANCE);
    return DEFAULT_APPEARANCE;
  }
}

export function watchSystemTheme(listener: () => void): () => void {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
    return () => undefined;
  }
  const query = window.matchMedia('(prefers-color-scheme: light)');
  const onChange = (): void => listener();
  if (typeof query.addEventListener === 'function') {
    query.addEventListener('change', onChange);
    return () => query.removeEventListener('change', onChange);
  }
  return () => undefined;
}
