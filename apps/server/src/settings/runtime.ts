/** Runtime status for the settings page: harness, bot processes and the three engines. */

import { selectedVersion } from '../harness/kernel-manager.js';
import type { BotStatus } from '../api/protocol.js';
import type { EngineHealthDto, RuntimeBotDto, RuntimeSettingsDto } from '../api/protocol.js';
import type { BotManifest, BotRegistry } from '../bots/index.js';
import type { ChivesConfig } from '../config.js';
import type { HarnessProcessMonitor } from '../harness/process-monitor.js';
import type { SettingsService } from './service.js';

export const ENGINE_PORTS: readonly number[] = [8865, 8866, 8867];
const HEALTH_TIMEOUT_MS = 1_000;

export type EngineHealthCheck = (port: number) => Promise<boolean>;

async function defaultEngineHealth(port: number): Promise<boolean> {
  try {
    const response = await fetch(`http://127.0.0.1:${port}/health`, {
      signal: AbortSignal.timeout(HEALTH_TIMEOUT_MS),
    });
    return response.ok;
  } catch {
    return false;
  }
}

function processState(
  bot: BotManifest,
  status: BotStatus,
  monitor: HarnessProcessMonitor,
): RuntimeBotDto['process'] {
  const observed = monitor.state(bot.id);
  if (observed !== undefined) return observed;
  if (status === 'working' || status === 'starting' || status === 'awaiting_approval') {
    return 'running';
  }
  return status === 'error' ? 'error' : 'not_started';
}

export interface RuntimeInput {
  config: ChivesConfig;
  registry: BotRegistry;
  status: (botId: string) => BotStatus;
  monitor: HarnessProcessMonitor;
  settings: SettingsService;
  engineHealth?: EngineHealthCheck;
}

export async function readRuntime(input: RuntimeInput): Promise<RuntimeSettingsDto> {
  const check = input.engineHealth ?? defaultEngineHealth;
  const engines: EngineHealthDto[] = await Promise.all(
    ENGINE_PORTS.map(async (port) => ({ port, healthy: await check(port) })),
  );
  const bots = input.registry.list().map((bot) => ({
    id: bot.id,
    name: bot.name,
    process: processState(bot, input.status(bot.id), input.monitor),
  }));
  return {
    harness: {
      name: input.config.harness === 'dsh' ? 'DeepSeek Harness' : 'Fake Harness',
      version: input.config.harness==='dsh' ? selectedVersion(input.config.dataDir) : null,
      connected: input.settings.modelRouteConfigured || input.monitor.anyRunning(),
    },
    bots,
    engines,
  };
}
