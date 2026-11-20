/** Builds the local JSON export; deliberately excludes credentials and environment data. */

import { toDeliverableDto, toMessageDto, toRoutineDto, toTaskDto } from '../api/dto.js';
import type { BotRegistry } from '../bots/index.js';
import type { MemoryService } from '../memory/index.js';
import { readProactiveSettings } from '../proactive-settings.js';
import type { Store } from '../store/index.js';
import type { SettingsService } from './service.js';

export const EXPORT_FORMAT_VERSION = 1;

export interface ExportInput {
  store: Store;
  registry: BotRegistry;
  memory: MemoryService;
  settings: SettingsService;
  now: Date;
}

function pad(value: number): string {
  return String(value).padStart(2, '0');
}

export function exportFileName(now: Date): string {
  return `chives-export-${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}-${pad(
    now.getHours(),
  )}${pad(now.getMinutes())}.json`;
}

export function buildExport(input: ExportInput): Record<string, unknown> {
  const { store, registry, settings } = input;
  const overrides = new Map(store.bots.list().map((entry) => [entry.id, entry]));
  const summaries = new Map(store.summaries.listAll().map((entry) => [entry.taskId, entry]));

  return {
    formatVersion: EXPORT_FORMAT_VERSION,
    app: 'Chives',
    exportedAt: input.now.toISOString(),
    bots: registry.list().map((bot) => {
      const override = overrides.get(bot.id);
      return {
        id: bot.id,
        name: override?.displayName ?? bot.name,
        role: bot.role,
        avatar: {
          emblem: override?.avatarEmblem ?? bot.avatar.emblem,
          tone: override?.avatarTone ?? bot.avatar.tone,
        },
        model: bot.model,
        skills: [...bot.skills],
        mcp: [...bot.mcp],
        background: bot.background,
      };
    }),
    messages: store.messages.listAll().map(toMessageDto),
    tasks: store.tasks.listAll().map((task) => ({
      ...toTaskDto(task, summaries.get(task.id)),
      summary: summaries.get(task.id) ?? null,
    })),
    deliverables: store.deliverables.listAll().map(toDeliverableDto),
    memories: registry.list().flatMap((bot) =>
      input.memory.listDto(bot.id).items.map((item) => ({ botId: bot.id, ...item })),
    ),
    routines: store.routines.list().map((routine) => ({
      ...toRoutineDto(routine),
      botName: overrides.get(routine.botId)?.displayName ?? registry.get(routine.botId)?.name ?? routine.botId,
    })),
    settings: {
      proactive: readProactiveSettings(store),
      appearance: settings.readAppearance(),
      defaultModel: settings.defaultModel(),
      modelOptions: settings.modelSettings().options,
    },
  };
}
