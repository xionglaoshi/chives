import { execFile } from 'node:child_process';
import { readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { promisify } from 'node:util';

const refreshAfterMs = 45 * 60_000;
const retryAfterMs = 5 * 60_000;
const run = promisify(execFile);

export function marketNewsService(repoRoot: string, cacheDir: string) {
  const file = join(cacheDir, 'market', 'market-news.json');
  let pending: Promise<void> | undefined;
  let lastAttempt: number | undefined;

  const existing = () => {
    try {
      return { content: JSON.parse(readFileSync(file, 'utf8')) as unknown, modified: statSync(file).mtimeMs };
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === 'ENOENT') return undefined;
      throw error;
    }
  };

  return async () => {
    const cached = existing();
    const now = Date.now();
    if ((!cached || now - cached.modified >= refreshAfterMs) &&
        !pending && (lastAttempt === undefined || now - lastAttempt >= retryAfterMs)) {
      lastAttempt = now;
      const python = process.env.CALENDAR_PYTHON ?? join(repoRoot, '.venv/bin/python');
      pending = run(python, [join(repoRoot, 'scripts/update-market-news.py'), '--output', file], {
        timeout: 25_000,
      }).then(() => undefined, () => undefined).finally(() => { pending = undefined; });
    }
    if (cached) return cached.content;
    await pending;
    return existing()?.content ?? {};
  };
}
