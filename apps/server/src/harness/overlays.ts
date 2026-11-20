/** Reads dsh Cordis patch overlays without evaluating their `!!js` expressions. */

import { readdirSync, readFileSync } from 'node:fs';
import { join, resolve } from 'node:path';

import { parse } from 'yaml';

export interface PatchEntry {
  id?: string;
  name?: string;
  insert?: PatchEntry[];
  config?: Record<string, unknown>;
  [key: string]: unknown;
}

export interface McpOverlayConfig {
  serverName: string;
  command: string;
  args: string[];
  cwd?: string;
  env?: Record<string, string>;
  /** Absolute path of the overlay that declared this server. */
  file: string;
}

export interface LoadedOverlayConfigs {
  byServer: Map<string, McpOverlayConfig>;
  byFile: Map<string, McpOverlayConfig[]>;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/**
 * Marks a `!!js` expression so callers can tell it apart from a literal env
 * value. The expression is never evaluated here.
 */
export const JS_ENV_SENTINEL = '__CHIVES_JS_ENV__:';

export function isJsExpression(value: string): boolean {
  return value.startsWith(JS_ENV_SENTINEL);
}

export function jsExpression(value: string): string {
  return value.slice(JS_ENV_SENTINEL.length);
}

/**
 * Replaces `KEY: !!js <expression>` with a quoted YAML string carrying the
 * sentinel, so the expression survives parsing verbatim.
 */
export function stripJsTags(text: string): string {
  return text.replace(/!!js[ \t]+([^\n]+)/g, (_match, expression: string) =>
    JSON.stringify(`${JS_ENV_SENTINEL}${expression.trim()}`),
  );
}

export function parseCordisPatch(text: string): PatchEntry[] {
  const document: unknown = parse(stripJsTags(text));
  if (!Array.isArray(document)) {
    throw new Error('Cordis patch must be a YAML sequence');
  }
  return document.filter(isRecord) as PatchEntry[];
}

export function readCordisPatch(file: string): PatchEntry[] {
  return parseCordisPatch(readFileSync(file, 'utf8'));
}

function collectEntries(entries: readonly PatchEntry[], into: PatchEntry[]): void {
  for (const entry of entries) {
    into.push(entry);
    if (Array.isArray(entry.insert)) collectEntries(entry.insert, into);
  }
}

function readMcpConfig(entry: PatchEntry, file: string): McpOverlayConfig | undefined {
  const config = entry.config;
  if (config === undefined || !isRecord(config)) return undefined;
  const serverName = config.serverName;
  if (typeof serverName !== 'string' || serverName.length === 0) return undefined;

  if (config.transport !== 'stdio') {
    throw new Error(`${file}: MCP "${serverName}" uses an unsupported transport (only stdio)`);
  }
  const command = config.command;
  if (typeof command !== 'string' || command.length === 0) {
    throw new Error(`${file}: MCP "${serverName}" has no command`);
  }
  const args = config.args;
  if (args !== undefined && (!Array.isArray(args) || args.some((arg) => typeof arg !== 'string'))) {
    throw new Error(`${file}: MCP "${serverName}" has non-string args`);
  }
  const cwd = config.cwd;
  if (cwd !== undefined && typeof cwd !== 'string') {
    throw new Error(`${file}: MCP "${serverName}" has a non-string cwd`);
  }
  const env = config.env;
  if (
    env !== undefined &&
    (!isRecord(env) || Object.values(env).some((value) => typeof value !== 'string'))
  ) {
    throw new Error(`${file}: MCP "${serverName}" has a non-string env value`);
  }

  return {
    serverName,
    command,
    args: (args as string[] | undefined) ?? [],
    ...(cwd === undefined ? {} : { cwd }),
    ...(env === undefined ? {} : { env: env as Record<string, string> }),
    file,
  };
}

export function loadOverlayMcpConfigs(repoRoot: string): LoadedOverlayConfigs {
  const overlaysDir = join(resolve(repoRoot), 'overlays');
  const files = readdirSync(overlaysDir)
    .filter((name) => name.endsWith('.cordis.yml'))
    .sort()
    .map((name) => join(overlaysDir, name));

  const byServer = new Map<string, McpOverlayConfig>();
  const byFile = new Map<string, McpOverlayConfig[]>();
  for (const file of files) {
    const entries: PatchEntry[] = [];
    collectEntries(readCordisPatch(file), entries);
    const configs: McpOverlayConfig[] = [];
    for (const entry of entries) {
      const config = readMcpConfig(entry, file);
      if (config === undefined) continue;
      configs.push(config);
      byServer.set(config.serverName, config);
    }
    byFile.set(file, configs);
  }
  return { byServer, byFile };
}
