/** Translates a bot manifest into dsh ACP process configuration (patch YAML, MCP list, spawn spec). */

import { botWorkspace } from '../deliverables/files.js';
import { selectedVersion } from './kernel-manager.js';
import { mkdirSync, writeFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import {
  pluginPath,
  streamPatchYaml,
  type McpNameValue,
  type McpServer,
} from '@chives/acp-client';
import { stringify } from 'yaml';

import { botSkillsDir, syncBotSkills, type BotManifest } from '../bots/index.js';
import {
  isJsExpression,
  jsExpression,
  loadOverlayMcpConfigs,
  parseCordisPatch,
  readCordisPatch,
  type PatchEntry,
} from './overlays.js';

export const DEFAULT_REPO_ROOT = resolve(fileURLToPath(new URL('../../../../', import.meta.url)));


export interface DshModelRoute {
  provider: string;
  model: string;
}

export interface DshPatchOptions {
  /** `BotRegistry.personaText(bot.id)` — shared rules plus the bot persona. */
  personaText: string;
  /** Route-name to provider/model mapping supplied by the caller, never read from a private overlay. */
  routes?: Readonly<Record<string, DshModelRoute>>;
  /** Alias for `routes`, kept for callers that name the map after the model catalog. */
  models?: Readonly<Record<string, DshModelRoute>>;
  /** Explicit override used by tests or callers that already resolved the route. */
  model?: DshModelRoute;
  /** When set, also writes `<dataDir>/harness/dsh/<bot>.patch.yml`. */
  dataDir?: string;
  repoRoot?: string;
  /** Mount the verbatim-streaming side-channel plugin. Defaults to true. */
  streaming?: boolean;
  attachmentsRead?:boolean;
  workspaceWrite?:boolean;
}

export interface DshSpawnOptions extends DshPatchOptions {
  workspaceWrite?:boolean;
  dataDir: string;
  dshHome: string;
  /** Usually `process.env.DSH_FINANCE_OVERLAY`, passed through as a path only. */
  modelOverlay: string;
  env?: Readonly<Record<string, string | undefined>>;
  /** Chives-configured model endpoint; when present it replaces `modelOverlay` and the default route. */
  modelRuntime?: DshModelRuntime;
}

export interface DshModelRuntime {
  reasoningEffort?: string;
  patchPath: string;
  route: DshModelRoute;
  env: Readonly<Record<string, string>>;
}

export interface DshSpawnSpec {
  command: string;
  args: string[];
  env: Record<string, string | undefined>;
  cwd: string;
}

export function dshPatchPath(dataDir: string, botId: string): string {
  return join(dataDir, 'harness', 'dsh', `${botId}.patch.yml`);
}

function resolveRoute(bot: BotManifest, options: DshPatchOptions): DshModelRoute | undefined {
  if (bot.model === 'default') {
    // "default" uses the caller's default route when one is configured; otherwise dsh's own default.
    return options.model ?? options.routes?.default ?? options.models?.default;
  }
  const route = options.model ?? options.routes?.[bot.model] ?? options.models?.[bot.model];
  if (route === undefined) {
    throw new Error(
      `bot "${bot.id}" requires model route "${bot.model}" but the caller supplied no provider/model mapping`,
    );
  }
  return route;
}

/**
 * Returns the generated patch YAML. The trading guard is embedded from
 * `overlays/trading-guard.cordis.yml` (rather than passed as a second
 * `--patch`) so one generated file fully describes the bot: persona, model
 * route, guard, and streaming plugin cannot drift apart at spawn time.
 */
export function buildDshPatch(bot: BotManifest, options: DshPatchOptions): string {
  const repoRoot = options.repoRoot ?? DEFAULT_REPO_ROOT;
  const entries: PatchEntry[] = [
    { id: 'system-prompt', config: { personaPrefix: options.personaText } },
  ];

  if (options.dataDir !== undefined) {
    entries.push({insert:[{id:'chives-staff-boundary',name:join(repoRoot,'overlays/staff-boundary.plugin.mjs'),
      config:{workspace:botWorkspace(options.dataDir, bot.id),readOnly:bot.id==='ceo'||options.workspaceWrite===false,attachmentsRead:options.attachmentsRead!==false}}]});
    entries.push({
      id: 'skill-filesystem',
      config: {
        includeDefaultRoots: false,
        customSkillDirs: [botSkillsDir(options.dataDir, bot.id)],
      },
    });
  }

  const route = resolveRoute(bot, options);
  if (route !== undefined) {
    entries.push({ id: 'acp', config: { provider: route.provider, model: route.model } });
  }

  if (bot.trading_guard) {
    const guardPath = join(repoRoot, 'overlays/trading-guard.cordis.yml');
    entries.push(...readCordisPatch(guardPath));
  }

  if (options.streaming !== false) {
    entries.push(...parseCordisPatch(streamPatchYaml(pluginPath())));
  }

  const text = stringify(entries, { lineWidth: 0 });
  if (options.dataDir !== undefined) {
    const path = dshPatchPath(options.dataDir, bot.id);
    mkdirSync(join(options.dataDir, 'harness', 'dsh'), { recursive: true });
    writeFileSync(path, text, 'utf8');
  }
  return text;
}

/** Writes the generated patch and returns its path. */
export function writeDshPatch(bot: BotManifest, options: DshPatchOptions & { dataDir: string }): string {
  buildDshPatch(bot, options);
  return dshPatchPath(options.dataDir, bot.id);
}

const SIMPLE_ENV = /^process\.env\.([A-Za-z_][A-Za-z0-9_]*)\s*\?\?\s*''$/;
const OR_ENV = /^\(process\.env\.([A-Za-z_][A-Za-z0-9_]*)\s*\|\|\s*''\)$/;
const HOME_FALLBACK_ENV =
  /^\(process\.env\.([A-Za-z_][A-Za-z0-9_]*)\s*\|\|\s*\(process\.env\.HOME\s*\+\s*'\/\.dsh'\)\)$/;

/**
 * Evaluates only the three `!!js` shapes present in this repository's
 * overlays. Anything else is rejected: the expression is never eval'd.
 */
export function evaluateOverlayEnv(
  expression: string,
  env: Readonly<Record<string, string | undefined>>,
  context = 'overlay env',
): string {
  const simple = SIMPLE_ENV.exec(expression);
  const simpleName = simple?.[1];
  if (simpleName !== undefined) return env[simpleName] ?? '';

  const or = OR_ENV.exec(expression);
  const orName = or?.[1];
  if (orName !== undefined) return env[orName] ?? '';

  const homeFallback = HOME_FALLBACK_ENV.exec(expression);
  if (homeFallback !== null) {
    if (homeFallback[1] !== 'DSH_HOME') {
      throw new Error(`unsupported !!js expression at ${context}: ${expression}`);
    }
    const dshHome = env.DSH_HOME;
    if (dshHome !== undefined && dshHome.length > 0) return dshHome;
    const home = env.HOME;
    return home !== undefined && home.length > 0 ? `${home}/.dsh` : '';
  }

  throw new Error(`unsupported !!js expression at ${context}: ${expression}`);
}

export interface ChivesMcpServerOptions {
  /** Chives Server base URL, e.g. `http://127.0.0.1:8880`. */
  api?: string;
  /** Per-task session token; an empty value is omitted from the ACP declaration. */
  token?: string;
  /** Optional chives-mcp features, e.g. `['watches']`; exposed as CHIVES_FEATURES. */
  features?: readonly string[];
}

export interface McpServerBuildOptions {
  /** When set, replaces `paper_broker`'s `--state-dir` value. */
  paperStateDir?: string;
  /** Per-bot strategy ids; injected into the `strategy` MCP as CHIVES_STRATEGIES. */
  strategies?: readonly string[];
}

function withPaperStateDir(args: readonly string[], stateDir: string | undefined): string[] {
  const next = [...args];
  if (stateDir === undefined || stateDir === '') return next;
  const index = next.indexOf('--state-dir');
  if (index >= 0 && index + 1 < next.length) next[index + 1] = stateDir;
  else next.push('--state-dir', stateDir);
  return next;
}

/** The built-in delegation MCP is attached to every bot, not listed in bot.yaml. */
export function chivesMcpServer(
  options: ChivesMcpServerOptions = {},
  repoRoot: string = DEFAULT_REPO_ROOT,
): McpServer {
  const envPairs: McpNameValue[] = [];
  if (options.api !== undefined && options.api !== '') {
    envPairs.push({ name: 'CHIVES_API', value: options.api });
  }
  if (options.token !== undefined && options.token !== '') {
    envPairs.push({ name: 'CHIVES_SESSION_TOKEN', value: options.token });
  }
  if (options.features !== undefined) {
    envPairs.push({ name: 'CHIVES_FEATURES', value: options.features.join(',') });
  }
  return {
    name: 'chives',
    command: process.execPath,
    args: [join(repoRoot, 'packages/chives-mcp/dist/main.js')],
    env: envPairs,
  };
}

/**
 * Builds the ACP stdio declarations for the bot's MCP list plus the built-in
 * `chives` server. `chives` is never written into `bot.yaml`: every bot gets it,
 * and the server-side whitelist decides which targets are reachable.
 */
export function buildMcpServers(
  bot: BotManifest,
  env: Readonly<Record<string, string | undefined>>,
  repoRoot: string = DEFAULT_REPO_ROOT,
  chives: ChivesMcpServerOptions = {},
  options: McpServerBuildOptions = {},
): McpServer[] {
  const overlays = loadOverlayMcpConfigs(repoRoot);
  const servers: McpServer[] = bot.mcp.map((serverName) => {
    const overlay = overlays.byServer.get(serverName);
    if (overlay === undefined) {
      throw new Error(`bot "${bot.id}" lists MCP "${serverName}" but no overlay declares that serverName`);
    }

    const envPairs: McpNameValue[] = [];
    for (const [name, raw] of Object.entries(overlay.env ?? {})) {
      const value = isJsExpression(raw)
        ? evaluateOverlayEnv(jsExpression(raw), env, `${overlay.file} env.${name}`)
        : raw;
      if (value !== '') envPairs.push({ name, value });
    }
    if (serverName === 'cn_market' && ['ceo','trader','analyst','cro','cio'].includes(bot.id))
      envPairs.push({name:'CHIVES_MARKET_DESK',value:bot.id});
    if (serverName === 'strategy' && bot.id !== 'ceo' && options.strategies !== undefined) {
      const kept = envPairs.filter((entry) => entry.name !== 'CHIVES_STRATEGIES');
      envPairs.length = 0;
      envPairs.push(...kept, { name: 'CHIVES_STRATEGIES', value: options.strategies.join(',') });
    }
    const args =
      serverName === 'paper_broker'
        ? withPaperStateDir(overlay.args, options.paperStateDir)
        : [...overlay.args];

    if (overlay.cwd !== undefined) {
      return {
        name: serverName,
        command: '/bin/sh',
        args: ['-c', 'cd "$0" && exec "$@"', overlay.cwd, overlay.command, ...args],
        env: envPairs, // ACP requires `env`; dsh skips a stdio server whose declaration omits it.
      };
    }
    return {
      name: serverName,
      command: overlay.command,
      args,
      env: envPairs, // ACP requires `env`; dsh skips a stdio server whose declaration omits it.
    };
  });
  servers.push(
    chivesMcpServer(
      chives.features === undefined ? { ...chives, features: bot.panels ?? [] } : chives,
      repoRoot,
    ),
  );
  return servers;
}

/**
 * `npx -y @deepseek-ai/dsh@0.2.2-rc.1 --profile acp --patch <model patch> --patch <generated patch>`.
 * The model patch is Chives's own (settings page) when configured, otherwise the launcher's overlay.
 */
export function dshSpawnSpec(bot: BotManifest, options: DshSpawnOptions): DshSpawnSpec {
  const repoRoot = options.repoRoot ?? DEFAULT_REPO_ROOT;
  syncBotSkills(bot, { repoRoot, dataDir: options.dataDir });
  const runtime = options.modelRuntime;
  const routes =
    runtime === undefined ? options.routes : { ...options.routes, default: runtime.route };
  const patchPath = writeDshPatch(bot, {
    ...options,
    repoRoot,
    ...(routes === undefined ? {} : { routes }),
  });
  const cwd = botWorkspace(options.dataDir, bot.id);
  mkdirSync(cwd, { recursive: true });
  const modelPatch = runtime?.patchPath ?? options.modelOverlay;

  return {
    command: 'npx',
    args: [
      '-y',
      '@deepseek-ai/dsh@'+selectedVersion(options.dataDir),
      '--profile',
      'acp',
      ...(modelPatch === '' ? [] : ['--patch', modelPatch]),
      '--patch',
      patchPath,
    ],
    env: {
      ...process.env,
      ...options.env,
      ...runtime?.env,
      DSH_HOME: options.dshHome,
      DSH_PERMISSION_MODE: options.workspaceWrite===false?'read-only':'workspace-write',
      DSH_TELEMETRY_MODE: 'DISABLED',
    },
    cwd,
  };
}
