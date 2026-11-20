/** Runtime configuration for Chives Server, read from the environment only. */

import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

export const DEFAULT_PORT = 8880;
/** One harness process per shipped bot; the pool also evicts idle processes when the cap is reached. */
export const DEFAULT_MAX_PROCESSES = 5;
export const DEFAULT_IDLE_MS = 10 * 60_000;
export const DEFAULT_DELEGATION_CONCURRENCY = 3;
/** A pending approval becomes a rejection after this long. */
export const DEFAULT_APPROVAL_TIMEOUT_MS = 10 * 60_000;
/** An inactive task segment is closed after this long. */
export const DEFAULT_TASK_IDLE_CLOSE_MS = 30 * 60_000;
/** Loopback address of the cn-market-gateway daemon used by the dashboard. */
export const DEFAULT_GATEWAY_URL = 'http://127.0.0.1:8868';

export type HarnessKind = 'dsh' | 'fake';
export type ClassifierKind = 'model' | 'rules';

export interface ChivesModelRoute {
  provider: string;
  model: string;
}

export interface ChivesConfig {
  repoRoot: string;
  botsDir: string;
  dataDir: string;
  port: number;
  harness: HarnessKind;
  /** Passed to the child as `DSH_HOME`; its contents are never read. */
  dshHome: string;
  /** Passed to the child as a patch path; its contents are never read. */
  dshOverlay: string;
  /** Base URL of the cn-market-gateway (`CHIVES_GATEWAY_URL`, default loopback 8868). */
  gatewayUrl: string;
  defaultRoute?: ChivesModelRoute;
  maxProcesses: number;
  idleMs: number;
  /** Per-bot cap on simultaneously running delegated children. */
  delegationConcurrency: number;
  /** Server-side timeout after which a pending approval is rejected. */
  approvalTimeoutMs: number;
  /** How an `uncertain` segmentation decision is resolved. */
  classifier: ClassifierKind;
  /** Idle window after which a task segment is closed. */
  taskIdleCloseMs: number;
  /** Optional replacement for `paper_broker`'s `--state-dir` argument. */
  paperStateDir?: string;
}

export class ConfigError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'ConfigError';
  }
}

export const DEFAULT_REPO_ROOT = resolve(fileURLToPath(new URL('../../../', import.meta.url)));

function readPort(raw: string | undefined): number {
  if (raw === undefined || raw.trim() === '') return DEFAULT_PORT;
  const value = Number(raw);
  if (!Number.isInteger(value) || value < 1 || value > 65_535) {
    throw new ConfigError(`CHIVES_PORT must be an integer between 1 and 65535, got "${raw}"`);
  }
  return value;
}

function readPositiveInt(raw: string | undefined, name: string, fallback: number): number {
  if (raw === undefined || raw.trim() === '') return fallback;
  const value = Number(raw);
  if (!Number.isInteger(value) || value < 1) {
    throw new ConfigError(`${name} must be a positive integer, got "${raw}"`);
  }
  return value;
}

function readGatewayUrl(raw: string | undefined): string {
  const text = raw?.trim();
  if (text === undefined || text === '') return DEFAULT_GATEWAY_URL;
  let url: URL;
  try {
    url = new URL(text);
  } catch {
    throw new ConfigError(`CHIVES_GATEWAY_URL must be an http(s) URL, got "${raw}"`);
  }
  if (url.protocol !== 'http:' && url.protocol !== 'https:') {
    throw new ConfigError(`CHIVES_GATEWAY_URL must be an http(s) URL, got "${raw}"`);
  }
  const path = url.pathname.replace(/\/+$/, '');
  return `${url.origin}${path}`;
}

function readHarness(raw: string | undefined): HarnessKind {
  if (raw === undefined || raw.trim() === '') return 'dsh';
  if (raw === 'dsh' || raw === 'fake') return raw;
  throw new ConfigError(`CHIVES_HARNESS must be "dsh" or "fake", got "${raw}"`);
}

function readClassifier(raw: string | undefined): ClassifierKind {
  if (raw === undefined || raw.trim() === '') return 'model';
  if (raw === 'model' || raw === 'rules') return raw;
  throw new ConfigError(`CHIVES_CLASSIFIER must be "model" or "rules", got "${raw}"`);
}

function readRoute(raw: string | undefined): ChivesModelRoute | undefined {
  if (raw === undefined || raw.trim() === '') return undefined;
  const text = raw.trim();
  const slash = text.indexOf('/');
  const provider = slash < 0 ? '' : text.slice(0, slash);
  const model = slash < 0 ? '' : text.slice(slash + 1);
  if (provider === '' || model === '') {
    throw new ConfigError(`CHIVES_DEFAULT_ROUTE must look like "provider/model", got "${raw}"`);
  }
  return { provider, model };
}

/**
 * Builds configuration from environment variables. `DSH_FINANCE_HOME` and
 * `DSH_FINANCE_OVERLAY` are carried as paths only: nothing here or downstream
 * opens them.
 */
export function loadConfig(env: NodeJS.ProcessEnv = process.env): ChivesConfig {
  const repoRoot = DEFAULT_REPO_ROOT;
  const dataDirRaw = env.CHIVES_DATA_DIR?.trim();
  const dataDir = resolve(dataDirRaw === undefined || dataDirRaw === '' ? `${repoRoot}/.chives` : dataDirRaw);
  const dshHome = env.DSH_FINANCE_HOME ?? `${env.HOME ?? ''}/.dsh`;
  const route = readRoute(env.CHIVES_DEFAULT_ROUTE);
  const config: ChivesConfig = {
    repoRoot,
    botsDir: resolve(
      env.CHIVES_BOTS_DIR === undefined || env.CHIVES_BOTS_DIR.trim() === ''
        ? `${repoRoot}/bots`
        : env.CHIVES_BOTS_DIR,
    ),
    dataDir,
    port: readPort(env.CHIVES_PORT),
    harness: readHarness(env.CHIVES_HARNESS),
    dshHome,
    dshOverlay: env.DSH_FINANCE_OVERLAY ?? '',
    gatewayUrl: readGatewayUrl(env.CHIVES_GATEWAY_URL),
    maxProcesses: readPositiveInt(
      env.CHIVES_MAX_PROCESSES,
      'CHIVES_MAX_PROCESSES',
      DEFAULT_MAX_PROCESSES,
    ),
    idleMs: readPositiveInt(env.CHIVES_IDLE_MS, 'CHIVES_IDLE_MS', DEFAULT_IDLE_MS),
    delegationConcurrency: readPositiveInt(
      env.CHIVES_DELEGATION_CONCURRENCY,
      'CHIVES_DELEGATION_CONCURRENCY',
      DEFAULT_DELEGATION_CONCURRENCY,
    ),
    approvalTimeoutMs: readPositiveInt(
      env.CHIVES_APPROVAL_TIMEOUT_MS,
      'CHIVES_APPROVAL_TIMEOUT_MS',
      DEFAULT_APPROVAL_TIMEOUT_MS,
    ),
    classifier: readClassifier(env.CHIVES_CLASSIFIER),
    taskIdleCloseMs: readPositiveInt(
      env.CHIVES_TASK_IDLE_CLOSE_MS,
      'CHIVES_TASK_IDLE_CLOSE_MS',
      DEFAULT_TASK_IDLE_CLOSE_MS,
    ),
  };
  const paperStateDir = env.CHIVES_PAPER_STATE_DIR?.trim();
  if (paperStateDir !== undefined && paperStateDir !== '') config.paperStateDir = paperStateDir;
  if (route !== undefined) config.defaultRoute = route;
  return config;
}
