/** Settings that are not bot-specific: profile, proactive, models, appearance, data. */

import { existsSync, lstatSync, readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';

import type { SessionConfigOption } from '@chives/acp-client';

import type {
  AppearanceSettingsDto,
  ChangeColorMode,
  DataLocationDto,
  ModelChoiceDto,
  ModelKeyDto,
  ModelSettingsDto,
  SettingsProfileDto,
  SettingsTheme,
} from '../api/protocol.js';
import type { ChivesConfig } from '../config.js';
import type { Store } from '../store/index.js';
import {
  ProfileMcpClient,
  ProfileToolError,
  ProfileUnavailableError,
  resolveProfileServer,
  type ProfileServerConfig,
} from './profile.js';

export const APPEARANCE_KEY = 'appearance';
export const DEFAULT_MODEL_KEY = 'default_model';
export const MODEL_OPTIONS_KEY = 'default_model_options';

export const DEFAULT_APPEARANCE: AppearanceSettingsDto = {
  theme: 'system',
  changeColor: 'red-up',
};

const THEMES: readonly SettingsTheme[] = ['dark', 'light', 'system'];
const CHANGE_COLORS: readonly ChangeColorMode[] = ['red-up', 'green-up'];
const MODEL_KEY_NAMES = ['TAVILY_API_KEY', 'GILDATA_TOKEN'] as const;

export class SettingsError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.name = 'SettingsError';
    this.status = status;
    this.code = code;
  }
}

export interface SettingsServiceOptions {
  store: Store;
  config: ChivesConfig;
  profileServer?: { config: ProfileServerConfig | null; error: string | null };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function parseModelOptions(raw: unknown): ModelChoiceDto[] {
  if (!Array.isArray(raw)) return [];
  const options: ModelChoiceDto[] = [];
  for (const entry of raw) {
    if (!isRecord(entry)) continue;
    const value = entry['value'];
    const name = entry['name'];
    if (typeof value !== 'string' || value === '' || typeof name !== 'string') continue;
    const description = entry['description'];
    options.push({
      value,
      name,
      ...(typeof description === 'string' && description !== '' ? { description } : {}),
    });
  }
  return options;
}

function parseAppearance(raw: unknown): AppearanceSettingsDto {
  if (!isRecord(raw)) return { ...DEFAULT_APPEARANCE };
  const theme = raw['theme'];
  const changeColor = raw['changeColor'];
  return {
    theme: THEMES.includes(theme as SettingsTheme)
      ? (theme as SettingsTheme)
      : DEFAULT_APPEARANCE.theme,
    changeColor: CHANGE_COLORS.includes(changeColor as ChangeColorMode)
      ? (changeColor as ChangeColorMode)
      : DEFAULT_APPEARANCE.changeColor,
  };
}

function directoryBytes(path: string): number {
  let total = 0;
  let entries: string[];
  try {
    entries = readdirSync(path);
  } catch {
    return 0;
  }
  for (const entry of entries) {
    const absolute = join(path, entry);
    let stats;
    try {
      stats = lstatSync(absolute);
    } catch {
      continue;
    }
    if (stats.isSymbolicLink()) continue;
    if (stats.isDirectory()) total += directoryBytes(absolute);
    else if (stats.isFile()) total += stats.size;
  }
  return total;
}

export class SettingsService {
  readonly profile: ProfileMcpClient;
  private readonly store: Store;
  private readonly config: ChivesConfig;
  private modelOptions: ModelChoiceDto[];
  private modelRouteReady = false;

  constructor(options: SettingsServiceOptions) {
    this.store = options.store;
    this.config = options.config;
    this.modelOptions = parseModelOptions(options.store.settings.get(MODEL_OPTIONS_KEY));
    const resolved =
      options.profileServer ?? resolveProfileServer(options.config.repoRoot, options.config.dshHome);
    this.profile = new ProfileMcpClient(resolved.config, resolved.error);
  }

  async getProfile(): Promise<SettingsProfileDto> {
    return this.profile.get();
  }

  async updateProfile(fields: Record<string, unknown>): Promise<SettingsProfileDto> {
    try {
      return await this.profile.update(fields);
    } catch (error) {
      throw this.profileError(error);
    }
  }

  async clearProfile(fields: readonly string[]): Promise<SettingsProfileDto> {
    try {
      return await this.profile.clear(fields);
    } catch (error) {
      throw this.profileError(error);
    }
  }

  readAppearance(): AppearanceSettingsDto {
    return parseAppearance(this.store.settings.get(APPEARANCE_KEY));
  }

  writeAppearance(patch: Record<string, unknown>): AppearanceSettingsDto {
    const allowed = new Set(['theme', 'changeColor']);
    for (const key of Object.keys(patch)) {
      if (!allowed.has(key)) throw new SettingsError(400, 'validation_error', `unknown field "${key}"`);
    }
    const current = this.readAppearance();
    let theme = current.theme;
    let changeColor = current.changeColor;
    if (patch['theme'] !== undefined) {
      if (!THEMES.includes(patch['theme'] as SettingsTheme)) {
        throw new SettingsError(400, 'validation_error', 'theme must be dark, light or system');
      }
      theme = patch['theme'] as SettingsTheme;
    }
    if (patch['changeColor'] !== undefined) {
      if (!CHANGE_COLORS.includes(patch['changeColor'] as ChangeColorMode)) {
        throw new SettingsError(400, 'validation_error', 'changeColor must be red-up or green-up');
      }
      changeColor = patch['changeColor'] as ChangeColorMode;
    }
    const next: AppearanceSettingsDto = { theme, changeColor };
    this.store.settings.set(APPEARANCE_KEY, next);
    return next;
  }

  modelSettings(): ModelSettingsDto {
    const selectedRaw = this.store.settings.get(DEFAULT_MODEL_KEY);
    const selected = typeof selectedRaw === 'string' && selectedRaw !== '' ? selectedRaw : null;
    return {
      selected,
      options: this.modelOptions.map((option) => ({ ...option })),
    };
  }

  defaultModel(): string | null {
    const selectedRaw = this.store.settings.get(DEFAULT_MODEL_KEY);
    return typeof selectedRaw === 'string' && selectedRaw !== '' ? selectedRaw : null;
  }

  writeDefaultModel(value: string | null): ModelSettingsDto {
    if (value === null) {
      this.store.settings.delete(DEFAULT_MODEL_KEY);
      return this.modelSettings();
    }
    if (typeof value !== 'string' || value.trim() === '') {
      throw new SettingsError(400, 'validation_error', 'value must be a model id or null');
    }
    if (this.modelOptions.length === 0) {
      throw new SettingsError(400, 'validation_error', '还没有可选的模型，请先开始一次对话');
    }
    if (!this.modelOptions.some((option) => option.value === value)) {
      throw new SettingsError(400, 'validation_error', `unknown model "${value}"`);
    }
    this.store.settings.set(DEFAULT_MODEL_KEY, value);
    return this.modelSettings();
  }

  /** Records the `model` choices of the latest `session/new` and persists them. */
  noteConfigOptions(options: readonly SessionConfigOption[]): void {
    const modelOption = options.find((option) => option.id === 'model');
    if (modelOption === undefined || !Array.isArray(modelOption.options)) return;
    const choices: ModelChoiceDto[] = [];
    // ACP select options may be flat or grouped ({group, name, options: [...]}); dsh groups them by provider.
    const flat: Array<Record<string, unknown>> = [];
    for (const entry of modelOption.options as unknown as Array<Record<string, unknown>>) {
      if (Array.isArray(entry['options'])) flat.push(...(entry['options'] as Array<Record<string, unknown>>));
      else flat.push(entry);
    }
    for (const choice of flat as Array<{ value?: unknown; name?: unknown; description?: unknown }>) {
      if (typeof choice.value !== 'string' || choice.value === '') continue;
      if (typeof choice.name !== 'string' || choice.name === '') continue;
      if (choices.some((entry) => entry.value === choice.value)) continue;
      choices.push({
        value: choice.value,
        name: choice.name,
        ...(typeof choice.description === 'string' && choice.description !== ''
          ? { description: choice.description }
          : {}),
      });
    }
    if (choices.length === 0) return;
    this.modelOptions = choices;
    this.store.settings.set(MODEL_OPTIONS_KEY, choices);
  }

  noteSessionEstablished(): void {
    this.modelRouteReady = true;
  }

  get modelRouteConfigured(): boolean {
    return this.modelRouteReady;
  }

  readKeys(
    env: NodeJS.ProcessEnv = process.env,
    secretsFile: string = join(this.config.repoRoot, 'config', 'secrets.env'),
  ): ModelKeyDto[] {
    // Data services (e.g. tavily-mcp) read their keys from config/secrets.env, so presence there counts too.
    const inFile = namesWithValues(secretsFile);
    const keys: ModelKeyDto[] = MODEL_KEY_NAMES.map((name) => ({
      name,
      configured: (env[name] ?? '').trim() !== '' || inFile.has(name),
    }));
    keys.push({ name: '模型路由', configured: this.modelRouteReady });
    return keys;
  }

  dataLocation(): DataLocationDto {
    return { path: this.config.dataDir, bytes: directoryBytes(this.config.dataDir) };
  }

  async close(): Promise<void> {
    await this.profile.close();
  }

  private profileError(error: unknown): SettingsError {
    if (error instanceof ProfileToolError) {
      return new SettingsError(400, error.code, error.message);
    }
    if (error instanceof ProfileUnavailableError) {
      return new SettingsError(503, 'profile_unavailable', error.message);
    }
    return new SettingsError(
      500,
      'profile_error',
      error instanceof Error ? error.message : '画像服务出错',
    );
  }
}

/**
 * Names in a dotenv-style file whose value is non-empty. Only the names leave this function: each value is
 * checked for emptiness and dropped on the spot, never stored, logged or returned.
 */
export function namesWithValues(path: string): Set<string> {
  const names = new Set<string>();
  if (!existsSync(path)) return names;
  let text: string;
  try {
    text = readFileSync(path, 'utf8');
  } catch {
    return names;
  }
  for (const line of text.split(/\r?\n/)) {
    const match = /^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$/.exec(line);
    if (match === null) continue;
    const name = match[1] ?? '';
    const hasValue = (match[2] ?? '').replace(/^['"]|['"]$/g, '').trim() !== '';
    if (hasValue) names.add(name);
  }
  return names;
}
