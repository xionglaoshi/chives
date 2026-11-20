/** Parses one bot.yaml with a strict schema and readable, path-bearing errors. */

import { parse } from 'yaml';

import { BotLoadError } from './errors.js';
import { parseSchedule, RoutineValidationError } from '../routines/types.js';
import {
  EMBLEMS,
  TONES,
  botManifestSchema,
  strategyIdOfPanel,
  type BotManifest,
} from './types.js';

interface ZodIssueLike {
  code?: string;
  path?: readonly PropertyKey[];
  message?: string;
  keys?: readonly string[];
  input?: unknown;
}

function valueAt(document: unknown, path: readonly PropertyKey[]): unknown {
  let current: unknown = document;
  for (const key of path) {
    if (typeof current !== 'object' || current === null) return undefined;
    current = (current as Record<PropertyKey, unknown>)[key];
  }
  return current;
}

function issueText(issue: ZodIssueLike, document: unknown): string {
  const path = (issue.path ?? []).map(String).join('.');
  const actual = valueAt(document, issue.path ?? []);
  if (issue.code === 'unrecognized_keys') {
    return `unknown field "${(issue.keys ?? []).join('", "')}"`;
  }
  if (issue.code === 'invalid_type' && issue.input === undefined) {
    return `missing field "${path}"`;
  }
  if (path === 'avatar.emblem') {
    return `invalid emblem "${String(actual)}" (allowed: ${EMBLEMS.join(', ')})`;
  }
  if (path === 'avatar.tone') {
    return `invalid tone "${String(actual)}" (allowed: ${TONES.join(', ')})`;
  }
  if (path.length > 0) return `${path}: ${issue.message ?? 'invalid value'}`;
  return issue.message ?? 'invalid manifest';
}

export function parseBotManifest(text: string, file: string): BotManifest {
  let document: unknown;
  try {
    document = parse(text);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    throw new BotLoadError([{ file, message: `invalid YAML: ${message}` }]);
  }

  const result = botManifestSchema.safeParse(document);
  if (!result.success) {
    const issues = (result.error.issues as ZodIssueLike[]).map((issue) => ({
      file,
      message: issueText(issue, document),
    }));
    throw new BotLoadError(issues);
  }
  const strategies = new Set(result.data.strategies ?? []);
  for (const panel of result.data.panels ?? []) {
    const strategyId = strategyIdOfPanel(panel);
    if (strategyId !== null && !strategies.has(strategyId)) {
      throw new BotLoadError([
        {
          file,
          message: `panels: ${panel} 中的策略 "${strategyId}" 不在 strategies 列表中`,
        },
      ]);
    }
  }
  result.data.routines.forEach((routine, index) => {
    try {
      parseSchedule(routine.schedule);
    } catch (error) {
      if (!(error instanceof RoutineValidationError)) throw error;
      throw new BotLoadError([
        { file, message: `routines.${index}.schedule: ${error.message}` },
      ]);
    }
  });
  return result.data;
}
