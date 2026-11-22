/** Assembles the read-only bot profile returned by `GET /api/bots/:id/profile`. */

import type {
  BotDelegateInfo,
  BotMemoryList,
  BotProfile,
  BotSummary,
  DeliverableDto,
  RoutineDto,
  WatchDto,
} from '../api/protocol.js';
import { botWorkspace, workspaceStats } from '../deliverables/index.js';
import type { BotManifest } from './types.js';

export interface BotProfileInput {
  kernel?: 'dsh';
  bot: BotManifest;
  summary: BotSummary;
  personaSummary: string;
  skillDescriptions: ReadonlyMap<string, string>;
  delegateNames: ReadonlyMap<string, string>;
  model: string;
  dataDir: string;
  recentDeliverables: DeliverableDto[];
  routines: RoutineDto[];
  /** T139: active and historical watches shown as their own profile group. */
  watches?: WatchDto[];
  /** T134: real bot-level memories replace the M2 placeholder. */
  memory: BotMemoryList;
}

export function buildBotProfile(input: BotProfileInput): BotProfile {
  const { bot, summary } = input;
  const workspacePath = botWorkspace(input.dataDir, bot.id);
  const stats = workspaceStats(workspacePath);
  const canDelegateTo: BotDelegateInfo[] = summary.canDelegateTo.map((id) => ({
    id,
    name: input.delegateNames.get(id) ?? id,
  }));

  return {
    bot: summary,
    role: bot.role,
    personaSummary: input.personaSummary,
    skills: bot.skills.map((name) => ({
      name,
      description: input.skillDescriptions.get(name) ?? '',
    })),
    mcp: [...bot.mcp],
    tools: { ...bot.tools },
    canDelegateTo,
    routines: input.routines,
    ...(input.watches === undefined ? {} : { watches: input.watches }),
    memoryPolicy: { ...bot.memory },
    tradingGuard: bot.trading_guard,
    model: input.model,
    ...(input.kernel ? {kernel: input.kernel} : {}),
    workspace: { path: workspacePath, ...stats },
    recentDeliverables: input.recentDeliverables,
    memory: input.memory,
    defaults: {
      name: bot.name,
      avatar: { emblem: bot.avatar.emblem, tone: bot.avatar.tone },
    },
  };
}
