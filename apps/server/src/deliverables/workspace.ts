/** Prepares a bot workspace on first use: directories plus an initial MAP.md. */

import { existsSync } from 'node:fs';
import { join } from 'node:path';

import { ensureWorkspaceDirectories, WORKSPACE_MAP_FILE } from './layout.js';
import { writeWorkspaceMap } from './map.js';

export interface PrepareWorkspaceOptions {
  now?: Date;
}

/**
 * Creates the conventional directories and, when the workspace has no map yet,
 * writes an initial `MAP.md`. Existing files are never overwritten.
 */
export function prepareWorkspace(workspace: string, options: PrepareWorkspaceOptions = {}): void {
  ensureWorkspaceDirectories(workspace);
  if (existsSync(join(workspace, WORKSPACE_MAP_FILE))) return;
  writeWorkspaceMap(workspace, options);
}
