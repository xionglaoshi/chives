/** "Reveal in Finder" without a shell, with an injectable exec for tests. */

import { execFile as nodeExecFile } from 'node:child_process';

import { AppError } from '../errors.js';

export type ExecFileFn = (
  file: string,
  args: readonly string[],
  callback: (error: Error | null) => void,
) => void;

export interface RevealOptions {
  exec?: ExecFileFn;
  platform?: NodeJS.Platform;
}

const defaultExec: ExecFileFn = (file, args, callback) => {
  nodeExecFile(file, [...args], { timeout: 10_000 }, (error) => callback(error));
};

async function runOpen(
  args: readonly string[],
  options: RevealOptions,
): Promise<void> {
  const platform = options.platform ?? process.platform;
  if (platform !== 'darwin') {
    throw new AppError(501, 'reveal_unsupported', 'reveal is only supported on macOS');
  }
  const exec = options.exec ?? defaultExec;
  return new Promise<void>((resolve, reject) => {
    exec('open', args, (error) => {
      if (error === null) resolve();
      else reject(new AppError(500, 'reveal_failed', error.message));
    });
  });
}

/** Runs `open -R <absolutePath>` on macOS; 501 everywhere else. */
export function revealInFinder(absolutePath: string, options: RevealOptions = {}): Promise<void> {
  return runOpen(['-R', absolutePath], options);
}

/** Opens a directory itself in Finder (`open <dir>`), used by the bot profile page. */
export function openInFinder(absolutePath: string, options: RevealOptions = {}): Promise<void> {
  return runOpen([absolutePath], options);
}
