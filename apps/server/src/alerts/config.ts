/** Alert routing/limits config; `config/chives-alerts.yaml` is optional. */

import { existsSync, readFileSync } from 'node:fs';
import { join } from 'node:path';

import { parse } from 'yaml';

export const ALERT_CONFIG_FILE = 'chives-alerts.yaml';
export const DEFAULT_COOLDOWN_SECONDS = 1800;
export const DEFAULT_MAX_ALERT_AGE_SECONDS = 300;
export const DEFAULT_RUN_TIMEOUT_SECONDS = 600;
export const DEFAULT_BATCH_SIZE = 5;
export const DEFAULT_POLL_SECONDS = 3;

export type AlertSourceName = 'cn-watch' | 'market-watch' | 'strategy-hub';

export interface AlertSourceConfig {
  name: AlertSourceName;
  url: string;
  enabled: boolean;
  /** cn-watch takes `after_id`; market-watch takes `since_id`. */
  cursorParam: 'after_id' | 'since_id';
  batchLimit: number;
}

export interface AlertRoute {
  source: string;
  ruleId: string;
  code: string;
  bot: string;
}

export interface AlertsLimits {
  cooldownSeconds: number;
  maxAlertAgeSeconds: number;
  runTimeoutSeconds: number;
  batchSize: number;
  pollSeconds: number;
  observeOnly: boolean;
}

export interface AlertsConfig {
  sources: AlertSourceConfig[];
  routes: AlertRoute[];
  limits: AlertsLimits;
}

export const DEFAULT_ROUTES: AlertRoute[] = [
  { source: 'cn-watch', ruleId: '*', code: '*', bot: 'operator' },
  { source: 'market-watch', ruleId: '*', code: '*', bot: 'operator' },
];

export const DEFAULT_LIMITS: AlertsLimits = {
  cooldownSeconds: DEFAULT_COOLDOWN_SECONDS,
  maxAlertAgeSeconds: DEFAULT_MAX_ALERT_AGE_SECONDS,
  runTimeoutSeconds: DEFAULT_RUN_TIMEOUT_SECONDS,
  batchSize: DEFAULT_BATCH_SIZE,
  pollSeconds: DEFAULT_POLL_SECONDS,
  observeOnly: false,
};

export const DEFAULT_ALERTS_CONFIG: AlertsConfig = {
  sources: [
    {
      name: 'cn-watch',
      url: 'http://127.0.0.1:8865',
      enabled: true,
      cursorParam: 'after_id',
      batchLimit: 100,
    },
    {
      name: 'market-watch',
      url: 'http://127.0.0.1:8866',
      enabled: true,
      cursorParam: 'since_id',
      batchLimit: 50,
    },
    {
      name: 'strategy-hub',
      url: 'http://127.0.0.1:8869',
      enabled: true,
      cursorParam: 'since_id',
      batchLimit: 500,
    },
  ],
  routes: DEFAULT_ROUTES.map((route) => ({ ...route })),
  limits: { ...DEFAULT_LIMITS },
};

export class AlertConfigError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'AlertConfigError';
  }
}

/** Loopback only; suffix tricks such as `127.0.0.1.evil.com` are rejected. */
export function isLoopbackUrl(raw: string): boolean {
  let url: URL;
  try {
    url = new URL(raw);
  } catch {
    return false;
  }
  if (url.protocol !== 'http:' && url.protocol !== 'https:') return false;
  if (url.username !== '' || url.password !== '') return false;
  const host = url.hostname.toLowerCase();
  return host === '127.0.0.1' || host === 'localhost' || host === '::1' || host === '[::1]';
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function readPositiveInt(value: unknown, name: string, fallback: number): number {
  if (value === undefined) return fallback;
  if (typeof value !== 'number' || !Number.isInteger(value) || value <= 0) {
    throw new AlertConfigError(`${name} must be a positive integer`);
  }
  return value;
}

function readString(value: unknown, name: string): string {
  if (typeof value !== 'string' || value.trim() === '') {
    throw new AlertConfigError(`${name} must be a non-empty string`);
  }
  return value.trim();
}

function readSources(raw: unknown): AlertSourceConfig[] {
  if (raw === undefined) return DEFAULT_ALERTS_CONFIG.sources.map((source) => ({ ...source }));
  if (!isRecord(raw)) throw new AlertConfigError('sources must be a mapping');
  const sources: AlertSourceConfig[] = [];
  for (const name of ['cn-watch', 'market-watch', 'strategy-hub'] as const) {
    const value = raw[name];
    const fallback = DEFAULT_ALERTS_CONFIG.sources.find((entry) => entry.name === name);
    if (value === undefined) {
      if (fallback !== undefined) sources.push({ ...fallback });
      continue;
    }
    if (!isRecord(value)) throw new AlertConfigError(`sources.${name} must be a mapping`);
    const enabled = value['enabled'] === undefined ? true : value['enabled'];
    if (typeof enabled !== 'boolean') {
      throw new AlertConfigError(`sources.${name}.enabled must be a boolean`);
    }
    const url = readString(value['url'] ?? fallback?.url, `sources.${name}.url`);
    if (!isLoopbackUrl(url)) {
      throw new AlertConfigError(`sources.${name}.url must point at a loopback host`);
    }
    sources.push({
      name,
      url: url.replace(/\/+$/, ''),
      enabled,
      cursorParam: name === 'cn-watch' ? 'after_id' : 'since_id',
      batchLimit:
        name === 'cn-watch'
          ? readPositiveInt(value['batch_limit'], `sources.${name}.batch_limit`, 100)
          : name === 'market-watch'
            ? readPositiveInt(value['batch_limit'], `sources.${name}.batch_limit`, 50)
            : readPositiveInt(value['batch_limit'], `sources.${name}.batch_limit`, 500),
    });
  }
  return sources;
}

function readRoutes(raw: unknown): AlertRoute[] {
  if (raw === undefined) return DEFAULT_ROUTES.map((route) => ({ ...route }));
  if (!Array.isArray(raw) || raw.length === 0) {
    throw new AlertConfigError('routes must be a non-empty array');
  }
  return raw.map((entry, index) => {
    if (!isRecord(entry)) throw new AlertConfigError(`routes[${index}] must be a mapping`);
    const allowed = new Set(['source', 'rule_id', 'code', 'bot']);
    for (const key of Object.keys(entry)) {
      if (!allowed.has(key)) throw new AlertConfigError(`routes[${index}].${key} is unknown`);
    }
    return {
      source: readString(entry['source'], `routes[${index}].source`),
      ruleId: readString(entry['rule_id'] ?? '*', `routes[${index}].rule_id`),
      code: readString(entry['code'] ?? '*', `routes[${index}].code`).toUpperCase(),
      bot: readString(entry['bot'], `routes[${index}].bot`),
    };
  });
}

function readLimits(raw: unknown): AlertsLimits {
  if (raw === undefined) return { ...DEFAULT_LIMITS };
  if (!isRecord(raw)) throw new AlertConfigError('limits must be a mapping');
  const observe = raw['observe_only'] ?? DEFAULT_LIMITS.observeOnly;
  if (typeof observe !== 'boolean') {
    throw new AlertConfigError('limits.observe_only must be a boolean');
  }
  return {
    cooldownSeconds: readPositiveInt(
      raw['cooldown_seconds'],
      'limits.cooldown_seconds',
      DEFAULT_LIMITS.cooldownSeconds,
    ),
    maxAlertAgeSeconds: readPositiveInt(
      raw['max_alert_age_seconds'],
      'limits.max_alert_age_seconds',
      DEFAULT_LIMITS.maxAlertAgeSeconds,
    ),
    runTimeoutSeconds: readPositiveInt(
      raw['run_timeout_seconds'],
      'limits.run_timeout_seconds',
      DEFAULT_LIMITS.runTimeoutSeconds,
    ),
    batchSize: readPositiveInt(raw['batch_size'], 'limits.batch_size', DEFAULT_LIMITS.batchSize),
    pollSeconds: readPositiveInt(raw['poll_seconds'], 'limits.poll_seconds', DEFAULT_LIMITS.pollSeconds),
    observeOnly: observe,
  };
}

export function parseAlertsConfig(text: string): AlertsConfig {
  let document: unknown;
  try {
    document = parse(text);
  } catch (error) {
    throw new AlertConfigError(
      `invalid YAML: ${error instanceof Error ? error.message : String(error)}`,
    );
  }
  if (document === null || document === undefined) return DEFAULT_ALERTS_CONFIG;
  if (!isRecord(document)) throw new AlertConfigError('config must be a mapping');
  const allowed = new Set(['sources', 'routes', 'limits']);
  for (const key of Object.keys(document)) {
    if (!allowed.has(key)) throw new AlertConfigError(`unknown field "${key}"`);
  }
  return {
    sources: readSources(document['sources']),
    routes: readRoutes(document['routes']),
    limits: readLimits(document['limits']),
  };
}

/** Reads `config/chives-alerts.yaml`; absence is normal and yields built-in defaults. */
export function loadAlertsConfig(repoRoot: string): AlertsConfig {
  const path = join(repoRoot, 'config', ALERT_CONFIG_FILE);
  if (!existsSync(path)) return parseAlertsConfig('');
  return parseAlertsConfig(readFileSync(path, 'utf8'));
}
