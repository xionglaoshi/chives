/** Proactive-message master switch and automatic-analysis permission, persisted in `settings`. */

import type { Store } from './store/index.js';

export const PROACTIVE_SETTINGS_KEY = 'proactive';
export interface ProactiveSettings {
  enabled: boolean;
  autoAnalysis: boolean;
  observeOnly: boolean;
  /** Browser Notification popups (the bell list always updates). */
  browserNotify: boolean;
  /** macOS `osascript` notifications for when the page is closed. */
  systemNotify: boolean;
  /** `info` only enters the bell list; `important` and above may pop up. */
  importantOnly: boolean;
}

export const DEFAULT_PROACTIVE_SETTINGS: ProactiveSettings = {
  enabled: true,
  autoAnalysis: true,
  observeOnly: false,
  browserNotify: true,
  systemNotify: true,
  importantOnly: true,
};

/** Merges the stored JSON with defaults; malformed fields fall back one by one. */
export function readProactiveSettings(store: Store): ProactiveSettings {
  const raw = store.settings.get<Record<string, unknown>>(PROACTIVE_SETTINGS_KEY);
  if (raw === undefined || typeof raw !== 'object' || raw === null) return { ...DEFAULT_PROACTIVE_SETTINGS };
  return {
    enabled: typeof raw['enabled'] === 'boolean' ? raw['enabled'] : DEFAULT_PROACTIVE_SETTINGS.enabled,
    autoAnalysis: typeof raw['autoAnalysis'] === 'boolean' ? raw['autoAnalysis'] : raw['dailyLimit'] !== 0,
    observeOnly:
      typeof raw['observeOnly'] === 'boolean'
        ? raw['observeOnly']
        : DEFAULT_PROACTIVE_SETTINGS.observeOnly,
    browserNotify:
      typeof raw['browserNotify'] === 'boolean'
        ? raw['browserNotify']
        : DEFAULT_PROACTIVE_SETTINGS.browserNotify,
    systemNotify:
      typeof raw['systemNotify'] === 'boolean'
        ? raw['systemNotify']
        : DEFAULT_PROACTIVE_SETTINGS.systemNotify,
    importantOnly:
      typeof raw['importantOnly'] === 'boolean'
        ? raw['importantOnly']
        : DEFAULT_PROACTIVE_SETTINGS.importantOnly,
  };
}

export function writeProactiveSettings(store: Store, patch: Record<string, unknown>): ProactiveSettings {
  const current = readProactiveSettings(store);
  const next = { ...current };
  for (const [key,value] of Object.entries(patch)) {
    if (!Object.hasOwn(current,key)) throw new Error(`unknown field "${key}"`);
    if (typeof value !== 'boolean') throw new Error(`${key} must be a boolean`);
    next[key as keyof ProactiveSettings] = value;
  }
  store.settings.set(PROACTIVE_SETTINGS_KEY, next);
  return next;
}
