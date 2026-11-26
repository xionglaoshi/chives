/** Runtime status for the settings page: harness, bot processes and the backend services. */

import { selectedVersion } from '../harness/kernel-manager.js';
import type { BotStatus } from '../api/protocol.js';
import type { EngineHealthDto, RuntimeBotDto, RuntimeSettingsDto, ProcessHealth, SystemProcessDto } from '../api/protocol.js';
import type { BotManifest, BotRegistry } from '../bots/index.js';
import type { ChivesConfig } from '../config.js';
import type { HarnessProcessMonitor } from '../harness/process-monitor.js';
import type { SettingsService } from './service.js';

export const ENGINE_PORTS: readonly number[] = [8865, 8866, 8867, 8868, 8869];
const HEALTH_TIMEOUT_MS = 1_000;

export type EngineHealthCheck = (port: number) => Promise<boolean>;

export async function engineProcess(port: number): Promise<ProcessHealth> {
  try {
    const response = await fetch(`http://127.0.0.1:${port}/health`, {
      signal: AbortSignal.timeout(HEALTH_TIMEOUT_MS),
    });
    return response.ok ? 'running' : 'error';
  } catch (error) {
    const cause = error instanceof Error ? error.cause as NodeJS.ErrnoException | undefined : undefined;
    return cause?.code === 'ECONNREFUSED' ? 'not_started' : 'error';
  }
}

function processState(
  bot: BotManifest,
  status: BotStatus,
  monitor: HarnessProcessMonitor,
): RuntimeBotDto['process'] {
  if (status === 'working' || status === 'starting' || status === 'awaiting_approval') {
    return 'running';
  }
  return status === 'error' || monitor.state(bot.id) === 'error' ? 'error' : 'not_started';
}

export interface RuntimeInput {
  config: ChivesConfig;
  registry: BotRegistry;
  status: (botId: string) => BotStatus;
  monitor: HarnessProcessMonitor;
  settings: SettingsService;
  engineHealth?: EngineHealthCheck;
  systems?: SystemProcessDto[];
}

export async function readRuntime(input: RuntimeInput): Promise<RuntimeSettingsDto> {
  const engines: EngineHealthDto[] = await Promise.all(ENGINE_PORTS.map(async port => {
    const process = input.engineHealth
      ? (await input.engineHealth(port) ? 'running' : 'not_started')
      : await engineProcess(port);
    return { port, healthy: process === 'running', process };
  }));
  const bots = input.registry.list().map((bot) => ({
    id: bot.id,
    name: bot.name,
    role: bot.role,
    emblem: bot.avatar.emblem,
    process: input.registry.isHired(bot.id) ? processState(bot, input.status(bot.id), input.monitor) : 'inactive' as const,
  }));
  return {
    harness: {
      name: input.config.harness === 'dsh' ? 'DeepSeek Harness' : 'Fake Harness',
      version: input.config.harness==='dsh' ? selectedVersion(input.config.dataDir) : null,
      connected: input.settings.modelRouteConfigured || input.monitor.anyRunning(),
    },
    systems: input.systems ?? [],
    bots,
    engines,
  };
}
