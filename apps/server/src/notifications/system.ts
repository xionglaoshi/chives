/** macOS system notifications: one plain-text title and body, never a shell string. */

export type ExecFileFn = (
  file: string,
  args: readonly string[],
  options: { timeout: number },
  callback: (error: Error | null) => void,
) => void;

/** AppleScript string literal: backslash and double quote are the only escapes. */
export function appleScriptString(value: string): string {
  const singleLine = value.replace(/[\r\n]+/g, ' ');
  return `"${singleLine.replace(/\\/g, '\\\\').replace(/"/g, '\\"')}"`;
}

export interface SystemNotifierOptions {
  platform?: NodeJS.Platform;
  execFile?: ExecFileFn;
  log?: (message: string, detail?: unknown) => void;
}

/** Returns false when the notification was not attempted (wrong platform). */
export function sendSystemNotification(
  title: string,
  body: string,
  options: SystemNotifierOptions = {},
): boolean {
  const platform = options.platform ?? process.platform;
  const log = options.log ?? ((message, detail) => console.log(message, detail ?? ''));
  if (platform !== 'darwin') {
    log('system notification skipped: not macOS');
    return false;
  }
  const script = `display notification ${appleScriptString(body)} with title ${appleScriptString(title)}`;
  const execFile =
    options.execFile ??
    ((file, args, execOptions, callback) => {
      // Loaded lazily so tests never import the real sender on non-macOS.
      void import('node:child_process').then(({ execFile: run }) => {
        run(file, [...args], execOptions, (error) => callback(error));
      });
    });
  try {
    execFile('osascript', ['-e', script], { timeout: 5_000 }, (error) => {
      if (error !== null) log('system notification failed', error);
    });
  } catch (error) {
    log('system notification failed', error);
  }
  return true;
}
