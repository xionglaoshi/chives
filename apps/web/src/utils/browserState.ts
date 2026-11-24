import { appPath } from '../appPath';

const generationKey = 'chives.browserStateGeneration';

export function applyBrowserState(storage: Storage, generation: string, adoptLegacy: boolean): void {
  const previous = storage.getItem(generationKey);
  if (previous === generation) return;
  if (previous !== null || !adoptLegacy) {
    for (let index = storage.length - 1; index >= 0; index--) {
      const key = storage.key(index);
      if (key?.startsWith('chives.')) storage.removeItem(key);
    }
  }
  storage.setItem(generationKey, generation);
}

export async function syncBrowserState(): Promise<boolean> {
  try {
    const response = await fetch(appPath('/api/health'), { cache: 'no-store', signal: AbortSignal.timeout(3000) });
    if (!response.ok) return false;
    const state = (await response.json()).browserState;
    if (typeof state?.generation !== 'string') return false;
    const previous = localStorage.getItem(generationKey);
    applyBrowserState(localStorage, state.generation, state.adoptLegacy === true);
    return previous !== state.generation;
  } catch {
    // The workbench can still open when the backend or browser storage is temporarily unavailable.
    return false;
  }
}
