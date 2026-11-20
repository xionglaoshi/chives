/** Declarative bot manifest types and the strict schema used to load them. */

import { pixelIconIds } from './pixel-icons.js';
import { z } from 'zod';

export const EMBLEMS = [
  'crown',
  'scale',
  'lens',
  'bars',
  'scroll',
  'compass',
  'coin',
  'quill',
  'key',
  'hourglass',
  'lamp',
  'shield',
  'stone',
  'orb',
  'peak',
  'page',
  ...pixelIconIds,
] as const;

export const TONES = ['gold', 'silver', 'bronze', 'jade', 'ink'] as const;

/** Right-hand panels a bot may opt into, in display order. */
export const PANELS = ['market', 'portfolio', 'watches'] as const;
export const STRATEGY_PANEL_PREFIX = 'strategy:';
export const PANEL_PATTERN = /^(market|portfolio|watches|strategy:[A-Za-z0-9_-]+)$/;

export type Emblem = (typeof EMBLEMS)[number];
export type Tone = (typeof TONES)[number];
export type BotPanel = (typeof PANELS)[number] | `strategy:${string}`;

/** `strategy:<id>` panels are checked against `strategies` while parsing. */
export function isBotPanel(value: unknown): value is BotPanel {
  return typeof value === 'string' && PANEL_PATTERN.test(value);
}

export function strategyIdOfPanel(panel: string): string | null {
  return panel.startsWith(STRATEGY_PANEL_PREFIX) ? panel.slice(STRATEGY_PANEL_PREFIX.length) : null;
}

export interface RoutineManifest {
  id: string;
  title: string;
  schedule: Record<string, unknown>;
  prompt: string;
  trading_days_only?: boolean | undefined;
  enabled?: boolean | undefined;
}

export interface BotManifest {
  id: string;
  name: string;
  role: string;
  headline?: string | undefined;
  persona: string;
  avatar: { emblem: Emblem; tone: Tone };
  skills: string[];
  mcp: string[];
  tools: { code: 'sandboxed'; write: 'workspace-only' };
  model: string;
  can_delegate_to: string[];
  routines: RoutineManifest[];
  memory: { user: 'read' | 'none'; bot: 'read-write' | 'read' | 'none' };
  background: boolean;
  trading_guard: boolean;
  panels?: BotPanel[] | undefined;
  /** Strategy ids this bot may read; also gates `strategy:<id>` panels. */
  strategies?: string[] | undefined;
  /** Watch tools without the watches panel (the panel also grants them). */
  watches?: boolean | undefined;
}

/** A bot may create, edit and list watches when it opts in or shows the watches panel. */
export function botHasWatches(bot: Pick<BotManifest, 'panels' | 'watches'>): boolean {
  return bot.watches === true || (bot.panels ?? []).includes('watches');
}

export interface BotCatalog {
  skills: readonly string[];
  mcp: readonly string[];
}

const avatarSchema = z
  .object({
    emblem: z.enum(EMBLEMS),
    tone: z.enum(TONES),
  })
  .strict();

const toolsSchema = z
  .object({
    code: z.literal('sandboxed'),
    write: z.literal('workspace-only'),
  })
  .strict();

const routineScheduleSchema = z.union([
  z.object({ cron: z.string().min(1), tz: z.enum(['Asia/Shanghai', 'UTC']) }).strict(),
  z.object({ every_minutes: z.number().int().min(5) }).strict(),
  z.object({ once_at: z.string().min(1) }).strict(),
]);

const routineSchema = z
  .object({
    id: z.string().min(1),
    title: z.string().min(1),
    schedule: routineScheduleSchema,
    prompt: z.string().min(1),
    trading_days_only: z.boolean().optional(),
    enabled: z.boolean().optional(),
  })
  .strict();

const memorySchema = z
  .object({
    user: z.enum(['read', 'none']),
    bot: z.enum(['read-write', 'read', 'none']),
  })
  .strict();

export const botManifestSchema = z
  .object({
    id: z.string().min(1),
    name: z.string().min(1),
    role: z.string().min(1),
    headline: z.string().min(1).optional(),
    persona: z.string().min(1),
    avatar: avatarSchema,
    skills: z.array(z.string().min(1)),
    mcp: z.array(z.string().min(1)),
    tools: toolsSchema,
    model: z.string().min(1),
    can_delegate_to: z.array(z.string().min(1)),
    routines: z.array(routineSchema),
    memory: memorySchema,
    background: z.boolean(),
    trading_guard: z.boolean(),
    strategies: z.array(z.string().min(1)).optional(),
    watches: z.boolean().optional(),
    panels: z.array(z.custom<BotPanel>((value) => isBotPanel(value), { message: 'invalid panel' })).optional(),
  })
  .strict();
