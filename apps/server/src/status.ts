/** Assembles the cross-cutting runtime status returned by `GET /api/status`. */

import type {
  ChivesStatusDto,
  RuntimeSettingsDto,
  StatusFailureDto,
} from './api/protocol.js';
import { statusFailure } from './failures.js';
import type { MessageRecord, TaskRecord } from './store/index.js';

export const ENGINE_NAMES: Readonly<Record<number, string>> = {
  8865: 'cn-watch',
  8866: 'market-watch',
  8867: 'chives-hub',
};

export interface StatusInput {
  runtime: RuntimeSettingsDto;
  /** Newest first, as returned by `store.tasks.listWithErrorCode`. */
  errors: readonly TaskRecord[];
  noticeFor: (taskId: string) => MessageRecord | undefined;
  now: Date;
}

export function buildStatus(input: StatusInput): ChivesStatusDto {
  const failures: StatusFailureDto[] = [];
  for (const task of input.errors) {
    const failure = statusFailure(task, input.noticeFor);
    if (failure !== null) failures.push(failure);
  }
  const firstOf = (codes: readonly StatusFailureDto['code'][]): StatusFailureDto | null =>
    failures.find((failure) => codes.includes(failure.code)) ?? null;
  return {
    ok: true,
    updatedAt: input.now.toISOString(),
    harness: {
      ...input.runtime.harness,
      lastError: firstOf(['harness_unavailable', 'harness_crashed']),
    },
    engines: input.runtime.engines.map((engine) => ({
      ...engine,
      name: ENGINE_NAMES[engine.port] ?? `engine-${engine.port}`,
    })),
    network: { lastError: firstOf(['network']) },
    lastModelError: firstOf(['model_quota', 'model_auth']),
  };
}
