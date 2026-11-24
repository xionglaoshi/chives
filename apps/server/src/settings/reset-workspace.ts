import { existsSync, mkdirSync, mkdtempSync, renameSync, rmdirSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';

import { DATABASE_FILE } from '../store/index.js';

/** Keep previous deliverables recoverable without exposing them to the new user state. */
export function resetWorkspaceIfUserDataIsMissing(dataDir: string, workspaceDir: string | undefined): void {
  const root = dirname(dataDir);
  const workspace = join(root, 'workspace');
  if (dataDir !== join(root, 'user-data') || !workspaceDir || resolve(workspaceDir) !== workspace
      || existsSync(join(dataDir, DATABASE_FILE)) || !existsSync(workspace)) return;

  const runtime = join(root, 'runtime');
  mkdirSync(runtime, { recursive: true });
  const recovery = mkdtempSync(join(runtime, 'user-reset-'));
  try {
    renameSync(workspace, join(recovery, 'workspace'));
  } catch (error) {
    rmdirSync(recovery);
    throw error;
  }
}
